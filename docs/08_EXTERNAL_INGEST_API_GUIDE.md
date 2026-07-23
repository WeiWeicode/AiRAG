# 外部應用串接指南 — 多應用 RAG 向量同步與切分 API (`POST /api/external/ingest/trigger`)

## 0. 文件資訊

* **對象**：公司內網異質應用系統（如 GigaSolarKnowledgeBase, BPM, Meeting, NotesAPP 等）的開發者。
* **對應功能規劃文件**：[MULTI_APP_RAG_SYNC_PLAN.md](DevelopmentProcess/MULTI_APP_RAG_SYNC_PLAN.md)（多應用 RAG 向量同步與附件 API 整合規範）。
* **實作對照程式碼**：
  * API 進入點：[backend/routers/external.py](../backend/routers/external.py)
  * Schema 定義：[backend/schemas/ingest.py](../backend/schemas/ingest.py)
  * 背景任務處理：[backend/worker.py](../backend/worker.py)、[backend/services/ingest_service.py](../backend/services/ingest_service.py)
* **建立日期**：2026-07-23。

---

## 1. 這是什麼

`POST /api/external/ingest/trigger` 是 AiRAG 提供給公司內網**各應用系統**（KnowledgeBase, BPM, Meeting 等）觸發文件向量化、文本切分（Parent-Child Chunking）、Embedding 計算與 Qdrant 寫入/刪除的非同步 API 端點。

### 核心運作機制（異步 Pull 模式）

1. **輕量觸發 (ACK)**：當外部應用有文章或附件新增/更新/刪除時，發起本 Trigger 請求。請求中僅包含中繼資料（Metadata），不傳送檔案全文或二進位串流。AiRAG 驗證後立即回傳 `202 Accepted` 與 `taskId`。
2. **背景拉取與切分**：AiRAG 的 `arq` 背景佇列行程取得任務後，依據各 App 登錄的端點資訊，帶上專屬金鑰 `X-RAG-Sync-Key` **主動向該 App 的 API 拉取**全文或二進位附件檔，並執行切分與 Embedding 寫入 Qdrant。
3. **結果回調 (Webhook Callback)**：當切分成功或失敗時，AiRAG 發起 `POST` 請求向外部應用的 `callbackUrl` 回報狀態與進度。

---

## 2. Base URL 與認證

### 2.1 Base URL
```
http://<AiRAG 後端主機>:53020/api
```

> ⚠️ **Base URL 拼接防護**：Client App 配置 `AIRAG_BASE_URL` 時，請填寫 `http://<主機位址>:53020`（**勿包含 `/api` 後綴**），避免呼叫時疊加成 `/api/api/external/ingest/trigger` 導致 404 錯誤。

### 2.2 認證方式

* **Header**：`X-API-Key: <AIRAG_INGEST_API_KEY>`
* **說明**：本 API 採用 Ingest 專屬的金鑰權限驗證。請向 AiRAG 管理者索取或於 AiRAG 管理介面申請對應權限之 API Key。若未帶標頭或 Key 無效，回應 `401 Unauthorized`。

---

## 3. 前置準備：App 登錄 (App Registration)

外部應用接入前，需由 AiRAG 管理員在系統中建立 `AppRegistration` 紀錄：
1. **`appId`**：應用識別碼（全小寫英數字，例如 `bpm`, `meeting`, `kb`）。
2. **`base_url`**：外部應用後端服務基底網址（例如 `http://bpm-backend.company.internal`）。
3. **`content_docs_path_template`**：文章內容 API 路徑樣板（例如 `/api/v1/rag-sync-content/docs/{id}`）。
4. **`content_attachment_path_template`**：附件 API 路徑樣板（例如 `/api/v1/rag-sync-content/attachments/{id}`）。
5. **`report_mode`**：進度回報模式（`webhook` 或 `direct_db`）。
6. **環境變數 `{APP_ID}_RAG_SYNC_KEY`**：由 AiRAG 後端維運人員設定於 `.env` 中，供 AiRAG 主動拉取外部應用 API 時驗證身份。

---

## 4. API 契約規範 (`POST /api/external/ingest/trigger`)

### 4.1 Request Headers
| Header | 值 | 說明 |
|---|---|---|
| `Content-Type` | `application/json` | |
| `X-API-Key` | `<AIRAG_INGEST_API_KEY>` | **必填**。Ingest 專用金鑰 |

### 4.2 Request Body 欄位說明 (camelCase)

| 欄位名稱 | 型態 | 必填 | 說明 | 範例 / 預設值 |
|---|---|---|---|---|
| `appId` | String | **是** | 已登錄的應用識別碼 | `"bpm"` |
| `docType` | String | **是** | 文件類型。`attachment_file` 代表附件二進位檔，其餘代表文字/文章 | `"attachment_file"` 或 `"article"` |
| `sourceId` | Integer / String | **是** | 來源系統內部的檔案/文章主鍵 ID | `2048` |
| `title` | String | 否 | 檔案名稱或文章標題 | `"EFGP-ReleaseNote.pdf"` |
| `targetVersion` | Integer | **是** | 本次異動的目標版本號（防止競態覆蓋） | `3` |
| `action` | String | 否 | 動作類型：`"upsert"`（新增/更新）或 `"delete"`（刪除） | 預設 `"upsert"` |
| `knowledgeBaseId` | String | **是** | 欲寫入的 AiRAG 知識庫/Qdrant Collection ID | `"kb_6a389dc83578b9d3d717244d"` |
| `callbackUrl` | String | 條件必填 | 當 App 的 `report_mode` 為 `webhook` 時**必填**；AiRAG 處理完畢後的回調 Webhook | `"http://bpm-backend.company.internal/api/v1/rag-sync/callback"` |
| `permissions` | Object | 否 | 檢索權限控制物件（詳見 4.3 節） | |

### 4.3 `permissions` 物件欄位 (camelCase)

| 欄位名稱 | 型態 | 預設值 | 說明 |
|---|---|---|---|
| `isPublic` | Boolean | `false` | 是否公開。`true` 代表所有人皆可檢索 |
| `accessDept` | String / null | `null` | 允許存取的部門代碼（如 `"IT01"`） |
| `accessLevel` | Integer / null | `null` | 允許存取的最低職稱等級 |
| `accessMembers` | Array[String] | `[]` | 個人白名單工號列表（例如 `["S112009", "S220011"]`） |

### 4.4 Request 範例

```json
POST /api/external/ingest/trigger
Header:
  Content-Type: application/json
  X-API-Key: your-ingest-api-key

Body:
{
  "appId": "bpm",
  "docType": "attachment_file",
  "sourceId": 2048,
  "title": "EFGP-ReleaseNote.pdf",
  "targetVersion": 3,
  "action": "upsert",
  "knowledgeBaseId": "kb_6a389dc83578b9d3d717244d",
  "callbackUrl": "http://bpm-backend.company.internal/api/v1/rag-sync/callback",
  "permissions": {
    "isPublic": false,
    "accessDept": "IT01",
    "accessLevel": 6,
    "accessMembers": ["S112009", "S220011"]
  }
}
```

### 4.5 Response 規範 (202 Accepted)

```json
HTTP/1.1 202 Accepted
Content-Type: application/json

{
  "success": true,
  "message": "Task queued successfully",
  "taskId": "7f8b9a2c-3d4e-5f6a-8b9c-0d1e2f3a4b5c"
}
```

---

## 5. 外部應用需配合開放之端點與契約

外部應用欲整合此向量同步服務，需在其系統中實作以下端點供 AiRAG 呼叫與回調：

### 5.1 文章/內容拉取端點 (AiRAG 呼叫 外部應用)
* **HTTP Method**：`GET`
* **路徑**：依登錄之 `content_docs_path_template`（如 `/api/v1/rag-sync-content/docs/:id`）
* **驗證 Header**：`X-RAG-Sync-Key: <{APP_ID}_RAG_SYNC_KEY>`
* **Response 範例**：
  ```json
  {
    "appId": "bpm",
    "docType": "article",
    "sourceId": 1001,
    "title": "系統修復公告",
    "content": "# 標題\n這是 Markdown 全文內容...",
    "version": 1,
    "updatedAt": "2026-07-23T10:00:00Z",
    "permissions": {
      "isPublic": true
    }
  }
  ```

### 5.2 附件二進位拉取端點 (AiRAG 呼叫 外部應用)
* **HTTP Method**：`GET`
* **路徑**：依登錄之 `content_attachment_path_template`（如 `/api/v1/rag-sync-content/attachments/:id`）
* **驗證 Header**：`X-RAG-Sync-Key: <{APP_ID}_RAG_SYNC_KEY>`
* **Response**：回傳檔案二進位流 (Binary Stream)。
* **Response Headers 需求**：
  * `X-Doc-Version`: 版本號（例如 `3`）
  * `X-Doc-App-Id`: 應用識別碼（例如 `bpm`）
  * `X-Doc-Is-Public`: `"true"` 或 `"false"`

### 5.3 Webhook 回調端點 (AiRAG 回報進度給 外部應用)
* **HTTP Method**：`POST`
* **路徑**：即 Trigger 帶入之 `callbackUrl`
* **Body 範例 (完成時)**：
  ```json
  {
    "appId": "bpm",
    "docType": "attachment_file",
    "sourceId": 2048,
    "status": "completed",
    "progress": 100,
    "syncedVersion": 3,
    "title": "EFGP-ReleaseNote.pdf",
    "updatedAt": "2026-07-23T10:05:00Z"
  }
  ```

---

## 6. 常見問題與開發注意事項

1. **冪等性與競態防護 (Race Condition)**：
   外部應用收到 Webhook 回調更新狀態時，建議使用 SQL `WHERE target_version = syncedVersion` 條件更新，避免較舊版本的異步任務覆蓋較新的同步狀態。
2. **刪除操作 (Delete Action)**：
   若需從 Qdrant 刪除某文件向量，設定 `"action": "delete"` 即可。此時無需提供傳輸長內文，AiRAG 會清除指定 `appId` + `docType` + `sourceId` 的所有向量點位。
