# Qdrant Group By 搜尋分組（多樣性檢索優化）規劃文件

> 狀態：**規劃完成 / 獨立立案待驗證**  
> 預估效益：**中～高** —— 解決長檔案與超多 Child Chunks 佔滿召回名額導致的文件多樣性丟失問題，原生保證 Top-K 召回內容涵蓋多個不同參考文件。  
> 影響範圍：**中～高** —— 改動 `backend/services/qdrant_service.py` 核心檢索路徑（`search_similar()` 與 `search_similar_two_step()` 的 1st-hop 與 2nd-hop 查詢）。建議先於測試環境完成檢索效果與延遲驗證後再上線。

---

## 1. 問題背景與現狀分析

### 1.1 長檔案 Child Chunks 佔滿召回名額（洗版問題）

在現行的 `QdrantService.search_similar()` 中，當 `disable_parent_merge=False` 時，拉取點位上限設定為：
```python
search_limit = top_k if disable_parent_merge else max(top_k * 4, 20)
```

當知識庫中存在長篇文件（如：數百頁的設備操作手冊或規章制度），該檔案會被切碎片組合成大量的 Child Chunks（例如單一 Parent 擁有 30~50 個 Child Chunks）。

若使用者問題恰好命中該長檔案的描述主題，在 Qdrant 的 Prefetch 與 RRF 階段回傳的前 20 筆最高分 Chunks 中，**可能 20 筆全部來自該單一檔案的不同 Child Chunks**。

### 1.2 應用層去重截斷導致檢索多樣性（Diversity）嚴重丟失

現行邏輯在 Qdrant 回傳 20 筆 Chunks 後，於應用層執行 Python 去重與截斷：
1. **依 `parent_id` 去重**：只保留第一筆出現的 `parent_id` 點位（其餘同檔案點位直接捨棄）。
2. **截斷至 `top_k`**：將去重後的清單截斷回前 `top_k` 筆（預設 5 筆）。

**結果**：由於前 20 筆 Chunks 全部屬於同一個 `parent_id`，去重後僅剩下 **1 筆** 結果！即使知識庫中還有其他同樣相關的參考文件（排名在第 21 筆之後），也因為預設的 `search_limit=20` 的上限而被擋在外面。

這會導致 RAG 的 LLM 提示詞脈絡中只獲得單一文件的資訊，失去跨文件比對與多元參考的能力。

---

## 2. 優化方案：引入 Qdrant 原生 Group By 功能

### 2.1 核心機制

使用 Qdrant 1.18.0 原生支援的 **Group By（搜尋分組）** API（`query_points_groups`）。

在 Qdrant 引擎端檢索時：
* 以 `parent_id` Payload 欄位作為 `group_by` 的分組依據。
* 設定 `group_size=1`（或 2），限制每個 `parent_id` 最多只回傳分數最高的 1（或 2）個 Child Chunks。
* 設定 `limit=top_k`，要求 Qdrant 直接回傳 `top_k` 個**不同 Parent 分組**。

### 2.2 與現行作法對比

| 比較項目 | 現行作法（擴大 limit + 應用層去重） | 建議方案（Qdrant 原生 Group By） |
|:---|:---|:---|
| **多樣性保證** | 無保證（若單檔佔滿 `search_limit` 則只剩 1 份文件） | **原生保證**（必包含 `top_k` 個不同 Parent 文件） |
| **網路傳輸量** | 固定拉取 20 筆點位 Payload | 僅傳輸 `top_k` 筆最高分點位 Payload |
| **運算位置** | Python 應用層記憶體走訪去重 | Qdrant C++ 核心原生地高效分組過濾 |
| **Prefetch / RRF 相容性** | 沿用 Prefetch | **完全相容**（`query_points_groups` 支援 Prefetch 與 RRF） |

---

## 3. 程式碼實作細節

### 3.1 Qdrant Client API 驗證（`qdrant-client 1.18.0`）

已於本專案環境核對 `AsyncQdrantClient` 的方法簽章，確認使用 `query_points_groups()` 方法（非 `query_groups`），其完整簽章與支援參數如下：

```python
response = await client.query_points_groups(
    collection_name=collection_name,
    prefetch=prefetch_list,               # 沿用現行 Dense + Sparse + Exact Keyword 3路 Prefetch
    query=models.FusionQuery(fusion=models.Fusion.RRF), # 沿用 RRF 排名融合
    group_by="parent_id",                 # 以 parent_id 作為分組依據
    group_size=1,                         # 每組取分數最高的前 1 筆
    limit=top_k,                          # 回傳 top_k 個不同的 parent 分組
    query_filter=query_filter,            # 沿用過濾器 (tags, filename, db_query_profile 等)
    with_payload=True,
    with_vectors=[""]                     # 供 _compute_semantic_score 重算 cosine 分數用
)
```

### 3.2 搜尋結果解析邏輯

`query_points_groups` 回傳的結構為 `PointGroups` 物件，包含 `groups: List[PointGroup]`：

```python
# 遍歷分組提取點位（group.hits 已依分數由高至低排序，取每組最相關的第一筆）
results = []
for group in response.groups:
    if group.hits:
        # 取出該 Group 中分數最高的第一筆點位
        top_hit = group.hits[0]
        results.append(top_hit)
```

提取出 `results` 後，後續的 `_compute_semantic_score()` 重算、字典結構轉換、Parent-Child 併行還原合併（方向三）皆可無縫接軌。

---

## 4. 關鍵設計考量與注意事項

### 4.1 `group_size` 參數取捨（1 vs 2）

* **`group_size = 1`**：
  * **優點**：多樣性最大化，`top_k=5` 一定涵蓋 5 份不同的 Parent 文件。
  * **考量**：若同一份長檔案中確實有兩個不同章節都與問題強相關，第二個章節會被強制排除。
* **`group_size = 2`**：
  * **優點**：允許相關性極高的同一檔案提供最多 2 個重點段落，平衡單檔深度與跨檔廣度。
* **建議**：初始實作可設為預設 `group_size=1`，並提供設定檔（或參數）供評估測試時調校。

### 4.2 核心檢索與 Two-Step 關聯搜尋（2nd-hop）相容性

1. **`search_similar()`**：第一階段核心檢索可直接切換為 Group By。
2. **`search_similar_two_step()`**：第二階段（2nd-hop 鄰居點位搜尋，[qdrant_service.py:630-736](../../backend/services/qdrant_service.py)）同樣使用 `query_points` 拉取鄰居。鄰居拉取是否也要走 Group By，需評估是否要避免同一關聯檔案佔滿所有鄰居名額。
3. **`disable_parent_merge=True` 分支**：
   當呼叫端明確要求不進行 Parent-Child 合併時（例如：無 parent 概念的微型點位搜尋），應**維持原本的 `query_points` 路徑**，避免強制分組造成非預期的點位遺失。

---

## 5. Proposed Changes (建議修改檔案)

### [MODIFY] [qdrant_service.py](file:///d:/%E6%AA%94%E6%A1%88%E5%88%86%E4%BA%AB/%E7%A8%8B%E5%BC%8F%E7%A2%BC/AiRAG/backend/services/qdrant_service.py)

- 在 `search_similar()` 中：
  - 當 `disable_parent_merge=False` 且使用 RRF 融合或純向量搜尋時，將 `client.query_points()` 替換為 `client.query_points_groups()`。
  - 調整 `search_limit` 傳參為 `group_by="parent_id", group_size=1, limit=top_k`。
  - 調整 response 轉換邏輯，從 `response.groups` 解析 hit 點位。
  - 移除舊有在應用層迴圈進行 `seen_parents` 去重與 `[:top_k]` 截斷的 redundant 程式碼。

---

## 6. 驗證與測試計畫

### 6.1 測試場景驗證
1. **多樣性驗證**：在含有單一檔案多 Child Chunks 的知識庫中進行查詢，驗證回傳的 `final_results` 筆數與相異 `filename` 數量確實達到 `top_k`。
2. **無 Parent ID 資料相容性**：驗證未設定 `parent_id` 的點位在 Group By 運作下是否能正常回傳。
3. **Two-Step 關聯檢索驗證**：驗證雙階段檢索完整流程不受影響，`semantic_score` 重算正確。

### 6.2 效能與延遲比較
- 比較 `query_points_groups` 與原本 `query_points` 的 Qdrant 查詢響應時間（ms），確認 Qdrant 端 Group By 的 overhead 屬於微秒/毫秒等級，不會帶來額外延遲。
