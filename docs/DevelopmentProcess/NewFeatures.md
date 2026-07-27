<!-- 新功能紀錄(最新紀錄放最前面) -->

## 2026-07-27 回報圖片描述失敗數給來源應用（captionFailedCount）

### 背景
承同日「圖片描述失敗自動重試與重新產生描述」功能。使用者詢問 KB（GigaSolarKnowledgeBase）端的
「全量校驗」與「同步排程」是否能發現圖片描述失敗，實查結論為**兩者都查不到**：

- 圖片描述失敗時 `_process_upsert()` 正常回傳，`IngestReportService` 回報的是 `status="completed"`，
  KB 端狀態為「AI 已就緒」，排程只撈 `not_synced` / `outdated` / `failed`，永遠不會回頭處理。
- KB 的 `runFullAudit()` 僅比對 `meta.version`，而 `findPointMeta()` 只 scroll 一個 point 取
  `version` / `updated_date`，不看 chunk 內容；描述失敗不影響版本號，因此永遠判定無漂移。

### 變更內容
- `backend/services/ingest_service.py`：
  - `_process_upsert()` 回傳值由 `(filename, version)` 改為 `(filename, version, caption_failed_count)`，
    數量取自 `extracted_images` 中 `caption_failed` 為 True 的張數。
  - `process()` 解包後傳給回報服務，且在 `caption_failed_count > 0` 時輸出 warning log。
- `backend/services/ingest_report_service.py`：
  - `report()` / `_report_webhook()` / `_report_direct_db()` 新增 `caption_failed_count` 參數。
  - Webhook body 新增 `captionFailedCount` 欄位。
  - `direct_db` 模式（目前僅 `app_id == "kb"`）在 `status == "completed"` 的 UPDATE 中一併寫入
    `caption_failed_count`（`None` 時寫 0）。
- `docs/08_EXTERNAL_INGEST_API_GUIDE.md`：5.3 節 Webhook 回調契約補上 `captionFailedCount`
  與說明（強調 `status` 仍為 `completed`，外部應用只靠 status 無法察覺）。

### 驗證
- `main.py` import 成功；`IngestReportService.report` / `_report_webhook` / `_report_direct_db`
  三個簽章皆確認含 `caption_failed_count` 參數。
- `delete` 路徑的回報未帶此參數（預設 `None`），行為不變。
- KB 端對應施作（資料表欄位、全量校驗查 Qdrant、管理端警示標籤）見 GigaSolarKnowledgeBase 的
  `docs/DevelopmentProcess/RAG_CAPTION_FAILED_TRACKING.md`。
- ⚠️ 部署順序：**KB 需先執行 `node src/scripts/addRagSyncCaptionFailedColumn.js` 建立欄位**，
  否則 direct_db 回報的 UPDATE 會因缺少欄位而失敗，同步狀態會卡在 `processing`。

---

## 2026-07-27 圖片描述失敗自動重試與「重新產生圖片描述」修復功能

### 背景
同日修正 `.docx` 圖片描述逾時問題後（見 [BugFix.md](BugFix.md) 2026-07-27），仍有少部分圖片會因地端 vLLM
偶發逾時或無限重複迴圈而落到 `caption_failed` 佔位邏輯，在向量庫留下
`[圖片描述產生失敗：ERP Tiptop災難實境演練.docx_img2]` 這類無檢索價值的段落。使用者需求為
「針對少部分圖片描述產生失敗，自動刪除該段落並重新產生描述」。

原本無法修復既有失敗段落的關鍵限制與可行性：
- `caption_failed` 只存在於 `ExtractedImageItem`，**沒有寫進 Qdrant payload**，只能靠內文字串辨識。
- 但**原圖有留存在磁碟**（`FILE_ATTACHMENTS_DIR/FILE_ATTACHMENTS_IMAGE_SUBDIR/<uuid>.<ext>`），
  且 `image_filename` 在 payload 中，因此可以取回原圖重新產生描述。

### 變更內容
**1. 同步時自動重試（降低失敗率）**
- `backend/services/llm_service.py`：新增 `LLMService.describe_image_with_retry()`，包裝
  `describe_image()`，每次嘗試套用 `IMAGE_CAPTION_TIMEOUT` 牆鐘上限，失敗則遞增等待後重試，
  最多 `IMAGE_CAPTION_MAX_ATTEMPTS` 次，全部失敗才拋出最後一次例外交由呼叫端處理。
  描述被 `max_tokens` 截斷（`truncated=True`）仍有可用內容，不視為失敗、不重試。
- `backend/services/ingest_service.py`：改呼叫 `describe_image_with_retry()`（取代前次修正加入的
  單層 `asyncio.wait_for`）；圖片 chunk 的 metadata 與 Qdrant payload 新增 `caption_failed` 欄位，
  供修復功能篩選。

**2. 重新產生描述的修復 API（處理既有資料）**
- 新增 `backend/services/image_caption_repair_service.py`：
  - `is_caption_failed()`：優先看 payload 的 `caption_failed`，舊資料退回比對內文
    `[圖片描述產生失敗` 前綴。
  - `_resolve_image_path()`：只取 `os.path.basename()` 組路徑，避免 payload 被竄改造成路徑穿越。
  - `_replace_main_content()`：**只替換 `[主要內容]` 之後的描述本文**，保留原本
    `[檔案名稱]` / `[段落編號]` / `[分類標籤]` 結構化前綴，確保與 ingest 寫入格式一致。
  - `repair()`：依 `point_ids` 或 `filename` 取出圖片段落，以 `IMAGE_CAPTION_CONCURRENCY`
    併發重新產生描述，成功者重新 embedding 並**以相同 point id upsert 覆蓋**
    （Qdrant upsert 同 ID 會整筆換掉 payload 與向量，等同刪除失敗段落再寫入新描述，
    因此 `chunk_count` 不需調整）；失敗者保留原段落不動並逐筆回報原因。
- `backend/services/qdrant_service.py`：
  - 新增 `get_image_points()`：依 `point_ids` 取回或依 `filename` + `chunk_type == "image"` 掃出圖片段落。
  - `upsert_chunks()` 新增選用參數 `point_ids`，未提供時行為與原本完全相同（產生新 UUID），
    提供時沿用指定 ID 以原地覆蓋。既有 4 個呼叫端皆為位置參數呼叫，不受影響。
- `backend/schemas/retrieval.py`：新增 `RegenerateImageCaptionsRequest`
  （`point_ids` / `filename` 二者擇一、`only_failed` 預設 `true` 避免誤覆蓋已成功的描述）。
- `backend/routers/retrieval.py`：新增
  `POST /api/retrieval/knowledge-bases/{knowledge_base_id}/images/regenerate-captions`，
  回傳 `repaired_count` / `failed_count` / `skipped_count` 與逐筆 `details`；有成功筆數才
  invalidate metadata cache 並更新 `kb.updated_at`。

**3. 前端操作入口**
- `frontend/src/services/retrievalService.js`：新增 `regenerateImageCaptions()`。
- `frontend/src/components/embedding/VectorManagementTab.vue`：
  - 圖片段落標題列新增 ↻ 按鈕，單筆重新產生描述（`only_failed: false`，可強制重做成功的描述），
    處理中顯示 spinner 並停用；描述失敗時按鈕呈琥珀色。
  - 描述失敗的段落在「圖片描述 (AI Generated Caption)」旁顯示「描述失敗，可按上方 ↻ 重新產生」標記。
  - 檔案工具列在該檔案存在失敗段落時顯示「重新產生失敗描述 (N)」按鈕，一次修復整個檔案
    （`only_failed: true`），完成後 alert 統計並重新載入段落。

**4. 設定項**
- `backend/config.py`、`backend/.env.example`、`backend/.env`：新增
  `IMAGE_CAPTION_MAX_ATTEMPTS`（預設 3）、`IMAGE_CAPTION_RETRY_DELAY`（預設 5 秒）；
  `INGEST_JOB_TIMEOUT` 預設由 3600 調整為 7200 秒（含重試後最壞情況約
  `ceil(19 / 3) × 3 × 180 = 3780` 秒，需留足餘裕）。

### 驗證
- `main.py` import 成功，OpenAPI 已註冊
  `/api/retrieval/knowledge-bases/{knowledge_base_id}/images/regenerate-captions`。
- `upsert_chunks` 簽章確認為
  `(collection_name, chunks, vectors, batch_size=20, point_ids=None)`，既有呼叫端不受影響。
- `ImageCaptionRepairService` 純函式實測：
  - `_replace_main_content()` 正確保留 `[檔案名稱]` / `[段落編號]` / `[分類標籤]` 前綴，只換描述本文；
    無結構化前綴時回退為直接使用新描述。
  - `is_caption_failed()` 對「僅內文有失敗前綴的舊資料」、「payload `caption_failed=true`」皆為 True，
    正常描述為 False。
  - `_build_context_hint()` 依序取 `section` → `第 N 頁` → 空字串。
  - `_resolve_image_path('../../etc/passwd')` 被 `basename` 收斂後拋 `FileNotFoundError`，路徑穿越無效。
- `npm run build` 通過（僅既有的 chunk > 500 kB 警告）。
- 依專案慣例未自行開啟瀏覽器驗證，實際 UI 操作與地端 vLLM 重試行為待使用者手動測試。

### 已知限制
- Word 圖片的標題階層（`header_path`）在 ingest 時已被雜湊為 `parent_id`，無法還原，
  修復時的 `context_hint` 只能退回 `section` 或頁碼，因此重新產生的描述上下文提示會比首次同步時薄。
- 修復 API 為同步呼叫，整個檔案的圖片較多時 HTTP 請求會持續數分鐘（前端有 spinner 但無進度回報）；
  若日後需求擴大可改走 arq 背景任務。
- 若原圖檔案已被 `_cleanup_orphaned_image_files` 清掉或人為刪除，該段落無法修復，
  會回報 `FileNotFoundError` 並保留原失敗段落。

---

## 2026-07-23 新增多應用 RAG 向量同步系統測試計畫 (MultiAppRAGSyncTestPlan.md)

### 背景
針對已建置完成的多應用 RAG 向量同步與附件 API 整合架構（[MULTI_APP_RAG_SYNC_PLAN.md](MULTI_APP_RAG_SYNC_PLAN.md) / [08_EXTERNAL_INGEST_API_GUIDE.md](../08_EXTERNAL_INGEST_API_GUIDE.md)），於 `docs/DevelopmentProcess/` 新增完整的測試計畫文件，供開發團隊與 QA 進行驗證。

### 變更內容
- **新增文件 `docs/DevelopmentProcess/MultiAppRAGSyncTestPlan.md`**：
  - 測試目標與範疇：涵蓋 API Key 驗證、`arq worker` 背景佇列、`AppRegistration` 樣板、`AppContentClient` 拉取、Qdrant 向量點位寫入/清掃、混合進度回報與雙權限過濾。
  - 測試環境與前置條件配置說明。
  - 詳細測試案例（TC-API、TC-PULL、TC-VEC、TC-RPT、TC-PERM 五大階段 13 個測試案例）。
  - 自動化與 cURL 指令驗證步驟與驗收標準。

### 驗證
- 檢查文件 Markdown 語法與內部文件連結引用正確性。

---


### 背景
配合多應用 RAG 向量同步與附件 API 整合規範（[MULTI_APP_RAG_SYNC_PLAN.md](MULTI_APP_RAG_SYNC_PLAN.md)），在 `docs/` 目錄下建立針對外部應用系統開發者的獨立串接指南文件，提供 `POST /api/external/ingest/trigger` 端點的完整規範與介面說明。

### 變更內容
- **新增文件 `docs/08_EXTERNAL_INGEST_API_GUIDE.md`**：
  - 核心機制：說明非同步 Pull 模式（Trigger 傳送 Metadata 立即回傳 ACK 202，背景佇列主動向外部 App 拉取全文/二進位附件並執行向量化，完成後 Webhook 回調）。
  - Base URL 與認證：明確配置規範（`AIRAG_BASE_URL` 勿加 `/api`）與 Ingest 專屬 `X-API-Key` 驗證。
  - 前置 App 登錄規範 (`AppRegistration`)。
  - API 契約 (Request Header, camelCase Body, `permissions` 結構, Response 202 與 `taskId`)。
  - 外部應用需配合開放之端點契約（文章拉取 API、附件拉取 API、Webhook Callback 端點）。
  - 常見問題（Target Version 防競態覆蓋、刪除 Action 處理方式）。

### 驗證
- 檢查 Markdown 連結與標題層級正確性，完成文件落地。

---


### 背景
依規劃文件 [MULTI_APP_RAG_SYNC_PLAN.md](MULTI_APP_RAG_SYNC_PLAN.md)（v1.2）第 6 節「後續執行步驟」第 2 項施作：AiRAG 引擎擴充，讓多個外部應用（KB、BPM、Meeting 等）能透過標準化 API 觸發 AiRAG 對文件進行切分、embedding 並寫入 Qdrant，取代原本僅支援單一 KB 系統的假設。本次施作範圍為 AiRAG 側（步驟 2），各應用自己的接入（步驟 3）與 App Registry／ingest 金鑰的前端管理介面不在本次範圍（已與使用者確認：先做後端 CRUD，UI 之後再補）。

### 變更內容
- **背景佇列（新引入 arq + Redis）**：
  - `docker-compose.yml` 新增 `redis` 服務與 `worker` 服務（沿用 `backend` 的 build context，`command: arq worker.WorkerSettings`）；`backend` 服務新增 `REDIS_HOST=redis` 環境變數。
  - `backend/requirements.txt` 新增 `arq>=0.26.0`；`backend/config.py` 新增 `REDIS_HOST`/`REDIS_PORT`。
  - `backend/services/arq_pool.py`（新檔）：`ArqPool.get_pool()` lazy singleton，供 API 行程端推入任務。
  - `backend/worker.py`（新檔）：arq `WorkerSettings`，`process_ingest_task` 委派給 `IngestService.process()`；`on_startup` 呼叫既有 `init_mongodb()` 初始化 worker 行程自己的 MongoDB/Beanie 連線。
- **App Registry（`app_registrations` collection，見規劃文件 2.4 節）**：
  - `backend/models/app_registration.py`（新檔）：`AppRegistration` Document（`app_id` 唯一索引、`base_url`、內容/附件路徑樣板、`report_mode`）。
  - `backend/routers/app_registrations.py`（新檔）：JWT 保護的 CRUD，掛載於 `/api/app-registrations`；`report_mode="direct_db"` 僅開放 `app_id="kb"`（程式邏輯白名單）。
- **Ingest 觸發端點與處理管線**：
  - `backend/schemas/ingest.py`（新檔）：`IngestTriggerRequest`/`IngestPermissions`，以 Pydantic alias 對應規劃文件 2.1 節的 camelCase 傳輸契約。
  - `backend/routers/external.py`：新增 `POST /ingest/trigger`（最終路徑 `/api/external/ingest/trigger`），驗證 App Registry 登錄狀態、webhook 模式必須帶 `callbackUrl`、`knowledgeBaseId` 需存在，通過後推入 arq 佇列並立即回傳 `202`。
  - `backend/services/app_content_client.py`（新檔）：依 App Registry 登錄的路徑樣板呼叫各應用的內容/附件端點（`X-RAG-Sync-Key` 標頭）。
  - `backend/services/ingest_service.py`（新檔）：核心處理邏輯——拉取內容（`doc_type=="attachment_file"` 走附件二進位端點，其餘走文字端點）、重用既有 `ChunkingService`/`EmbeddingService` 切分與 embedding、呼叫 `QdrantService` 清舊 chunk 後 upsert、更新 `KnowledgeBase.chunk_count`。
  - `backend/services/ingest_report_service.py`（新檔）：混合回報機制，依 `report_mode` 分派至 `_report_webhook`（POST 回呼 `callbackUrl`）或 `_report_direct_db`（pyodbc 直連目標 App DB，SQL 對應 `RAG_SYNC_PLAN.md` 6 節第 5 點，含 `target_version` 防競態條件）。
- **`QdrantService`（`backend/services/qdrant_service.py`）**：新增 `delete_by_app_source(collection_name, app_id, doc_type, source_id)`（比照既有 `delete_by_filename` 的 scroll+delete 模式）；`search_similar`／`search_similar_two_step`／`get_by_parent_id` 的 payload 讀回投影補上 `app_id`/`doc_type`/`source_id`/`version`/`updated_date`/`is_public`/`access_dept`/`access_level`/`access_members`/`total_chunks`。
- **API Key 用途分離（規劃文件 5.2 節第 8 點）**：`ExternalApiKey` 新增 `scope`（`chat`/`ingest`，預設 `chat`，既有金鑰自動相容）；`utils/security.py` 拆分為 `verify_external_api_key`（`scope=chat`）與新增的 `verify_ingest_api_key`（`scope=ingest`），確保問答與寫入金鑰互不相通；`external_api_keys.py` 建立/查詢回應同步補上 `scope` 欄位。
- **`PermissionService` 雙欄位支援（規劃文件 5.1 節第 6 點）**：`UserProfile` 新增 `employee_id`（`get_user_from_external_info` 一併帶入），供 `access_members` 個人白名單比對；`filter_results()` 新增與舊式 `is_confidential` 互斥的新分支——`is_public` 為 true 直接放行，否則套用「(部門符合 AND 等級足夠) OR 工號在 `access_members` 名單內」的覆蓋式規則。

### 驗證
- 後端：`ast.parse` 全數新增/修改檔案語法檢查通過；以 venv Python 實際 `import main` 確認所有路由正確註冊（`/api/external/ingest/trigger`、`/api/app-registrations` 及其子路徑皆出現在 OpenAPI schema 中）。
- 啟動本機 `mongodb`+`redis` 容器，直接呼叫 `trigger_ingest()` 驗證五種分支：未登錄 App、webhook 缺 `callbackUrl`、`knowledgeBaseId` 格式錯誤、`knowledgeBaseId` 不存在皆正確回傳 `400`；成功案例正確推入 arq 佇列並回傳 `taskId`。
- 實際啟動 `arq worker.WorkerSettings`：worker 成功消費佇列中的任務，`AppRegistration` 查無登錄時正確記錄錯誤並提前中止（未崩潰），確認 Qdrant 未連線時 `init_mongodb()` 的索引檢查僅記錄警告、不影響 worker 啟動。
- 尚待驗證（需要真實外部應用或 KB 端實際部署，非本次可測範圍）：對真實 App 內容端點的實際拉取與切分、`direct_db` 模式對真實 KB SQL Server 的寫入、webhook 模式對真實回呼端點的送達。

## 2026-07-22 後端支援 Qdrant API Key 安全認證與多應用連線配置

### 背景
為支援外部不同應用程式（如微服務、批次腳本等）直接連線至 Qdrant 向量資料庫進行資料寫入與查詢，同時強化系統資料庫之存取安全性，於 Docker 環境與後端服務中引入了 Qdrant API Key 認證機制。

### 變更內容
- **環境設定 (`docker-compose.yml` & `backend/.env`)**：
  - `docker-compose.yml` 中的 `qdrant` 服務新增環境變數 `QDRANT__SERVICE__API_KEY`，開啟 Qdrant 服務端 API Key 防護。
  - `docker-compose.yml` 中的 `backend` 服務與 `backend/.env` 新增 `QDRANT_API_KEY` 環境變數傳遞。
- **後端架構 (`backend/config.py` & `backend/services/qdrant_service.py`)**：
  - `backend/config.py` 中的 `Settings` 新增 `QDRANT_API_KEY: Optional[str]` 設定項。
  - `backend/services/qdrant_service.py` 於 `AsyncQdrantClient` 連線初始化時帶入 `api_key=settings.QDRANT_API_KEY` 與 `https=False` 參數，保證後端能帶著憑證並經由 HTTP 協議穩定連線至 Qdrant。

### 驗證
- 驗證 Qdrant API Key 安全機制：未帶 Key 存取 REST API 均回傳 `401 Unauthorized`；攜帶 Header `api-key` 後可正常存取。
- `airag-backend` 容器重新編譯並啟動後，與 Qdrant 之間建立 Collection、點位寫入與向量檢索操作皆保持正常連線。

---

## 2026-07-17 外部 API 真實使用者身分、問答稽核紀錄、API Key 驗證機制實作完成

### 背景
延續同日稍早的「外部 API 測試頁面」規劃，依 [NewFeaturesPlan_ExternalApiTestPlan.md](NewFeaturesPlan_ExternalApiTestPlan.md) 第 8～12 節實作。核心變更：外部應用改以真實員工身分（`external_user`）取代內部測試專用的 `simulated_user_id`；每次呼叫留存問答稽核紀錄；`/api/external/chat` 新增 API Key 驗證，修正先前「暫不驗證」的決策。

### 變更內容
- **後端**：
  - `Department` 新增 `code` 欄位；`UserProfile` 新增 `department_code`（建立時從所屬部門連動帶出）；`PermissionService.filter_results()` 部門比對改為代號／名稱雙軌相容（過渡期不需遷移既有 Qdrant 資料）。
  - `ChatParams` 新增 `external_user`（`ExternalUserInfo`：工號/姓名/部門代號/部門名稱/級職名稱/級職等級），`rag_chat_stream()` 優先採用它解析權限身分；`PermissionService.get_user_from_external_info()` 將其轉換為與模擬使用者相同形狀的物件，不落地寫入 `users` collection。
  - 新增 `ExternalApiKey`（`external_api_keys`，prefix+bcrypt hash 儲存）與 `external_api_keys.py` 管理路由（JWT 保護）；`utils/security.py` 新增 `generate_external_api_key()`／`verify_external_api_key()`（`X-API-Key` 標頭驗證，與 JWT 各自獨立）。
  - `POST /api/external/chat` 掛上金鑰驗證、要求 `params.external_user` 必填；新增 `ExternalChatLog`（`external_chat_logs`）稽核模型，`external.py` 以 `try...finally` 包一層 `_external_chat_with_logging()`，確保正常結束與中途斷線都會落地寫入（旁路 best-effort，不影響對話流程）。
- **前端**：
  - `RoleSettingsView.vue` 部門表單新增代號欄位，新增「外部 API 金鑰管理」區塊（建立/刪除，明碼只顯示一次）。
  - `VectorManagementTab.vue` 機密權限控管改用部門代號送出與比對。
  - 外部 API 測試頁新增 `ExternalUserInfoPanel.vue`（API Key + 6 個使用者身分欄位），`externalChatStore.js` 送出 `external_user` 並帶 `X-API-Key` 標頭（不再送 `simulated_user_id`），`ApiJsonPreviewPanel.vue` 欄位說明與 Header 說明同步更新。
- **文件**：更新 `docs/03_API_CONTRACT.md`（§3.4、§17、新增 §19）與 `docs/04_DB_SCHEMA.md`（§3.15-3.18、§4.2），記錄於 `BackendCorrection.md`／`FrontendCorrection.md`。

### 驗證
- 後端：`py_compile` 全數通過；以 venv Python 實際 import 所有新增/修改模組，驗證 `ChatParams.external_user`、路由註冊、`get_user_from_external_info()` 轉換邏輯、`generate_external_api_key()` 產生的金鑰可正確雜湊與驗證。
- 前端：`npm run build` 通過，無編譯錯誤。
- 尚待使用者手動驗證：金鑰管理介面實際操作、外部頁面送出含 `external_user` 的請求、以及中途斷線情境下 `ExternalChatLog` 是否確實落地（依專案慣例不由 AI 開瀏覽器驗證）。

## 2026-07-17 外部 API 測試頁面 (External API Test) 實作完成

### 背景
依規劃文件 [NewFeaturesPlan_ExternalApiTestPlan.md](NewFeaturesPlan_ExternalApiTestPlan.md) 實作。提供獨立於內部測試 API 的外部端點 `POST /api/external/chat`，供公司內網外部應用未來串接使用；並新增前端「外部 API 測試」頁，讓使用者用與「RAG 功能測試」相同的檢索/生成參數表單組出 Request JSON、即時預覽並附上逐欄位說明，同時可額外自訂「總結提示詞」，送出後在同一頁面對話視窗查看完整 SSE 處理過程。

### 變更內容
- **後端 (`backend/routers/`)**：
  - `external.py`（新檔）：新增 `POST /api/external/chat`，未掛 `Depends(get_current_user)`，直接重用 `rag.py` 既有的 `ChatRequest` schema 與 `rag_chat_stream()` 管線，避免複製一份檢索/摘要/串流邏輯。
  - `rag.py`：`ChatParams` 新增 `custom_system_prompt` 選填欄位；`rag_chat_stream()` 三處 System Prompt 組裝分支（`semantic_db_query`／一般參考資料／無資料）皆支援以此欄位覆蓋預設指示規則文字，檢索到的參考資料仍由後端自動接續在後方；未帶知識庫且有帶此欄位時不再強制接上「知識庫沒有相關資訊」警語，可用於純 Prompt／LLM 行為測試。
  - `main.py`：註冊 `external.router`。
- **前端 (`frontend/src/`)**：
  - `composables/useChatStream.js`（新檔）：從 `chatStore.js` 抽出共用的 fetch + SSE 事件解析邏輯，供內部與外部兩個對話 store 共用。
  - `stores/externalChatStore.js`（新檔）：獨立於 `chatStore.js` 的對話狀態，呼叫 `/api/external/chat`（不帶 `Authorization` 標頭），並匯出 `buildExternalChatPayload()` 供 JSON 預覽元件共用同一份 payload 組裝邏輯。
  - `stores/chatStore.js`：改呼叫抽出後的 `useChatStream.js`（純重構，行為不變）。
  - `stores/paramsStore.js`：新增 `customSystemPrompt` 欄位。
  - `components/chat/ChatWindow.vue`：新增可選 `store` prop，未傳入時預設沿用 `useChatStore()`，供外部頁面注入 `externalChatStore`。
  - `components/params/CustomSystemPromptPanel.vue`（新檔）：自訂總結提示詞輸入框。
  - `components/params/ApiJsonPreviewPanel.vue`（新檔）：即時組出 Request JSON、逐欄位白話說明與複製按鈕。
  - `views/ExternalApiTestView.vue`（新檔）：組裝對話視窗與四個參數面板。
  - `router/index.js` / `components/common/AppSidebar.vue`：新增 `/external-api-test` 路由與導覽選單項目。
- **文件與紀錄**：
  - 更新 `docs/03_API_CONTRACT.md`（§1 認證方式說明、§3.4 新增端點條目）。
  - 記錄於 `BackendCorrection.md` 與 `FrontendCorrection.md`。

### 驗證
- 後端：`py_compile` 通過；以 venv Python 實際 import `routers.external`／`routers.rag` 確認 `custom_system_prompt` 欄位存在且 `POST /external/chat` 路由正確註冊。
- 前端：`npm run build` 通過，無編譯錯誤。
- 尚待使用者於瀏覽器手動驗證實際對話流程與 JSON 預覽畫面（依專案慣例不由 AI 開瀏覽器驗證）。

## 2026-07-16 文件機密權限控管 (Confidential Document Access Control) 實作完成

### 背景
依規劃文件 [NewFeaturesPlan_ConfidentialAccessControlPlan.md](NewFeaturesPlan_ConfidentialAccessControlPlan.md) 實作。本功能提供企業級文件存取權限控管，以數值等級 (Level 1~10，越小越機密) 與部門限制為雙重基準。透過「模擬使用者名冊」供內部測試評估過濾隔離效果，保證未授權片段與隱私中繼資料決不餵給 LLM 總結。

### 變更內容
- **後端 (`backend/models/` / `services/` / `routers/` / `schemas/`)**：
  - `Department` 與 `UserProfile` Beanie Documents（註冊至 `init_beanie`）。
  - `PermissionService`：實作核心權限過濾邏輯（比對 `user.level <= file.confidential_level` 與 `user.department in file.confidential_departments`），以及隱私防禦型排除摘要產生器。
  - `QdrantService`：`get_unique_metadata` 擴充權限中繼資料解析，新增 `update_permissions_by_filename` 批次點位更新。
  - `retrieval.py` / `rag.py`：檢索與 RAG 管道整合權限過濾（包含雙階段檢索前置防漏過濾），新增 POST `/files/update-permissions` 與 `/api/users/*` 管理 API。
- **前端 (`frontend/src/`)**：
  - `userService.js`：部門與使用者名冊 API 客戶端。
  - `paramsStore.js` / `RagParamsPanel.vue` / `RetrievalTestView.vue`：加入「模擬使用者權限測試」開關與身分選單。
  - `RoleSettingsView.vue`（新頁面）：部門與模擬使用者名冊管理介面。
  - `AppSidebar.vue`：加入「角色與權限設定」導覽項目。
  - `VectorManagementTab.vue`：全檔「機密權限控管設定」卡片與 🔒 點位徽章。
- **文件與紀錄**：
  - 更新 `docs/03_API_CONTRACT.md`（§3.1, §4.1, §4.8, §17）與 `docs/04_DB_SCHEMA.md`（§3.15, §3.16, §4.2）。
  - 記錄於 `BackendCorrection.md` 與 `FrontendCorrection.md`。

### 驗證
- 後端 Python AST/py_compile 檢查通過。
- 前端 Build 檢查通過。

## 2026-07-13 AI 總結相似度門檻與拒絕生成機制實作完成

### 背景
依規劃文件 [NewFeaturesPlan_SimilaritySummaryThresholdPlan.md](NewFeaturesPlan_SimilaritySummaryThresholdPlan.md)（A 方案）實作。於前端「檢索設定」新增可自訂之「AI 總結相似度門檻 (AI SUMMARY THRESHOLD)」。當檢索片段相似度低於此分數時自動排除於 LLM 脈絡外；當全數片段皆低於門檻時，觸發 Early Exit 硬防護跳過 LLM 總結，節省 100% vLLM 推論算力與 Token，並防範幻覺。

### 變更內容
- **後端 (`backend/routers/rag.py` / `backend/schemas/retrieval.py`)**：
  - `ChatParams` 與 `SearchParams` 新增 `ai_summary_score_threshold` 欄位（預設 `0.60`）。
  - 在 `raw_results` 遍歷時，比對 `semantic_score >= ai_summary_score_threshold`，僅達標片段進入 `context_parts`。
  - 當無任何片段達標時，觸發 Early Exit，由 SSE 直接回傳友善警示文字與 `sources`，無須呼叫 LLM 推論。
  - 每筆 `sources` 回傳 `semantic_score` 與 `metadata.included_in_ai_context` 狀態。
- **前端 (`frontend/src/stores/paramsStore.js` / `RagParamsPanel.vue` / `chatStore.js` / `SourceChunks.vue`)**：
  - `paramsStore.js` 新增 `aiSummaryScoreThreshold` (預設 0.60) 與 `aiSummaryScoreThresholdEnabled` (預設 true)。
  - `RagParamsPanel.vue` 在「相似度閾值 (Score Threshold)」下方加入專屬 Slider 與開關 Checkbox。
  - `chatStore.js` 發送請求時自動帶入 `ai_summary_score_threshold` 參數。
  - `SourceChunks.vue` 為達標與未達標片段標示「已採納」與「未採納」視覺徽章。
- **文件與紀錄**：
  - 更新 `docs/03_API_CONTRACT.md`。
  - 記錄於 `BackendCorrection.md` 與 `FrontendCorrection.md`。

### 驗證
- 後端 Python 檔 `py_compile` 檢查通過。
- 前端 `npm run build` 通過（產生最新生產部署 dist 包）。

## 2026-07-13 專用 Cross-Encoder Rerank 規劃取消

### 背景
依使用者確認，原定規劃 [NewFeaturesPlan_CrossEncoderRerankPlan.md](NewFeaturesPlan_CrossEncoderRerankPlan.md)（引進本地 fastembed `TextCrossEncoder` 進行 Rerank）經實作測試與評估後效果未達預期，取消此規劃項目，維持現行 `RerankService`（LLM listwise 排序）運作機制。

## 2026-07-09 檢索命中分析儀表板（Retrieval Stats Dashboard）實作完成

### 背景
依規劃文件 [NewFeaturesPlan_RetrievalStatsDashboardPlan.md](NewFeaturesPlan_RetrievalStatsDashboardPlan.md) 實作，新增獨立的檢索命中統計，讓使用者能主動發現「哪些問題常檢索不到／分數偏低」，而非被動等待使用者透過 `feedback.py` 回報問題。前置阻塞事項（RRF 分數與 `score_threshold` 尺度不匹配，見 [`NewFeaturesPlan_RRFScoreThresholdMismatchPlan.md`](NewFeaturesPlan_RRFScoreThresholdMismatchPlan.md)）已於同日先行修正並實測驗證。

### 變更內容
- `backend/models/retrieval_stats.py`（新檔）：新增 `RetrievalStats` beanie Document，獨立於既有 `ChatMessage.source_chunks`；已註冊進 `backend/models/mongodb.py` 的 `document_models`。
- `backend/config.py`：新增 `DASHBOARD_STATS_DEFAULT_PERIOD_DAYS`（預設 7）、`RETRIEVAL_STATS_ENABLED`（預設 `True`，總開關）。
- `backend/services/retrieval_stats_service.py`（新檔）：`RetrievalStatsService.record()` 讀取 `raw_results` 每筆候選的 `semantic_score`（而非原始 RRF `score`）計算 `hit_count`/`avg_score`/`min_score`/`max_score`，best-effort 寫入，失敗只記錄 warning。
- `backend/routers/rag.py`：`rag_chat_stream()` 於 `vector`/`hybrid`/`semantic_hybrid*` 檢索完成、`context_parts`/`sources` 組裝完畢後，新增 try/except 包裹的旁路呼叫 `RetrievalStatsService.record()`；`semantic_db_query` 查詢法不記錄。
- `backend/routers/dashboard.py`（新檔，掛載於 `/api/dashboard`）：`GET /retrieval-stats/summary`（`$facet` 聚合近 N 天總檢索次數/零命中數/平均分數/依知識庫分組）、`GET /retrieval-stats/zero-hit-questions`（分頁）。兩端點皆用記憶體 `{str(kb.id): kb.name}` 對照表解析 `knowledge_base_name`，不使用 `$lookup`；已刪除的知識庫回傳 `"(已刪除)"`。實作時發現本專案固定的 beanie 2.1.0／motor 3.7.1／pymongo 4.17.0 版本組合下，`Document.aggregate().to_list()` wrapper 會對 cursor 多 await 一次拋出 `TypeError`（與 `models/mongodb.py` 既有的 `append_metadata` 相容性補丁屬同一類問題），改為直接呼叫 `get_pymongo_collection().aggregate(pipeline)` 繞開。
- `backend/main.py`：掛載新的 `dashboard` router。
- `frontend/src/views/DashboardView.vue`：`stats` 陣列新增「近7日無命中問題比例」「近7日平均檢索分數」兩張卡片；新增零命中問題清單下鑽 Modal（表格呈現問題內容/所屬知識庫/查詢法/發生時間，支援分頁）；`zero_hit_rate` 卡片依規劃文件補上 `cursor-pointer`／hover 視覺提示，其餘卡片維持原樣。
- `docs/03_API_CONTRACT.md`：新增第 16 節，記錄兩個新端點。
- `docs/04_DB_SCHEMA.md`：新增第 3.14 節 `retrieval_stats` collection schema，collection 總數 14→15。

### 驗證
- 後端：`python -m ast` 語法檢查通過；於 `airag-backend` 容器內（fastembed/beanie 皆正常載入）對真實 MongoDB 執行端到端測試，涵蓋 `RetrievalStatsService.record()` 的一般命中/零命中/零候選三種情境（`hit_count`/`avg_score` 皆正確，空候選時 `avg_score=None`）、`dashboard.py` 兩個端點函式直接呼叫（`summary` 的 `$facet` 聚合、`knowledge_base_name` 解析含「已刪除」情境、`zero-hit-questions` 分頁與零命中判斷），並確認 MongoDB `$avg` 原生正確忽略 `None` 值（(0.633+0.075)/2 = 0.354，與已刪除知識庫記錄的 `avg_score=None` 未被計入一致）。測試記錄使用後皆已清除，未留下測試資料。透過 `main.app.openapi()` 確認兩個新端點已正確掛載於 `/api/dashboard/retrieval-stats/*`。
- 前端：`npm run build` 通過，無編譯錯誤。
- 未自行開瀏覽器做人工功能測試（依 CLAUDE.md 慣例，使用者手動驗證）；`airag-backend` 容器執行中的 API 進程仍是修改前載入的舊模組，需重啟容器後才會實際套用本次所有後端變更（含前一項 RRF 修正）。

## 2026-07-08 多輪對話指代消解（Conversational Reference Resolution）實作完成

### 背景
依規劃文件 [NewFeaturesPlan_ConversationalReferenceResolutionPlan.md](NewFeaturesPlan_ConversationalReferenceResolutionPlan.md) 實作，解決 `search_type` 為 `semantic_hybrid`／`semantic_hybrid_feedback`／`semantic_hybrid_attachment` 時，`EmbeddingService.query_to_semantic_json()` 語義 JSON 解析階段看不到對話歷史，導致使用者追問「那份文件的第二點是什麼」這類指代問題時容易撈錯內容的問題。

### 變更內容
- `backend/config.py`：新增 `SEMANTIC_JSON_HISTORY_TURNS`（預設 3），作為前端未指定歷史則數時的後端預設值。
- `backend/services/embedding_service.py`：`query_to_semantic_json()` 新增可選參數 `chat_history`、`pinned_filename`（皆預設 `None`，向後相容），並在系統提示中加法式插入【使用者已手動鎖定檔案】與【近期對話歷史】／【指代消解規則】兩個獨立區塊；既有 JSON Schema、Few-Shot Examples、fallback JSON、重試溫度序列皆未修改。
- `backend/routers/rag.py`：
  - 新增 `_build_history_window()` helper，依 `history_context_turns` 截取最近 N 則 `chat_history`（只保留 `role in ("user", "assistant")`）。
  - `ChatParams` 新增 `history_context_turns`／`pinned_filename` 欄位。
  - `filter_filename` 優先權調整為「使用者手動鎖定（`pinned_filename`） > AI 自動判斷（`metadata.source_file`） > 不篩選」。
  - `semantic_analysis` 步驟 SSE 事件（`running` 與 `success` 兩次皆會覆蓋前一次內容，因此兩處都要加）新增「帶入歷史訊息數」與「手動鎖定檔案」兩行事後透明度資訊。
  - 呼叫點僅 `search_type in ("semantic_hybrid", "semantic_hybrid_feedback", "semantic_hybrid_attachment")` 分支一處，`vector`／`hybrid`／`semantic_db_query` 三種查詢法完全不受影響。
- `frontend/src/stores/paramsStore.js`：新增 `autoContextEnabled`（預設 `true`）、`historyTurnCount`（預設 `null`）、`pinnedFilename`（預設 `null`）。
- `frontend/src/components/params/RagParamsPanel.vue`：於語義混合家族查詢法（`semantic_hybrid`／`semantic_hybrid_feedback`／`semantic_hybrid_attachment`）選定時，新增「自動指代消解」勾選框 + 歷史則數輸入框 + 「手動鎖定檔案」下拉選單；下拉選單選項重用既有 `GET /api/knowledge-bases/{id}/metadata`，並在知識庫切換時比對重置不存在新清單中的殘留鎖定檔名。
- `frontend/src/stores/chatStore.js`：payload 新增 `history_context_turns`（勾選框關閉時強制送 `0`，並將清空的輸入框正規化為 `null` 避免後端 422）、`pinned_filename`。
- `docs/03_API_CONTRACT.md`：`ChatParams` 補上 `history_context_turns`／`pinned_filename` 欄位說明，`semantic_analysis` 步驟說明補上透明度資訊格式。

### 驗證
後端 `python -m py_compile` 通過；前端 `npm run build` 通過。人工功能測試（追問指代消解、手動鎖定檔案、關閉自動指代消解、切換知識庫重置鎖定檔案）留待使用者手動驗證，未自行開瀏覽器測試。

## 2026-07-08 查詢法／功能優化建議清單（尚未實作，待使用者確認）

### 背景
使用者詢問 AiRAG 還可以增加什麼查詢法或功能，盤點現有已實作查詢法（`vector`／`hybrid`／`semantic_hybrid`／`semantic_hybrid_feedback`／`semantic_hybrid_attachment`／`semantic_db_query`）與 `docs/DevelopmentProcess/NewFeaturesPlan_SemanticSearchOptimizationPlan.md` 尚未執行的優化項後，提出以下新建議，先記錄成待辦，尚未開始實作。

### 待辦優先：既有規劃文件中尚未執行的項目
`NewFeaturesPlan_SemanticSearchOptimizationPlan.md` 內第 1、2、4、5、6 項（`get_unique_metadata` 快取、2nd-hop 鄰居搜尋門檻放寬、語義 JSON 轉換失敗可觀測性、中文關鍵字正則支援、Instruct AI JSON 語法失敗修正）皆仍為「規劃中」狀態，已完成分析與優先級排序，建議優先執行。該文件第 3 項「融合後加入 Rerank 層」實際上已於 [rag.py:395](../../backend/routers/rag.py) 透過 `RerankService`（LLM listwise 重排序）實作完成，文件狀態尚未同步更新，之後修訂該規劃文件時應一併更正。

### 新建議查詢法
1. **多輪對話指代消解**：目前 `EmbeddingService.query_to_semantic_json()`（呼叫處見 [rag.py:307](../../backend/routers/rag.py)）只傳入當次 `question`，不帶 `chat_history`，使用者追問「那份文件的第二點是什麼」這類依賴上文的問題，語義 JSON 解析容易失焦。建議把最近幾輪對話歷史一併帶入 Instruct AI 的 Prompt 做指代消解後，再產生 `embeddings_input`／`sparse_keywords`。詳細規劃見 [NewFeaturesPlan_ConversationalReferenceResolutionPlan.md](NewFeaturesPlan_ConversationalReferenceResolutionPlan.md)。
2. **Tag／類別篩選式檢索（Faceted Search）**：讓使用者在前端 UI 手動勾選標籤／類別，作為 Qdrant filter 條件縮小語義檢索範圍，對大型知識庫的精準度有幫助，但需要新增前端篩選器 UI 與對應的後端 filter 參數。詳細規劃見 [NewFeaturesPlan_FacetedFilterSearchPlan.md](NewFeaturesPlan_FacetedFilterSearchPlan.md)。
3. **查詢法自動路由**：現行需使用者手動於 UI 選擇 6 種查詢法之一，可加一層「先讓 AI 判斷該題適合用哪種查詢法」的路由層，減少手動操作，但會多一次 LLM 呼叫延遲，且有路由誤判風險。詳細規劃見 [NewFeaturesPlan_QueryTypeAutoRoutingPlan.md](NewFeaturesPlan_QueryTypeAutoRoutingPlan.md)。

### 新建議功能
4. **專用 Cross-Encoder Rerank 模型（已取消）**：原規劃引進本地 fastembed `TextCrossEncoder`。經實作評估後發現效果未達預期，已確認取消此項目。詳細規劃見 [NewFeaturesPlan_CrossEncoderRerankPlan.md](NewFeaturesPlan_CrossEncoderRerankPlan.md)。
5. **檢索命中分析儀表板**：統計哪些問題常檢索不到／分數偏低，結合既有 `backend/routers/feedback.py` 回饋機制，主動發現知識庫內容缺口，而非被動等待使用者回報。已與使用者確認技術方向為新增獨立的 MongoDB `RetrievalStats` collection（不重用 `ChatMessage.source_chunks`）。詳細規劃見 [NewFeaturesPlan_RetrievalStatsDashboardPlan.md](NewFeaturesPlan_RetrievalStatsDashboardPlan.md)。


---

## 2026-07-16 手動建立與選擇 Qdrant 知識庫 (Knowledge Base / Collections) 功能實作

### 功能說明
完成「手動建立與選擇 Qdrant 知識庫 (Knowledge Base / Collections)」功能的完整前後端實作，詳見 [`NewFeaturesPlan_ManualKnowledgeBaseCollectionsPlan.md`](NewFeaturesPlan_ManualKnowledgeBaseCollectionsPlan.md)。

### 主要變更
1. **後端**：
   - `backend/routers/evaluation.py`：移除 `["tech_specs", "hr_docs"]` 舊相容分支，簡化知識庫解析邏輯為直接依 `PydanticObjectId` 尋找 `KnowledgeBase` 模型（無效或查無時 fallback 第一個知識庫）。
   - `backend/routers/feedback.py`：`FeedbackItem` 補上 `knowledge_base_id` 與 `knowledge_base_name` 欄位；`create_feedback` 單筆查詢知識庫名稱；`list_feedbacks` 批次查詢並過濾無效 `ObjectId` 字串，避免 N+1 與髒資料崩潰。
2. **前端**：
   - `frontend/src/stores/paramsStore.js`：將 `knowledgeBaseId` 預設值由舊字串 `'hr_docs'` 修正為 `null`。
   - `frontend/src/components/common/KnowledgeBaseSelector.vue`：將無可用知識庫時的預設選項 `value` 由 `'hr_docs'` 修正為 `''`。
   - `frontend/src/components/eval/TestSetManager.vue` 與 `frontend/src/views/EvaluationView.vue`：引入 `KnowledgeBaseSelector`，並將評估請求 payload 的 `knowledge_base_id` 綁定至 `paramsStore.knowledgeBaseId`。
   - `frontend/src/views/FeedbackView.vue`：歷史回饋表格新增「知識庫」欄位，顯示 `item.knowledge_base_name || '未指定'`。
   - 新增 `frontend/src/services/knowledgeBaseService.js`：封裝 `list()`、`create()`、`remove()` 三支知識庫管理 API。
   - 新增 `frontend/src/views/KnowledgeBaseSettingsView.vue`：提供建立知識庫表單、知識庫清單與已向量化段落數統計、刪除確認彈窗（包含輸入檔名二次確認警示），並於刪除當前選用知識庫時自動重置全域 `paramsStore.knowledgeBaseId`。
   - `frontend/src/router/index.js` & `frontend/src/components/common/AppSidebar.vue`：註冊 `/knowledge-base-settings` 路由，並於側邊選單加入「知識庫管理 (Knowledge Base)」與 Database 意象 SVG 圖示。

---

## 2026-07-24 新增集團知識庫專用語義混合查詢法 (`KB_semantic_hybrid`) 實作完成

### 背景與功能說明
依據 [NewFeaturesPlan_KBSemanticHybridPlan.md](NewFeaturesPlan_KBSemanticHybridPlan.md) 實作，新增獨立檢索模式 `KB_semantic_hybrid`（集團知識庫語義混合查詢法）。透過此模式，將集團內部文件檢索邏輯與既有 `semantic_hybrid` 進行隔離，並針對 Qdrant Point Payload 中的 `is_public` (boolean) 屬性執行客製化的機密權限過濾。

### 主要變更
1. **後端**：
   - `backend/services/permission_service.py`：新增 `PermissionService.filter_results_kb_semantic_hybrid()` 類別方法，依 `is_public` 進行分流過濾：
     - `is_public == true`：公開文件（不限制部門），但必須符合職級門檻 (`user.level <= access_level`)。
     - `is_public == false`：非公開文件，必須符合部門限制 (`user.department` 或 `department_code` 等於 `access_dept`) **且** 符合職級門檻 (`user.level <= access_level`)。
     - `access_members` 為個人白名單，優先放行。
   - `backend/routers/rag.py`：`rag_chat_stream()` 內新增 `KB_semantic_hybrid` 選項判斷與專屬權限過濾呼叫。
   - `backend/routers/retrieval.py`：`/api/retrieval/search` 檢索測試端點支援 `KB_semantic_hybrid`。
2. **前端**：
   - `frontend/src/components/params/RagParamsPanel.vue`：新增「集團知識庫語義混合查詢 (KB Semantic Hybrid)」下拉選項與指代消解判斷。
   - `frontend/src/views/RetrievalTestView.vue`：新增 `KB_semantic_hybrid` 選項、RRF Score 標籤顯示與步驟狀態更新。
   - `frontend/src/components/params/ApiJsonPreviewPanel.vue`：更新 API 參數預覽註解。
   - `frontend/src/components/eval/TestSetManager.vue`：測試集管理頁面新增該選項。
3. **文件與測試**：
   - `docs/DevelopmentProcess/NewFeaturesPlan_KBSemanticHybridPlan.md`：建立新功能規劃與實作說明文件。
   - `docs/03_API_CONTRACT.md`：更新 API 合約說明。
   - 通過 `test_kb_semantic_hybrid.py` 權限單元測試（包含公開/非公開、部門限制、職級門檻與白名單過濾案例）。

