<!-- 後端修正紀錄(最新紀錄放最前面) -->

## 2026-07-13 Qdrant 檢索查詢優化（中文 Tokenizer 設定與既有索引自動升級）

### 背景
依優化規劃文件 [QdrantRetrievalOptimizationPlan.md](QdrantRetrievalOptimizationPlan.md) 實作建議優先順序第 3 項目（方向二：優化中文全文檢索分詞 Tokenizer）。原本的 `models.TokenizerType.WORD` 是針對英文空格切分，導致中文查詢時的 Exact Keyword Boost（`models.MatchText`）幾乎無法命中。

### 變更內容
- [qdrant_service.py](file:///d:/%E6%AA%94%E6%A1%88%E5%88%86%E4%BA%AB/%E7%A8%8B%E5%BC%8F%E7%A2%BC/AiRAG/backend/services/qdrant_service.py)：
  - 在 `create_collection()` 方法中，將 `content` Payload 欄位的 Text Index Tokenizer 從 `WORD` 調整為 `MULTILINGUAL`（多語言/中文分詞器）。
  - 新增 `ensure_all_collections_payload_index()` 方法，自動遍歷 Qdrant 中所有 Collection 並升級 `content` 欄位的 Text Index 至 `MULTILINGUAL`。
- [mongodb.py](file:///d:/%E6%AA%94%E6%A1%88%E5%88%86%E4%BA%AB/%E7%A8%8B%E5%BC%8F%E7%A2%BC/AiRAG/backend/models/mongodb.py)：
  - 在後端啟動初始化邏輯 `init_mongodb()` 中呼叫 `QdrantService.ensure_all_collections_payload_index()`，讓現存的舊 Collection 於系統啟動時自動在背景完成中文分詞索引升級重建，無須手動執行重建指令或重灌向量資料。

### 驗證
- 語法編譯檢查（`python -m py_compile backend/services/qdrant_service.py backend/models/mongodb.py`）通過。

## 2026-07-13 Qdrant 檢索查詢優化（併行 Sibling 檢索與元資料分頁滾動）

### 背景
依優化規劃文件 [QdrantRetrievalOptimizationPlan.md](QdrantRetrievalOptimizationPlan.md) 實作建議優先順序第 1 與 2 項目（方向三與方向四）。

### 變更內容
- [qdrant_service.py](file:///d:/%E6%AA%94%E6%A1%88%E5%88%86%E4%BA%AB/%E7%A8%8B%E5%BC%8F%E7%A2%BC/AiRAG/backend/services/qdrant_service.py)：
  - **方向三（併行 Sibling 檢索）**：在 `search_similar()` 與 `search_similar_two_step()` 的 Parent-Child 還原合併階段，將原本依序串行（Sequential）執行的 `await cls.get_siblings_and_merge()` / `await cls.get_image_siblings()` 改為使用 `asyncio.gather()` 非同步併行執行。消除 Head-of-Line Blocking，顯著降低 1st-hop 與 2nd-hop 的 I/O 響應時間。
  - **方向四（元資料分頁滾動）**：在 `get_unique_metadata()` 中將一次性截斷抓取 `limit=10000` 改為基於 Cursor Pagination 的 `while True` 滾動分頁（每頁 1000 筆，迭代至 `next_offset` 為空），解決大規模 Collection（超過 10,000 點位）時元資料選單漏失檔案與標籤的問題。

### 驗證
- 語法編譯檢查（`python -m py_compile backend/services/qdrant_service.py`）通過。
