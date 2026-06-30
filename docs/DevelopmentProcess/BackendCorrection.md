<!-- 後端修正紀錄 -->

## 2026-06-30 自動化評估端點 `/run` 支援語義混合查詢（Semantic Hybrid Search）

### 修改內容
1. `backend/routers/evaluation.py` (修改):
   - **調整評估內嵌之檢索邏輯**：於 `run_evaluation` 評估任務迴圈中，檢查傳入之 `search_type`。若為 `semantic_hybrid`，則先調用 Instruct AI 進行提問重寫與關鍵字提取，取得密集與稀疏特徵後對 `embeddings_input` 進行向量化，並將 `sparse_keywords` 拼接成稀疏文本提供給 Qdrant 進行混合檢索跑分，確保評估時使用的背景上下文檢索機制與實際對話、搜尋一致。

## 2026-06-30 擴充向量檢索端點 `/semantic-hybrid-search` 語義化分析與回傳資料

### 修改內容
1. `backend/schemas/retrieval.py` (修改):
   - **擴充 `RetrievalResponse` 欄位**：新增 `semantic_json`、`embeddings_input`、`sparse_keywords`、`query_vector_preview` 與 `vector_size` 等可選屬性，以便將中間分析過程回傳給檢索測試頁面。
2. `backend/routers/retrieval.py` (修改):
   - **優化 `/semantic-hybrid-search` 實作**：將其調整為與 RAG 對話路由一致的雙階段處理——先呼叫 Instruct AI 將提問轉為結構化 JSON，再針對產生的 `embeddings_input` 進行語義向量化，並使用 `sparse_keywords` 執行稀疏向量檢索，最後將所有過程的元資料隨檢索結果一同打包回傳給前端。

## 2026-06-30 串接 Instruct 語義化 AI 將提問轉 JSON 與向量化 embeddings_input

### 修改內容
1. `backend/services/embedding_service.py` (修改):
   - **新增 `query_to_semantic_json` 方法**：實作將使用者提問發送至 `settings.DENSE_VECTOR_LLAMACPP_BASE_URL` 的 chat completions 端點，並指示 AI 轉換成帶有 `embeddings_input` 與 `sparse_keywords` 的 JSON。當請求失敗時，採用動態降級產出之預設 JSON。
   - **修正 `get_semantic_embedding` 呼叫端點**：將原呼叫 `settings.DENSE_VECTOR_LLAMACPP_BASE_URL` (8082, Qwen3VL-Instruct 模型，無向量生成能力) 修正為呼叫 `settings.LLAMACPP_BASE_URL` (8081, Qwen3-Embedding-8B 模型)，修復生成向量回傳 0.0 之問題。
2. `backend/routers/rag.py` (修改):
   - **串接語義分析與 JSON 回傳**：在 `rag_chat_stream` 的 `semantic_hybrid` 分流中，先發送「正在進行語義分析與結構化轉換」事件，並調用 `EmbeddingService.query_to_semantic_json`。
   - **生成與檢索向量優化**：在 SSE 狀態內容中渲染產出的 JSON，以 Qwen3-Embedding-8B 密集向量模型對 `embeddings_input` 欄位進行向量化，並將 `sparse_keywords` 拼接成用以執行稀疏檢索的文本。修正日誌步驟中顯示的模型名稱與 Base URL 為正確的 `EMBEDDING_MODEL` 與 `LLAMACPP_BASE_URL`。
3. `backend/routers/embedding.py` (修改):
   - **修正 `vectorize-json` 回傳模型資訊**：將回傳 payload 中的 `embedding_model` 欄位由 `settings.DENSE_VECTOR_INSTRUCT_MODEL` 修正為 `settings.EMBEDDING_MODEL`，維持一致性。

## 2026-06-30 修正 RAG 對話路由之 f-string 反斜線語法錯誤與導入設定檔

### 修改內容
1. `backend/routers/rag.py` (修改):
   - **導入 settings**：新增 `from config import settings` 導入語句，修正變數 `settings` 未定義之問題。
   - **獨立 JSON 字典宣告**：將 `rag_chat_stream` 函式中發送「語義分析」與「向量資料查詢」之事件 payload 字典移出 f-string，改為在 `yield` 前先定義為局部變數（`step_data`），避免在 Python 3.12 之前的版本中因 f-string `{}` 內含反斜線而引發 `SyntaxError`。

## 2026-06-30 修正 SQL Server (FreeTDS) 與資料庫設定參數之空白修剪

### 修改內容
1. `backend/routers/database_indexing.py` (修改):
   - **`get_db_connection` 函數**：在與資料庫建立連線前，對 `host`、`database` 及 `username` 進行 `.strip()` 修剪，防止尾隨空格導致 FreeTDS 解析失敗。
   - **`/configs` 儲存與修改端點**：於 `create_config` 與 `update_config` 端點中，將 `name`、`db_type`、`host`、`database` 與 `username` 進行 `.strip()`，以維持 MongoDB 中設定資料的潔淨度。

## 2026-06-29 支援 Genero .4fd 畫面定義檔大小雙層切分與 API 分流

### 修改內容
1. `backend/services/parent_child_chunker.py` (修改):
   - **實作 .4fd XML 大小雙層解析器**：新增 `parse_4fd_to_parents` 解析 `.4fd` XML 結構，提取 `Layout`、`FormItems`、`BindFiles` 及 `ScreenRecords` 節點做為 Parent Chunks，轉為完整 XML 字串。
   - **實作 .4fd XML 子片段切分器**：新增 `slice_4fd_to_children` 依區塊類別遍歷內部的 `FormItem`、`Grid`、`Table` 節點或直接子節點（例如 `BindRow`、`RecordField`）作為 Child Chunks。
   - **實作屬性提取與識別字標準化**：新增 `extract_4fd_metadata` 提取子節點的所有屬性（如 `id`、`name` 等），並將關鍵識別欄位標準化注入 rich metadata。
2. `backend/routers/embedding.py` (修改):
   - **分流路由支援**：在 `/chunk` 路由中新增 `.4fd` 檔案類型之 parent-child 分流與切分調用。
3. `scripts/parent_child_chunker.py` (修改):
   - **CLI 與通用入口整合**：同步新增 `.4fd` 切分函數，並重構 `process_file` 與主程式引數解析，使其支援對 `.4fd` 檔案之切分。

## 2026-06-29 修正資料庫匯入向量化之舊點清理邏輯與知識庫計數方式

### 修改內容
1. `backend/routers/database_indexing.py`：
   - 將在寫入 Qdrant 之前刪除重複匯入的資料庫備份點所誤呼叫的 `QdrantService.delete_by_filter` 方法替換為 `QdrantService.delete_by_filename`，解決 `delete_by_filter` 方法不存在引發的 500 錯誤。
   - 接收從 `QdrantService.delete_by_filename` 回傳的已刪除向量點計數 `deleted_count`。
   - 更新 MongoDB 中的 `kb.chunk_count` 時，使用 `max(0, kb.chunk_count - deleted_count + inserted_total)` 代替原先直接累加的方式，以確保當存在重複匯入更新時，知識庫的點數量計數依然維持準確無誤。

## 2026-06-29 支援 Oracle 11g 資料庫連線與修正 SQL 查詢 Date 型態解析錯誤

### 修改內容
1. **Dockerfile 擴充**：
   - 於 `backend/Dockerfile` 中，針對 Debian Trixie (Debian 13) 系統安裝 `libaio1t64` 依賴。
   - 由於 Oracle Instant Client 需要 `libaio.so.1` 軟連結，在 Dockerfile 中建立符號連結：`ln -s /usr/lib/x86_64-linux-gnu/libaio.so.1t64 /usr/lib/x86_64-linux-gnu/libaio.so.1`。
   - 下載、解壓並配置 Oracle Instant Client 19c (Linux x64)，寫入系統 `ldconfig`，並設定環境變數 `ORACLE_HOME` 與 `LD_LIBRARY_PATH`，藉此完成容器內的 Oracle 用戶端底層環境布署。
2. **啟用 Oracle Thick Mode**：
   - 在 `backend/routers/database_indexing.py` 模組載入時，加入 `oracledb.init_oracle_client()` 呼叫，使 `python-oracledb` 進入 Thick Mode，進而支援對舊版 Oracle 資料庫（如 11g 版本）的向下相容連線。
   - 移除了先前引起報錯的 `request_timeout` 參數。
3. **修復 isinstance() 型態檢查錯誤**：
   - 修正了 `backend/routers/database_indexing.py` 中 `fetch_metadata` 與 `ingest_database` 的欄位資料型態過濾邏輯。
   - 原先程式碼中使用 `isinstance(val, (datetime, datetime.date))`，但由於頂部已宣告了 `from datetime import datetime`，此處 `datetime` 指向類別而 `datetime.date` 成了該類別的 `date()` 方法（非型態/類別），導致 isinstance 拋出 `isinstance() arg 2 must be a type, a tuple of types, or a union` 錯誤。
   - **修正方法**：修改導入為 `from datetime import datetime, date`，並將檢查式更正為 `isinstance(val, (datetime, date))`。

## 2026-06-26 新增 MongoDB 標籤與類別路由、擴充 Qdrant "class" 欄位讀寫支援

### 修改內容
1. `backend/models/tag.py` & `backend/models/class_option.py` (新增):
   - 實作 Beanie MongoDB Document models：`Tag` 與 `ClassOption`，用於儲存與查詢自訂的標籤與類別選項。
2. `backend/models/mongodb.py`:
   - 於 Beanie 初始化註冊列表 `document_models` 中導入並加入 `Tag` 與 `ClassOption`。
3. `backend/schemas/embedding.py`:
   - 新增 `TagCreate` 與 `ClassOptionCreate` Pydantic schemas。
4. `backend/schemas/retrieval.py`:
   - 修改 `RetrievalMetadata` schema，新增 `class_list` (別名為 `"class"`)，以允許將從 Qdrant 查詢回傳的 `"class"` 陣列欄位自動對照與映射為 `class_list`。
5. `backend/routers/embedding.py`:
   - 新增 `GET /api/embedding/tags`, `POST /api/embedding/tags` 路由，提供分類標籤之獲取與新建。
   - 新增 `GET /api/embedding/classes`, `POST /api/embedding/classes` 路由，提供類別選項之獲取與新建。
   - 於向量化端點 `/vectorize` 中，提取 chunk metadata 中的 `classes` (或 `class`)，並以 `"class"` 鍵值存入 Qdrant payload。
6. `backend/routers/retrieval.py`:
   - 於檢索端點中，將從 Qdrant 取得之 `"class"` metadata 欄位對照還原回傳，確保檢索出的 Points 均能正確攜帶 `"class"` 欄位返給前端。

## 2026-06-25 移除向量化預存 parent_content 以優化 Qdrant 資料量，並調整 Nginx 上傳限制

### 修改內容
1. `backend/routers/embedding.py`:
   - 移除向量化切分時注入 metadata 的 `parent_content`。此優化阻斷了每個 Child Chunk 重複儲存數百 KB 父程式碼內容的問題，避免大檔案批次寫入時 payload 因千倍膨脹引發 `413 Request Entity Too Large` 錯誤與 Qdrant 儲存空間浪費。
2. `nginx.conf`:
   - 於 `server` 區段中新增 `client_max_body_size 100m;`，放寬 Nginx 反向代理的上傳檔案與寫入請求 Body 大小限制，以完美支援大檔案分切上傳及批次處理。
3. `運行指令實施配置`:
   - 執行 `docker exec airag-frontend nginx -s reload` 指令動態重載前端 Nginx 服務，令新設定生效。

## 2026-06-25 實作 Parent-Child 檢索去重與兄弟節點自動拼接合併還原

### 修改內容
1. `backend/routers/embedding.py`:
   - 於 Parent-Child 分切或 `.4gl` 程式碼分切時，主動計算每一個父區塊 (Parent Block) 所分切出的子片段 (Child Chunks) 索引範圍 `parent_chunk_index_range`（如 `"4~16"`）。
   - 將完整的 `parent_content` 內容及該範圍字串注入至每個子片段的 `metadata` 中，並隨向量化保存至 Qdrant 中。
2. `backend/schemas/retrieval.py`:
   - 修改 `RetrievalMetadata` schema，將 `chunk_index` 的資料類型改為 `Optional[Any] = None`，以容許接收並回傳包含連接符號的區間範圍字串。
3. `backend/services/qdrant_service.py`:
   - **兄弟去重機制**：於 `search_similar` 召回結果後，遍歷所有 results，依據 `parent_id` 進行唯一性去重，僅保留相似度分數最高的子片段，避免重複傳送相同的父區塊上下文。
   - **元資料還原 (情況 A)**：若檢索點的 Qdrant Payload 中已帶有 `parent_content` 與範圍欄位，則對其結構化樣式（若以 `[檔案名稱]` 開頭）進行重建拼接，替換為完整的父區塊程式碼。
   - **動態拼接還原 (情況 B，相容舊資料)**：若檢索點中無預存 Parent 內容（相容先前已建索引之舊有資料），則新增非同步輔助方法 `get_by_parent_id(collection_name, parent_id)` 以拉取所有同屬該 parent 的 child points。排序後呼叫 `get_siblings_and_merge` 進行邊界重疊區間的字元級去重拼接，動態還原出完整的程式碼與 `chunk_index` 範圍。

## 2026-06-25 修正 Docker 容器內無 scripts 模組導致的文本切分 500 錯誤

### 修改內容
1. **背景原因**：
   - 後端 Docker 容器的建置 context 為 `./backend`，且在執行時將 `./backend` 掛載為容器的 `/app`。
   - 原先在 `backend/routers/embedding.py` 中直接嘗試自 `scripts` 專案根目錄導入 `parent_child_chunker`，導致容器內因找不到 `scripts` 資料夾而拋出 `ModuleNotFoundError: No module named 'scripts'`。
2. **解決方案**：
   - 將 `scripts/parent_child_chunker.py` 複製為後端核心服務的一部分：`backend/services/parent_child_chunker.py`，使之包含在容器 context 中。
   - 將 `backend/routers/embedding.py` 中的導入路徑從 `from scripts.parent_child_chunker ...` 修改為 `from services.parent_child_chunker ...`，順利解決 Docker 環境下的依賴導入問題。

## 2026-06-25 實作 Qdrant 依檔名刪除向量 API 與擴充 4GL 格式解析支援

### 修改內容
1. `backend/services/document_parser.py`:
   - 修改 `parse_file` 中副檔名分流邏輯。將 `4gl` 納入與 `txt`, `md` 等文字檔案相同的文字讀取與解碼分流（`parse_text`），實現對 `.4gl` 程式碼文件的正確文字提取。
2. `backend/services/qdrant_service.py`:
   - 新增 `delete_by_filename(collection_name, filename)` 非同步類別方法。使用 `AsyncQdrantClient.scroll` 加上 filename 過濾條件拉取所有符合該檔案名稱的 points 列表。
   - 提取 point id，並呼叫 `AsyncQdrantClient.delete` 進行刪除，最終返回刪除的 point 總數。
3. `backend/schemas/retrieval.py`:
   - 新增 `DeleteByFilenameRequest` Pydantic Schema，封裝 `filename: str` 欄位。
4. `backend/routers/retrieval.py`:
   - 新增 `POST /api/retrieval/knowledge-bases/{knowledge_base_id}/files/delete-by-filename` 路由端點。
   - 透過 Beanie 異步獲取指定的 `KnowledgeBase`，調用 `QdrantService.delete_by_filename` 刪除該檔案之向量。
   - 連帶更新 MongoDB 中的知識庫屬性，將 `chunk_count` 扣減已刪除之數量，並保存更新狀態回傳。

## 2026-06-25 於評估模組新增向量/混合查詢檢索模式支援並修復 fastembed OOM

### 修改內容
1. `backend/models/eval_report.py`:
   - 在 `EvalParams` schema 中加入 `search_type: Optional[str] = "vector"`，供測試報告持久化儲存時紀錄該次評估採用的檢索模式。
2. `backend/routers/evaluation.py`:
   - 在 `EvalParamsInput` 中新增 `search_type` 參數，以便接收前端發起的評估請求檢索模式。
   - 於評估進度產生器 `event_generator` 提取並傳遞 `search_type` 給相似度檢索方法 `QdrantService.search_similar`，實踐混合檢索評估。
   - 修復因取代區塊造成的 `max_tokens` 變數遺失 Bug。
3. `backend/services/sparse_embedding_service.py`:
   - 在 `get_model` 初始化 `SparseTextEmbedding` 時，顯式傳入 `model_name="prithivida/Splade_PP_en_v1"`，解決未給予核心參數造成拋出 `TypeError` 且稀疏向量回傳空值的 Bug。
   - 新增 `threads=2` 參數限制 ONNX Runtime 在計算稀疏向量時的 CPU 線程數，防範線程過多導致系統資源耗盡。
   - 在 `get_sparse_vectors_batch` 方法中將 `model.embed` 加上 `batch_size=16`，使大批次（如 170 筆）文字在推理時分批進行，降低峰值記憶體開銷，防止 Docker 容器因記憶體不足被系統強制終止 (Exit Code 137, OOM Killed)。

## 2026-06-24 調整 RAG 對話串流 (SSE) 事件傳送順序解決引用來源丟失問題

### 修改內容
1. `backend/routers/rag.py`:
   - 調整 `rag_chat_stream` 尾部事件發送順序，改為優先 yield 傳送 `sources` 引用來源事件，再 yield 傳送完成之 `done` 事件。
   - 此調整保證了即使在生產環境 (如 Nginx 反向代理、高併發或跨網域連線) 下，後端在關閉 Streaming 串流連線前，瀏覽器端均能 100% 確實且完整接收到引用文獻資料 Chunks。

## 2026-06-24 支援評估任務中自訂生成最大 Token 數 (max_tokens) 參數

### 修改內容
1. `backend/models/eval_report.py`:
   - 修改 `EvalParams` schema，新增 `max_tokens: Optional[int] = 1024` 欄位並提供預設值，確保資料庫儲存與舊資料庫欄位向前相容。
2. `backend/routers/evaluation.py`:
   - 在 `EvalParamsInput` Pydantic schema 中，新增 `max_tokens` 選填參數。
   - 修改 `/run` 串流評估 API 邏輯：從 payload.params 中解析 `max_tokens` 參數（若無則預設為 `1024`）。
   - 在呼叫對答生成服務 `LLMService.chat_completion(...)` 時，動態將該 `max_tokens` 設定傳入，取代原先寫死的 `1024`，讓使用者有能力控制超長答覆與思考流程。
   - 在最終向 Beanie / MongoDB 儲存 `EvalReport` 報告實體時，將此參數保存進報告的 `params` 欄位中，以便留存日誌查閱。

## 2026-06-24 實作 Qdrant 向量 Points 批次刪除 API 支援

### 修改內容
1. `backend/schemas/retrieval.py`:
   - 新增 `BatchDeleteRequest` Pydantic Model，定義接收點 ID 列表 (`point_ids: List[str]`)。
2. `backend/services/qdrant_service.py`:
   - 新增 `delete_points(cls, collection_name: str, point_ids: List[str]) -> bool` 方法，透過 Qdrant 異步客戶端的 `delete` 方法與 `PointIdsList` 刪除指定的一組點。
3. `backend/routers/retrieval.py`:
   - 導入 `BatchDeleteRequest` 與 `datetime`。
   - 新增 `POST /knowledge-bases/{knowledge_base_id}/points/batch-delete` 路由端點。此端點會驗證知識庫與其 Collection，呼叫 `QdrantService.delete_points` 進行批次刪除，並同步扣除 MongoDB 中的 `chunk_count` 以保持狀態一致。

## 2026-06-23 實作 Qdrant 雙路召回與 RRF 混合檢索 (Hybrid Search) 後端支援


### 修改內容
1. `backend/requirements.txt`:
   - 增加 `fastembed>=0.3.0` 依賴。
2. `backend/services/sparse_embedding_service.py` (新增檔案):
   - 封裝 `fastembed.SparseTextEmbedding`。
   - 提供 `get_sparse_vector(text)` 與 `get_sparse_vectors_batch(texts)` 方法，將生成之 sparse 向量映射為 Qdrant 的 `models.SparseVector` 結構。
3. `backend/services/qdrant_service.py`:
   - `create_collection`: 新增 `sparse_vectors_config` 將 `"sparse-text"` 指定為稀疏向量空間，配置在磁碟上儲存索引。
   - `upsert_chunks`: 呼叫 `SparseEmbeddingService` 批次算出稀疏向量，將原點向量改為 `{ "": vectors[i], "sparse-text": sparse_vectors[i] }`。同時增加錯誤捕獲與安全退回機制：若目標集合不支援 `"sparse-text"`（例如舊有集合），自動退回成僅寫入密集向量，防止寫入出錯。
   - `search_similar`: 擴充 `query_text` 與 `search_type` 參數。若為 `"hybrid"` 且有查詢文字，則建立雙 `Prefetch`（Dense + Sparse），使用 `FusionQuery(fusion=models.Fusion.RRF)` 進行檢索；設有 `try-except` 捕獲異常並安全降級為純密集向量搜尋。
4. `backend/routers/retrieval.py`:
   - `search`: 呼叫 `QdrantService.search_similar` 時額外傳入 `query_text=request.query` 與 `search_type=request.params.search_type`。
5. `backend/routers/rag.py`:
   - `ChatParams`: 新增 `search_type: Optional[str] = "vector"` 選項定義。
   - `rag_chat_stream`: 解析 `search_type`，並在呼叫 `search_similar` 時將 `query_text` 與 `search_type` 穿透傳送。

## 2026-06-23 於回饋模組路由新增單筆與批次刪除 API 端點

### 修改內容
1. `backend/routers/feedback.py`:
   - 定義 `BatchDeleteRequest` Pydantic Schema（接收 `feedback_ids: List[str]`）。
   - 實作 `DELETE /{feedback_id}`：根據 PydanticObjectId 解析 ID 並安全刪除特定回饋紀錄。
   - 實作 `POST /batch-delete`：接受一組 IDs，執行 MongoDB 批次安全刪除。

## 2026-06-23 調整 Feedback 模型並實作回饋 API 端點

### 修改內容
1. `backend/models/feedback.py`:
   - 調整 `Feedback` Beanie 模型之欄位。將 `chat_message_id` 的類型從原先的 `PydanticObjectId` 調整為 `str`，以符合前端提交的暫時性字串 ID（例如 `"msg_assistant_1782202045238"`）；並將 `session_id` 設為 `Optional[str] = None`。
2. `backend/routers/feedback.py`:
   - 重構該檔案，移除原本僅回傳 `"stub"` 的 Mock 端點，改為對 MongoDB/Beanie 進行真實讀寫。
   - 實作 `POST /` (建立回饋)、`GET /` (分頁及條件篩選取得回饋清單)、`POST /export-to-dataset` (將特定不正確回饋同步/匯出至指定的評估測試集，若無指定則動態建立新測試集，且在完成後回填回饋資料中的 `exported_to_dataset_id` 欄位)。
   - 實作 `GET /export` (支援依 format 參數將所有回饋資料匯出下載為 JSON 或 CSV 檔，其中 CSV 格式使用 `utf-8-sig` 編碼，以確保微軟 Excel 能正確解碼繁體中文字元熱區)。

## 2026-06-23 新增預設 RAG 智慧對話 Prompt 範本測試紀錄 (PromptTestRecord)

### 修改內容
1. `backend/models/prompt_test_record.py`:
   - 新增 `seed_default_records` 異步方法。該方法會檢查 MongoDB 中是否已存在名為「預設 RAG 智慧對話範本」的 `PromptTestRecord`。若不存在，則自動寫入該紀錄（包含最新的 `rag.py` 系統設定、使用者範本、測試 Context 與測試問題），方便在「自訂 Context 生成」頁面中直接從歷史紀錄中載入並選取。
2. `backend/models/mongodb.py`:
   - 於 `init_mongodb` 的資料庫引導種植階段呼叫 `seed_default_records()`。
   - 於 `seed_default_prompt_templates` 中同步更新預設 RAG 助手 `PromptTemplate` 的系統設定，同樣新增文檔與段落引用規則。

## 2026-06-23 修正 RAG 智慧對話 Prompt 以強制要求 AI 引用文檔段落編號

### 修改內容
1. `backend/routers/rag.py`:
   - 於向量檢索完成組裝 `context_parts` 時，在提示詞中併入段落編號 `meta.get("chunk_index")` 與檔名。
   - 重構 RAG 的 `system_prompt`，於規則中新增第 4 點，明確要求 AI 必須在回答的開頭或結尾指出參考了哪些來源文件與段落，並指定固定格式為：「依據 [文件名] 段落: #段落編號 做出以下結論：」或是「（參考來源：[文件名] 段落: #段落編號）」，並給予多重引用之頓號分隔範例。

## 2026-06-23 修正無向量條件之 Scroll 檢索產生的 Record 物件無 score 屬性錯誤

### 修改內容
1. `backend/services/qdrant_service.py`:
   - 於 `search_similar` 中，對無向量條件下使用 `client.scroll` 檢索回傳的 `Record` 列表，改以 `getattr(res, "score", 0.0)` 安全讀取 `score`，解決 `Record` 無 `score` 屬性引發 `AttributeError` 崩潰並造成回傳空資料的 Bug。

## 2026-06-23 實作 A/B 測試平行異步串流、知識庫元數據接口與 Qdrant 檔案篩選

### 修改內容
1. `backend/services/qdrant_service.py`:
   - **過濾檔案與標籤條件**：擴充 `search_similar` 方法以支援額外的 `filter_filename` 參數。如果提供，它會與標籤過濾一起被包裝為 Qdrant 的 `must` 篩選條件。若 `query_vector` 為 `None`，則透過 `client.scroll` 進行純篩選查詢。
   - **元數據提取功能**：新增 `get_unique_metadata` 方法。該方法使用 Qdrant client 的 `scroll` 功能（只抓取 payload 中的 "filename" 與 "tags" 以取得最大效能，關閉 vector 載入），遍歷收集並回傳所有唯一的檔案名稱與標籤。
2. `backend/schemas/retrieval.py`:
   - 在 `SearchParams` 類中新增可選的 `filter_filename: Optional[str]` schema 屬性。
3. `backend/routers/retrieval.py`:
   - 在 `/search` 路由的 Qdrant 檢索中傳遞 `filter_filename` 參數。若 `query` 參數為空則跳過向量生成，直接執行無向量 Scroll 檢索。
4. `backend/routers/knowledge_base.py`:
   - 新增 `GET /knowledge-bases/{id}/metadata` 路由。在檢索到指定的知識庫後，調用 `QdrantService.get_unique_metadata` 回傳集合內所有的唯一 filename 與 tags 陣列。
5. `backend/routers/prompt.py`:
   - **A/B 測試平行異步串流**：
     - 重構 `POST /ab-test` 路由以回傳 `StreamingResponse`。
     - 內部實作異步 `ab_test_stream_generator()` 產生器，使用 `asyncio.Queue` 搭配 `asyncio.create_task` 在背景平行執行 Variant A 與 Variant B 的 LLM 對答流式推論。
     - 各任務取得 `delta` 區塊時（包含 content 與 reasoning_content 等），寫入 queue 中。產生器持續從 queue 取出資料，以標準 Server-Sent Events (SSE) 格式推送到前端。

## 2026-06-23 實作自訂 Context 與多參數 A/B 測試 Prompt 端點功能

### 修改內容
1. `backend/routers/prompt.py`:
   - 重構原 Stub 端點，定義 `PreviewRequest`、`PreviewResponse`、`ABTestRequest` 與 `ABTestResponse` 等 Pydantic models。
   - 於 `/preview` 中，實作安全字串替換，組合出最終的 user prompt，並套用 `(len(sys) + len(user)) * 1.3` 的 token 估計規則回傳。
   - 於 `/ab-test` 中，解析 variants 的超參數列表，呼叫 `LLMService.chat_completion` 完成真實 LLM 推論生成，並以毫秒精準統計耗時，回傳各 variants 的比較回答。

## 2026-06-23 實作自動化評估即時串流 (SSE Streaming) 與問答上限限制

### 修改內容
1. `backend/routers/evaluation.py`:
   - 修改 `POST /run` 評估路由。限制評估問答項目最大上限為 5 筆（使用 `dataset.items[:5]`），並回傳 `StreamingResponse`。
   - `StreamingResponse` 中定義 `event_generator()` 異步產生器，以 Server-Sent Events (SSE) 協議向前端推送狀態事件：
     - `event: init`：發送評估總筆數與測試集名稱。
     - `event: progress`：發送當前正在評估的問答索引與問題文字。
     - `event: item_done`：發送當前問題經 RAG 向量檢索、AI對答生成及 LLM-as-a-Judge 評分完成後之詳細結果（含有 generated_answer 與每項評分 metrics）。
     - `event: result`：發送最終評估總分數與所有明細，並將評估報告持久化儲存至 MongoDB。

## 2026-06-23 實作 RAG 準確度評估自動化系統

### 修改內容
1. `backend/models/mongodb.py`:
   - 新增 `seed_default_datasets` 異步方法。在系統啟動時若發現資料庫無測試集資料，則自動寫入「技術規格測試集」與「人事規章測試集」，以供使用者立即開始進行 RAG 評估。
2. `backend/routers/evaluation.py`:
   - 將原本的 Stub 接口重構為實質功能。
   - `GET /datasets`：返回測試集清單，並依測試集名稱將 ID 動態轉為 `"dataset_tech"` 與 `"dataset_hr"` 以對接前端的硬編碼設定。
   - `POST /datasets`：實作測試集新增與匯入功能，並寫入 MongoDB `test_datasets` 集合。
   - `POST /run`：解析傳入的測試集與知識庫 ID（支援 dummy ID 與真實 ID 解析）。針對每筆測試問答執行真實 RAG 向量檢索與生成，再呼叫後端 LLM 執行 LLM-as-a-Judge 計算 Faithfulness、Relevancy、Precision 與 Recall，最終計算平均分並保存為 `EvalReport` 紀錄返回。
   - `GET /reports/{report_id}`：實作讀取指定評估報告詳情。

## 2026-06-23 修正無參考資料時 AI 的回覆規則

### 修改內容
1. `backend/routers/rag.py`:
   - 修改 `system_prompt` 邏輯。當 `context_str` 為空（無參考資料）時，設定 System Prompt 強制要求 AI 僅直接回答『知識庫沒有相關資訊。』。
   - 當 `context_str` 不為空但參考資料不足以回答問題時，亦要求 AI 直接回答『知識庫沒有相關資訊。』，禁止使用既有知識回答或編造內容。

## 2026-06-22 新增 Qdrant 標籤 (Tags) 寫入與過濾功能

### 修改內容
1. `backend/services/qdrant_service.py`:
   - 擴充 `search_similar` 方法，新增 `filter_tags` 參數。若有指定標籤篩選，則動態構建 Qdrant 的 `models.Filter(must=[FieldCondition(key="tags", match=MatchAny(any=filter_tags))])` 篩選條件，實現高效 Pre-filtering。
   - 在搜尋回傳的 metadata 中加入 `tags` 欄位。
2. `backend/schemas/retrieval.py`:
   - 於 `SearchParams` 中新增 `filter_tags: Optional[List[str]]`。
   - 於 `RetrievalMetadata` 中新增 `tags: Optional[List[str]]`。
3. `backend/routers/retrieval.py`:
   - 在 `/search` 與 `/query-transform` 路由中，將 `filter_tags` 傳入 `search_similar`，並將回傳的標籤對應至回應。
4. `backend/routers/rag.py`:
   - 於 `ChatParams` 中新增 `filter_tags: Optional[List[str]]`，並在 RAG 串流中傳入相似度檢索，並隨 `sources` 回傳給前端。
5. `backend/routers/embedding.py`:
   - 修正向量化寫入時遺漏標籤之 Bug：在將 Chunks payload 寫入 Qdrant 以前，顯式自 `chunk.metadata` 提取 `tags` 寫入 Qdrant 的 payload。

## 2026-06-22 支援 vLLM 思考模式/推理解析

### 修改內容
1. `backend/routers/rag.py`:
   - 調整 `rag_chat_stream` 產生器，在提取 `choices[0].delta` 時，支援從 `reasoning_content`、`thought` 或 `reasoning` 多個欄位提取思考區塊，確保對不同 vLLM 版本或推論引擎具有最大相容性。
   - 若有思考區塊，會以符合 SSE 協議之 `event: chunk` 流式推送 `type: 'reasoning'` 的 JSON 片段給前端，讓前端能夠獨立呈現思考過程。

## 2026-06-22 實現 RAG 串接真實 vLLM 推論與 Qdrant 檢索服務

### 修改內容
1. `backend/routers/rag.py`:
   - 移除原有的模擬對話產生器 (`mock_chat_stream`)，改用真實的對話流 `rag_chat_stream`。
   - 整合 `EmbeddingService` 提問向量化與 `QdrantService.search_similar` 向量檢索：如果請求包含 `knowledge_base_id` 則自動從對應 Collection 檢索相似文檔區塊 (Chunks) 並整合成 Context。
   - 串接 `LLMService.chat_completion(..., stream=True)`：將組裝好的 Prompt (含 Context) 與聊天歷史併同呼叫外部 vLLM 服務（`.env` 指定的 `10.10.130.45:8080/v1`），實現即時串流生成回答。
   - 以符合 SSE 協議之 `event: chunk` 與 `event: sources` 流式推送字元片段及參考來源引用給前端。

## 2026-06-22 實現 RAG 對話串流模擬 (Mock SSE Stream)


### 修改內容
1. `backend/routers/rag.py`:
   - 定義 `ChatRequest`、`ChatHistoryItem`、`ChatParams` 等 Pydantic Schema，符合 `/api/rag/chat` 的請求規格。
   - 實作符合 Server-Sent Events (SSE) 規格之 `mock_chat_stream` 產生器，能根據使用者問題（例如含有「分機」時回傳 Markdown 團隊分機表，其他則回傳參數摘要與問候）提供模擬的回答與參考文檔引用 (Sources)。
   - 回傳 `StreamingResponse` 搭配 `text/event-stream` 格式，讓前端 `chatStore` 可正確以串流形式接收並渲染，提供高保真的 RAG 端到端介面測試。
   - 新增 `DELETE /history/{session_id}` 模擬路由以符合刪除歷史對話 API 合約。


## 2026-06-22 實現資料庫初始化引導種植 (Database Seeding)

### 修改內容
1. `backend/models/mongodb.py`:
   - 新增 `seed_default_knowledge_base` 異步方法。該方法會在 Beanie 初始化成功後執行。
   - 方法會查詢當前 `KnowledgeBase` 集合的文檔數，若數量為 0，則利用 `PydanticObjectId()` 生成新 ID，自動在 MongoDB 建立名為「預設知識庫」的項目，並透過 `QdrantService.create_collection` 在 Qdrant 中建立對應的 Collection，以保證系統運行時始終有至少一個可用的知識庫，提供前端正確的 ObjectId。

## 2026-06-22 修正外部服務連線設定與向量解析器相容性

### 修改內容
1. `docker-compose.yml`:
   - 移除 `backend` 服務下對 `VLLM_BASE_URL` 與 `LLAMACPP_BASE_URL` 的環境變數覆寫，以避免強行覆寫為 `host.docker.internal` 造成連線失敗，直接繼承並讀取 `.env` 檔案內設定的伺服器 IP `10.10.130.45`。
2. `backend/services/embedding_service.py`:
   - 重構 `EmbeddingService.get_embedding` 中的 JSON 解析器。
   - 使其支援多層級向量包裝格式，相容於列表型格式（如 `[{"embedding": [[...]]}]` 或 `[{"embedding": [...]}]`）、舊版字典格式、以及 OpenAI 規範 a 包裝結構，避免格式不一致導致解析拋出例外。

## 2026-06-22 實現向量檢索搜尋與查詢轉換服務

### 修改內容
1. `backend/schemas/retrieval.py` (新增檔案):
   - 定義向量搜尋與查詢重寫/HyDE 的 Pydantic 請求與回應 Schema（`RetrievalRequest`, `RetrievalResponse`, `QueryTransformRequest`, `QueryTransformResponse` 等），確保 API 完全符合合約定義。
2. `backend/services/llm_service.py` (新增檔案):
   - 建立對外部 vLLM（OpenAI 兼容接口）之 `LLMService`。
   - 實作端到端 Chat Completions 呼叫邏輯，包含非同步 Stream（串流）與一般 JSON 回傳支援。
   - 實作 `query_rewrite`（查詢重寫）與 `hyde_generation`（假設文檔生成）之 LLM Prompt 提示詞包裝方法。
3. `backend/routers/retrieval.py`:
   - 取代原有 Stub 路由，實作實際向量搜尋。
   - 藉由 `EmbeddingService` 將查詢向量化後，透過 `QdrantService.search_similar` 取得相似 Chunks 並回傳詳細 Metadata 與 Score。
   - 實作 `query-transform` 路由，執行 `rewrite`（重寫）或 `hyde` 策略生成轉換查詢後，呼叫 Qdrant 進行語意搜尋並回傳結果。