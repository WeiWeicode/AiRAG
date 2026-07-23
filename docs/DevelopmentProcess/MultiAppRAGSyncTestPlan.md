# 多應用 RAG 向量同步系統 測試計畫 (Multi-App RAG Sync Test Plan)

> **文件狀態**：初稿（2026-07-23）  
> **目標功能**：多應用 RAG 向量同步與切分觸發 API (`POST /api/external/ingest/trigger`)、arq 背景佇列、App Registry、內容拉取與 Qdrant 寫入、混合進度回報與雙權限過濾。  
> **對應規格文件**：[MULTI_APP_RAG_SYNC_PLAN.md](MULTI_APP_RAG_SYNC_PLAN.md)、[08_EXTERNAL_INGEST_API_GUIDE.md](../08_EXTERNAL_INGEST_API_GUIDE.md)  
> **對應程式碼**：`backend/routers/external.py`, `backend/worker.py`, `backend/services/ingest_service.py`, `backend/services/app_content_client.py`, `backend/services/ingest_report_service.py`, `backend/services/permission_service.py`

暫時用api key
b9KoW0DRsjyg3xX9H3qvm85oN6UN3GUdkCu5Yw_BcjE

---

## 1. 測試目標與範疇 (Test Scope & Objectives)

本測試計畫旨在確保多應用 RAG 同步架構的穩定性、安全性與資料一致性，測試範疇涵蓋：
1. **API 入口與權限控制**：驗證 Trigger 端點驗證邏輯與 Ingest 專屬 `X-API-Key` 隔離。
2. **非同步背景佇列**：驗證 `arq worker` + Redis 任務調度、重試與例外捕獲。
3. **應用登錄與樣板匹配**：驗證 `AppRegistration` 的路由樣板解析與機敏 Key 傳送。
4. **內容與附件 Pull 拉取**：驗證文章 Markdown 與附件二進位檔 (PDF/Docx) 的拉取相容性與異常處理。
5. **向量化與 Qdrant 寫入/刪除**：驗證 Parent-Child 切分、Embedding 計算、舊點位殘留清掃 (`delete_by_app_source`) 與全新點位寫入。
6. **混合狀態回報**：驗證 HTTP Webhook 回調與 KB 專用 Direct DB (SQL Server) 寫入防競態機制 (`WHERE target_version = version`)。
7. **雙權限過濾**：驗證新增之 `is_public` / `access_dept` / `access_level` / `access_members` 與既有權限欄位之相容性與檢索隔離。

---

## 2. 測試環境與前置準備 (Prerequisites)

### 2.1 服務組態需求
- **MongoDB**：需運行並包含 `app_registrations` 與 `knowledge_bases` 測試集合。
- **Redis**：`redis://localhost:6379`（供 `arq` 任務佇列使用）。
- **Qdrant Vector DB**：運行中，已建立測試用 Collection（如 `kb_test_collection`）。
- **Mock External App Server**：測試用微服務或 Mock HTTP Server，需提供：
  - GET `/api/v1/rag-sync-content/docs/:id`（回傳測試 Markdown）
  - GET `/api/v1/rag-sync-content/attachments/:id`（回傳測試 PDF 二進位檔與 Headers）
  - POST `/api/v1/rag-sync/callback`（接收 Webhook 回調）

### 2.2 預先建立之測試資料
1. **API Key**：建立一筆 `scope="ingest"` 的 `ExternalApiKey`（明碼設為 `test-ingest-api-key-12345`）。
2. **App 登錄**：建立 `AppRegistration`：
   - `app_id`: `"bpm_test"`
   - `base_url`: `"http://localhost:8080"` (Mock Server)
   - `content_docs_path_template`: `"/api/v1/rag-sync-content/docs/{id}"`
   - `content_attachment_path_template`: `"/api/v1/rag-sync-content/attachments/{id}"`
   - `report_mode`: `"webhook"`
3. **環境變數**：在 `.env` 中設定 `BPM_TEST_RAG_SYNC_KEY="bpm-secret-sync-key"`。

---

## 3. 詳細測試案例清單 (Test Cases)

### 3.1 階段一：API 驗證與傳輸契約 (API Trigger & Validation)

| 案例編號 | 測試名稱 | 測試步驟 / 輸入條件 | 預期結果 | 驗證方式 |
|---|---|---|---|---|
| **TC-API-01** | 無權限/無效 Key 拒絕 | 發送 Trigger 請求，`X-API-Key` 帶無效字串或 `scope="chat"` 之 Key | HTTP `401 Unauthorized` | 檢查 HTTP Response Code & Body |
| **TC-API-02** | 未登錄的 appId | Request Body `appId: "unknown_app"` | HTTP `400 Bad Request`（提示 `appId 未登錄或已停用`） | 檢查 HTTP 400 詳細訊息 |
| **TC-API-03** | Webhook 模式未帶 callbackUrl | `appId: "bpm_test"`，`callbackUrl` 設為 `null` 或未帶 | HTTP `400 Bad Request`（提示 `report_mode='webhook' 必須帶 callbackUrl`） | 檢查 HTTP 400 詳細訊息 |
| **TC-API-04** | 不存在的 knowledgeBaseId | Request Body 傳入隨機 ObjectId 字串如 `"60f1b2c3d4e5f6a7b8c9d0e1"` | HTTP `400 Bad Request`（提示 `知識庫不存在`） | 檢查 HTTP 400 詳細訊息 |
| **TC-API-05** | 合法 Trigger 觸發 | 傳入合法 `appId`, `sourceId`, `knowledgeBaseId`, `callbackUrl` 等 | HTTP `202 Accepted`，Response 包含 `"success": true` 與 `taskId`  uuid | 檢查 202 狀態碼與 JSON 回傳 |

---

### 3.2 階段二：背景佇列與內容拉取 (Queue & Content Pulling)

| 案例編號 | 測試名稱 | 測試步驟 / 輸入條件 | 預期結果 | 驗證方式 |
|---|---|---|---|---|
| **TC-PULL-01** | 文字文章內容 Pull | `docType: "article"`，Trigger 成功後，觀察 `arq worker` 執行 | Worker 呼叫 Mock Server `GET /api/v1/rag-sync-content/docs/1001`，帶 Header `X-RAG-Sync-Key: bpm-secret-sync-key` | 檢查 Mock Server 接收日誌與 Header |
| **TC-PULL-02** | 附件二進位檔 Pull | `docType: "attachment_file"`，Trigger 成功後，觀察 `arq worker` 執行 | Worker 呼叫 Mock Server `GET /api/v1/rag-sync-content/attachments/2048`，正確取得二進位串流與 Response Headers | 檢查 Worker 系統日誌與抓取長度 |
| **TC-PULL-03** | 外部 App 端點 404 / 500 異常 | Mock Server 對該 ID 回傳 `404 Not Found` | Worker 捕獲 `httpx.HTTPStatusError` 例外，觸發 Webhook 回報 `status: "failed"`，記載錯誤原因，系統不崩潰 | 檢查 Webhook 是否收到 failed 訊息 |

---

### 3.3 階段三：切分向量化與 Qdrant 寫入 (Ingest & Qdrant Operations)

| 案例編號 | 測試名稱 | 測試步驟 / 輸入條件 | 預期結果 | 驗證方式 |
|---|---|---|---|---|
| **TC-VEC-01** | 新增/更新 Upsert 向量 | `action: "upsert"`，傳送 5KB Markdown 文章內容 | 1. 舊點位已被全數清掃 (`delete_by_app_source`)<br>2. 新點位切分後寫入 Qdrant<br>3. Payload 包含 `app_id: "bpm_test"`, `source_id: 1001`, `version: 1`<br>4. `KnowledgeBase.chunk_count` 數值正確更新 | 查詢 Qdrant Collection 點位 Metadata 與 Mongo `knowledge_bases` 紀錄 |
| **TC-VEC-02** | 重複更新 (清掃舊點位殘留) | 對同一 `sourceId` 先後執行版次 1 與版次 2 之 Trigger | Qdrant 中屬於版次 1 的點位全數消失，僅保留版次 2 向量點位，無重複殘留點 | 以 `app_id` + `source_id` 查詢 Qdrant 所有點位，確認版本全為 2 |
| **TC-VEC-03** | 刪除 Action | 傳送 `action: "delete"`，`sourceId: 1001` | Qdrant 中屬於該 `appId`+`docType`+`sourceId` 的所有點位被全數刪除，`chunk_count` 相應扣減 | 查詢 Qdrant 驗證點位數量為 0 |

---

### 3.4 階段四：混合狀態回報 (Progress & Webhook Reporting)

| 案例編號 | 測試名稱 | 測試步驟 / 輸入條件 | 預期結果 | 驗證方式 |
|---|---|---|---|---|
| **TC-RPT-01** | Webhook 回調通知 | `report_mode: "webhook"` 且執行完成 | 外部 Mock Callback 收到 `POST /api/v1/rag-sync/callback`，Body 包含 `status: "completed"`, `progress: 100`, `syncedVersion: 1` | 檢查 Mock Callback 接收到的 JSON 內容 |
| **TC-RPT-02** | Direct DB SQL 寫入防競態 | `report_mode: "direct_db"`（KB 專用），模擬目標資料庫版本為 2，傳入舊任務版次 1 | 執行 SQL `UPDATE ... WHERE target_version = version`，因條件不符更新 0 筆，避免舊任務蓋掉新狀態 | 檢查 SQL 執行日誌與受影響列數 |

---

### 3.5 階段五：雙權限檢索過濾 (Permissions & Retrieval)

| 案例編號 | 測試名稱 | 測試步驟 / 輸入條件 | 預期結果 | 驗證方式 |
|---|---|---|---|---|
| **TC-PERM-01** | 公開文件 (`isPublic: true`) | 上傳 `isPublic: true` 之文件，以任意使用者身份執行 RAG 檢索 | 能成功檢索到該文件 Chunks | 呼叫 `/api/external/chat` 觀察 `sources` 結果 |
| **TC-PERM-02** | 個人白名單 (`accessMembers`) | 上傳 `isPublic: false`，`accessMembers: ["S112009"]`<br>1. 以 `employee_id: "S112009"` 身份檢索<br>2. 以 `employee_id: "S999999"` 身份檢索 | 1. S112009 可檢索到<br>2. S999999 被過濾掉（無法查到） | 帶入不同 `external_user` 測試檢索結果 |
| **TC-PERM-03** | 既有與新型權限雙軌相容 | 向量庫同時存在既有 `is_confidential: true` 點位與新版 `is_public: false` 點位 | `PermissionService.filter_results()` 正確依據各點位出現的欄位套用對應的篩選邏輯，無 KeyError 或崩潰 | 混合點位進行檢索測試 |

---

## 4. 執行與驗證步驟 (Step-by-Step Verification Guide)

### 4.1 自動化指令驗證步驟

1. **啟動測試環境**：
   ```bash
   docker-compose up -d redis qdrant mongodb
   ```
2. **啟動 arq worker**（在 backend 目錄）：
   ```bash
   python -m arq worker.WorkerSettings
   ```
3. **發送 Trigger 測試 (cURL)**：
   ```bash
   curl -X POST "http://localhost:53020/api/external/ingest/trigger" \
     -H "Content-Type: application/json" \
     -H "X-API-Key: test-ingest-api-key-12345" \
     -d '{
       "appId": "bpm_test",
       "docType": "article",
       "sourceId": 1001,
       "title": "測試文件",
       "targetVersion": 1,
       "action": "upsert",
       "knowledgeBaseId": "60f1b2c3d4e5f6a7b8c9d0e1",
       "callbackUrl": "http://localhost:8080/api/v1/rag-sync/callback",
       "permissions": {
         "isPublic": false,
         "accessMembers": ["S112009"]
       }
     }'
   ```

---

## 5. 驗收與通過標準 (Acceptance Criteria)

- [ ] **API 安全性**：未經授權或非 Ingest 權限的 API Key 一律被拒絕 (401/400)。
- [ ] **佇列可靠性**：Trigger 成功回應 202，背景 worker 可無阻礙消費任務。
- [ ] **向量完整性**：舊版本向量清理乾淨，新版本點位精確寫入，Payload Metadata 完備。
- [ ] **權限隔離性**：個人白名單 (`accessMembers`) 與公開設定能 100% 精準進行向量過濾。
- [ ] **容錯與回報**：任務完成或失敗皆能透過 Webhook 或 Direct DB 正確回報，且不干擾後端服務運行。
