<!-- 新增功能紀錄 -->

## 2026-06-29 新增資料庫自訂資料向量化 (Embedding & Indexing) 匯入功能

### 功能描述
實作了自訂資料向量化 (Embedding & Indexing) 的「資料庫匯入向量化」Tab 與對應介面，支援：
1. **連線設定 & 快速選取**：可自行輸入 IP、Port、資料庫、帳號、密碼進行連線測試，並可將連線設定檔儲存至 MongoDB 中以便後續快速選取使用。
2. **安全過濾機制**：提供前後端 SQL 查詢語句驗證，強制限制僅執行 `SELECT` 或 `WITH` 開頭的唯讀語句，防止 SQL 注入與資料修改 (INSERT/UPDATE/DELETE/DROP 等)。
3. **三階段配置流程**：
   - 第一階段：查詢與取得欄位/樣品資料。
   - 第二階段：自訂欄意轉換，並可隨時變更為自然語言敘述或 Structured JSON 轉換模式。
   - 第三階段：即時樣品轉換成果預覽。
4. **批次向量化匯入**：支援一筆資料獨立為一向量段落，自動分批 (每批 20 筆) 進行向量化計算，並以 `DB_IMPORT_{tableName}` 檔名覆蓋寫入 Qdrant 向量資料庫與更新知識庫計數。

### 實作內容
1. **資料庫模型與 Schema**：
   - 新增 `backend/models/database_config.py`，定義 `DatabaseConfig` Beanie 集合，存儲 DB 設定。
   - 於 `backend/models/mongodb.py` 中註冊 `DatabaseConfig` 文件模型。
   - 新增 `backend/schemas/database_indexing.py`，包含設定 CRUD、連線測試、中介資料與向量化寫入之 Pydantic 傳輸 Schema。
2. **後端 Router 與驅動配置**：
   - 在 `backend/requirements.txt` 中追加 `oracledb>=2.0.0` 依賴。
   - 新增 `backend/routers/database_indexing.py`，內部實作 SQL 安全語法過濾器 `validate_sql_query`、SQL Server 的 `pyodbc` 多驅動程式自適應解析、Oracle Database 的 `oracledb` Thin 模式無驅動連線與資料提取、段落文字轉換公式、Qdrant 向量批次寫入與自動覆蓋刪除同名資料功能。
   - 在 `backend/main.py` 中註冊 `database_indexing` router。
3. **前端 API 與 UI 整合**：
   - 新增 `frontend/src/services/databaseIndexingService.js` 封裝所有資料庫 API 方法。
   - 於 `frontend/src/views/EmbeddingTestView.vue` 引入該服務，並在 script 中加入相關的狀態、連線測試、SQL 檢驗、中介資料取得、即時計算預覽文字 `dbPreviewText` 及匯入 API 呼叫。
   - 在 template 中新增「資料庫匯入向量化」按鈕，並編寫精美流暢的 Glassmorphic 連線設定表單、SQL 編輯器、欄位配置表格、樣品轉換預覽區與匯入執行按鈕與狀態回報。

### 修改檔案
- `backend/requirements.txt` (修改)
- `backend/models/database_config.py` (新增)
- `backend/models/mongodb.py` (修改)
- `backend/schemas/database_indexing.py` (新增)
- `backend/routers/database_indexing.py` (新增)
- `backend/main.py` (修改)
- `frontend/src/services/databaseIndexingService.js` (新增)
- `frontend/src/views/EmbeddingTestView.vue` (修改)

## 2026-06-26 新增客製化副檔名批次上傳限制、MongoDB 分類標籤與自訂類別選項管理

### 功能描述
優化自訂資料向量化 (Embedding & Indexing) 中的批次文件上傳流程：
1. **限制單一副檔名上傳與客製化切分**：限制批次上傳檔案必須符合選定的單一副檔名格式，並依選取的副檔名載入預設的客製化切分設定 (如切分大小、重疊大小、分隔符號與切分模式)。
2. **MongoDB 分類標籤管理**：分類標籤改為從 MongoDB 動態載入，使用者可一鍵勾選或在介面即時建立新標籤存入資料庫。
3. **自訂類別選項 (Class Array) 持久化與 Qdrant 寫入**：新增「類別選項 (Class)」管理，使用者可自行建立類別選項（儲存於 MongoDB），並在資料向量化時將選取之類別陣列寫入 Qdrant 向量點資料的 `"class"` 欄位中，且支援於 RAG 與向量搜尋結果中解析並回傳。

### 實作內容
1. **單一副檔名上傳限制**：
   - 於 `EmbeddingTestView.vue` 新增 `selectedExtension` 下拉式選單與預設切分參數對照表。
   - 修改 `addFilesToQueue` 邏輯，非指定副檔名檔案拒絕加入佇列。
   - 調整 Dropzone 的 `:accept` 屬性動態綁定 `selectedExtension`。
2. **分類標籤 (Tags) 與類別選項 (Classes) 管理**：
   - 實作 MongoDB / Beanie `Tag` 與 `ClassOption` 資料模型，並新增 API 端點提供查詢與建立功能。
   - 於前端 `embeddingService` 整合 `getTags()`, `createTag(name)`, `getClasses()`, `createClass(name)` API 方法。
   - 於 `EmbeddingTestView.vue` 中重構單筆編輯 (Tab 1) 與批次編輯 (Tab 2) 的 UI，移除原自由文字輸入框，替換為動態載入的 Checkbox 標籤/類別氣泡按鈕及即時建立新標籤/類別之輸入框。
3. **Qdrant `"class"` 欄位寫入與檢索回傳**：
   - 在後端向量化 API `/api/embedding/vectorize` 中，提取 `classes` 欄位並以 `"class"` 鍵值存入 Qdrant Metadata payload。
   - 修改後端 `RetrievalMetadata` 結構，加入 `class_list` 欄位並將其 alias 設為 `"class"`，實現對 Qdrant payload `"class"` 欄位的自動解析。
   - 於後端檢索與 RAG 端點中將 `"class"` 屬性對照回傳給前端。

### 修改檔案
- `backend/models/tag.py` (新增)
- `backend/models/class_option.py` (新增)
- `backend/models/mongodb.py` (修改)
- `backend/schemas/embedding.py` (修改)
- `backend/schemas/retrieval.py` (修改)
- `backend/routers/embedding.py` (修改)
- `backend/routers/retrieval.py` (修改)
- `frontend/src/services/embeddingService.js` (修改)
- `frontend/src/views/EmbeddingTestView.vue` (修改)

## 2026-06-25 新增 Genero 4GL 大小雙層檢索 (Parent-Child Retriever) 語法切分與前端自動分批寫入整合

### 功能描述
為了改善傳統字元切分容易將 4GL 程式碼截斷、導致語意上下文丟失的問題，實作了專屬的 4GL 大小雙層檢索切分與處理腳本。並將此切分能力整合至「自動分批寫入 (Batch Indexing)」功能中，允許使用者在批次處理時選用大小雙層結構切分，自動於向量庫點資料中寫入父子區塊關聯元資料。

### 實作內容
1. **父區塊語法結構解析 (Parent Chunks)**：
   - 提取 `MAIN ... END MAIN` 區塊。
   - 提取 `FUNCTION 函數名(...) ... END FUNCTION` 區塊。
   - 提取 `REPORT 報表名(...) ... END REPORT` 區塊。
   - 收集所有在上述結構之外的全域宣告（如 `DATABASE`, `GLOBALS`, `DEFINE`），合併切分為一個名為 `Global_Declarations` 的父區塊。
   - 透過正則與注釋過濾機制（排除 `#`, `--` 及 `{ ... }` 的偽關鍵字干擾），產出具備唯一 `parent_id`、`type`、`name` 與完整原始碼內容的 Parent Chunk 字典。
2. **子區塊滑動窗口切分 (Child Chunks)**：
   - 針對每個 Parent Chunk 的內容，使用固定的字元大小 `child_size`（預設 250 字元）進行切分。
   - 配置 `child_overlap`（預設 20% 重疊區間，即 50 字元），以防關鍵語句或條件判斷在切分邊界被截斷。
   - 自動將父節點元資料（`parent_id`, `source_file`, `type`, `function_name`）綁定至每個 Child Chunk 中，便於寫入向量資料庫。
3. **前端與後端批次寫入整合**：
   - **後端擴充**：在 `/api/embedding/chunk` 與 `/api/embedding/vectorize` 接口中，支援傳入 `chunk_mode` 與 `filename` 參數。若為 `parent_child` 模式或 `.4gl` 檔案，則自動調用 `parent_child_chunker` 產生帶有父區塊關聯 Metadata 的子區塊，並在寫入向量庫時將 `parent_id` 等欄位合併存入 Payload。
   - **前端擴充**：於 `EmbeddingTestView.vue` 之「自動分批寫入設定」面板新增「切分模式」下拉選單（包含「標準字元切分」與「大小雙層結構切分」）。批次發送時自動將選定模式發送給後端，並將後端回傳的父區塊 Metadata 完美合併至向量化 Request 中。

### 修改檔案
- `scripts/parent_child_chunker.py` (新增)
- `tests/test_parent_child_chunker.py` (新增)
- `backend/schemas/embedding.py` (修改)
- `backend/routers/embedding.py` (修改)
- `frontend/src/views/EmbeddingTestView.vue` (修改)

## 2026-06-25 新增自動分批寫入之重複檔案處理設定 (覆蓋與略過選項)

### 功能描述
為「自動分批寫入」新增重複檔案處理選項設定，允許使用者選擇「刪除重新上傳(覆蓋)」或「舊檔案略過不覆蓋（跳過）」。在批次處理開始前自動向後端獲取現有檔案清單，並依此判斷是否需略過已存在的檔案。

### 實作內容
1. **前端狀態擴充**：
   - 於 `frontend/src/views/EmbeddingTestView.vue` 新增 `batchDuplicateMode` 狀態（預設為 `overwrite`）。
2. **批次略過處理邏輯**：
   - 修改 `startBatchProcessing`：執行前呼叫 `/api/knowledge-bases/{kb_id}/metadata` API 取得最新庫內檔案名稱列表。
   - 迭代佇列時，若偵測到重複檔名且設定為 `skip`，則將進度設為 100%、狀態設為已完成，並顯示「檔案已存在於向量庫中，已自動略過不覆蓋」，直接進入下一個檔案處理。
   - 當寫入成功時，動態更新已存在檔案清單，以避免同批次或後續執行之檔案發生重複寫入。
3. **介面 UI 整合**：
   - 於「批次寫入設定」面板中加入「重複檔案處理」下拉選單，並將網格配置由雙欄調整為三欄。

### 修改檔案
- `frontend/src/views/EmbeddingTestView.vue`

## 2026-06-25 新增自訂資料分批寫入功能 (含批次上傳、4GL 格式支援與自動重複清理)

### 功能描述
於自訂資料向量化 (Embedding & Indexing) 頁面中，新增一個分頁「自動分批寫入」。使用者可一次性拖放或選取多個檔案（包含 `.4gl` 原始碼檔案）進行批次處理，系統將自動分批切分並將 Chunks 批次寫入 Qdrant 與 MongoDB 資料庫。若檢測到與資料庫內檔案名稱重複，則會先自動刪除該檔案先前之所有向量資料再重新寫入，並在前端提供直觀的整體進度條與檔案佇列詳細狀態指示。

### 實作內容
1. **後端支援與檔案相容性擴充**：
   - 修改 `backend/services/document_parser.py`：在 `parse_file` 中將 `.4gl` 副檔名加入文字解析分流中，使其能以純文字格式進行解碼與提取。
   - 修改 `backend/services/qdrant_service.py`：新增 `delete_by_filename` 類別方法，使用 Qdrant Scroll API 查找指定檔名的所有點 ID，並呼叫 `AsyncQdrantClient.delete` 進行刪除，回傳刪除的點數量。
   - 修改 `backend/schemas/retrieval.py`：新增 `DeleteByFilenameRequest` 結構體。
   - 修改 `backend/routers/retrieval.py`：新增 `POST /api/retrieval/knowledge-bases/{knowledge_base_id}/files/delete-by-filename` 端點。呼叫 `delete_by_filename` 刪除同名資料，並更新 MongoDB 知識庫的 `chunk_count` 總數。
2. **前端服務對接**：
   - 修改 `frontend/src/services/retrievalService.js`：新增 `deleteFileByFilename` API 方法。
3. **前端 UI 與批次佇列引擎開發**：
   - 修改 `frontend/src/views/EmbeddingTestView.vue`：
     - **新分頁整合**：新增 `activeTab = 'batch_indexing'` 分頁。
     - **批次檔案管理**：設計支援拖拽與多檔案選取的 Dropzone 介面，可載入多個檔案至佇列。
     - **分批配置設定**：提供分類標籤 (Tags) 輸入，以及「向量寫入批次大小」配置 (Chunk/Batch)，預設為每次 20 段，用以降低連線或 Payload 過大之錯誤率。
     - **全域與個別進度條**：使用 computed 計算總體進度百分比，並透過 `Parsing`, `Chunking`, `Deleting`, `Vectorizing (Batch X/Y)`, `Success`, `Failed` 等狀態更新各檔案微型進度條與狀態訊息。
     - **依序非同步佇列處理**：以迴圈依序執行各檔案之：上傳解析、文本切分、庫內重複資料刪除、分批向量化寫入 Qdrant 與 Beanie 流程。

### 修改檔案
- `backend/services/document_parser.py`
- `backend/services/qdrant_service.py`
- `backend/schemas/retrieval.py`
- `backend/routers/retrieval.py`
- `frontend/src/services/retrievalService.js`
- `frontend/src/views/EmbeddingTestView.vue`

## 2026-06-24 新增自訂資料向量化文字結構化 (Structured Chunks) 功能

### 功能描述
於「自訂資料向量化 (Embedding & Indexing)」頁面之切分預覽功能中，新增文字結構化設定。啟用此功能後，文字切分時將自動結合檔案名稱、段落編號與分類標籤資訊，整合成結構化格式再進行向量化寫入 Qdrant 向量資料庫，以強化後續 RAG 檢索的語意關聯與元資料提取品質。

### 實作內容
1. **全域參數擴充**：
   - 修改 `frontend/src/stores/paramsStore.js`，於 Pinia store 中新增 `enableStructuring` 狀態開關，預設為 `true`。
2. **參數控制面板整合**：
   - 修改 `frontend/src/components/params/ChunkingParams.vue`，在切分參數邊欄的切分符號下方新增「啟用文字結構化 (Structure Text)」的 checkbox 開關，支援全域狀態雙向綁定。
3. **前端切分邏輯整合與精確估算**：
   - 修改 `frontend/src/views/EmbeddingTestView.vue`，當執行「開始文本切分」時，若啟用文字結構化，則自動將各個 chunk 依據格式範本（含檔名、段落、標籤與主要內容）進行字串重新格式化。
   - 實作前端的 CJK 字元/英文 token 精確估算器 `estimateTokens`，動態更新結構化段落的 tokens 數與字元數以提供最真實的切分預覽，並確保寫入資料庫的內容完全與預覽一致。

### 修改檔案
- `frontend/src/stores/paramsStore.js`
- `frontend/src/components/params/ChunkingParams.vue`
- `frontend/src/views/EmbeddingTestView.vue`

## 2026-06-23 新增 Qdrant 雙路召回與 RRF 混合檢索 (Hybrid Search) 功能

### 功能描述
實作結合「密集語意向量 (Dense Vector) 檢索」與「稀疏關鍵字向量 (Sparse Vector / SPLADE) 檢索」的雙路融合檢索（Hybrid Search）。以 Qdrant 的 Reciprocal Rank Fusion (RRF) 整合兩路檢索結果，顯著提升專有名詞與精確型號、關鍵字的查詢準確度。

### 實作內容
1. **依賴管理**：
   - 於 `backend/requirements.txt` 中新增 `fastembed>=0.3.0` 套件依賴，以高效地生成語意與詞頻稀疏向量。
2. **稀疏向量產生模組**：
   - 新建 `backend/services/sparse_embedding_service.py`，封裝 `fastembed.SparseTextEmbedding` (預設為 SPLADE) 生成器，支援單筆與批次文字的稀疏向量生成。
3. **向量庫 Schema 與寫入更新**：
   - 修改 `backend/services/qdrant_service.py`：
     - `create_collection`：在建立 Collection 時定義命名空間 `"sparse-text"` 及其對應的稀疏索引。
     - `upsert_chunks`：變更資料寫入的 Vector 結構，呼叫 `SparseEmbeddingService` 自動批次計算並儲存對應的稀疏向量。
4. **雙路檢索與安全降級 (Fallback)**：
   - 修改 `search_similar` 介面：支援 `search_type` 與原始 `query_text` 參數。
   - 當 `search_type` 為 `"hybrid"` 時，同時預檢索 Dense 與 Sparse 兩路，再利用 Qdrant `FusionQuery(fusion=models.Fusion.RRF)` 計算最佳綜合排序。
   - 增加安全降級防線：若因舊 Collection 不支援或其他未知異常，會自動捕捉例外並降級為常規純向量搜尋，保障高可用性。
5. **RAG 對話與檢索 API 銜接**：
   - 修改 `backend/routers/retrieval.py` 與 `backend/routers/rag.py` 路由，將前端發送的 `search_type`（混合/向量）參數穿透傳遞給底層檢索引擎，使對話串流與獨立檢索都支援 Hybrid 模式。

### 修改檔案
- `backend/requirements.txt`
- `backend/services/sparse_embedding_service.py` (新設)
- `backend/services/qdrant_service.py`
- `backend/routers/retrieval.py`
- `backend/routers/rag.py`

## 2026-06-23 新增人工回饋紀錄單筆刪除與批次刪除功能

### 功能描述
為「人工回饋與標註歷史」頁面擴充紀錄清理與刪除功能，支援單筆回饋紀錄刪除，以及多選核取方塊後的批次刪除，以便於管理與整理匯入測試集前的標註數據。

### 實作內容
1. **後端刪除 API 實作**：
   - 實作 `DELETE /api/feedback/{feedback_id}` 端點，用於刪除指定的單一回饋紀錄。
   - 實作 `POST /api/feedback/batch-delete` 端點，以接收包含多個 ID 的 payload，進行安全的 MongoDB 批次刪除。
2. **前端 Store 狀態對接**：
   - 在 Pinia Store (`feedbackStore.js`) 中新增 `deleteFeedback` 與 `batchDeleteFeedbacks` Actions 以連接後端刪除端點。
3. **前端 UI 與操作交互**：
   - 在 `FeedbackView.vue` 列表的標題操作列新增「刪除選取」按鈕，並於多選 checkbox 有勾選時啟用，點擊後會彈出確認視窗，執行完成後清空選取狀態並重新載入列表。
   - 在表格每行末尾新增一個「操作」欄位，擺放紅色的垃圾桶按鈕以支援單筆刪除。

### 修改檔案
- `backend/routers/feedback.py`
- `frontend/src/stores/feedbackStore.js`
- `frontend/src/views/FeedbackView.vue`

## 2026-06-23 新增 Prompt 測試多源引用與 A/B 測試結果歷史存檔系統

### 功能描述
為「Prompt 測試」頁面擴充四項大幅提升調優效率之進階功能，支援範本與測試結果的 MongoDB 歷史存檔、引導載入預設 RAG 範本、針對 Qdrant 知識庫執行即時向量檢索多選注入、以及引用評估集問題（並能聯動載入標準答案與相關上下文）。

### 實作內容
1. **測試歷史與範本存檔**：
   - 後端新增 `PromptTestRecord` MongoDB 資料模型，紀錄 System Prompt、User Template、Context、Question 與 A/B 測試 Variant 的生成 answer、elapsed_ms 與 parameters。
   - 提供 `GET /api/prompt/records`、`POST /api/prompt/records`、`DELETE /api/prompt/records/{id}` 對應 API。
   - 前端點擊「儲存本次測試與結果」可為本次結果命名存檔；點擊「檢視歷史紀錄」彈出暗色玻璃擬物 Modal，顯示歷史列表，並提供「還原參數」與「刪除」功能。
2. **預設/自訂範本引用機制**：
   - 後端在 `mongodb.py` 初始化中實作 `seed_default_prompt_templates()`，若資料庫為空則自動載入「預設 RAG 助手」與「嚴格知識問答」兩款內建範本。
   - 提供 `GET /api/prompt/templates`、`POST /api/prompt/templates`、`DELETE /api/prompt/templates/{id}` 等範本 API。
   - 前端 System Prompt 設定上方新增「載入範本」與「儲存為範本」按鈕。點選載入可彈出視窗並套用範本，非預設範本可執行刪除。
3. **Qdrant 知識庫 Chunk 段落多選引用**：
   - 前端 Context 上方新增「檢索並引用 Qdrant Chunks」按鈕。
   - 點選彈出 Modal 視窗，使用者可選擇系統內現有 Knowledge Base，輸入關鍵字後呼叫後端 `/api/retrieval/search` 進行真實向量檢索。
   - 以相似度排序顯示 Chunks，支援多選 Checkbox，確認後自動將所選段落附帶檔名與頁碼以 `\n---\n` 串接注入 Context 輸入框。
4. **評估集問題引用**：
   - 前端 User Query 上方新增「引用評估集問題」按鈕。
   - 點選彈出 Modal 視窗，使用者可選擇測試集並自動加載問答清單。
   - 點擊特定項目即填入問題，並提示是否一併將該問答對應的標準答案 (Ground Truth) 與 relevant contexts 追加載入 Context 輸入框。

### 修改檔案
- `backend/models/prompt_test_record.py` (新設)
- `backend/models/mongodb.py`
- `backend/routers/prompt.py`
- `frontend/src/views/PromptTestView.vue`

## 2026-06-24 新增刪除向量資料的 Points 功能 (含檔案名稱過濾與批次刪除)

### 功能描述
於向量檢索測試頁面中新增 Qdrant 向量 Points 的管理與刪除功能，免去手動登入 Qdrant 後台的操作。功能包含：透過知識庫元資料（Metadata）動態取得唯一檔案清單並進行前端下拉式檔案名稱過濾篩選、檢索結果的單筆與 checkbox 多選核取，以及批次永久刪除 Qdrant 向量 Points 並連帶更新 MongoDB 知識庫的 chunk 總數。

### 實作內容
1. **後端 Qdrant 服務與 API 端點實作**：
   - 修改 `backend/services/qdrant_service.py`：新增 `delete_points` 類別方法，封裝 `AsyncQdrantClient.delete` 並使用 `PointIdsList` 進行 Qdrant 點的刪除。
   - 修改 `backend/schemas/retrieval.py`：新增 `BatchDeleteRequest` 結構，包含要刪除的點 ID 列表 (`point_ids: List[str]`)。
   - 修改 `backend/routers/retrieval.py`：新增 `POST /api/retrieval/knowledge-bases/{knowledge_base_id}/points/batch-delete` 路由端點。刪除 Qdrant 對應 Point 後，自動將 MongoDB 中該知識庫紀錄的 `chunk_count` 扣除對應刪除數量並保存。
2. **前端服務對接**：
   - 修改 `frontend/src/services/retrievalService.js`：新增 `batchDeletePoints(knowledgeBaseId, pointIds)` 方法對接後端批次刪除 API。
3. **前端 UI 與交互優化**：
   - 修改 `frontend/src/views/RetrievalTestView.vue`：
     - **檔案名稱過濾**：新增 `watch` 監聽知識庫 ID，當切換時自動向 `/api/knowledge-bases/{id}/metadata` 請求元資料，並提供 `檔案名稱過濾` 下拉選單供使用者限制檢索範圍。
     - **單筆刪除與批次刪除**：在檢索結果列表的每一筆資料右上角放置紅色垃圾桶圖示，點擊可單獨刪除該點；列表左上方新增全選與「刪除所選」按鈕，配合每筆資料左側 Checkbox 供多選與批次刪除。
     - **即時響應**：點擊刪除並確認後，直接在前端結果陣列中剔除已刪除的資料，不需重新發起搜尋即可即時更新。

### 修改檔案
- `backend/services/qdrant_service.py`
- `backend/schemas/retrieval.py`
- `backend/routers/retrieval.py`
- `frontend/src/services/retrievalService.js`
- `frontend/src/views/RetrievalTestView.vue`