<!-- 新功能紀錄(最新紀錄放最前面) -->
## 2026-07-03 語義資料庫查詢法新增「必定查詢」設定檔標記，作為問題語意不明確時的兜底機制

### 功能描述
實測發現：當使用者問題與任何查詢設定檔都無明顯語意關聯時（例如問「Tiptop相關資訊」，但目前設定檔都是知識庫文章/附件用途），AI 依語意判斷會回傳「與任何設定檔都無關」，導致直接查無設定檔而不查詢。但某些設定檔（例如通用文章庫）用途夠廣泛，即使 AI 判斷不出明確關聯，仍值得嘗試查詢一次。新增「必定查詢」標記：使用者可在建立/編輯查詢設定檔時勾選此選項，勾選後不論 AI 的語意選擇結果為何，此設定檔都會被強制加入候選查詢清單。

### 實作內容
1. `backend/models/db_query_profile.py`：`DBQueryProfile` 新增 `is_default: bool = False` 欄位。
2. `backend/schemas/ai_db_query.py`：`DBQueryProfileCreate`/`DBQueryProfileResponse` 新增 `is_default` 欄位。
3. `backend/services/qdrant_service.py`：`upsert_db_query_profile()` 新增 `is_default` 參數，寫入 Qdrant payload（新增 `is_default` key）。
4. `backend/routers/ai_db_query.py`：建立/更新設定檔時讀取並傳遞 `is_default` 至 MongoDB 與 Qdrant。
5. `backend/services/ai_db_query_service.py`：`match_profiles()` 於取得 AI 選擇結果後，額外將目錄中標記 `is_default=True` 且未被選中的設定檔強制加入候選清單最前面，並於 `selection_reason` 註明是被強制加入；即使 AI 判斷「與任何設定檔都無關」，只要有設定檔標記為必定查詢，仍會產生候選並繼續執行查詢，不會直接判定查無設定檔。
6. `frontend/src/components/embedding/DBQueryProfileManager.vue`：新增「設為必定查詢設定檔」checkbox（建立/編輯表單），已建立的設定檔清單於標記為必定查詢者旁顯示「必定查詢」徽章。

### 修改檔案
- `backend/models/db_query_profile.py`
- `backend/schemas/ai_db_query.py`
- `backend/services/qdrant_service.py`
- `backend/routers/ai_db_query.py`
- `backend/services/ai_db_query_service.py`
- `frontend/src/components/embedding/DBQueryProfileManager.vue`

## 2026-07-03 語義資料庫查詢法改為「先提供完整設定檔清單，由 AI 直接判斷選用哪幾個」取代向量相似度門檻篩選

### 功能描述
延續同日「不限定知識庫」多設定檔合併查詢的調整，使用者實測後回報：即使已支援多設定檔合併，實際結果仍只選到 1 個設定檔（例如問題同時涉及「附件」與「文章」，卻只查了附件表），原因是向量相似度門檻/排序本質上是個粗略的量化篩選機制，容易讓語意上明顯相關但分數略低的設定檔被排除。使用者建議「在使用語義 AI 之前，先提供目前有的設定檔給語義 AI，讓語義 AI 自己判斷使用哪幾個」。
本次採納此建議，將設定檔選擇機制從「向量相似度門檻/Top-K 排序」改為「先列出目前所有查詢設定檔的完整清單（名稱/表格/用途），交給地端 Instruct AI 直接依問題語意判斷需要用到哪幾個設定檔（可複選、可 0 個）」，從根本上避免量化門檻造成的漏選問題。

### 實作內容
1. `backend/services/ai_db_query_service.py`：
   - 移除 `_rewrite_question_for_profile_match()`（向量檢索用的問題重寫，不再需要）。
   - 新增 `_select_relevant_profiles_from_catalog()`：把候選範圍內（指定知識庫或全部知識庫）的 `DBQueryProfile` 完整清單提供給 Instruct AI，要求以 JSON 回傳 `selected_profile_ids`（可複選）與 `reason`（選擇理由），防幻想規則要求只能選清單中確實存在的 id。
   - `match_profiles()` 改為直接從 MongoDB 撈取候選範圍內的 `DBQueryProfile` 清單（不再呼叫 `QdrantService.search_db_query_profiles()`），依 AI 選擇結果組裝候選清單（`score` 欄位改為依 AI 回傳順序的遞減示意分數，非向量相似度）。
2. `backend/schemas/ai_db_query.py`、`backend/routers/ai_db_query.py`：`MatchProfilesResponse.embeddings_input` 更名為 `selection_reason`（欄位語意已改變，不再是向量檢索輸入文字，而是 AI 的選擇理由）。
3. `backend/routers/rag.py`：語義分析步驟顯示的結構化 JSON 改為 `{"original_question", "scope", "selected_profiles", "selection_reason"}`，取代原本的 `embeddings_input`。
4. Profile 向量寫入機制（`QdrantService.upsert_db_query_profile()`／建立與更新設定檔時寫入 Qdrant）維持不變（仍可供向量管理頁面檢視、未來可能的擴充使用），僅選擇邏輯不再讀取這些向量；`QdrantService.search_db_query_profiles()` 暫時保留但未被呼叫。

### 修改檔案
- `backend/services/ai_db_query_service.py`
- `backend/schemas/ai_db_query.py`
- `backend/routers/ai_db_query.py`
- `backend/routers/rag.py`
- `docs/DevelopmentProcess/SemanticDatabaseQueryPlan.md`（補充架構異動說明）

## 2026-07-03 語義資料庫查詢法「不限定知識庫」模式支援自動執行多個候選設定檔並合併結果

### 功能描述
實測發現「不限定知識庫」模式原本只會自動選擇分數最高的**單一**候選設定檔執行查詢，當使用者問題同時橫跨多張表格/設定檔時（例如同時問到「附件」與「文章」，分屬 attachments/articles 兩個查詢設定檔），只查了其中一個表格，導致漏答。改為依分數排序依序執行前 N 個（預設 3 個，`AI_DB_QUERY_MAX_PROFILES_PER_QUERY`）候選設定檔，各自產生 SQL 並查詢後合併結果再交給主模型總結；僅有 1 個候選時行為不變。此變更僅影響「不限定知識庫」的自動選取路徑，指定知識庫時使用者手動選擇單一候選的既有兩段式流程不受影響。

### 實作內容
1. `backend/config.py`：新增 `AI_DB_QUERY_MAX_PROFILES_PER_QUERY`（預設 3）。
2. `backend/routers/rag.py`：`_run_execute()` 改為累加 `context_str`/`sources`（而非覆寫），使其可被呼叫多次；`_run_semantic_db_query()` 的 `global_scan` 分支改為依序對前 N 個候選呼叫 `_run_execute()`。
3. `frontend/src/views/RetrievalTestView.vue`：`dbQueryResult`（單一物件）改為 `dbQueryResults`（陣列），「不限定知識庫」時對前 3 個候選依序呼叫執行並合併顯示每個設定檔各自的 SQL 與查詢結果。

### 修改檔案
- `backend/config.py`
- `backend/routers/rag.py`
- `frontend/src/views/RetrievalTestView.vue`

## 2026-07-03 語義資料庫查詢法新增「不限定知識庫」跨知識庫自動掃描模式

### 功能描述
延續同日新增的「語義資料庫查詢法」，補上使用者的追加需求：允許不預先指定目標知識庫，改由 AI 掃描**所有**知識庫的查詢設定檔並自動判斷要用哪一個。因為此模式沒有預設範圍可供使用者判斷取捨，決定採「直接自動選分數最高的候選」而非列出候選讓使用者選（與指定知識庫時的既有兩段式選取流程並存，兩者依是否指定知識庫自動切換，互不影響）。

### 實作內容
1. **後端**：
   - `backend/services/ai_db_query_service.py`：`AIDBQueryService.match_profiles()` 的 `knowledge_base_id` 改為選填；未提供時改為列舉所有 `KnowledgeBase`，逐一呼叫 `QdrantService.search_db_query_profiles()` 後合併排序，取全域分數最高的候選清單。
   - `backend/schemas/ai_db_query.py`：`MatchProfilesRequest.knowledge_base_id` 改為 `Optional[str]`。
   - `backend/routers/rag.py`：`_run_semantic_db_query()` 移除「必須指定知識庫」的硬性檢查；新增 `global_scan` 判斷，若未指定知識庫且找到候選，直接自動選分數最高者並繼續執行 SQL（不送出 `profile_candidates` 事件、不中斷等待選擇），語義分析的 JSON 內容一併標註 `scope`（"所有知識庫（不限定）" 或 "指定知識庫"）供使用者辨識目前是哪種模式。
2. **前端**：
   - `frontend/src/stores/paramsStore.js`：新增 `dbQueryAutoKb` 狀態。
   - `frontend/src/components/params/RagParamsPanel.vue`、`frontend/src/views/RetrievalTestView.vue`：語義資料庫查詢法參數區新增「不限定知識庫」checkbox。
   - `frontend/src/stores/chatStore.js`：勾選後對話請求改送 `knowledge_base_id: null`。
   - `frontend/src/views/RetrievalTestView.vue` 的 `handleSemanticDbQuerySearch()`：勾選後不顯示候選選取 UI，取得候選清單後直接呼叫 `handleSelectDbProfile()` 自動執行分數最高者。

### 修改檔案
- `backend/services/ai_db_query_service.py`
- `backend/schemas/ai_db_query.py`
- `backend/routers/rag.py`
- `frontend/src/stores/paramsStore.js`
- `frontend/src/components/params/RagParamsPanel.vue`
- `frontend/src/views/RetrievalTestView.vue`
- `frontend/src/stores/chatStore.js`

## 2026-07-03 新增「語義資料庫查詢法」，讓 AI 自動判斷資料庫查詢設定檔、產生 SQL 並查詢既有關聯式資料庫

### 功能描述
新增一種全新的檢索模式 `semantic_db_query`（語義資料庫查詢法），使用者可先在「資料庫匯入向量化」頁面建立「查詢設定檔」（描述某個資料庫連線下某張表格與各欄位的用途），系統會將設定檔組成自然語言描述並向量化。之後在 RAG 對話測試、向量搜尋測試、準確度評估中選擇此查詢法時，AI 會先語義理解問題、比對出候選查詢設定檔（列出讓使用者選取，而非自動猜測），使用者選定後才由地端 Instruct AI 產生唯讀 SQL、執行查詢（套用筆數/字數上限與逐欄位截斷），最後把查詢結果交給主模型（vLLM）統整成答案。全程完全新增，不修改既有 `vector`/`hybrid`/`semantic_hybrid`/`semantic_hybrid_feedback` 四種查詢法與既有「資料庫匯入向量化」（DB → 向量長期存放）功能的任何行為。詳細規劃見 `docs/DevelopmentProcess/SemanticDatabaseQueryPlan.md`。

### 實作內容
1. **查詢設定檔資料模型與向量儲存**：
   - 新增 `backend/models/db_query_profile.py`：`DBQueryProfile` Document（含 `database_config_id`/`knowledge_base_id`/`table_name`/`columns`（每欄位可選填 `max_length` 截斷長度）/`composed_description`/`qdrant_point_id`），已註冊進 `backend/models/mongodb.py` 的 `document_models`。
   - Profile 向量依使用者需求存進**選定 KnowledgeBase 的既有 Qdrant collection**（而非獨立 collection），payload 新增 `source: "db_query_profile"`。為避免混入既有文件檢索結果，修改 `backend/services/qdrant_service.py` 的 `search_similar()`/`search_similar_two_step()`，加上一條**加法式** `must_not: source == "db_query_profile"` 過濾條件——既有資料從未出現此值，對既有四種查詢法零行為影響。另新增獨立方法 `upsert_db_query_profile()`/`delete_db_query_profile_point()`/`search_db_query_profiles()`，不共用、不修改既有 `upsert_chunks`/`search_similar` 方法本體。
2. **核心查詢流程 Service**：
   - 新增 `backend/services/ai_db_query_service.py`：`AIDBQueryService.match_profiles()`（語義理解 + Profile 向量比對，回傳候選清單供使用者選取，找不到候選時明確回報而非亂猜）、`AIDBQueryService.execute()`（依選定設定檔讓 Instruct AI 產生唯讀 SQL、重用 `database_indexing.py` 既有的 `validate_sql_query()`/`get_db_connection()`、套用筆數/字數上限與逐欄位自訂截斷、將結果文字化）。任一階段失敗皆拋出 `AIDBQueryError` 附明確原因，不靜默降級。
3. **新 API Router**：
   - 新增 `backend/routers/ai_db_query.py`（`/api/ai-db-query`）：查詢設定檔 CRUD、`list-tables`/`list-columns`（純 schema 探索，供前端下拉選單）、兩段式查詢執行 `match-profiles`/`execute`。已掛載至 `backend/main.py`。
   - 新增 `backend/schemas/ai_db_query.py`。
4. **設定值**：
   - 修改 `backend/config.py`：新增 `AI_DB_QUERY_MAX_ROWS`（預設 50）、`AI_DB_QUERY_MAX_CHARS`（預設 4000）、`AI_DB_QUERY_PROFILE_SCORE_THRESHOLD`（預設 0.5）。
5. **三處測試頁面整合（加法式，不改既有分支邏輯）**：
   - 修改 `backend/routers/rag.py`：新增 `_run_semantic_db_query()` 分支，`search_type == "semantic_db_query"` 時走此流程。採兩階段 SSE 串流——第一次請求僅回傳候選設定檔清單（新增 SSE `step: "profile_candidates"`）後即結束串流；使用者選定後帶 `selected_db_profile_id` 重新呼叫同一端點才繼續產生 SQL、查詢、交給主模型總結。
   - 修改 `backend/routers/evaluation.py` 與 `backend/models/eval_report.py`：批次評估流程無真人可選候選，自動取分數最高候選（Top-1）執行，新增 `EvalDetail.db_query_note` 欄位標記「自動選取、非人工確認」或失敗原因。
   - 檢索測試頁不經過 `/api/retrieval/search`，前端直接呼叫 `ai_db_query` router 的 `match-profiles`/`execute`（回應格式與一般 chunk 檢索不同）。
6. **前端：新增查詢設定檔管理 UI**：
   - 新增 `frontend/src/services/aiDbQueryService.js`。
   - 新增 `frontend/src/components/embedding/DBQueryProfileManager.vue`：可選取資料庫連線設定檔、表格（呼叫 `list-tables`）、欄位（呼叫 `list-columns`，可設定啟用/意義/截斷長度），即時預覽自動組合的自然語言描述，並列出/編輯/刪除現有設定檔。
   - 修改 `frontend/src/components/embedding/DatabaseIndexingTab.vue`：新增子模式切換（① 將資料庫內容轉向量【既有功能不動】／② AI 查詢設定檔【新增】），既有向量化流程完整保留於 `v-else` 區塊。
7. **前端：三處測試頁面新增查詢法選項**：
   - 修改 `frontend/src/components/params/RagParamsPanel.vue`、`frontend/src/views/RetrievalTestView.vue`、`frontend/src/components/eval/TestSetManager.vue`：新增「語義資料庫查詢法 (Semantic DB Query)」選項，並提供筆數/字數上限輸入框（`frontend/src/stores/paramsStore.js` 新增 `dbQueryMaxRows`/`dbQueryMaxChars`）。
   - `RetrievalTestView.vue` 新增候選設定檔選取 UI 與 SQL/查詢結果顯示區塊（`handleSemanticDbQuerySearch()`/`handleSelectDbProfile()`）。
   - 修改 `frontend/src/stores/chatStore.js`：抽出共用的 `_streamChat()`，新增 `selectDbQueryProfile()` action 供使用者選定候選後沿用同一則 assistant 訊息繼續串流；`step` 事件新增對 `profile_candidates` 的處理。
   - 修改 `frontend/src/components/chat/MessageBubble.vue`/`ChatWindow.vue`：新增候選查詢設定檔選取區塊與 `select-db-profile` 事件轉發。
   - 修改 `frontend/src/views/EvaluationView.vue`：評估明細列表新增 `db_query_note` 顯示。
8. **文件同步**：更新 `docs/03_API_CONTRACT.md`（新增第 13 節）、`docs/04_DB_SCHEMA.md`（新增 `db_query_profiles` collection 與 `source` 欄位新值說明）。

### 修改檔案
- `backend/models/db_query_profile.py`（新增）
- `backend/models/mongodb.py`
- `backend/models/eval_report.py`
- `backend/schemas/ai_db_query.py`（新增）
- `backend/services/ai_db_query_service.py`（新增）
- `backend/services/qdrant_service.py`
- `backend/routers/ai_db_query.py`（新增）
- `backend/routers/rag.py`
- `backend/routers/evaluation.py`
- `backend/config.py`
- `backend/main.py`
- `frontend/src/services/aiDbQueryService.js`（新增）
- `frontend/src/components/embedding/DBQueryProfileManager.vue`（新增）
- `frontend/src/components/embedding/DatabaseIndexingTab.vue`
- `frontend/src/components/params/RagParamsPanel.vue`
- `frontend/src/views/RetrievalTestView.vue`
- `frontend/src/components/eval/TestSetManager.vue`
- `frontend/src/stores/paramsStore.js`
- `frontend/src/stores/chatStore.js`
- `frontend/src/components/chat/MessageBubble.vue`
- `frontend/src/components/chat/ChatWindow.vue`
- `frontend/src/views/EvaluationView.vue`
- `docs/03_API_CONTRACT.md`
- `docs/04_DB_SCHEMA.md`
- `docs/DevelopmentProcess/SemanticDatabaseQueryPlan.md`（規劃文件，先前新增）

## 2026-07-02 新增可切換的本地 Embedding API 風格，支援居家 Ollama / LM Studio 取代地端部署

### 功能描述
為了讓使用者能在家用 Ollama、llama.cpp、LM Studio 三套本地引擎取代公司地端的 vLLM / llama.cpp 部署，補上環境變數範本，並讓 Embedding 服務可依設定切換呼叫端點與 payload 格式。對話（`VLLM_BASE_URL` + `/chat/completions`）與 Instruct 語義解析（`DenseVector_LLAMACPP_BASE_URL` + `/v1/chat/completions`）原本就已是 OpenAI 相容格式，Ollama／LM Studio 皆相容，僅需調整 `.env`；只有 Embedding 因為原本寫死呼叫 llama.cpp 原生 `/embedding` 端點，需要新增可切換的 API 風格。

### 實作內容
1. **Embedding API 風格切換**：
   - 修改 `backend/config.py`：新增 `EMBEDDING_API_STYLE`（預設 `llamacpp`，可選 `ollama`／`openai`）。
   - 修改 `backend/services/embedding_service.py`：抽出共用私有方法 `_fetch_embedding()`，依 `EMBEDDING_API_STYLE` 決定端點路徑（`/embedding` vs `/api/embeddings` vs `/v1/embeddings`）與 payload key（`content` vs `prompt` vs `input`），回應解析沿用既有的多格式彈性解析邏輯；`get_embedding()` 與 `get_semantic_embedding()` 改為呼叫共用方法，公開簽章不變，既有呼叫端零影響。
2. **環境變數範本**：
   - 新增 `backend/.env.example`：涵蓋公司地端（vLLM/llama.cpp）與居家（Ollama/LM Studio）的對話、Instruct 語義解析、Embedding 三組設定範例（後兩者以註解形式提供替代方案），並註明 docker-compose 容器需用 `host.docker.internal` 連到宿主機上執行的本地引擎。

### 修改檔案
- `backend/config.py`
- `backend/services/embedding_service.py`
- `backend/.env.example`（新增）

## 2026-07-02 新增「語義混合回饋查詢法」並補上人工回饋→檢索來源的資料鏈路

### 功能描述
補完 RPD 4.6「人工回饋與標註歷史」的資料閉環：過去 `Feedback` 只記錄問答文字，並未記錄該次回答引用了哪些檢索片段，導致回饋資料無法回頭影響檢索排序。本次新增後，標註時會一併儲存來源片段（`filename` + `chunk_index`），並新增一種檢索模式 `semantic_hybrid_feedback`（語義混合回饋查詢法），在既有語義混合（Two-Step Hybrid + Instruct 語義分析 + RRF + LLM Rerank）流程最後，依歷史人工回饋對命中片段做分數加權重排。

### 實作內容
1. **回饋資料模型擴充**：
   - 修改 `backend/models/feedback.py`：新增內嵌模型 `FeedbackSourceChunk`（`filename`/`chunk_index`），`Feedback` 新增 `source_chunks`、`knowledge_base_id` 欄位，並新增 `source_chunks.filename` 索引。
   - 修改 `backend/routers/feedback.py`：`FeedbackCreate` 新增對應欄位，`create_feedback()` 寫入時一併儲存。
2. **前端送出回饋時夾帶來源片段**：
   - 修改 `frontend/src/components/chat/ChatWindow.vue`：`openFeedbackModal()` 額外取出當次回答的 `sources`，傳給 `FeedbackPanel`。
   - 修改 `frontend/src/components/chat/FeedbackPanel.vue`：新增 `sources` prop，送出回饋時組出 `source_chunks` 與 `knowledge_base_id`（取自 `paramsStore.knowledgeBaseId`）。
3. **回饋加權服務**：
   - 新增 `backend/services/feedback_boost_service.py`：`FeedbackBoostService.apply_feedback_boost()`，依 `(filename, chunk_index)` 統計歷史回饋正確/不正確次數，`boost = (正確-不正確)/(正確+不正確)`，套用 `final_score = score × (1 + FEEDBACK_BOOST_WEIGHT × boost)` 後重新排序；任何錯誤皆優雅降級為保留原排序，比照 `RerankService` 的寫法。
   - 修改 `backend/config.py`：新增可調參數 `FEEDBACK_BOOST_WEIGHT`（預設 `0.2`）。
4. **三處檢索路由接上新 search_type**：
   - 修改 `backend/routers/retrieval.py`（`search()`、`semantic_hybrid_search()`）、`backend/routers/rag.py`（`rag_chat_stream()`）、`backend/routers/evaluation.py`（評估執行迴圈）：`search_type in ("semantic_hybrid", "semantic_hybrid_feedback")` 時走既有語義混合流程，呼叫 Qdrant 服務時固定傳字面值 `"semantic_hybrid"`（Qdrant 層完全不修改），rerank 後若為 `semantic_hybrid_feedback` 則多套用一次 `FeedbackBoostService`。`rag.py` 額外在 SSE `vector_search` step 內容附註「已套用歷史回饋加權」。
5. **前端新增檢索模式選項**：
   - 修改 `frontend/src/components/params/RagParamsPanel.vue`、`frontend/src/views/RetrievalTestView.vue`、`frontend/src/components/eval/TestSetManager.vue`：新增「語義混合回饋查詢法 (Semantic Hybrid + Feedback)」選項；`RetrievalTestView.vue` 的 `handleSearch()` 路由判斷（打哪個端點、是否顯示語義分析步驟 UI）一併涵蓋新選項。

### 修改檔案
- `backend/models/feedback.py`
- `backend/routers/feedback.py`
- `backend/services/feedback_boost_service.py`（新增）
- `backend/config.py`
- `backend/routers/retrieval.py`
- `backend/routers/rag.py`
- `backend/routers/evaluation.py`
- `frontend/src/components/chat/ChatWindow.vue`
- `frontend/src/components/chat/FeedbackPanel.vue`
- `frontend/src/components/params/RagParamsPanel.vue`
- `frontend/src/views/RetrievalTestView.vue`
- `frontend/src/components/eval/TestSetManager.vue`

## 2026-07-01 向量管理頁面新增關聯檔案 (links_to) 管理與顯示功能

### 功能描述
在向量管理頁面中，點選主要檔案後可額外選取多個關聯檔案，並批次寫入對應點位的 `links_to` 欄位中，以便支援雙階段檢索（Two-Step Hybrid Retrieval），同時在段落列表上顯示關聯檔案徽章。

### 實作內容
1. **後端 Qdrant 批次更新**：
   - 修改 `backend/services/qdrant_service.py`：新增 `update_links_to_by_filename` 類別方法，利用 Scroll API 拉取該檔案所有 Chunks 的 Point ID，再呼叫 `set_payload` API 批次更新這些點位的 `links_to` 欄位。
2. **後端 API 路由與 Schema**：
   - 修改 `backend/schemas/retrieval.py`：新增 `UpdateLinksRequest` 模型。
   - 修改 `backend/routers/retrieval.py`：新增 `/knowledge-bases/{knowledge_base_id}/files/update-links` POST 端點。
3. **前端 API 與 UI 串接**：
   - 修改 `frontend/src/services/retrievalService.js`：新增 `updateLinks` 方法調用。
   - 修改 `frontend/src/components/embedding/VectorManagementTab.vue`：
     - 新增多選關聯檔案編輯區（Links To），自動從 Metadata 中讀取並同步既有之關聯檔案關係。
     - 在 Chunks 列表上為具備 `links_to` 的 Chunk 繪製藍色關聯徽章。

### 修改檔案
- `backend/services/qdrant_service.py`
- `backend/schemas/retrieval.py`
- `backend/routers/retrieval.py`
- `frontend/src/services/retrievalService.js`
- `frontend/src/components/embedding/VectorManagementTab.vue`

## 2026-07-01 新增雙階段關聯檢索與防幻想語意分析層系統

### 功能描述
實作具備 Graph RAG 概念的「雙階段關聯檢索」與「防幻想語意分析層」系統，優化語意混合檢索的上下文命中率與抗幻想能力。

### 實作內容
1. **語意分析層 (Query Rewriter) Prompt 優化**：
   - 修改 `backend/services/embedding_service.py`：在 `query_to_semantic_json` 的 System Prompt 中加入嚴格的反幻想限制宣告，並提供對比鮮明的 3 個 Few-Shot 範例（Good/Bad），使重寫後的 `embeddings_input` 與 `sparse_keywords` 專注於核心實體檢索特徵，避免模型擅自腦補背景。
2. **Qdrant Indexing / Payload 關聯欄位擴充**：
   - 修改 `backend/services/qdrant_service.py` (`upsert_semantic_json_chunks`) 與 `backend/routers/embedding.py` (`/vectorize` 路由)：寫入 Qdrant 點位時，手動在 Payload 中寫入 `links_to` (關聯檔案名稱或自訂 Point ID) 與 `class` 清單。
3. **雙階段檢索機制 (Two-Step Hybrid Retrieval) 實作**：
   - 修改 `backend/services/qdrant_service.py`：新增 `search_similar_two_step` 類別方法。第一階段呼叫 `search_similar` 取得 core point；第二階段提取點位的 `links_to` 陣列，使用 Qdrant Scroll API 拉取這些關聯的一階鄰居點位 (2nd-hop Search)。最後對鄰居點位執行 parent_id 合併還原，並與 core points 合併進行嚴格的內容 `.strip()` 去重後回傳。
4. **API 與 RAG 流程整合**：
   - 修改 `backend/schemas/retrieval.py`：在 `RetrievalMetadata` 中新增 `links_to` 欄位。
   - 修改 `backend/routers/rag.py` 的對話串流與 `backend/routers/retrieval.py` 的 `/search`、`/semantic-hybrid-search` 路由，當啟用語義混合查詢 (`search_type == "semantic_hybrid"`) 時，調用 `search_similar_two_step` 取代原本的一階段 hybrid 檢索，並將關聯欄位輸出。
5. **單元測試建立**：
   - 新增 `tests/test_two_step_search.py` 測試檔案，對雙階段檢索進行 Mock 測試，模擬無 link、有 link 及重複內容去重的各種檢索情境，確保功能完整性。

### 修改檔案
- `backend/services/embedding_service.py`
- `backend/services/qdrant_service.py`
- `backend/routers/embedding.py`
- `backend/routers/rag.py`
- `backend/routers/retrieval.py`
- `backend/schemas/retrieval.py`
- `tests/test_two_step_search.py` (新設)
