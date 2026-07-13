# Qdrant Group By 搜尋分組（多樣性檢索優化）規劃文件

> 狀態：**規劃完成（已選定方向 A）/ 待實作**  
> 預估效益：**中～高** —— 解決長檔案（不論是否有 `parent_id`）佔滿召回名額導致的文件多樣性丟失問題，原生保證 Top-K 召回內容涵蓋多個不同參考檔案。  
> 影響範圍：**中～高** —— 改動 `backend/services/qdrant_service.py` 核心檢索路徑（`search_similar()`，適用於 `vector`／`hybrid`／`semantic_hybrid` 三種 `search_type`）。建議先於測試環境完成檢索效果與延遲驗證後再上線。

> **2026-07-13 複核（阻塞性問題，已解決）**：已用臨時測試 Collection 實測 `query_points_groups()` 對「缺少 `group_by` 欄位之點位」的實際行為，確認**該類點位會被完全排除，不會有 fallback 或空值分組**。並確認本專案「標準切分」（`ChunkingService.split_text()`，非 `.4fd`/`.4gl`/`.md` 結構化格式）路徑產生的 Chunks **從不寫入 `parent_id`**，代表這不是邊角案例，而是會影響大量一般文件的真實風險。**已決議採用第 4.3.3 節方向 A（改用 `filename` 作為 `group_by` 欄位）解決此問題**，因為所有寫入路徑都保證 `filename` 有值，不會有點位被排除。詳見第 4.3 節。

> **2026-07-13 補充澄清**：此優化與 `search_type` 無關。現行 `search_similar()` 的 `search_limit` 計算（[qdrant_service.py:367](../../backend/services/qdrant_service.py:367)）與後續依 `parent_id` 去重、截斷至 `top_k` 的邏輯（[qdrant_service.py:496-602](../../backend/services/qdrant_service.py:496)），在 `vector`／`hybrid`／`semantic_hybrid` 三種 `search_type` 下是**完全相同的一段共用程式碼**，並非只有純向量查詢才會遇到單一檔案佔滿名額的問題；Hybrid／語義混合查詢的 RRF 融合與既有的 Parent-Child 內容合併（把同一 `parent_id` 的多個 Child Chunks 合併顯示成一筆，例如「段落: #2~3」）是另一個獨立步驟，並不會避免這裡討論的多樣性丟失問題。因此本次改動需套用到所有三種 `search_type`。

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
* 以 **`filename`** Payload 欄位作為 `group_by` 的分組依據（**已決議採方向 A，非原先草案的 `parent_id`**，理由見第 4.3 節）。
* 設定 `group_size`（初始建議 2～3，見第 4.1 節），限制每個檔案最多只回傳分數最高的 N 個 Chunks。
* 設定 `limit=top_k`，要求 Qdrant 直接回傳 `top_k` 個**不同檔案**的分組。

### 2.2 與現行作法對比

| 比較項目 | 現行作法（擴大 limit + 應用層依 `parent_id` 去重） | 建議方案（Qdrant 原生 Group By，以 `filename` 分組） |
|:---|:---|:---|
| **多樣性保證** | 無保證（若單檔佔滿 `search_limit` 則只剩 1 份文件） | **原生保證**（必包含 `top_k` 個不同檔案，且不論該檔案是否有 `parent_id` 都保證有效，見第 4.3 節） |
| **網路傳輸量** | 固定拉取 20 筆點位 Payload | 僅傳輸 `top_k × group_size` 筆最高分點位 Payload |
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
    group_by="filename",                  # 已決議採方向 A：以 filename 作為分組依據（非 parent_id，見 4.3 節）
    group_size=2,                         # 每組取分數最高的前 N 筆，初始建議 2～3（見 4.1 節）
    limit=top_k,                          # 回傳 top_k 個不同的檔案分組
    query_filter=query_filter,            # 沿用過濾器 (tags, filename, db_query_profile 等)
    with_payload=True,
    with_vectors=[""]                     # 供 _compute_semantic_score 重算 cosine 分數用
)
```

> **注意（純向量搜尋分支）**：現行 `search_similar()` 的「純向量搜尋」（非 Hybrid）分支目前會將 `score_threshold=score_threshold` 傳給 `query_points()`。已核對 `query_points_groups()` 簽章同樣支援 `score_threshold` 參數，實作該分支時務必一併帶入，否則會遺失分數門檻過濾，讓低相關度的點位也被納入分組結果。

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

### 4.1 `group_size` 參數取捨

> 因已決議以 `filename`（而非 `parent_id`）作為 `group_by` 依據，`group_size` 的意義從「同一 Parent 區塊最多幾個 Child Chunks」變成「**同一份檔案最多幾筆結果**」，取捨考量也隨之改變，`group_size=1` 的風險比原始草案更明顯，需特別留意：

* **`group_size = 1`**：
  * **優點**：跨檔案多樣性最大化，`top_k=5` 一定涵蓋 5 份不同的檔案。
  * **風險（較原始草案更明顯）**：若同一份長文件（不論有無 `parent_id`）恰好有多個不同章節都與問題強相關，因為現在是以「整份檔案」為分組單位，這些章節會**全部只剩 1 筆**，可能砍掉原本應該一起呈現、答案分散在多章節的完整脈絡。
* **`group_size = 2～3`**：
  * **優點**：允許同一檔案提供最多 2～3 個重點段落，平衡「單檔深度」與「跨檔廣度」，緩解上述風險。
  * **代價**：`top_k` 個分組合計可能回傳到 `top_k × group_size` 筆點位，LLM Context 長度需求隨之增加。
* **建議**：初始實作採 `group_size=2～3`（而非原始草案的 1），並在 6.1 節新增的「同檔案多章節」測試場景中實測驗證，確認跨章節問題仍能取得完整答案後再視情況調整。

### 4.2 核心檢索與 Two-Step 關聯搜尋（2nd-hop）相容性

1. **`search_similar()`**：第一階段核心檢索可直接切換為 Group By，且**需套用到 `vector`／`hybrid`／`semantic_hybrid` 三種 `search_type`**——現行 `search_limit` 計算與後續去重截斷邏輯（[qdrant_service.py:367](../../backend/services/qdrant_service.py:367)、[qdrant_service.py:496-602](../../backend/services/qdrant_service.py:496)）在三種 `search_type` 下是同一段共用程式碼，多樣性丟失風險並非純向量查詢獨有，Hybrid／語義混合的 RRF 融合與既有 Parent-Child 內容合併都不會避免這個問題（詳見文件開頭「2026-07-13 補充澄清」）。
2. **`search_similar_two_step()`**：第二階段（2nd-hop 鄰居點位搜尋，[qdrant_service.py:630-736](../../backend/services/qdrant_service.py)）同樣使用 `query_points` 拉取鄰居。鄰居拉取是否也要走 Group By，需評估是否要避免同一關聯檔案佔滿所有鄰居名額。
3. **`disable_parent_merge=True` 分支**：
   當呼叫端明確要求不進行 Parent-Child 合併時（例如：無 parent 概念的微型點位搜尋），應**維持原本的 `query_points` 路徑**，避免強制分組造成非預期的點位遺失。

### 4.3 【阻塞性問題】缺少 `parent_id` 的點位會被 Group By 完全排除

#### 4.3.1 實測結果

用臨時測試 Collection 建立 5 筆點位（3 筆有 `parent_id`：P1 x2、P2 x1；2 筆完全不寫入 `parent_id` 欄位），分別以一般 `query_points()` 與 `query_points_groups(group_by="parent_id")` 查詢：

| 查詢方式 | 回傳筆數 | 說明 |
|:---|:---:|:---|
| `query_points()`（現行作法） | 5 筆 | 正確包含全部點位，含 2 筆無 `parent_id` 者 |
| `query_points_groups(group_by="parent_id")` | 3 筆（2 個分組） | **無 `parent_id` 的 2 筆點位完全消失**，未被歸入任何「空值分組」，也沒有 fallback 機制 |

這代表原第 6.1 節第 2 項「驗證未設定 `parent_id` 的點位在 Group By 運作下是否能正常回傳」這項測試，答案已確定為：**不能，會被靜默排除**。

#### 4.3.2 這不是邊角案例，而是會影響大量一般文件的真實風險

已對照程式碼確認：
- [chunking_service.py](../../backend/services/chunking_service.py) 的標準切分方法 `ChunkingService.split_text()`，其輸出**從不包含 `parent_id` 欄位**。
- [embedding.py:325](../../backend/routers/embedding.py:325) 顯示，只有 `.4fd`/`.4gl`（`parent_child_chunker`）與 `.md`（`markdown_parent_child_chunker`）這幾種結構化格式才會走 Parent-Child 切分並產生 `parent_id`；**其餘一般文件（純文字、一般 PDF 等）都是走這條「標準切分」路徑（[embedding.py:325](../../backend/routers/embedding.py:325)），完全不會有 `parent_id`。**

換言之，一旦 `search_similar()` 切換為以 `parent_id` 做 Group By，知識庫中任何用標準切分上傳的一般文件，其 Chunks 會在檢索時被**整批靜默排除**，而不只是排名變差、或多樣性不足——這是嚴重的檢索完整性回歸，且發生範圍不是理論上的極端情況，而是任何未使用 `.4fd`/`.4gl`/`.md` 結構化格式上傳的一般文件都會受影響。

（目前正式環境的 `kb_6a389dc83578b9d3d717244d` Collection 剛好全部 3366 筆點位都有 `parent_id`，但這只是巧合，不代表其他既有或未來知識庫也是如此，不能作為此問題不存在的依據。）

#### 4.3.3 因應方向：已決議採用方向 A

* **✅ 方向 A（已決議採用）：改用一定存在的欄位作為 `group_by`，即 `filename`**——已確認所有寫入路徑（`upsert_chunks`／`upsert_semantic_json_chunks`）都保證 `filename` 有預設值（`"unknown"`），不會缺漏，因此不論是否有 `parent_id`、不論是 Parent-Child 切分或標準切分文件，都能正常參與分組，不會再有點位被排除的問題。副作用（同一份檔案的不同章節會互相競爭同一組名額）已在第 4.1 節調整 `group_size` 為 2～3 因應，並在第 6.1 節新增對應測試場景。
* **方向 B（暫不採用）：在寫入端替沒有 `parent_id` 的標準切分 Chunks 補一個唯一值**，使其自成一個單筆分組。需要對既有資料做欄位回填遷移，工程量較大，且無法解決標準切分文件本身的多樣性問題（因為每個標準切分 Chunk 都會是獨立分組，Group By 對它們形同虛設）。
* **方向 C（暫不採用）：拆成兩條查詢路徑**（有 `parent_id` 走 Group By、無 `parent_id` 走現行邏輯）再合併結果。實作複雜度最高，需要維護兩份 Prefetch／RRF 邏輯與額外的合併排序設計，相對方向 A 投報率較低。

若日後方向 A 搭配 `group_size=2～3` 測試後，仍發現「同一份長檔案跨章節的答案被截斷」是常態性問題，可再回頭評估方向 B／C 是否值得投入。

---

## 5. Proposed Changes (建議修改檔案)

> 已決議採方向 A（`group_by="filename"`），以下為實作範圍規劃，**尚未動工，等待後續排入實作排程**。

### [MODIFY] [qdrant_service.py](file:///d:/%E6%AA%94%E6%A1%88%E5%88%86%E4%BA%AB/%E7%A8%8B%E5%BC%8F%E7%A2%BC/AiRAG/backend/services/qdrant_service.py)

- 在 `search_similar()` 中：
  - 當 `disable_parent_merge=False` 時（涵蓋 `vector`／`hybrid`／`semantic_hybrid` 三種 `search_type`），將 `client.query_points()` 替換為 `client.query_points_groups()`。
  - 傳參調整為 `group_by="filename", group_size=2~3, limit=top_k`（實際 `group_size` 依 4.1 節測試結果調校）。
  - 純向量搜尋分支需一併帶入 `score_threshold`（見 3.1 節注意事項）。
  - 調整 response 轉換邏輯，從 `response.groups` 解析 hit 點位。
  - 移除舊有在應用層迴圈進行 `seen_parents` 去重與 `[:top_k]` 截斷的 redundant 程式碼。
- 若 4.2 節決議 `search_similar_two_step()` 的 2nd-hop 鄰居搜尋也要套用 Group By，需一併列入本節修改範圍（目前尚未決定，暫不列入）。

---

## 6. 驗證與測試計畫

### 6.1 測試場景驗證
1. **多樣性驗證**：在含有單一檔案多 Chunks 的知識庫中進行查詢，驗證回傳的 `final_results` 筆數與相異 `filename` 數量確實達到 `top_k`。
2. **無 Parent ID 資料相容性**：驗證未設定 `parent_id` 的標準切分文件點位，在改用 `filename` 分組後能正常出現在檢索結果中（對照 4.3.1 節的實測方法，確認這次不會再被排除）。
3. **同檔案多章節驗證（因改用 `filename` 分組而新增）**：針對同一份長文件中確實有多個不同章節都與問題強相關的情境進行查詢，確認 `group_size=2～3` 下這些章節仍能一併出現，回答不會因為分組粒度變粗而遺漏關鍵章節。若仍有遺漏，需回頭調高 `group_size` 或評估 4.3.3 節的方向 B／C。
4. **Two-Step 關聯檢索驗證**：驗證雙階段檢索完整流程不受影響，`semantic_score` 重算正確。
5. **混合知識庫驗證**：使用同時包含「標準切分文件」與「Parent-Child 切分文件」的知識庫進行查詢，確認兩種文件皆能出現在結果中，且多樣性效果對兩者都成立。
6. **跨 `search_type` 驗證**：分別以 `vector`、`hybrid`、`semantic_hybrid` 三種 `search_type` 重複第 1～5 項測試，確認 Group By 效果與相容性在三種模式下一致（見文件開頭「2026-07-13 補充澄清」）。

### 6.2 效能與延遲比較
- 比較 `query_points_groups` 與原本 `query_points` 的 Qdrant 查詢響應時間（ms），確認 Qdrant 端 Group By 的 overhead 屬於微秒/毫秒等級，不會帶來額外延遲。
- 建議評估是否需要對 `filename` 欄位建立 Payload Index 以提升大型 Collection 的分組效能（現行 `create_collection()` 僅對 `content` 建立 text index，`filename` 目前沒有索引）。
