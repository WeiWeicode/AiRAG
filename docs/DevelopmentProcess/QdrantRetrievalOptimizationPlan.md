# Qdrant 檢索查詢優化建議方案

本文件針對 [/backend/services/qdrant_service.py](file:///Users/wei/Code/AiRAG/backend/services/qdrant_service.py) 現有的檢索設計（特別是 `search_similar` 與 `search_similar_two_step` 方法）進行評估，並記錄未來可行的四大優化方向。

現有架構已實現極為先進的 Hybrid 檢索（Dense + Sparse）、RRF 融合、動態關鍵字增強（Exact Keyword Boost）、Parent-Child 還原合併以及雙階段關聯檢索（Two-Step Hop-2）。然而，在極端或特定大規模生產場景下，仍有以下方向可以進一步優化。

---

## 建議優化方向一：引入 Qdrant Group By 解決多樣性丟失問題

### 1. 現狀分析
在現有的 `search_similar` 方法中，系統預設的拉取點位上限為：
```python
search_limit = top_k if disable_parent_merge else max(top_k * 4, 20)
```
如果一份長文件與使用者問題高度相關，且被切碎成許多 Child Chunks，則這 20 筆召回結果可能全部被該文件的 Chunks 佔滿。在經過 `parent_id` 去重並截斷至 `top_k`（例如 5）後，最終可能**只剩下一份文件**。這會導致檢索的多樣性丟失，LLM 無法獲取其他同樣相關的參考文件。

### 2. 優化方案
使用 Qdrant 原生的 **Group By（搜尋分組）** 功能。在檢索時以 `parent_id` 作為分組依據，限制每個 `parent_id` 最多只回傳 1 或 2 個分數最高的 Child Chunks。

### 3. 程式碼修改示意（非同步 API）
```python
from qdrant_client import models

# 使用 query_groups 替代 query_points
response = await client.query_groups(
    collection_name=collection_name,
    query=query_vector,  # 或 FusionQuery
    group_by="parent_id",
    group_size=1,  # 每個 parent 只取最相關的 1 筆
    limit=top_k,   # 回傳 top_k 個不同的 parent 分組
    query_filter=query_filter,
    with_payload=True
)
# 遍歷分組提取點位
results = [group.hits[0] for group in response.groups if group.hits]
```

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
