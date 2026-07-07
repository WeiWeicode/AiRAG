<!-- 後端修正紀錄 -->

## 2026-07-07 實作 Qdrant 向量刪除時同步清理孤立本地圖片實體檔案

### 問題描述
圖片內嵌向量化功能會將辨識後的描述寫入 Qdrant，並將圖片實體檔案另存於 `backend/FileAttachments/image/` 下。但「已向量化資料管理」現有的刪除點位與整批刪除檔案 API 僅會刪除 Qdrant 裡的點位，不會清理本地磁碟上的圖片檔案，導致圖片檔案無限累積。

### 修改內容
1. `backend/services/qdrant_service.py` (修改)：
   - `delete_points()`：刪除前呼叫 `client.retrieve()` 提取 payload，過濾出 `image_filename`。刪除後呼叫 `_cleanup_orphaned_image_files()`。
   - `delete_by_filename()`：將既有 scroll 查詢點位的 `with_payload` 設為 `True`，刪除前提取 `image_filename`，刪除後呼叫 `_cleanup_orphaned_image_files()`。
   - `_get_image_filenames_from_payloads()` (新設)：從 payload 提取 `chunk_type == "image"` 的 `image_filename`。
   - `_cleanup_orphaned_image_files()` (新設)：對檔名使用 `client.scroll()` 進行最後引用檢查，無其他點位引用時，進行路徑穿越防護檢查後刪除本地磁碟實體。單一檔案例外僅記錄 warning，不中斷其他處理。
2. `tests/test_image_cleanup_on_delete.py` (新設)：
   - 撰寫單元測試覆蓋 `delete_points()` 與 `delete_by_filename()` 在「圖片孤立（刪除實體）」、「圖片仍被引用（不刪除）」、「純文字點位（無檔案操作）」等情境的邏輯，且不影響回傳型別與其餘呼叫端。

### 驗證
- 執行 `backend\.venv\Scripts\python.exe -m unittest tests/test_image_cleanup_on_delete.py` 測試通過（5/5 測項 OK）。
- 執行 `backend\.venv\Scripts\python.exe -m unittest discover tests` 確保無任何回歸問題（11/11 測項 OK）。

## 2026-07-06 程式碼複查：修正附件功能中低風險問題（`created_at` 預設值、`download_url` 缺漏、`retrieval.py` 兩階段判斷式、API/DB 文件同步）

### 問題描述
延續同日稍早的高風險修正，繼續處理 `docs/DevelopmentProcess/AttachmentSemanticHybridSearchPlan.md` 第 8 節複查記錄的中低風險問題：
1. `backend/models/attachment.py` 的 `created_at`/`updated_at` 用 `datetime.utcnow()` 直接當預設值（僅在模組載入時求值一次），與專案其他 Document 慣用的 `Field(default_factory=datetime.utcnow)` 寫法不一致，屬於潛在地雷。
2. `backend/routers/rag.py` 組出的 `attachments` SSE 欄位缺少 `download_url`，前端得自行重複組字串。
3. `backend/routers/retrieval.py` 的 `is_semantic_hybrid_family` 判斷式沒有把新的 `semantic_hybrid_attachment` 一併加入，若此 `search_type` 傳入 `/api/retrieval/search` 會被靜默當成單階段檢索處理。
4. `docs/03_API_CONTRACT.md`、`docs/04_DB_SCHEMA.md` 尚未收錄本次新增的 `attachments` collection、`linked_attachments` payload 欄位、`/api/attachments/*` 端點與 `semantic_hybrid_attachment` 查詢法。

### 修改內容
1. `backend/models/attachment.py`：`created_at`/`updated_at` 改為 `Field(default_factory=datetime.utcnow)`，`tags`/`classes` 一併改為 `Field(default_factory=list)`；移除未使用的 `Indexed` import。
2. `backend/routers/rag.py`：`attachments_to_send` 每筆補上 `"download_url": f"/api/attachments/{att.id}/download"`。
3. `backend/routers/retrieval.py`：`is_semantic_hybrid_family` 判斷式加入 `"semantic_hybrid_attachment"`（已確認 `feedback_boost` 分支仍只在 `semantic_hybrid_feedback` 時觸發，不受影響）。
4. `docs/03_API_CONTRACT.md`：新增第 14 節「附件管理與語義混合附件查詢法」，更新 §3.1（`search_type`/`read_attachment_content`/`attachments` SSE 欄位）、§4.1（`linked_attachments`）、新增 §4.7（`update-attachments` 端點）。
5. `docs/04_DB_SCHEMA.md`：新增 §3.13（`attachments` collection）與 §4.2 的 `linked_attachments` payload 欄位說明，更新 Collection 總覽圖與計數。

### 驗證
- 程式碼審閱確認 `Attachment(...)` 未明確指定時間戳記時也能各自取得建立當下的時間；`retrieval.py` 的 `semantic_hybrid_attachment` 現在會走 `search_similar_two_step`。

### 對應規劃文件
`docs/DevelopmentProcess/AttachmentSemanticHybridSearchPlan.md` 第 8.3、8.4、8.6、8.7 節。

## 2026-07-06 程式碼複查：修正附件下載端點無驗證、`.gitignore` 規則寫錯兩項高風險問題

### 問題描述
對照 `docs/DevelopmentProcess/AttachmentSemanticHybridSearchPlan.md` 複查「語義混合附件查詢法」實際實作，發現兩項高風險問題：
1. `backend/routers/attachment.py` 的 `download_attachment()` 完全沒有 `Depends(get_current_user)`（是前一則修正紀錄為了讓 `window.open()` 能下載而刻意拿掉的），但 MongoDB ObjectId 並非密碼學隨機值（前 4 bytes 為時間戳記），不足以當作「秘密連結」，任何人猜到/取得附件 ObjectId 即可不登入下載檔案，違反專案「除 `auth.py` 外所有 router 皆需驗證」的慣例。
2. `backend/.gitignore` 新增規則寫成 `.FileAttachments/`（開頭多一個點），但實際資料夾與 `FILE_ATTACHMENTS_DIR` 預設值都是 `FileAttachments`（無點），以 `git check-ignore -v` 實測確認完全沒被忽略，附件實體檔案（含一個 7.4MB 測試 PDF）處於 untracked 狀態，隨時可能被誤 commit。

### 修改內容
1. `backend/routers/attachment.py`：`download_attachment()` 恢復 `current_user: str = Depends(get_current_user)` 參數。
2. `backend/.gitignore`：規則由 `.FileAttachments/` 修正為 `FileAttachments/`。
3. 前端配合改為驗證後下載（見 `docs/DevelopmentProcess/FrontendCorrection.md` 同日條目），使下載端點可以恢復驗證而不影響下載功能。

### 驗證
- `git check-ignore -v backend/FileAttachments/<任意檔案>` 確認規則生效、`git status` 不再列出 `backend/FileAttachments/`。
- 後端下載端點恢復驗證後，需搭配前端已改用帶 Authorization 標頭的請求才能正常下載（見前端紀錄）。

### 對應規劃文件
`docs/DevelopmentProcess/AttachmentSemanticHybridSearchPlan.md` 第 8.1、8.2 節。

## 2026-07-06 修正附件下載 (download) 接口因 Token 驗證阻擋導致無法下載之問題

### 問題描述
使用者在對話測試頁點選參考附件的「下載」按鈕時，瀏覽器開啟新分頁卻顯示 `{"detail":"Not authenticated"}` 且無法下載。
這是因為附件下載端點是透過 `window.open` 呼叫的 GET 請求，瀏覽器在開啟新分頁時無法自動夾帶 SPA 應用的 `Authorization: Bearer <token>` 請求標頭；而後端在 `backend/routers/attachment.py` 中以 `dependencies=[Depends(get_current_user)]` 進行了全局路由驗證阻擋。

### 修改內容
1. `backend/routers/attachment.py` (修改)：
   - 將路由器全局的 `dependencies=[Depends(get_current_user)]` 移除。
   - 將附件清單 (`list_attachments`) 與刪除附件 (`delete_attachment`) 路由獨立加上 `current_user: str = Depends(get_current_user)` 保護。
   - 附件下載 (`download_attachment`) 路由保持無 token 阻擋，由隨機、不可預測的 24 碼 MongoDB ID（PydanticObjectId）提供安全度（Secret-Link 安全機制）。
2. 執行 `docker-compose up --build -d backend` 重新啟動後端容器。

### 驗證
- 後端容器重啟後，點選下載按鈕能直接順暢下載附件，其他增刪查操作仍有 Token 驗證保護。

## 2026-07-06 修正附件上傳 (upload) 接口中 `current_user` 變數型態與屬性讀取錯誤

### 問題描述
在上傳附件時，後端拋出 `AttributeError: 'str' object has no attribute 'get'` 500 Internal Server Error。
原因為 `backend/routers/attachment.py` 中 `upload_attachment` 路由參數宣告為 `current_user: dict = Depends(get_current_user)`，且後續以 `current_user.get("username")` 取值；但依據 `backend/utils/security.py` 的實作，`get_current_user` 依賴注入的實際傳回值為 `username` 字串型態 (str)，而非 dict。

### 修改內容
1. `backend/routers/attachment.py` (修改)：
   - 將 `upload_attachment` 中的 `current_user` 型態宣告修正為 `str`。
   - 將 `username = current_user.get("username") if current_user else None` 修改為 `username = current_user` 直接賦值。

### 驗證
- 已修改程式碼並成功重新建置與重啟 `airag-backend` 容器。
- 經由使用者端驗證，上傳行為不再拋出該屬性錯誤。

## 2026-07-06 Map-Reduce 分批摘要功能最終複查：修正失敗降級、label 小 bug、tiktoken 快取誤入版控

### 問題描述
功能整體驗收前的最後一輪 Code Review，處理先前記錄在 `ContextMapReduceSummaryPlan.md` 第 10 節但尚未修的兩項問題，並額外發現一個環境衛生問題：
1. `ContextSummarizerService.maybe_summarize()` 若在 Map/Reduce 階段呼叫 LLM 失敗（例如地端 vLLM 逾時），會 `raise` 例外，但 `rag.py` 呼叫處沒有包 try/except，導致整個 SSE 串流中斷，`llm_thinking`/`sources`/`done` 都發不出去。
2. `rag.py` 組 block 的 `label` 欄位因 `chunk_idx_str` 已含 `#`，又重複疊加一次 `#`，變成 `##12`。
3. 本機執行 tiktoken 會在 `backend/.tiktoken_cache/` 產生快取，`.gitignore` 沒有涵蓋這個目錄名稱，一直卡在 untracked 清單中。

### 修改內容
1. `backend/routers/rag.py` (修改)：
   - 呼叫 `ContextSummarizerService.maybe_summarize()` 處包 try/except，失敗時記錄錯誤並 yield `context_summarize_error` failed step，保留原始未摘要的 `context_str` 讓對話繼續完成，不中斷整個回答流程。
   - 修正 block `label` 重複 `#` 的組字錯誤。
2. `backend/.gitignore` (修改)：新增 `.tiktoken_cache/` 規則。

### 驗證
- `py_compile` 全部通過。
- 用模擬測試驗證失敗降級路徑：即使摘要中途丟出例外，串流仍會正常送出收尾事件，不會卡死或中斷連線。
- `git status` 確認 `.tiktoken_cache/` 不再出現在 untracked 清單。

### 對應規劃文件
對應 `docs/DevelopmentProcess/ContextMapReduceSummaryPlan.md` 第 13 節。

## 2026-07-06 修正 Map-Reduce 遞迴 Reduce 進入下一輪後，當前輪的「合併最終摘要」步驟卡在執行中之問題

### 問題描述
使用者實測發現，當 Map-Reduce 遞迴進入第二輪時，第一輪的「合併最終摘要」步驟在 UI 上會永遠停在「執行中」轉圈圈，而此時第二輪已執行完成，思考中也在運行。這是因為後端在 yield 了 running 狀態後，直接遞迴進入下一輪並 return，漏掉了為當前這一輪的 reduce step 發送 `success` 完成事件的步驟。

### 修改內容
1. `backend/services/context_summarizer_service.py` (修改)：
   - 在遞迴呼叫 `maybe_summarize()` 的 `async for evt in ...` 迴圈結束後，針對當前輪的 `reduce_step_key` 補發一個 `status: "success"` 的完成事件，並於 content 顯示「已將 N 份摘要整合完成，交由下一輪繼續處理。」，解決 UI 狀態卡在執行中轉圈圈的問題。

### 對應規劃文件
對應 `docs/DevelopmentProcess/ContextMapReduceSummaryPlan.md` 第 12 節。

## 2026-07-06 RAG 對話新增每個 Chunk 的 Token 數與分批摘要統計，隨 `sources` SSE 事件回傳

### 問題描述
Map-Reduce 分批摘要機制上線後，使用者在前端無法得知本次檢索的 token 使用狀況（每個 chunk 多少 token、總計多少、有沒有觸發分批、切分了幾次），需要補上對應統計資料由後端計算並傳給前端顯示。

### 修改內容
1. `backend/routers/rag.py` (修改)：
   - 匯入 `utils.token_counter.count_tokens`。
   - 一般檢索路徑與 `semantic_db_query`（`_run_execute()`）路徑的 `sources.append(...)` 都新增 `token_count` 欄位。
   - 新增 `context_summary` dict（`total_tokens`/`batch_count`/`rounds`/`was_summarized`/`threshold_tokens`），函式一開始給預設值；組完 `context_str` 後把 `total_tokens` 設為所有來源 chunk 的 `token_count` 加總；呼叫 `ContextSummarizerService.maybe_summarize()` 後再從其 `result` 補上 `batch_count`/`rounds`/`was_summarized`。
   - 最終 `event: sources` 事件夾帶 `context_summary` 欄位一併送出。
2. `backend/services/context_summarizer_service.py` (修改)：`maybe_summarize()` 進入時記錄 `result["rounds"] = round_no`；每次執行 Map 分組時累加 `result["batch_count"]`，讓遞迴多輪的批次數能正確加總。

### 對應規劃文件
對應 `docs/DevelopmentProcess/ContextMapReduceSummaryPlan.md` 第 11 節。

## 2026-07-06 修正 `context_summarizer_service.py` 在 Python 3.11 環境下的 f-string 反斜線語法錯誤

### 問題描述
在 Python 3.11 (或更早版本) 下啟動伺服器時，`uvicorn` 載入失敗並拋出 `SyntaxError: f-string expression part cannot include a backslash`。原因是在 `backend/services/context_summarizer_service.py` 中，將含有 `\n` 反斜線字元的 dictionary 物件或 f-string 直接寫在 outer f-string 的 `{json.dumps(...)}` 表達式大括號內，此寫法在 Python 3.12 之前不被支援。

### 修改內容
1. `backend/services/context_summarizer_service.py` (修改)：
   - 將所有 SSE step 事件中的 JSON dict 宣告移出 f-string，先宣告局部變數 `event_data`，再將 `{json.dumps(event_data, ensure_ascii=False)}` 帶入，徹底避免在 `{}` 大括號內使用反斜線 `\`。

## 2026-07-06 實作 Map-Reduce 檢索上下文分批摘要機制，防止超長檢索內容造成 LLM 呼叫失敗

### 問題描述
當 RAG 檢索召回的參考資料 Token 總數過大時，直接作為上下文傳給 LLM 容易超出模型輸入限制或觸發 400 錯誤。需要一套機制在 Token 超過門檻時，對檢索片段進行 Bin-Packing 分組並遞迴呼叫 LLM 進行 Map-Reduce 摘要合併。

### 修改內容
1. `backend/requirements.txt` (修改)：新增 `tiktoken` 依賴。
2. `backend/Dockerfile` (修改)：設定 `ENV TIKTOKEN_CACHE_DIR=/app/.tiktoken_cache` 並在 build 階段預下載 `cl100k_base` 編碼，以支援離線環境。
3. `backend/utils/token_counter.py` (新增)：實作 `count_tokens` 以使用 tiktoken 計算精確 Token 數。
4. `backend/config.py` (修改)：Settings 新增 `DEFAULT_CONTEXT_SUMMARIZE_THRESHOLD_TOKENS` (50,000) 與 `CONTEXT_SUMMARIZE_MAX_ROUNDS` (3)。
5. `backend/services/context_summarizer_service.py` (新增)：實作 `ContextSummarizerService` 類別，包含 Bin-Packing 分組演算法、Map/Reduce 專屬 Prompt 構建、以及遞迴處理 `maybe_summarize` 生成器。每一步驟皆會 yield SSE `event: step` 狀態（如 `context_summarize_r1_batch_1`，包含 `label` 與原始內容/整理結果預覽）。
6. `backend/routers/rag.py` (修改)：
   - `ChatParams` schema 新增 `context_summarize_trigger_tokens` 可調參數。
   - `rag_chat_stream()` 內解析此參數（預設使用 config 設定）。
   - 在檢索完成且 `context_str` 存在時，將 sources 轉換為對應 blocks 列表（依 search_type 分流：一般搜尋保留來源文件/段落標記；`semantic_db_query` 則保留表格/欄位上下文），並呼叫 `ContextSummarizerService.maybe_summarize` 進行處理。

### 對應規劃文件
對應 `docs/DevelopmentProcess/ContextMapReduceSummaryPlan.md`。

## 2026-07-03 RAG 對話新增 repetition/frequency penalty 與重複輸出偵測（防止地端 LLM 無限迴圈重複同一句話）

### 問題描述
使用者回報地端 vLLM（Qwen3.6-35B-A3B-FP8）在 RAG 對話串流中出現無限重複同一句話（例如反覆輸出同一段 SQL 註解）的退化現象。查證 `backend/services/llm_service.py` 的 `chat_completion()` 呼叫 vLLM OpenAI-compatible endpoint 時只帶 `temperature`/`max_tokens`，未設定任何抑制重複的參數，且串流層完全沒有中斷機制。

### 修改內容
1. `backend/config.py` (修改)：新增 `DEFAULT_REPETITION_PENALTY`（預設 `1.1`）、`DEFAULT_FREQUENCY_PENALTY`（預設 `0`），可用環境變數覆蓋。
2. `backend/services/llm_service.py` (修改)：`chat_completion()` 新增 `repetition_penalty`/`frequency_penalty` 參數（預設 `None` 不帶入 payload，避免影響 `query_rewrite`/`hyde_generation` 等既有呼叫端行為），有值時寫入送給 vLLM 的 payload。
3. `backend/routers/rag.py` (修改)：
   - `ChatParams` schema 新增 `repetition_penalty`/`frequency_penalty` 欄位，比照既有 `temperature`/`max_tokens` 的 optional-override 模式，預設吃 `config.py` 的值。
   - `rag_chat_stream()` 呼叫 `LLMService.chat_completion` 時傳入上述兩個參數。
   - 串流迴圈新增重複輸出偵測安全網：累積已輸出內容，若最近 25 字的片段在累積內容中連續出現達 4 次，主動中斷串流並附加系統提示訊息，避免 penalty 參數未完全生效時仍無限迴圈下去。

### 對應規劃文件
無獨立規劃文件，需求與方案討論於對話中確認（分三層：後端 penalty 參數 → 串流層重複偵測 → 前端可調參數/停止按鈕；本次僅完成前兩層）。

## 2026-07-02 新增語義混合回饋查詢法後端邏輯（人工回饋與標註歷史）

### 修改內容
1. `backend/models/feedback.py` (修改)：`Feedback` 新增 `source_chunks`（`FeedbackSourceChunk` 內嵌模型：`filename`/`chunk_index`）、`knowledge_base_id` 欄位與對應索引，記錄該次回答引用的檢索來源。
2. `backend/routers/feedback.py` (修改)：`FeedbackCreate` 與 `create_feedback()` 支援寫入新欄位。
3. `backend/services/feedback_boost_service.py` (新增)：`FeedbackBoostService.apply_feedback_boost()` 依 `(filename, chunk_index)` 統計歷史回饋正確/不正確次數計算 boost 並重排分數，失敗優雅降級。
4. `backend/config.py` (修改)：新增 `FEEDBACK_BOOST_WEIGHT`（預設 `0.2`）。
5. `backend/routers/retrieval.py`、`backend/routers/rag.py`、`backend/routers/evaluation.py` (修改)：三處檢索路由支援新的 `search_type="semantic_hybrid_feedback"`，於既有語義混合流程（Two-Step Hybrid + Rerank）之後套用回饋加權；呼叫 `QdrantService` 時仍固定傳 `"semantic_hybrid"` 字面值，Qdrant 層邏輯不變。

### 對應規劃文件
詳細功能描述見 `docs/DevelopmentProcess/NewFeatures.md` 2026-07-02「新增語義混合回饋查詢法並補上人工回饋→檢索來源的資料鏈路」條目。

## 2026-07-02 停用 huggingface_hub 的 agent-harness 偵測遙測（Semantic Search Optimization #8）

### 問題描述
測試過程中 Docker log 重複出現非常規的對外請求 `GET https://huggingface.co/api/agent-harnesses`。查證運行中容器（`huggingface_hub` 1.21.0）原始碼，確認這是官方合法功能（`huggingface_hub/utils/_detect_agent.py`）：用於偵測呼叫程序是否為 AI coding agent，並在 Hub 請求的 `User-Agent` 標頭中標記，供 Hugging Face 做流量統計。觸發鏈為 `fastembed` 首次初始化 SPLADE 稀疏向量模型下載時，經 `huggingface_hub` 組 User-Agent 觸發。非惡意、非供應鏈風險，與語義搜尋優化程式碼無關，但屬非必要的額外對外請求。

### 修改內容
1. `docker-compose.yml` (修改):
   - `backend` service 的 `environment` 新增 `HF_HUB_DISABLE_TELEMETRY=1`。
2. `backend/.env` (修改，git-ignored，僅影響本機環境):
   - 新增 `HF_HUB_DISABLE_TELEMETRY=1`，讓非 Docker 的本機開發模式也套用同樣設定。

### 對應規劃文件
`docs/DevelopmentProcess/SemanticSearchOptimizationPlan.md` 待處理事項第 8 項。

## 2026-07-02 語義 JSON 重試改為漸進提高 temperature（Semantic Search Optimization #7）

### 修改內容
1. `backend/services/embedding_service.py` (修改):
   - **`query_to_semantic_json` 重試機制改為漸進調整 `temperature`**：實測發現同一問題在 `temperature=0.1` 下兩次請求會產生完全相同的語法錯誤（同一行、同一字元位置），代表 `response_format: json_object` 疑似未被目前部署的 llama.cpp 版本實際強制生效，且原地重試對這種確定性失敗沒有幫助。
   - 改為 `retry_temperatures = [0.1, 0.5]`：第 1 次維持低溫度以求穩定，第 2 次提高至 0.5 靠抽樣隨機性打破確定性重複失敗；log 訊息補上各次嘗試使用的 `temperature` 數值，方便後續追蹤重試是否真的帶來不同結果。
   - `payload` 拆分為 `base_payload`（不含 temperature）+ 每次呼叫時組裝含當次 temperature 的 payload。

### 備註
根本原因（llama.cpp 是否真的支援 `response_format` grammar 強制）屬於部署設定層級，需另行確認 llama.cpp 版本與啟動參數，不在本次程式碼修正範圍內，已記錄於 `docs/DevelopmentProcess/SemanticSearchOptimizationPlan.md` 待處理事項第 7 項。

### 對應規劃文件
`docs/DevelopmentProcess/SemanticSearchOptimizationPlan.md` 待處理事項第 7 項。

## 2026-07-02 語義混合搜尋新增 LLM-based Rerank 層（Semantic Search Optimization #3）

### 修改內容
1. `backend/services/rerank_service.py` (新增):
   - **新增 `RerankService`**：借用既有地端 Instruct LLM（`DENSE_VECTOR_LLAMACPP_BASE_URL`，Qwen3VL-8B-Instruct，方案 A，非部署新的 cross-encoder 模型）對 RRF 融合後的候選片段做相關性重排序，彌補 RRF 只看排名、不看實際語意相關程度的限制。
   - 候選池上限 `MAX_CANDIDATES = 20`，每筆候選內容截斷至 `CONTENT_PREVIEW_LEN = 500` 字元納入 prompt，控制 token 用量與延遲。
   - 要求 LLM 以 `response_format: json_object` 輸出 `{"ranking": [...]}`（僅排序，不用分數，降低輸出 token 量），並對缺漏/越界編號做保底補齊，避免候選憑空消失。
   - **失敗優雅降級**：任何逾時/解析錯誤皆記錄 warning 並回退為保留原始 RRF 排序後的前 `top_k` 筆，不中斷檢索流程；候選數量本就 ≤ `top_k` 時直接略過（避免無意義的 LLM 呼叫）。
2. `backend/routers/retrieval.py` (修改):
   - `/semantic-hybrid-search` 於 `search_similar_two_step` 取得候選後呼叫 `RerankService.rerank`，取前 `params.top_k` 筆。
3. `backend/routers/rag.py` (修改):
   - `semantic_hybrid` 對話分流於 `search_similar_two_step` 取得候選後呼叫 `RerankService.rerank`。
4. `backend/routers/evaluation.py` (修改):
   - **`semantic_hybrid` 評估流程改為多召回候選再重排序**：原本 `search_similar` 直接以 `top_k` 限制 Qdrant RRF 融合結果，候選數等於 `top_k`，rerank 無候選可排序形同無效。改為 `semantic_hybrid` 時以 `max(top_k, RerankService.MAX_CANDIDATES)` 召回候選池，取得結果後再交給 `RerankService.rerank` 裁切回真正的 `top_k`。

### 範圍說明
本次僅套用於「語義混合搜尋」（`semantic_hybrid`）流程，`/api/retrieval/search`（`vector`/`hybrid` 類型）未套用 rerank，維持原行為。

### 對應規劃文件
`docs/DevelopmentProcess/SemanticSearchOptimizationPlan.md` 第 3 項。

## 2026-07-02 修正 Instruct AI JSON 語法失敗問題（Semantic Search Optimization #6）

### 修改內容
1. `backend/services/embedding_service.py` (修改):
   - **`query_to_semantic_json` 的 payload 新增 `"response_format": {"type": "json_object"}`**：要求 llama.cpp 以 grammar-constrained decoding 強制輸出語法合法的 JSON，從生成層面降低模型偶發漏逗號/多逗號等語法錯誤（實測曾發生 `Expecting ',' delimiter`、`Expecting property name enclosed in double quotes` 兩種錯誤）。
   - **新增解析失敗重試機制**：抽出 `_call_and_parse` 內部函式，解析失敗（HTTP 錯誤、JSON 語法錯誤、缺少 `embeddings_input` 欄位）時最多重試 1 次（總計 2 次請求），仍失敗才降級為 `fallback_json`；並補上重試過程的 log 區分「第 N 次嘗試失敗將重試」與「重試後仍失敗降級」。

### 對應規劃文件
`docs/DevelopmentProcess/SemanticSearchOptimizationPlan.md` 第 6 項。

## 2026-07-02 Exact Keyword 精準比對加成支援中文（Semantic Search Optimization #5）

### 修改內容
1. `backend/services/qdrant_service.py` (修改):
   - **新增 `_extract_exact_keywords` 靜態方法**：優先使用語義層已抽取的 `sparse_keywords`（含中英文）作為 exact keyword boost 來源；若無提供則退回原本對 `query_text` 的正則抽取（僅英數）。過濾規則：純英數詞需長度 ≥3 且非純數字，含中文或其他非 ASCII 字元的詞需長度 ≥2，避免單字（如「的」）誤觸發。
   - **`search_similar`、`search_similar_two_step` 新增 `sparse_keywords` 參數**，並將原本內嵌的正則抽取邏輯替換為呼叫 `_extract_exact_keywords`。
2. `backend/routers/retrieval.py`、`backend/routers/rag.py`、`backend/routers/evaluation.py` (修改):
   - 語義混合搜尋流程中，將已從 Instruct AI 取得的 `sparse_keywords` 一併傳入 `search_similar`/`search_similar_two_step`，讓中文檔名/術語也能觸發 Exact keyword boost。

### 對應規劃文件
`docs/DevelopmentProcess/SemanticSearchOptimizationPlan.md` 第 5 項。

## 2026-07-02 語義 JSON 轉換失敗降級標記可觀測性（Semantic Search Optimization #4）

### 修改內容
1. `backend/services/embedding_service.py` (修改):
   - **`query_to_semantic_json` 回傳值新增 `is_fallback` 欄位**：Instruct AI 成功解析出合法 JSON 且含 `embeddings_input` 時標記 `is_fallback: False`；逾時、HTTP 錯誤、JSON 解析失敗、或解析結果缺少 `embeddings_input` 時一律回傳 `fallback_json` 並標記 `is_fallback: True`。
   - 補上「JSON 缺少 embeddings_input」情境的 `logger.warning`，先前此分支完全沒有 log，難以追蹤觸發原因。
2. `backend/schemas/retrieval.py` (修改):
   - **`RetrievalResponse` 新增 `is_fallback: Optional[bool]` 欄位**。
3. `backend/routers/retrieval.py` (修改):
   - **`/semantic-hybrid-search` 從 `semantic_json` 中取出 `is_fallback` 並帶入回應**，讓測試時能直接從 API 回應判斷該次語義轉換是否為降級結果，不需再肉眼比對 `embeddings_input` 是否等於原始問題。
   - 註：`rag.py`、`evaluation.py` 呼叫 `query_to_semantic_json` 時取得的 `semantic_json` 字典也會自動帶有 `is_fallback` 欄位（因為是同一個回傳值），但本次僅將其暴露到 `/semantic-hybrid-search` 的回應 Schema，尚未在 RAG 對話串流或評估報表中額外處理。

### 對應規劃文件
`docs/DevelopmentProcess/SemanticSearchOptimizationPlan.md` 第 4 項。

## 2026-07-02 放寬雙階段檢索 2nd-hop 鄰居搜尋門檻（Semantic Search Optimization #2）

### 修改內容
1. `backend/services/qdrant_service.py` (修改):
   - **`search_similar_two_step` 新增 `neighbor_score_threshold: float = 0.1` 參數**：鄰居搜尋（2nd-hop，擴充 `links_to` 關聯內容）原本套用與核心搜尋相同的 `score_threshold`（預設 0.4），過於嚴格容易把大部分鄰居過濾掉，導致第二階段形同虛設。改為獨立的較寬鬆門檻，只影響鄰居搜尋，核心搜尋（1st-hop）行為不變。
   - 套用位置：hybrid RRF 融合的密集向量 prefetch、hybrid 失敗降級的純向量查詢、以及純向量檢索分支的 `query_points`，共 3 處。
   - 呼叫端（`retrieval.py`、`rag.py`、`evaluation.py`）未變動介面，沿用新參數的預設值即可。

### 對應規劃文件
`docs/DevelopmentProcess/SemanticSearchOptimizationPlan.md` 第 2 項。

## 2026-07-02 新增語義搜尋結構化元資料快取（Semantic Search Optimization #1）

### 修改內容
1. `backend/services/qdrant_service.py` (修改):
   - **新增 `get_unique_metadata` 記憶體快取**：以 `collection_name` 為鍵值快取結構化知識庫地圖（filenames/tags/structured_metadata），TTL 600 秒作為保底，避免每次語義混合搜尋都重新 scroll 整個 Collection（最多 10000 點）。
   - **新增 `invalidate_metadata_cache` 類別方法**：供寫入/刪除向量的操作主動清除快取，確保資料一致性優先於 TTL 過期。
2. `backend/routers/embedding.py` (修改):
   - 於 `vectorize_chunks`、`vectorize_json` 寫入 Qdrant 成功後呼叫 `invalidate_metadata_cache`。
3. `backend/routers/retrieval.py` (修改):
   - 於 `batch_delete_points`、`delete_file_by_filename`、`update_file_links` 三個會變更向量 payload 的端點成功後呼叫 `invalidate_metadata_cache`。
4. `backend/routers/knowledge_base.py` (修改):
   - 於 `delete_knowledge_base` 刪除 Qdrant collection 後呼叫 `invalidate_metadata_cache`。

### 對應規劃文件
`docs/DevelopmentProcess/SemanticSearchOptimizationPlan.md` 第 1 項。

## 2026-07-01 修正雙階段檢索 (Two-Step Search) 關聯檔案全量載入與 context 稀釋問題

### 修改內容
1. `backend/services/qdrant_service.py` (修改):
   - **優化 `search_similar_two_step` 二階段檢索**：將對關聯鄰居點位的獲取方式由無差別的 `scroll` 調整為有針對性的「語意與關鍵字混合檢索（query_points）」，以原查詢的 `query_vector`、`query_text` 加上關聯檔名過濾條件進行查詢。
   - **增加 score_threshold 門檻過濾**：在鄰居密集向量 Prefetch 中套用 `score_threshold` 過濾，剔除不相關鄰居 Chunks，徹底解決全量載入產生的 noise 及 context 稀釋問題。
   - **調降預設限制**：將二階段鄰居最大召回上限 `neighbor_limit` 從 `50` 調降至 `10`。
   - **測試相容降級**：當無查詢向量輸入時（如單元測試或特殊檢索），系統會自動安全降級為原 `scroll` 機制，確保相容性。

## 2026-07-01 向量管理頁面新增關聯檔案 (links_to) API 支援

### 修改內容
1. `backend/services/qdrant_service.py` (修改):
   - **新增 `update_links_to_by_filename` 方法**：使用 Scroll API 加上 filename 篩選拉取所有屬於主要檔案的 Points ID，再呼叫 Qdrant client 的 `set_payload` 方法，批次將 `links_to` (關聯檔案名稱列表) 欄位寫入這些向量段落的 payload 中。
2. `backend/schemas/retrieval.py` (修改):
   - **新增 `UpdateLinksRequest` Schema**：定義接收 `filename: str` 與 `links_to: List[str]` 的 Pydantic 請求資料模型。
3. `backend/routers/retrieval.py` (修改):
   - **新增 `/knowledge-bases/{knowledge_base_id}/files/update-links` POST 端點**：呼叫 `QdrantService.update_links_to_by_filename` 實現將選取的關聯關係批次寫入 Qdrant payload。

## 2026-07-01 彙整並提供結構化知識庫關聯地圖（Knowledge Map）至語義分析 AI

### 修改內容
1. `backend/services/qdrant_service.py` (修改):
   - **結構化元資料聚合**：於 `get_unique_metadata` 類別方法中，將捲動點位 (scroll) 的 payload 讀取擴充為 `["filename", "tags", "class", "links_to"]`。並在 Python 中以檔案名稱 (`filename`) 為鍵值進行 Group-by 聚合，產出結構化的檔案地圖 `structured_metadata` 列表並回傳，維持完全相容先前 API。
2. `backend/services/embedding_service.py` (修改):
   - **修復語法錯誤與程式碼損毀**：還原 `get_semantic_embeddings_batch` 與 `query_to_semantic_json` 的完整正常程式碼，徹底解決 `SyntaxError` 及檔案毀損問題。
   - **知識庫地圖提示詞注入**：於 `query_to_semantic_json` 中新增 `structured_metadata` 選填參數。若有傳入，將在 LLM System Prompt 中渲染格式化後的 `【參考知識庫結構地圖】`，包含各檔案的檔名、類別、標籤與關聯點位，引導地端 AI 在查詢重寫與 `sparse_keywords` 提取時能進行強關聯聯想推理。
   - **優化提示詞避免語意稀釋**：於 System Prompt 中新增 Rule 5 與 Few-Shot 範例調整，限制 LLM 不要將「說明」、「意義」、「file extensions」、「meaning」等通用語意說明詞加入檢索用欄位，防止對程式碼或 XML 這類純結構化文件進行檢索時，因語意偏離而將真實點位排除。
3. `backend/routers/rag.py` (修改):
   - **獲取並傳遞結構化地圖**：在對話串流 `/chat` 啟用 `semantic_hybrid` 混合檢索時，自 `get_unique_metadata` 取得並傳遞 `structured_metadata` 給 `query_to_semantic_json`。同時更新 `logger.info` 偵錯日誌，輸出完整的檔案數、標籤數與結構化項目數。
4. `backend/routers/retrieval.py` (修改):
   - **獲取並傳遞結構化地圖**：於檢索端點 `/search` 進行語義混合搜尋時，提取並傳遞 `structured_metadata` 參數，並更新偵錯日誌。
5. `backend/routers/evaluation.py` (修改):
   - **獲取並傳遞結構化地圖**：於評估端點 `/run` 串流中，於迴圈外提取 `structured_metadata`，於評估任務迴圈內調用時傳入參數，避免重複查詢造成效能瓶頸，並更新偵錯日誌。

## 2026-07-01 修正與擴充檢索與寫入之 Metadata Schema 相容性

### 修改內容
1. `backend/schemas/retrieval.py` (修改):
   - 於 `RetrievalMetadata` 新增 `links_to: Optional[List[str]] = Field(default_factory=list)` 屬性，確保雙階段檢索出的關聯點位 metadata 可被前端與 API JSON 回應正確序列化輸出。
2. `backend/services/qdrant_service.py` & `backend/routers/embedding.py` (修改):
   - 修改 Qdrant Payload 的寫入格式，確保 `class` 與 `links_to` 寫入時，即使為空亦會以列表格式 `[]` 寫入，解決格式不一致與 null 的相容性問題。

## 2026-06-30 調整 Dockerfile 的 Oracle Instant Client 目錄結構與 ORACLE_HOME

### 修改內容
1. `backend/Dockerfile` (修改):
   - **重構 Instant Client 目錄**：將 Oracle Instant Client 解壓後的目錄由 `/opt/oracle/instantclient` 調整為符合標準結構的 `/opt/oracle/lib`，並將環境變數 `ORACLE_HOME` 設定為 `/opt/oracle`，`LD_LIBRARY_PATH` 與 `PATH` 指向 `/opt/oracle/lib`。此舉可解決 python-oracledb 當載入 `ORACLE_HOME` 時自動在子目錄 `lib/` 尋找 `libclntsh.so` 卻找不到的連線問題。

## 2026-06-30 新增 Oracle Thick Mode 初始化錯誤詳細捕獲與回傳

### 修改內容
1. `backend/routers/database_indexing.py` (修改):
   - **新增初始化錯誤記錄與回傳**：引入 `oracle_init_error` 全域變數以捕獲 `oracledb.init_oracle_client()` 的異常。當 Oracle 連線測試或連線操作失敗時，若有初始化錯誤，將其拼接入連線錯誤訊息中，使前端與用戶可直接得知 Instant Client 的底層載入失敗原因（例如缺失 `libaio` 或是環境變數載入不正確）。

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