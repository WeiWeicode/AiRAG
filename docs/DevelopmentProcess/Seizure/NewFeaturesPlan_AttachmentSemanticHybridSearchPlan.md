# 語義混合附件查詢法（Semantic Hybrid Attachment Search）規劃文件

> 狀態：**已實作，2026-07-06 完成程式碼複查並修正全部發現的問題（8.1-8.7）**。實作與修正異動請對照 `docs/DevelopmentProcess/NewFeatures.md`／`BackendCorrection.md`／`FrontendCorrection.md` 2026-07-06 條目。複查過程與各項問題的修正結果見文末「第 8 節：程式碼複查發現的問題」。
>
> 目標範例：使用者在 RAG 測試頁選擇「語義混合附件查詢法」提問「我想了解git教學簡報並提供相關下載」，系統除了一般回答外，也要提供「git教學簡報.pdf」的下載點；若使用者勾選「AI 讀取附件內容」，AI 可讀取附件內容做總結。
>
> **重要架構決策（已與使用者確認）**：附件**不需要**獨立寫入 Qdrant 向量資料庫做語意搜尋，僅存 MongoDB metadata + 實體檔案（`backend/FileAttachments/`）。附件是否出現在回答中，完全依賴「附件與哪個已向量化文件建立關聯」+「該文件是否被既有語義混合兩階段檢索命中」決定，不需要對附件描述文字另外做 embedding/向量索引。這讓範圍縮小為「附件 CRUD + 檔案關聯 + RAG 流程串接」，不需要修改 Qdrant 的向量索引/RRF 邏輯本身。

## 1. 目標與範圍

新增一種**新的檢索模式** `semantic_hybrid_attachment`（語義混合附件查詢法），讓使用者能：
1. 上傳附件檔案（存於後端 `backend/FileAttachments/`），並填寫詳細內容說明、選取標籤與類別。
2. 在「已向量化資料管理與刪除」頁面，把附件用「關聯」的方式綁定到某個已向量化的文件（比照既有 `links_to` 檔案關聯機制）。
3. 在 RAG 測試頁選擇此查詢法提問時，流程等同既有 `semantic_hybrid`（兩階段關聯檢索）找到相關文件後，額外找出該文件關聯的附件：
   - 一律在回答中提供**下載點**。
   - 若勾選「AI 讀取附件內容」，附件的文字說明會併入 LLM 摘要用的 context（重用既有 Map-Reduce 分批摘要門檻機制），讓 AI 可摘要附件內容；不勾選則只顯示下載連結、不進 LLM context。

**明確不動的部分**（比照既有加法式開發慣例，見 2026-07-03「語義資料庫查詢法」規劃）：
- 既有 `vector`/`hybrid`/`semantic_hybrid`/`semantic_hybrid_feedback`/`semantic_db_query` 五種查詢法的程式路徑、Prompt **完全不修改**。
- 既有 `links_to`（文件↔文件關聯）機制與雙階段檢索邏輯**不變**，附件關聯是新增的獨立欄位 `linked_attachments`，不共用 `links_to`。
- 新查詢法以新增 `search_type` 值 `semantic_hybrid_attachment` 的方式加進 `rag.py`，只新增分支，不改動既有分支邏輯。
- 附件不寫入 Qdrant，因此**不需要**修改 `qdrant_service.py` 的 `search_similar`/`search_similar_two_step` 過濾條件（與 `db_query_profile` 用 `must_not` 隔離的做法不同，附件從一開始就不在 Qdrant 裡，無需隔離）。

## 2. 名詞定義

| 名詞 | 說明 |
|---|---|
| 附件 (Attachment) | **新概念**：使用者上傳的實體檔案（如 PDF/簡報），存於 MongoDB 的 metadata（原始檔名、重新編碼後的儲存檔名、詳細內容說明、標籤、類別）+ 磁碟實體檔案。不寫入 Qdrant。 |
| 關聯附件 (linked_attachments) | 已向量化文件（Qdrant Point 的 `filename`）與附件之間的多對多關聯，欄位存在 Qdrant payload 上，比照既有 `links_to` 欄位的維護方式（同一批 filename 的所有 chunks 共用同一份 `linked_attachments` 清單）。 |

## 3. 資料模型設計

### 3.1 新 MongoDB Document：`Attachment`

新檔案 `backend/models/attachment.py`：

```python
class Attachment(Document):
    knowledge_base_id: str          # 關聯 KnowledgeBase._id
    original_filename: str          # 使用者上傳時的原始檔名（可能含中文/特殊字元）
    stored_filename: str            # 落地於 FileAttachments/ 的重新編碼檔名 (uuid4().hex + 副檔名)
    description: str = ""           # 使用者填寫的詳細內容說明，供 AI 摘要使用
    tags: List[str] = []
    classes: List[str] = []
    content_type: str | None = None
    size: int = 0
    created_by: str | None = None
    created_at, updated_at: datetime

    class Settings:
        name = "attachments"
        indexes = ["knowledge_base_id", "-created_at"]
```

註冊進 `backend/models/mongodb.py` 的 `init_beanie(document_models=[...])` 清單（比照 `DBQueryProfile` 的註冊方式）。

### 3.2 實體檔案儲存與重新編碼（對應需求 5）

- `backend/config.py` 新增 `FILE_ATTACHMENTS_DIR: str = os.getenv("FILE_ATTACHMENTS_DIR", "FileAttachments")`（相對於 backend 執行目錄，即現有的 `backend/FileAttachments/`）。
- 上傳時重新編碼檔名：`stored_filename = f"{uuid4().hex}{Path(original_filename).suffix}"`，避免中文/特殊字元造成的檔案系統相容性問題、路徑穿越風險與檔名碰撞；`original_filename` 完整保留在 MongoDB，供下載時透過 `Content-Disposition` 還原成原始檔名。

## 4. 後端 API 設計

### 4.1 附件 CRUD + 下載：新 Router `backend/routers/attachment.py`（`/api/attachments`，掛 `Depends(get_current_user)`）

比照 `embedding.py`/`ai_db_query.py` 的風格：

- `POST /api/attachments/upload`：`UploadFile` + `Form` 欄位（`knowledge_base_id`、`description`、`tags`、`classes`，tags/classes 以逗號分隔字串傳入）。一次請求同時完成「存檔 + 填寫說明/標籤/類別」（不像既有 embedding 流程分成上傳/切分/向量化三步，因為附件不需要切分與向量化）。
- `GET /api/attachments?knowledge_base_id=`：列出指定知識庫的附件清單（供上傳頁列表管理，以及「已向量化資料管理」頁面的關聯勾選清單使用）。
- `DELETE /api/attachments/{id}`：刪除 Mongo 紀錄 + 刪除實體檔案。**不**級聯清除其他文件 chunks 上的 `linked_attachments` 參照（保持簡單）；RAG 流程讀取附件時，對已不存在的 id 靜默跳過（防禦性處理，非吞例外）。
- `GET /api/attachments/{id}/download`：讀取 Mongo 紀錄找到 `stored_filename`，用 `FileResponse(path, filename=attachment.original_filename, media_type=attachment.content_type or "application/octet-stream")` 回傳，Starlette 會自動處理非 ASCII 檔名的 `Content-Disposition: filename*=UTF-8''...`。

於 `backend/main.py` 掛載：`app.include_router(attachment.router, prefix="/api")`。

新增 `backend/schemas/attachment.py`：`AttachmentResponse`（id/original_filename/description/tags/classes/size/content_type/created_at）、`AttachmentListResponse`。

### 4.2 文件↔附件關聯（對應需求 2，比照既有 `links_to` 機制）

- `qdrant_service.py` 新增 `update_attachments_by_filename(collection_name, filename, attachment_ids)`：完全比照現有 `update_links_to_by_filename`（`backend/services/qdrant_service.py:917-952`），只是把 `set_payload` 的欄位從 `links_to` 換成 `linked_attachments`。
- `get_unique_metadata()`（`backend/services/qdrant_service.py:776-858`）比照 `links_to` 的收集邏輯，多 scroll 一個 payload 欄位 `linked_attachments`，並在回傳的 `structured_metadata` 每筆項目加上 `linked_attachments: List[str]`。
- `backend/schemas/retrieval.py` 新增 `UpdateAttachmentsRequest { filename: str; attachment_ids: List[str] }`；`RetrievalMetadata` 加一個 `linked_attachments: Optional[List[str]] = []` 欄位。
- `backend/routers/retrieval.py` 新增 `POST /knowledge-bases/{kb_id}/files/update-attachments`，完全比照 `update_file_links`（`backend/routers/retrieval.py:419-465`）呼叫新的 service 方法。

### 4.3 RAG 流程串接（對應需求 3、4）：`backend/routers/rag.py`

- `ChatParams` 新增 `read_attachment_content: Optional[bool] = False`。
- 在 `rag_chat_stream` 中，當 `search_type == "semantic_hybrid_attachment"` 時：
  1. 檢索邏輯完全比照現有 `semantic_hybrid` 分支（呼叫 `search_similar_two_step`、`RerankService.rerank`），**不需要**新增任何 Qdrant 呼叫。
  2. `sources` 組好之後，收集 `sources` 中出現過的所有 `linked_attachments` id（去重），透過 `Attachment.find(...).to_list()` 一次查出對應紀錄，對每筆組出 `{attachment_id, original_filename, download_url: f"/api/attachments/{id}/download", description}`，存進新的 `attachments` list。
  3. 若 `read_attachment_content` 為 True：把每筆附件的 `description` 當作額外的 `block`（`{"text": ..., "label": original_filename}`）併入既有的 `blocks` 列表（`backend/routers/rag.py:434-452` 附近邏輯），一起交給 `ContextSummarizerService.maybe_summarize`，**重用**既有的 `context_summarize_trigger_tokens` 門檻與分批摘要 SSE 事件（`context_summarize_r*_batch_*`/`_reduce`），**不需要另外開發新的批次摘要機制**（對應需求 3-3）。同時把附件內容以 `is_attachment: true` 標記加進 `sources`，讓摘要引用來源可以顯示是附件內容。
  4. 若 `read_attachment_content` 為 False：附件僅放進新的 `attachments` 列表（下載用），不進入 `blocks`/`context_str`，不影響 LLM 回答內容。
  5. 最終 `event: sources` 的 payload 除現有欄位外，新增 `"attachments": [...]`。

## 5. 前端設計

### 5.1 附件上傳（對應需求 1）— `EmbeddingTestView.vue` 新增分頁

- 新增 `frontend/src/components/embedding/AttachmentManagerTab.vue`（比照 `DBQueryProfileManager.vue`/`SingleIndexingTab.vue` 的結構與 Tailwind 樣式）：
  - 檔案選擇（原生 `<input type="file">`；不重用 `FileUploader.vue`，因為該元件會呼叫 `/api/embedding/upload` 做文字解析，附件不需要解析文字）。
  - 詳細內容說明 `<textarea>`、標籤/類別勾選（重用既有 `embeddingService.getTags/getClasses/createTag/createClass`，UI 抄 `SingleIndexingTab.vue:209-296` 的標籤/類別區塊）。
  - 送出時呼叫新的 `attachmentService.upload(formData)`（multipart）。
  - 下方列出目前知識庫已上傳的附件（`attachmentService.list(kbId)`），可刪除（`attachmentService.remove(id)`）。
- 在 `EmbeddingTestView.vue` 的分頁清單加入這個新分頁。
- 新增 `frontend/src/services/attachmentService.js`（比照 `embeddingService.js` 風格）：`upload`, `list`, `remove`, `downloadUrl(id)`。

### 5.2 附件關聯（對應需求 2）— `VectorManagementTab.vue`

- 在既有「設定關聯檔案 (Links To)」區塊（`VectorManagementTab.vue:238-277`）下方，新增一個結構相同的「關聯附件」區塊：
  - 用 `attachmentService.list(paramsStore.knowledgeBaseId)` 取得可選附件清單（勾選框列表，同 `candidateLinks` 的寫法）。
  - `managementStructuredMetadata` 內新增讀取後端回傳的 `linked_attachments` 欄位，初始化 `selectedAttachments`。
  - 儲存呼叫新的 `retrievalService.updateAttachments(kbId, filename, attachmentIds)` → 對應後端 `update-attachments`。
- `retrievalService.js` 新增 `updateAttachments` 方法（比照 `retrievalService.js:28-34` 的 `updateLinks`）。

### 5.3 RAG 測試頁（對應需求 3）

- `RagParamsPanel.vue`：在 search_type `<select>`（約 68-69 行附近）新增 `<option value="semantic_hybrid_attachment">語義混合附件查詢法</option>`；新增一個僅在選到此模式時顯示的 checkbox「AI 讀取附件內容並總結」，綁定新的 param 欄位 `read_attachment_content`，並確認送出 payload 時把它帶進 `params`。
- `SourceChunks.vue`（或 `ChatWindow.vue` 組裝訊息處）新增「附件下載」區塊：對 SSE `sources` event 新增的 `attachments` 陣列逐筆渲染檔名 + 下載按鈕。下載按鈕**不能**用普通 `<a href>`（後端下載端點掛 JWT 驗證），需用 `api.get(downloadUrl, {responseType: 'blob'})` 取得 blob 後用 `URL.createObjectURL` + 暫時 `<a download>` 觸發瀏覽器下載，檔名直接用已知的 `original_filename`。
- 若 `read_attachment_content` 勾選且附件內容被摘要引用，`sources` 內 `is_attachment: true` 的項目可在既有 chunk 引用清單中一併顯示，不需要額外元件。

## 6. 實作順序

1. 後端：`models/attachment.py` → `mongodb.py` 註冊 → `config.py` 新增 `FILE_ATTACHMENTS_DIR` → `schemas/attachment.py` → `routers/attachment.py` → `main.py` 掛載路由。
2. 後端：`qdrant_service.py` 新增 `update_attachments_by_filename` + `get_unique_metadata` 擴充 `linked_attachments` → `schemas/retrieval.py` + `routers/retrieval.py` 新增 `update-attachments` 端點。
3. 後端：`routers/rag.py` 新增 `read_attachment_content` 參數與 `semantic_hybrid_attachment` 分支邏輯。
4. 前端：`attachmentService.js` → `AttachmentManagerTab.vue` → 掛進 `EmbeddingTestView.vue` 分頁。
5. 前端：`VectorManagementTab.vue` 新增關聯附件區塊 + `retrievalService.updateAttachments`。
6. 前端：`RagParamsPanel.vue` 新增查詢法選項與 checkbox → `SourceChunks.vue`/`ChatWindow.vue` 渲染下載點。
7. 文件同步：更新 `docs/03_API_CONTRACT.md`（新增章節）、`docs/04_DB_SCHEMA.md`（新增 `attachments` collection、`linked_attachments` payload 欄位）、`docs/DevelopmentProcess/NewFeatures.md`/`BackendCorrection.md`/`FrontendCorrection.md`。

## 7. 驗證方式

使用者自行手動測試（依專案慣例不需開瀏覽器驗證）。建議驗證步驟：

1. 啟動後端 `uvicorn main:app --reload --port 53020`、前端 `npm run dev`。
2. 到「自訂資料向量化」新分頁上傳一個附件（含說明/標籤），確認 `backend/FileAttachments/` 出現重新編碼過的實體檔案，且 `GET /api/attachments` 能列出。
3. 到「已向量化資料管理」選擇某個已存在的文件，勾選剛上傳的附件並儲存，確認 `GET /api/knowledge-bases/{id}/metadata` 回傳的 `structured_metadata` 該檔案項目含 `linked_attachments`。
4. 到 RAG 測試頁選「語義混合附件查詢法」，提問能命中該文件的問題：
   - 不勾選「AI 讀取附件內容」：回答中應出現下載點，但附件內容不影響回答文字。
   - 勾選後：附件說明內容應納入摘要/回答依據，且觸發分批摘要門檻時應能看到既有的 `context_summarize_r*` 步驟事件正常運作（無需新機制）。
   - 點擊下載按鈕，確認下載下來的檔名是原始檔名（非 uuid），內容正確。

## 8. 程式碼複查發現的問題（2026-07-06，尚待修正）

比對實際實作（`backend/routers/attachment.py`、`backend/models/attachment.py`、`backend/routers/rag.py`、前端 `AttachmentManagerTab.vue`/`MessageBubble.vue`/`VectorManagementTab.vue` 等）與本規劃文件，發現以下問題：

### 8.1【高，已修正 2026-07-06】附件下載端點無身份驗證，且以 MongoDB ObjectId 當作「秘密連結」不夠安全
`backend/routers/attachment.py` 的 `download_attachment()` 完全沒有 `Depends(get_current_user)`（其餘 `upload`/list/`delete` 都有），這是 2026-07-06 `BackendCorrection.md` 記錄的「有意修正」——因為 `window.open()` 開新分頁下載時無法夾帶 SPA 的 `Authorization: Bearer <token>` 標頭，索性拿掉這條路由的驗證，改用「不可預測的 24 碼 ObjectId」當作安全機制。
問題：MongoDB ObjectId 並非密碼學隨機值，前 4 bytes 是**時間戳記**、其餘 bytes 也有可預測的計數器成分，不能真正當「秘密連結」使用；此作法也違反本專案 CLAUDE.md 明列的慣例（除 `auth.py` 外所有 router 都需 `Depends(get_current_user)`）。目前只要有人知道或猜到任一附件的 ObjectId，不需登入即可下載該附件實體檔案。
建議修正方式：改回本規劃文件原本設計的做法——前端改用 `api.get(downloadUrl, { responseType: 'blob' })`（會自動帶上攔截器夾帶的 Bearer token）取得 blob 後，用 `URL.createObjectURL` + 暫時 `<a download>` 觸發下載，藉此讓 `download_attachment()` 端點可以恢復 `Depends(get_current_user)` 保護，不需要犧牲驗證。

**修正結果**：`backend/routers/attachment.py` 的 `download_attachment()` 恢復 `current_user: str = Depends(get_current_user)`；新增 `frontend/src/services/attachmentService.js` 的 `download(id, filename)` 方法（`api.get(url, {responseType:'blob'})` + `URL.createObjectURL` + 暫時 `<a download>`），`frontend/src/components/chat/MessageBubble.vue`、`frontend/src/components/embedding/AttachmentManagerTab.vue` 皆改呼叫此方法取代原本的 `window.open`。

### 8.2【高，已修正 2026-07-06】`.gitignore` 規則寫錯，附件實體檔案目前並未被忽略
`backend/.gitignore` 新增的規則是 `.FileAttachments/`（開頭多一個點），但實際資料夾與 `config.py` 的 `FILE_ATTACHMENTS_DIR` 預設值都是 `FileAttachments`（沒有點）。以 `git check-ignore -v backend/FileAttachments/xxx` 實測確認**完全沒被忽略**——目前 `backend/FileAttachments/` 下已經有一個 7.4MB 的測試 PDF 呈現 untracked 狀態，等同隨時可能被誤 commit 進版控。
建議修正：把 `.gitignore` 該行改成 `FileAttachments/`（或 `backend/FileAttachments/`，視 `.gitignore` 檔案位置的相對路徑規則而定）。

**修正結果**：已將 `backend/.gitignore` 該行改為 `FileAttachments/`，並以 `git check-ignore -v` 實測確認 `backend/FileAttachments/` 下的檔案現在會被正確忽略。

### 8.3【中】`Attachment` 模型的 `created_at`/`updated_at` 使用「立即求值」預設值，而非 `default_factory`
`backend/models/attachment.py`：
```python
created_at: datetime = datetime.utcnow()
updated_at: datetime = datetime.utcnow()
```
`datetime.utcnow()` 只會在模組載入（class body 執行）當下被呼叫一次，之後所有未明確指定這兩個欄位的 `Attachment(...)` 都會共用同一個「伺服器啟動當下」的凍結時間戳記，而非各自的建立時間。目前因為 `routers/attachment.py` 的 `upload_attachment()` 每次都有明確傳入 `created_at=datetime.utcnow()`/`updated_at=datetime.utcnow()`，所以這個 bug 暫時沒有被觸發，但屬於地雷式的潛在缺陷，且與專案內其他 Document（例如 `backend/models/db_query_profile.py` 使用 `Field(default_factory=datetime.utcnow)`）的寫法不一致。
建議修正：改為 `Field(default_factory=datetime.utcnow)`，與既有慣例一致。

**修正結果**：`created_at`/`updated_at` 已改為 `Field(default_factory=datetime.utcnow)`；`tags`/`classes` 也一併改為 `Field(default_factory=list)` 與其他 Document 一致；同時移除未使用的 `Indexed` import（對應 8.3 節末的次要項目）。

### 8.4【低，已修正 2026-07-06】下載網址字串重複硬編碼在多處，且後端 `attachments` 事件缺少 `download_url` 欄位
規劃原先設計後端 `rag.py` 組出的 `attachments` 陣列每筆應含 `download_url` 欄位，但實作中 `attachments_to_send` 只有 `id`/`original_filename`/`description`，改由前端各自組字串 `` `/api/attachments/${id}/download` ``。`frontend/src/services/attachmentService.js` 已提供 `getDownloadUrl(id)` 集中管理這個路徑，但 `frontend/src/components/chat/MessageBubble.vue` 的 `downloadAttachment()` 並未呼叫它、而是自行重複硬編碼同一個字串樣板。目前兩處字串一致所以還能動作，但日後若下載路由路徑調整，容易漏改其中一處。
建議修正：`MessageBubble.vue` 改呼叫 `attachmentService.getDownloadUrl(id)`，或後端在 `attachments` 事件內直接補上 `download_url` 欄位讓前端不需要自己組字串。

**修正結果**：`backend/routers/rag.py` 的 `attachments_to_send` 每筆補上 `download_url`；前端下載呼叫已在 8.1 修正時一併統一改為 `attachmentService.download()`（內部呼叫 `getDownloadUrl()`），`MessageBubble.vue`/`AttachmentManagerTab.vue` 不再各自硬編碼字串樣板。

### 8.5【低，已修正 2026-07-06】向量管理頁的附件關聯徽章只顯示 ObjectId，不顯示附件檔名
`frontend/src/components/embedding/VectorManagementTab.vue` 的「Linked Attachments Badges」區塊（📎 附件關聯）目前每個徽章文字都寫死「📎 附件關聯」，`title` 屬性也只放原始 `aid`（ObjectId 字串），沒有比對 `allAttachments` 陣列還原成附件的 `original_filename`，使用者無法從畫面上一眼看出這個 chunk 到底關聯了哪個附件。
建議修正：用 `allAttachments.find(a => a.id === aid)?.original_filename` 顯示實際檔名。

**修正結果**：`VectorManagementTab.vue` 新增 `getAttachmentName(aid)`（對照 `allAttachments` 還原 `original_filename`，找不到時 fallback 回原始 id），徽章改顯示實際檔名。

### 8.6【低，已修正 2026-07-06】`semantic_hybrid_attachment` 尚未加入 `/api/retrieval/search` 的兩階段檢索判斷式
`backend/routers/retrieval.py` 第 52 行 `is_semantic_hybrid_family = request.params.search_type in ("semantic_hybrid", "semantic_hybrid_feedback")` 沒有把新的 `semantic_hybrid_attachment` 一併加入。目前因為 `RagParamsPanel.vue`（唯一暴露此查詢法選項的元件）只掛載在 `RagTestView.vue`、不在 `RetrievalTestView.vue`，所以這個落差目前不會被觸發；但如果之後有其他呼叫端（例如 `/api/evaluation/run` 或未來的檢索測試頁）傳入這個新 `search_type` 值，會被靜默當成普通 `search_similar`（單階段、不含附件）處理，而不是報錯，屬於「行為悄悄跟預期不一致」而非當機。建議在擴充其他呼叫端支援此查詢法時一併補上這個判斷式，並在 `docs/03_API_CONTRACT.md` 註明目前僅 `POST /api/rag/chat` 支援此查詢法。

**修正結果**：`is_semantic_hybrid_family` 已加入 `"semantic_hybrid_attachment"`，`/api/retrieval/search` 傳入此 `search_type` 時會正確走雙階段關聯檢索（`search_similar_two_step`）；已確認 `feedback_boost` 分支仍只在 `== "semantic_hybrid_feedback"` 時觸發，不受影響。此端點仍**不會**額外查詢 `Attachment` collection 或組出下載資訊（該行為僅存在於 `POST /api/rag/chat`），已在 `docs/03_API_CONTRACT.md` 第 14.3 節註明。

### 8.7【文件落差，已修正 2026-07-06】`docs/03_API_CONTRACT.md`、`docs/04_DB_SCHEMA.md` 尚未依本次新增內容更新
本次只更新了 `NewFeatures.md`/`BackendCorrection.md`/`FrontendCorrection.md`，但 CLAUDE.md「Known doc/code drift」段落要求觸及 routers/models/schemas 時應保持 `03_API_CONTRACT.md`/`04_DB_SCHEMA.md` 同步。目前這兩份文件完全沒有提到 `attachments` collection、`linked_attachments` payload 欄位、`/api/attachments/*` 端點與 `semantic_hybrid_attachment` 查詢法，之後若有人只看這兩份文件會誤以為此功能不存在。

**修正結果**：`docs/03_API_CONTRACT.md` 新增第 14 節（附件 CRUD/下載、文件↔附件關聯、RAG 對話整合三個小節），並更新 §3.1（`search_type`/`read_attachment_content`/`attachments` SSE 欄位）、§4.1（`linked_attachments`）、新增 §4.7（`update-attachments` 端點）。`docs/04_DB_SCHEMA.md` 新增 §3.13（`attachments` collection）與 §4.2 的 `linked_attachments` payload 欄位說明，並更新 Collection 總覽圖與計數。
