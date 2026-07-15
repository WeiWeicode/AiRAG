# Qdrant 檢索查詢優化建議方案

本文件針對 [/backend/services/qdrant_service.py](file:///Users/wei/Code/AiRAG/backend/services/qdrant_service.py) 現有的檢索設計（特別是 `search_similar` 與 `search_similar_two_step` 方法）進行評估，並記錄未來可行的四大優化方向。

現有架構已實現極為先進的 Hybrid 檢索（Dense + Sparse）、RRF 融合、動態關鍵字增強（Exact Keyword Boost）、Parent-Child 還原合併以及雙階段關聯檢索（Two-Step Hop-2）。然而，在極端或特定大規模生產場景下，仍有以下方向可以進一步優化。

> **2026-07-13 複核**：已逐行對照現行 `backend/services/qdrant_service.py` 與實際安裝的 `qdrant-client 1.18.0`（`requirements.txt` 要求 `>=1.8.0`），確認下述四個問題點目前均仍存在。複核中並發現方向一原範例程式碼使用的方法名稱有誤，已於該節修正並補充實作風險說明。

## 建議實作優先順序

| 順序 | 方向 | 風險 | 效益/性質 | 建議 |
|:---:|:---|:---:|:---|:---|
| 1 | 方向三：併行 Sibling 檢索 | 低 | 純效能優化，不改變檢索結果 | 可直接實作 |
| 2 | 方向四：元資料分頁滾動 | 低 | 修正正確性問題（超過 10000 點位會漏資料） | 可直接實作 |
| 3 | 方向二：中文 Tokenizer | 低～中 | 修正 Exact Keyword Boost 對中文幾乎失效的功能性問題 | 可實作，但需重建既有 Collection 的 text index |
| 4 | 方向一：Group By 多樣性 | 中～高 | 解決檢索多樣性丟失，但改動核心共用檢索路徑 | 建議獨立立案，先於測試環境驗證後再上線 |

排序原則：優先做風險低、不影響現有行為的項目（三、四），再做雖是設定變更但需要重建索引的項目（二），最後做影響面最大、牽動 `search_similar` 與 `search_similar_two_step` 共用邏輯的項目（一）。

## 建議優化方向一：引入 Qdrant Group By 解決多樣性丟失問題

> **獨立規劃文件**：詳細影響評估、`query_points_groups` 簽章與驗證計畫已獨立立案於 [NewFeaturesPlan_QdrantGroupByOptimizationPlan.md](NewFeaturesPlan_QdrantGroupByOptimizationPlan.md)。

### 1. 現狀分析
在現有的 `search_similar` 方法中，系統預設的拉取點位上限為：
```python
search_limit = top_k if disable_parent_merge else max(top_k * 4, 20)
```
如果一份長文件與使用者問題高度相關，且被切碎成許多 Child Chunks，則這 20 筆召回結果可能全部被該文件的 Chunks 佔滿。在經過 `parent_id` 去重並截斷至 `top_k`（例如 5）後，最終可能**只剩下一份文件**。這會導致檢索的多樣性丟失，LLM 無法獲取其他同樣相關的參考文件。

### 2. 優化方案
使用 Qdrant 原生的 **Group By（搜尋分組）** 功能。在檢索時以 `parent_id` 作為分組依據，限制每個 `parent_id` 最多只回傳 1 或 2 個分數最高的 Child Chunks，取代現行「先擴大 `search_limit = max(top_k*4, 20)` 拉取，再於應用層依 `parent_id` 去重截斷」的作法——後者在單一文件的相關 Chunks 遠超過 `top_k*4` 時仍可能被洗版，Group By 由 Qdrant 端原生保證多樣性，沒有這個上限問題。

### 3. 程式碼修改示意（非同步 API）
```python
from qdrant_client import models

# 注意：AsyncQdrantClient 實際方法名稱為 query_points_groups（非 query_groups）。
# 已於 qdrant-client 1.18.0 核對其簽章，確認支援 prefetch / FusionQuery / query_filter，
# 可沿用現行 search_similar() 內既有的 Dense+Sparse+Exact-keyword 三路 prefetch 邏輯。
response = await client.query_points_groups(
    collection_name=collection_name,
    prefetch=prefetch_list,               # 沿用現行 dense/sparse/exact-keyword 三路 Prefetch
    query=models.FusionQuery(fusion=models.Fusion.RRF),
    group_by="parent_id",
    group_size=1,  # 每個 parent 只取最相關的 1 筆，可視情況調整為 2（見下方注意事項）
    limit=top_k,   # 回傳 top_k 個不同的 parent 分組
    query_filter=query_filter,
    with_payload=True,
    with_vectors=[""]  # 供 _compute_semantic_score 重算 cosine 分數用，做法與現行一致
)
# 遍歷分組提取點位（group.hits 依分數排序，取每組最相關的第一筆）
results = [group.hits[0] for group in response.groups if group.hits]
```

### 4. 實作注意事項
* **影響面**：`search_similar` 是 `search_similar_two_step` 第一階段（1st-hop）與第二階段（2nd-hop 鄰居查詢）共用的核心邏輯，兩處的 Prefetch 組裝、Exact Keyword Boost、`is_rrf_fusion`／`semantic_score` 重算、Parent-Child 還原合併都需要同步檢視是否受影響，不能只改 1st-hop。
* **`group_size` 取捨**：設為 1 可最大化文件多樣性，但若同一文件內確實存在多個不同重點段落，可能被過度收斂成單一 Chunk；建議先以 `group_size=2` 在測試集合上比較召回品質，再決定是否收斂為 1。
* **與現行去重邏輯的關係**：導入 Group By 後，現行第 2 步「依 `parent_id` 去重」與第 2.5 步「截斷至 `top_k`」可整段移除（由 Qdrant 端原生保證），但 `disable_parent_merge=True` 的呼叫路徑（不需要 parent-child 合併時）要確認是否仍要走 Group By，或維持原本 `query_points` 路徑。
* **建議獨立立案**：由於改動範圍橫跨核心共用路徑，建議與方向二～四分開排程，先在測試環境以實際知識庫資料驗證 Two-Step 檢索的鄰居品質與回應延遲皆無退化後，再上線。

---

## 建議優化方向二：優化中文全文檢索分詞（Tokenizer）

### 1. 現狀分析
在建立 Collection 的 Text Index 時，現行 Tokenizer 被設定為 `WORD`：
```python
tokenizer=models.TokenizerType.WORD
```
`WORD` 分詞器是為英文等以空格分隔的語言設計的。對於中文而言，由於句子中沒有空格，`WORD` 僅能將整個中文句子當作單一 Token，或僅在標點符號處切分，這會導致精確關鍵字匹配（Exact keyword boost，使用 `models.MatchText`）在中文查詢中幾乎失效。

### 2. 優化方案
將 `content` 欄位的 Text Index Tokenizer 調整為 `multilingual`（多語言分詞器）或 `whitespace`，甚至依據 Qdrant 版本配置支援中文的分詞機制。

### 3. 程式碼修改示意
在 `create_collection` 方法中：
```python
await client.create_payload_index(
    collection_name=collection_name,
    field_name="content",
    field_schema=models.TextIndexParams(
        type="text",
        tokenizer=models.TokenizerType.MULTILINGUAL,  # 支援多語言分詞
        lowercase=True
    )
)
```
（已核對 `qdrant-client 1.18.0` 的 `models.TokenizerType` 確實提供 `MULTILINGUAL` 選項，可直接使用。）

### 4. 實作注意事項
* **既有 Collection 需重建索引**：此變更本質上是修正一個功能性問題——現行 `WORD` Tokenizer 下，中文查詢的 Exact Keyword Boost（`models.MatchText`）幾乎不會命中。但既有 Collection 已建立的 text index 不會自動套用新設定，需針對每個既有 Collection 重新呼叫 `create_payload_index`，Qdrant 會對集合內既有點位重新索引；資料量大的 Collection 建議排在離峰時段執行，避免佔用過多資源影響線上查詢。
* **驗證方式**：建議先在測試 Collection 上比較調整前後，針對中文關鍵字查詢的 Exact Keyword Boost 命中率與 Hybrid 檢索排序結果，確認確實改善後再套用到生產 Collection。

---

## 建議優化方向三：併行/批次 Sibling 節點檢索以降低 I/O 延遲

### 1. 現狀分析
在 RRF 融合或向量檢索完成後，系統需要還原完整的 Parent Content：
```python
# 迴圈中依序 await 查詢
for item in deduped_results:
    ...
    if not parent_content:
        parent_content, parent_range, image_chunks = await cls.get_siblings_and_merge(...)
```
如果在結果中有 5 個不同的 `parent_id`，系統將**依序（Sequential）進行 5 次獨立的 `scroll` 網路請求**。這會造成嚴重的線頭阻塞（Head-of-Line Blocking），顯著增加 API 的響應時間。

### 2. 優化方案
* **方案 A（併行請求）**：使用 `asyncio.gather` 同時發起所有 sibling 獲取請求。
* **方案 B（批次查詢）**：收集所有需要查詢的 `parent_id` 清單，使用一個 `scroll` 請求配上 `MatchAny` 條件一次性拉回所有兄弟節點，再於記憶體中完成分組與合併。

### 3. 程式碼修改示意（以方案 A 為例）
```python
import asyncio

tasks = []
for item in deduped_results:
    parent_id = item["metadata"].get("parent_id")
    if parent_id and not item["metadata"].get("parent_content"):
        tasks.append(
            cls.get_siblings_and_merge(
                collection_name=collection_name,
                parent_id=parent_id,
                orig_content=item["content"],
                metadata=item["metadata"]
            )
        )
    else:
        tasks.append(None)  # 保持索引對齊

# 併行執行
merge_results = await asyncio.gather(*[t for t in tasks if t is not None])

# 回填結果
merge_idx = 0
for i, item in enumerate(deduped_results):
    if tasks[i] is not None:
        parent_content, parent_range, image_chunks = merge_results[merge_idx]
        # 更新 item 的 content 與 metadata ...
        merge_idx += 1
```

### 4. 實作建議
優先採用**方案 A（併行請求）**：改動範圍小（僅迴圈邏輯，不改變既有 `get_siblings_and_merge` 內部實作與回傳結構），風險最低，且 `search_similar` 與 `search_similar_two_step` 兩處呼叫皆可套用同一套改法。方案 B（批次 scroll）雖然理論上網路請求數更少，但需要重寫 `get_siblings_and_merge` 內部依 `parent_id` 分組合併的邏輯，改動較大，建議留待方案 A 效果不夠時再評估。

---

## 建議優化方向四：解決元資料快取的滾動限制（Pagination）

### 1. 現狀分析
在 `get_unique_metadata` 方法中，系統使用快取機制來儲存集合中的所有唯一檔名與標籤，但其拉取邏輯中寫死了 `limit=10000`：
```python
scroll_result = await client.scroll(
    collection_name=collection_name,
    limit=10000,
    with_payload=["filename", "tags", "class", "links_to", "linked_attachments"],
    with_vectors=False
)
```
如果 Collection 內的文件與 Chunks 總量超過 10,000 個，後續的 Chunks 就無法被拉出，導致元資料選單漏失部分檔案或標籤。

### 2. 優化方案
實作分頁滾動（Pagination / Cursor Scroll），利用 `scroll_result[1]`（`next_page_offset`）持續迭代，直至拉取完 Collection 內所有點位。

### 3. 程式碼修改示意
```python
filenames = set()
tags = set()
structured_map = {}
offset = None

while True:
    scroll_result = await client.scroll(
        collection_name=collection_name,
        limit=1000,  # 每次分頁抓取
        offset=offset,
        with_payload=["filename", "tags", "class", "links_to", "linked_attachments"],
        with_vectors=False
    )
    points, next_offset = scroll_result
    
    for p in points:
        # 解析並收集 metadata ...
        ...

    if not next_offset:
        break
    offset = next_offset
```

### 4. 相關發現
`get_by_parent_id`（同檔案內，用於撈取單一 `parent_id` 下所有 Child Chunks 以還原內容）同樣寫死 `limit=1000`。單一 Parent Block 的 Chunks 數量正常情況下遠低於此上限，暫不視為急迫問題，但若日後發現超長文件被切成大量 Child Chunks 導致合併內容缺漏，可比照本方向的分頁邏輯一併修正。
