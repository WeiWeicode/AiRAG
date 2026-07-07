# API 合約文件 (API Contract)

## 1. 文件資訊
* **專案名稱**：AiRAG 內部測試平台
* **文件版本**：V 1.5（依實際程式碼校正）
* **建立日期**：2026-06-18
* **更新日期**：2026-07-06（新增第 14 節「附件管理與語義混合附件查詢法」）
* **Base URL**：`http://<host>:8000/api`
* **認證方式**：JWT Bearer Token（除 `/api/auth/login` 外，所有 API 皆掛載於各 router 的 `Depends(get_current_user)`，須帶 `Authorization: Bearer <token>`）

> 本版本已對照 `backend/routers/`、`backend/schemas/` 實際程式碼逐一校正欄位名稱、回應格式與端點清單。凡標記 **[Stub]** 者代表該端點目前為未完整實作的樁函式（stub），呼叫會成功但不執行真正的業務邏輯，請勿依賴其結果。

---

## 2. 認證 API (Auth)

### 2.1 POST `/api/auth/login` — 使用者登入
**Request Body**：
```json
{ "username": "admin", "password": "your_password" }
```
**Response 200**：
```json
{ "access_token": "string (JWT)", "token_type": "bearer", "expires_in": 86400 }
```

---

## 3. RAG 功能測試 API (§4.1)

### 3.1 POST `/api/rag/chat` — RAG 對話（SSE 串流）
**描述**：端到端 RAG 對話，支援 `vector`、`hybrid`、`semantic_hybrid`、`semantic_hybrid_feedback`、`semantic_hybrid_attachment`、`semantic_db_query` 六種模式。當 `search_type` 為 `semantic_hybrid`/`semantic_hybrid_feedback`/`semantic_hybrid_attachment` 時，實際呼叫的是**雙階段關聯檢索** `search_similar_two_step`（見 `02_ARCHITECTURE.md` §5.1），而非單純的雙路混合搜尋。`semantic_hybrid_attachment`（語義混合附件查詢法，2026-07-06 新增）另見第 14 節。

**Request Body**：
```json
{
  "question": "string",
  "knowledge_base_id": "string (選填)",
  "chat_history": [
    { "role": "user", "content": "string" },
    { "role": "assistant", "content": "string" }
  ],
  "params": {
    "model": "string (選填，目前未實際傳給 vLLM 呼叫，僅保留欄位)",
    "temperature": 0.3,
    "max_tokens": 1024,
    "top_k": 13,
    "score_threshold": 0.65,
    "filter_tags": ["string"],
    "search_type": "vector | hybrid | semantic_hybrid | semantic_hybrid_feedback | semantic_hybrid_attachment | semantic_db_query",
    "context_summarize_trigger_tokens": 50000,
    "read_attachment_content": false
  }
}
```
> 注意：`params` 內**沒有** `top_p` 欄位（此為前一版文件的錯誤）。上方數值為程式碼中未帶入時使用的預設值。`read_attachment_content`（2026-07-06 新增）僅在 `search_type == "semantic_hybrid_attachment"` 時有意義，見第 14 節。

**Response**：`text/event-stream` (SSE)，事件如下（實際欄位為 `step` / `status` / `content`，並非 `event` / `detail`）：

* **`event: step`** — 管道進度：
  ```
  event: step
  data: {"step": "semantic_analysis", "status": "running | success | failed", "content": "..."}
  ```
  固定步驟依序為 `semantic_analysis` → `vector_search` → （視情況插入 `attachment_extraction`，見下） → （視情況插入分批摘要步驟，見下） → `llm_thinking` → `conclusion`；`status` 為 `running`、`success`、`failed` 或（`conclusion` 步驟固定送出一次）`pending`。
  **`attachment_extraction`（擷取附件內容）動態步驟【新增，2026-07-06】**：僅當 `search_type == "semantic_hybrid_attachment"` 且 `params.read_attachment_content == true` 且本次確實找到關聯附件時，會在 `vector_search` 之後、分批摘要判斷之前插入此步驟，`content` 逐一列出每個關聯附件的檔名、Token 數與**實際餵給 AI 的文字內容**，讓使用者能親眼確認 AI 實際讀取了哪些附件內容。此文字內容優先取自附件上傳時自動解析出的檔案實際內容（`Attachment.extracted_content`），僅在該檔案格式無法自動解析時才會退回使用者填寫的備註（`description`），並在內容旁註明來源（見第 14.1/14.3 節）；未勾選 `read_attachment_content` 或無關聯附件時完全不會出現。
  **分批摘要（Map-Reduce Context Summary）動態步驟**：當檢索出的上下文 token 數超過 `context_summarize_trigger_tokens` 門檻時，會在 `vector_search`（或 `attachment_extraction`，若有）之後、`llm_thinking` 之前動態插入以下步驟（筆數依實際分批數量而定，非固定）：
  * `context_summarize_r{N}_batch_{i}`：第 N 輪第 i 批的分批整理，`content` 附帶 `label` 欄位（如「第 1 輪・分批整理 1/3（3 個區塊，約 45000 tokens）」）與原始內容/整理結果預覽。
  * `context_summarize_r{N}_reduce`：第 N 輪把多份分批摘要合併成一份的步驟。
  * `context_summarize_error`：分批摘要過程中若呼叫 LLM 失敗（例如逾時），會發出此 `status: "failed"` 步驟並降級為使用原始未摘要內容繼續回答，不會中斷整個串流。
  * 未觸發分批摘要時（多數情況），這些步驟完全不會出現，行為與未加入此功能前相同。詳見 `docs/DevelopmentProcess/ContextMapReduceSummaryPlan.md`。`semantic_hybrid_attachment` 模式下，關聯附件的內容說明也會被當作額外區塊併入同一套 Bin-Packing/Map-Reduce 機制，共用同一個門檻與步驟事件，不需另外的門檻設定。
* **`event: chunk`** — LLM 輸出：
  ```
  event: chunk
  data: {"type": "reasoning | content | done", "content": "回答文字（done 事件無 content）"}
  ```
* **`event: sources`**（在 `chunk: done` 之前送出一次）：
  ```json
  {
    "sources": [
      {
        "chunk_id": "string",
        "content": "段落內容",
        "metadata": {
          "filename": "string", "page": 1, "section": "string",
          "chunk_index": 0, "tags": ["string"], "class": ["string"],
          "links_to": ["string"], "linked_attachments": ["string"]
        },
        "score": 0.85,
        "token_count": 512
      }
    ],
    "context_summary": {
      "total_tokens": 45000,
      "batch_count": 0,
      "rounds": 0,
      "was_summarized": false,
      "threshold_tokens": 50000
    },
    "attachments": [
      {
        "id": "string",
        "original_filename": "string",
        "description": "string",
        "download_url": "/api/attachments/{id}/download"
      }
    ]
  }
  ```
  `token_count`（各 chunk）與 `context_summary`（本次檢索的 token 總計與分批摘要統計）為新增欄位。`context_summary.batch_count`/`rounds` 只有在觸發分批摘要時才會大於 0；未觸發時 `was_summarized` 固定為 `false`。`metadata.linked_attachments` 與最外層 `attachments`（2026-07-06 新增）僅在 `search_type == "semantic_hybrid_attachment"` 且命中片段帶有關聯附件時才會非空，其餘四種查詢法固定為空陣列，見第 14 節。

### 3.2 GET `/api/rag/history` — 取得對話歷史 **[Stub]**
固定回傳 `{"total": 0, "items": []}`，不查詢資料庫，目前尚未串接任何 `chat_sessions` 持久化邏輯。

### 3.3 DELETE `/api/rag/history/{session_id}` — 刪除對話 **[Stub]**
固定回傳 `{"message": "刪除成功"}`，不執行任何刪除操作。

---

## 4. 向量搜尋與 Point 管理 API (§4.2)

### 4.1 POST `/api/retrieval/search` — 向量/混合/語義混合檢索
**Request Body**：
```json
{
  "query": "string",
  "knowledge_base_id": "string",
  "params": {
    "top_k": 8,
    "score_threshold": 0.4,
    "search_type": "vector | hybrid | semantic_hybrid",
    "hnsw_ef_search": 128,
    "filter_tags": ["string"],
    "filter_filename": "string",
    "disable_parent_merge": false
  }
}
```
**Response 200**：
```json
{
  "query": "string",
  "results": [
    {
      "chunk_id": "string",
      "content": "string",
      "metadata": {
        "filename": "string", "page": 1, "section": "string", "chunk_index": 0,
        "tags": ["string"], "class": ["string"], "parent_id": "string",
        "function_name": "string", "type": "string", "links_to": ["string"],
        "linked_attachments": ["string"]
      },
      "score": 0.95,
      "distance": 0.05
    }
  ],
  "elapsed_ms": 45,
  "semantic_json": null,
  "embeddings_input": null,
  "sparse_keywords": null,
  "query_vector_preview": null,
  "vector_size": null
}
```
錯誤：`400` 無效的 `knowledge_base_id` 格式、`404` 知識庫不存在、`500` 檢索失敗。

> `linked_attachments`（2026-07-06 新增）為 Point payload 的 `linked_attachments` 欄位透傳，內容為關聯的 `Attachment._id` 清單，見第 14 節。`search_type` 傳入 `semantic_hybrid_attachment` 時，此端點也會走雙階段關聯檢索（`search_similar_two_step`），但**不會**額外查詢 `Attachment` collection 或回傳附件下載資訊——附件的查詢與下載資訊組裝僅實作於 `POST /api/rag/chat`，此端點只透傳 `linked_attachments` id 陣列本身。

### 4.2 POST `/api/retrieval/semantic-hybrid-search` — 獨立語義混合搜尋
**描述**：與 `/search` 相同的 Request/Response 結構，但伺服器端強制 `search_type="semantic_hybrid"`，並會實際填入 `semantic_json`、`embeddings_input`、`sparse_keywords`、`query_vector_preview`、`vector_size` 欄位。
> 前一版文件提到的「metadata 會額外傳回 `text_content`」為錯誤描述，`RetrievalMetadata` 並無 `text_content` 欄位。

### 4.3 POST `/api/retrieval/query-transform` — Query 轉換測試
**Request Body**：
```json
{ "query": "string", "strategy": "rewrite | hyde", "knowledge_base_id": "string" }
```
**Response 200**：
```json
{ "original_query": "string", "transformed_query": "string", "strategy": "rewrite", "results": [ ] }
```
內部固定使用 `top_k=8`、`score_threshold=0.3`，不可由呼叫端調整。

### 4.4 POST `/api/retrieval/knowledge-bases/{knowledge_base_id}/points/batch-delete` — 批次刪除向量點
**Request Body**：
```json
{ "point_ids": ["uuid-1", "uuid-2"] }
```
**Response 200**：
```json
{ "message": "批次刪除成功", "deleted_count": 2 }
```

### 4.5 POST `/api/retrieval/knowledge-bases/{knowledge_base_id}/files/delete-by-filename` — 依檔名刪除庫內資料
**Request Body**：
```json
{ "filename": "your_file.pdf" }
```
**Response 200**：
```json
{ "message": "成功刪除檔案 'your_file.pdf'", "deleted_count": 25 }
```
> 欄位為 `deleted_count`，非前一版文件所寫的 `deleted_points_count`。

### 4.6 POST `/api/retrieval/knowledge-bases/{knowledge_base_id}/files/update-links` — 更新檔案關聯 (`links_to`) 【新增，前一版文件未收錄】
**描述**：批次將指定檔案（`filename`）底下所有向量點的 `links_to` payload 欄位覆蓋為指定清單，供雙階段關聯檢索使用。

**Request Body**：
```json
{ "filename": "string", "links_to": ["string"] }
```
**Response 200**：
```json
{ "message": "成功更新檔案 'string' 的關聯檔案", "updated_count": 12 }
```

### 4.7 POST `/api/retrieval/knowledge-bases/{knowledge_base_id}/files/update-attachments` — 更新檔案關聯附件 (`linked_attachments`)【新增，2026-07-06】
**描述**：比照 4.6 的 `update-links`，批次將指定檔案（`filename`）底下所有向量點的 `linked_attachments` payload 欄位覆蓋為指定的 `Attachment._id` 清單，供「語義混合附件查詢法」使用。詳見第 14 節。

**Request Body**：
```json
{ "filename": "string", "attachment_ids": ["string"] }
```
**Response 200**：
```json
{ "message": "成功更新檔案 'string' 的關聯附件", "updated_count": 12 }
```

---

## 5. 準確度評估 API (§4.3)

### 5.1 POST `/api/evaluation/datasets` — 上傳測試集
**Request Body**：
```json
{
  "name": "測試集名稱",
  "description": "string (選填)",
  "items": [
    { "question": "string", "ground_truth": "string", "relevant_contexts": ["string"] }
  ]
}
```
**Response（狀態碼 200，非 201）**：
```json
{ "dataset_id": "string", "name": "測試集名稱", "item_count": 1 }
```

### 5.2 GET `/api/evaluation/datasets` — 取得測試集列表【新增，前一版文件未收錄】
**Response 200**：
```json
{ "items": [ { "dataset_id": "string", "name": "string", "item_count": 1 } ] }
```

### 5.3 GET `/api/evaluation/datasets/{dataset_id}` — 取得特定測試集
**Response 200**：包含 `dataset_id`、`name`、`description`、`item_count`、`items`（含 `question`/`ground_truth`/`relevant_contexts`）。

### 5.4 PUT `/api/evaluation/datasets/{dataset_id}` — 修改測試集
**Request Body**：`name`（選填）、`description`（選填）、`items`（必填陣列）。
**Response 200**：
```json
{ "dataset_id": "string", "name": "string", "item_count": 1 }
```
> 回應**不是** `{"message": "更新成功"}`（前一版文件錯誤）。

### 5.5 POST `/api/evaluation/run` — 執行 RAG 評估跑分（SSE 串流）
**描述**：此端點回傳的是 **`text/event-stream`**，並非單次 JSON 回應（前一版文件誤植為「Response 200 JSON」）。且目前程式碼**固定只評估測試集的前 5 筆**（硬編碼上限）。

**Request Body**：
```json
{
  "dataset_id": "string",
  "knowledge_base_id": "string (選填)",
  "params": {
    "model": "string", "temperature": 0.3, "top_k": 5, "score_threshold": 0.7,
    "max_tokens": 1024, "search_type": "vector | hybrid | semantic_hybrid"
  }
}
```
**Response 事件**：
* `event: init` — `{"total": N, "dataset_name": "string"}`
* `event: progress` — `{"index": 0, "question": "string"}`（每題開始時）
* `event: item_done` — 單題詳細結果（含 `scores`）
* `event: result` — 最終結果 `{"report_id": "string", "summary": {...}, "details": [...]}`

`summary` 與 `details[].scores` 皆為四項指標：`faithfulness`、`answer_relevancy`、`context_precision`、`context_recall`。

### 5.6 GET `/api/evaluation/reports/{report_id}` — 取得評估報告詳情【新增，前一版文件未收錄】
**Response 200**：`{"report_id": "string", "summary": {...4項指標}, "details": [...]}`。

---

## 6. Prompt 測試、範本與歷史紀錄 API (§4.4)

### 6.1 POST `/api/prompt/generate` — 【Stub，尚未實作】
> 前一版文件描述此端點會接收 `context`/`question`/`system_prompt`/`user_prompt_template`/`params` 並以 SSE 串流回答，**這並非目前的實際行為**。目前程式碼中此路由**不接受任何 Request Body**，直接回傳固定 JSON `{"message": "Prompt generation stub."}`，非串流。實際具備完整生成能力的端點是 §6.3 的 `/api/prompt/ab-test`。

### 6.2 POST `/api/prompt/preview` — Prompt 渲染預覽
**Request Body**：
```json
{ "context": "string", "question": "string", "system_prompt": "string", "user_prompt_template": "string" }
```
**Response 200**：
```json
{ "rendered_system_prompt": "string", "rendered_user_prompt": "string", "total_estimated_tokens": 123 }
```

### 6.3 POST `/api/prompt/ab-test` — A/B 測試（SSE 串流）
**描述**：前一版文件誤植為「Response 200 回傳多個 Variant 的 answer」，實際上此端點回傳 **SSE 串流**（`ABTestResponse`/`ABTestResult` 這兩個 schema 定義存在但未被實際使用）。

**Request Body**：
```json
{
  "context": "string",
  "question": "string",
  "variants": [
    { "label": "A組-低溫", "system_prompt": "string", "user_prompt_template": "string", "params": { "temperature": 0.1 } }
  ]
}
```
**Response 事件**（依 variant `index` 分流）：
```
event: chunk
data: {"index": 0, "type": "reasoning | content | error | done", "content": "string", "elapsed_ms": 1500}
```

### 6.4 GET/POST/DELETE `/api/prompt/templates` — 提示詞範本管理
* **`GET`**：回傳 `TemplateResponse` 陣列（`id`、`name`、`system_prompt`、`user_prompt_template`、`is_default`、`created_at`），含系統預設種子範本。
* **`POST`**（201）：`{"name": "...", "system_prompt": "... (選填)", "user_prompt_template": "..."}`。
* **`DELETE /api/prompt/templates/{template_id}`**：`{"message": "範本刪除成功"}`，找不到回 404。

### 6.5 GET/POST/DELETE `/api/prompt/records` — A/B 測試歷史存檔
* **`GET`**：回傳 `RecordResponse` 陣列（依 `created_at` 遞減排序），`results` 欄位為未強型別的 `List[Dict]`。
* **`POST`**（201）：`name`、`system_prompt`、`user_prompt_template`、`context`、`question`、`results` 皆為必填（無選填欄位）。
* **`DELETE /api/prompt/records/{record_id}`**：`{"message": "歷史紀錄刪除成功"}`，找不到回 404。

---

## 7. Embedding 向量化、標籤與類別 API (§4.5)

### 7.1 POST `/api/embedding/upload` — 上傳文件
**Request (multipart/form-data)**：`file`。
**Response 200**：`{"file_id": "string", "filename": "string", "content": "string", "page_count": 1, "char_count": 123}`。

### 7.2 POST `/api/embedding/chunk` — 文本切分預覽
**Request Body**：
```json
{
  "file_id": "string (選填)",
  "filename": "string (選填，傳入以自動分流 4GL/4FD/Word/MD 客製切分)",
  "content": "文本內容",
  "params": {
    "chunk_size": 512,
    "chunk_overlap": 50,
    "separator": "\n\n",
    "chunk_mode": "standard | parent_child"
  }
}
```
**Response 200**：
```json
{
  "chunks": [
    {
      "index": 0, "content": "string", "token_count": 65, "char_count": 120,
      "start_char": 0, "end_char": 120,
      "metadata": { "parent_id": "uuid", "header_path": "H1 > H2", "parent_chunk_index_range": "0~4", "file_type": "docx" }
    }
  ],
  "total_chunks": 5,
  "avg_token_count": 60
}
```

### 7.3 POST `/api/embedding/vectorize` — 向量化寫入 Qdrant
**Request Body**：`chunks`（含 `index`/`content`/`metadata`）、`knowledge_base_id`、`embedding_model`（選填，預設 `Qwen3-Embedding-8B-Q8_0.gguf`）。
**Response 200**：
```json
{ "knowledge_base_id": "string", "inserted_count": 5, "embedding_model": "string", "elapsed_ms": 1200 }
```

### 7.4 POST `/api/embedding/vectorize-json` — 地端 AI 語義 JSON 匯入
**Request Body**：
```json
{
  "knowledge_base_id": "string",
  "items": [
    {
      "id": "string (點 ID)",
      "text_content": "原始內容",
      "embeddings_input": "用來生成密集向量的語義化文本",
      "metadata": { "classes": ["類別1"], "tags": ["標籤1"] },
      "sparse_keywords": ["關鍵字1", "關鍵字2"]
    }
  ]
}
```
> `classes`/`tags` 並非每個 item 的頂層欄位，而是放在 `metadata` 物件內（前一版文件誤植為頂層欄位）。
**Response 200**：`{"knowledge_base_id": "string", "inserted_count": 1, "embedding_model": "string", "elapsed_ms": 1200}`。

### 7.5 GET/POST `/api/embedding/tags` — 分類標籤管理
* **`GET`**：回傳純字串陣列 `["標籤1", "標籤2"]`（非物件包裝）。
* **`POST`**：`{"name": "新標籤"}` → 回傳建立的標籤名稱（純字串），重複建立回 400。

### 7.6 GET/POST `/api/embedding/classes` — 類別選項管理
與 7.5 相同結構，端點對象為類別選項。

---

## 8. 資料庫自訂匯入 API (§4.5)

### 8.1 GET/POST `/api/database-indexing/configs` — DB 連線設定檔管理
`GET`/`POST` 回傳 `DBConfigResponse`（`id`/`name`/`db_type`/`host`/`port`/`database`/`username`/`password`）。
> ⚠️ **安全性提醒**：`password` 目前以明文形式儲存於 MongoDB，並在 `GET`/`POST`/`PUT` 回應中原樣回傳，前端需自行注意遮罩顯示。

### 8.2 PUT/DELETE `/api/database-indexing/configs/{config_id}` — 編輯/刪除設定檔
`PUT` 為全欄位覆寫（與 `POST` 相同欄位皆必填）。`DELETE` 回傳 `{"message": "資料庫設定檔已刪除"}`。

### 8.3 POST `/api/database-indexing/test-connection` — 連線測試
**Request Body**：`{"db_type": "sqlserver | oracle", "host", "port", "database", "username", "password"}`（皆必填）。
**Response 200**：`{"status": "success", "message": "..."}`。

### 8.4 POST `/api/database-indexing/fetch-metadata` — 讀取樣品欄位與資料
**Request Body**：`config_id`（選填）或 `connection`（選填，二擇一）、`sql_query`（必填）。
**Response 200**：`{"columns": [...], "sample_row": {...}, "table_name": "string"}`。僅允許 `SELECT`/`WITH` 開頭語句，偵測到 `INSERT`/`UPDATE`/`DELETE`/`DROP`/`ALTER`/`CREATE`/`TRUNCATE`/`RENAME`/`MERGE`/`EXEC`/`EXECUTE`/`GRANT`/`REVOKE` 等關鍵字回 400。

### 8.5 POST `/api/database-indexing/ingest` — 執行資料庫向量化匯入
**Request Body**：
```json
{
  "knowledge_base_id": "string",
  "config_id": "string (或提供 connection)",
  "sql_query": "SELECT * FROM articles",
  "ingestion_mode": "natural_language | json",
  "one_chunk_per_row": true,
  "table_meaning": "公司技術文章表",
  "columns_config": {
    "title": { "enabled": true, "meaning": "標題" },
    "content": { "enabled": true, "meaning": "詳細內容" }
  }
}
```
> `ingestion_mode` 合法值為 `natural_language`（預設）與 `json`，**不是** `text`（前一版文件錯誤；傳入 `"text"` 不會匹配程式碼中 `== "json"` 的判斷，會被靜默當作 `natural_language` 處理）。

**Response 200**：`{"status": "success", "inserted_count": 150, "knowledge_base_id": "string", "elapsed_ms": 3200, "filename": "DB_IMPORT_{table_name}"}`；查無資料時回傳 `{"status": "...", "inserted_count": 0, "message": "...", "elapsed_ms": ...}`。

---

## 9. 知識庫管理 API

### 9.1 GET `/api/knowledge-bases` — 取得知識庫列表【新增，前一版文件未收錄】
**Response 200**：`{"items": [{"id", "name", "description", "chunk_count", "created_at"}]}`。

### 9.2 POST `/api/knowledge-bases` — 建立知識庫【新增，前一版文件未收錄】
**Request Body**：`{"name": "string", "description": "string (選填)"}`。
**Response 201**：`KnowledgeBaseItem`。同步建立 Qdrant collection `kb_{id}`；若 Qdrant 建立失敗會回滾並回 503。

### 9.3 DELETE `/api/knowledge-bases/{id}` — 刪除知識庫【新增，前一版文件未收錄】
**Response 200**：`{"message": "刪除成功"}`。同步刪除 MongoDB 紀錄與對應 Qdrant collection；`400` 無效 ID、`404` 找不到。

### 9.4 GET `/api/knowledge-bases/{id}/metadata` — 取得庫內檔案清單與結構化地圖
**Response 200**：
```json
{
  "filenames": ["report.pdf", "manual.docx"],
  "tags": ["標籤1"],
  "structured_metadata": [
    { "filename": "report.pdf", "class": ["類別1"], "tags": ["標籤1"], "links_to": ["manual.docx"] }
  ]
}
```
> 前一版文件寫的回應格式 `{"files": [...]}` 是錯誤的，實際沒有 `files` 這個鍵。

---

## 10. SQL Server 既有知識庫 API【新增，前一版文件完全未收錄】

### 10.1 GET `/api/sqlserver/articles` — 分頁查詢既有文章
**Query 參數**：`page`（預設 1）、`page_size`（預設 10，上限 100）、`search`（選填，標題模糊搜尋）。
**Response 200**：`{"items": [{"id", "title", "is_published", "is_public", "access_dept", "access_members", "access_level", "version_number", "created_by", "created_by_name", "created_at", "updated_at"}], "total": N}`。

### 10.2 POST `/api/sqlserver/import` — 匯入指定文章至知識庫
**Request Body**：`{"article_id": "string", "knowledge_base_id": "string", "chunk_size": 512, "chunk_overlap": 50, "separator": "\n\n"}`（後三者皆選填）。
**Response 200**：`{"knowledge_base_id": "string", "inserted_count": N, "elapsed_ms": N}`。文章內容以 `SQLServer_Article_{article_id}` 作為 Qdrant `filename` 寫入。

---

## 11. 人工回饋 API (§4.6)

### 11.1 DELETE `/api/feedback/{feedback_id}` — 刪除單筆回饋

### 11.2 POST `/api/feedback/batch-delete` — 批次刪除回饋
**Request Body**：`{"feedback_ids": ["id-1", "id-2"]}`
**Response 200**：`{"message": "成功刪除 2 筆回饋紀錄"}`

---

## 12. 共用錯誤回應格式
```json
{ "detail": "錯誤訊息描述", "error_code": "ERROR_CODE", "timestamp": "2026-07-02T10:00:00Z" }
```

---

## 13. 語義資料庫查詢法 API (Semantic DB Query)【新增，2026-07-03】

新增的檢索模式，讓 AI 依自然語言問題自動比對「查詢設定檔」、產生唯讀 SQL、查詢既有關聯式資料庫，並將結果交給主模型總結。完全獨立於既有 `vector`/`hybrid`/`semantic_hybrid`/`semantic_hybrid_feedback` 四種查詢法，兩者互不影響。

### 13.1 查詢設定檔 (DB Query Profile) CRUD

* `GET /api/ai-db-query/profiles?knowledge_base_id=` — 列出指定知識庫下的查詢設定檔。
* `POST /api/ai-db-query/profiles` — 建立設定檔。**Request Body**：`{"name", "database_config_id", "knowledge_base_id", "platform_description", "table_name", "table_purpose", "columns": [{"column_name", "enabled", "meaning", "max_length"}], "is_default" (選填，預設 false)}`。`is_default`（2026-07-03 新增）標記此設定檔為「必定查詢」：問題與任何設定檔都無明顯語意關聯時，此設定檔仍會被強制加入候選查詢清單，作為兜底機制。建立時會自動組合自然語言描述文字並產生向量，寫入 `knowledge_base_id` 對應 Qdrant collection（payload `source: "db_query_profile"`，並帶入 `is_default`）。
* `PUT /api/ai-db-query/profiles/{profile_id}` — 更新設定檔（全欄位覆寫，重新產生向量）。
* `DELETE /api/ai-db-query/profiles/{profile_id}` — 刪除設定檔（同步刪除 Mongo 紀錄與 Qdrant point）。

**Response（`DBQueryProfileResponse`）**：`{"id", "name", "database_config_id", "knowledge_base_id", "platform_description", "table_name", "table_purpose", "columns", "is_default", "composed_description"}`。

### 13.2 資料庫 Schema 探索（供前端下拉選單使用）

* `POST /api/ai-db-query/list-tables` — **Request**：`{"config_id"}`。**Response**：`{"tables": ["articles", ...]}`（SQL Server 讀 `INFORMATION_SCHEMA.TABLES`，Oracle 讀 `USER_TABLES`，純 schema 查詢不撈資料）。
* `POST /api/ai-db-query/list-columns` — **Request**：`{"config_id", "table_name"}`。**Response**：`{"columns": ["id", "title", ...]}`。

### 13.3 兩段式查詢執行

* `POST /api/ai-db-query/match-profiles` — 第 1-2 步：語義理解 + Profile 選擇。**Request**：`{"question", "knowledge_base_id" (選填), "score_threshold" (選填，目前未使用，保留供未來擴充), "limit" (預設 5)}`。`knowledge_base_id` 留空代表「不限定知識庫」，會將所有知識庫的查詢設定檔清單一併提供給 AI 判斷。**選擇機制（2026-07-03 由向量相似度門檻改版）**：後端會撈取候選範圍內（指定知識庫或全部知識庫）目前所有查詢設定檔的完整清單（名稱/表格/用途），交給地端 Instruct AI 依問題語意直接判斷需要用到哪幾個設定檔（可複選、可 0 個），而非依向量相似度分數門檻篩選——避免問題橫跨多張表格時只選到其中一個。標記 `is_default: true` 的設定檔（2026-07-03 新增）不論 AI 判斷結果為何，一律會被強制加入候選清單最前面，作為問題語意不明確時的兜底機制。**Response**：`{"candidates": [{"profile_id", "name", "table_name", "table_purpose", "score"}], "selection_reason"}`；`score` 為依 AI 回傳順序的遞減示意分數（非向量相似度），`selection_reason` 為 AI 說明為何選擇/不選擇這些設定檔的簡短理由；`candidates` 為空代表查無對應設定檔，前端應明確告知使用者，不可自動假設。**呼叫端行為**：指定 `knowledge_base_id` 時列出候選讓使用者選取；未指定（不限定知識庫）時因無預設範圍可供人工判斷取捨，呼叫端會依序執行前 `AI_DB_QUERY_MAX_PROFILES_PER_QUERY`（預設 3）個候選並合併結果（`rag.py`/`RetrievalTestView.vue` 皆採此邏輯）。
* `POST /api/ai-db-query/execute` — 第 3-5 步：使用者從候選中選定一個後才呼叫。**Request**：`{"question", "profile_id", "max_rows" (選填，預設 `AI_DB_QUERY_MAX_ROWS`), "max_chars" (選填，預設 `AI_DB_QUERY_MAX_CHARS`)}`。**Response**：`{"profile_id", "profile_name", "generated_sql", "row_count", "context_text", "elapsed_ms"}`。SQL 產生時會被要求對文字欄位使用 `LIKE '%關鍵字%'` 模糊比對並以 `OR` 串接多個關鍵字/欄位（而非 `=` 完全比對疊加 `AND`），並盡量 `SELECT` 完整的啟用欄位而非單一欄位，以提高命中率與後續摘要判斷相關性所需的上下文；產生後一律重跑既有 `validate_sql_query()`（只准 `SELECT`/`WITH`），執行失敗或驗證失敗回 400，不重試硬猜。

### 13.4 三處測試整合方式

* `POST /api/rag/chat`：`params.search_type = "semantic_db_query"` 時走此查詢法。**兩階段串流**：第一次請求（未帶 `selected_db_profile_id`）在指定知識庫時僅回傳 SSE `step: "profile_candidates"` 事件（`content.candidates`）後即結束串流，前端顯示候選清單，使用者選定後帶 `selected_db_profile_id` 重新呼叫同一端點才會真正產生 SQL、查詢並讓主模型總結；未指定知識庫（不限定知識庫）時則在同一次請求中依序對前 N 個候選產生 SQL、查詢、合併結果後直接交給主模型總結，不中斷等待選擇。摘要階段使用專屬於 `semantic_db_query` 的 System Prompt（強調內容是真實資料庫查詢結果、不套用文件段落引用格式），與其餘四種查詢法的摘要 Prompt 分開、互不影響。
* `GET/POST` 檢索測試頁：前端直接呼叫 13.3 的 `match-profiles`/`execute`，不經過 `/api/retrieval/search`（回應格式與一般 chunk 檢索不同）。
* `POST /api/evaluation/run`：`params.search_type = "semantic_db_query"` 時，因批次評估無真人可選候選，自動取 AI 選擇結果中排序最高的候選（Top-1）執行，`EvalDetail.db_query_note` 會標記「自動選取設定檔（非人工確認）」或失敗原因。

---

## 14. 附件管理與語義混合附件查詢法 (Attachment / Semantic Hybrid Attachment Search)【新增，2026-07-06】

新增的檢索模式 `semantic_hybrid_attachment`，讓使用者可上傳附件檔案並關聯到已向量化的文件；語義混合檢索命中該文件時，自動在回答中附上附件下載點，並可選擇讓 AI 讀取附件的**實際內容**納入摘要。附件本身**不**寫入 Qdrant 做向量搜尋，僅存 MongoDB metadata + 磁碟實體檔案（`backend/FileAttachments/`），詳細規劃見 `docs/DevelopmentProcess/AttachmentSemanticHybridSearchPlan.md`。完全獨立於既有 `vector`/`hybrid`/`semantic_hybrid`/`semantic_hybrid_feedback`/`semantic_db_query` 五種查詢法，互不影響。

### 14.1 附件 CRUD 與下載

* `POST /api/attachments/upload`（multipart/form-data）— **Request**：`file`（檔案本體）、`knowledge_base_id`、`description`（選填，使用者填寫的備註，僅供顯示參考）、`tags`（選填，逗號分隔字串）、`classes`（選填，逗號分隔字串）。上傳時：
  1. 以 `{uuid4().hex}{副檔名}` 重新編碼實體檔名落地於 `FILE_ATTACHMENTS_DIR`（預設 `FileAttachments/`），原始檔名完整保留於 MongoDB 供下載還原。
  2. **自動解析檔案實際內容**（2026-07-06 新增）：呼叫與 `POST /api/embedding/upload` 共用的 `DocumentParser.parse_file()`（支援 PDF/DOCX/DOC/DOTX/TXT/MD/4GL/4FD），成功則存入 `Attachment.extracted_content`；失敗（例如上傳了目前不支援解析的格式，如 xlsx/pptx/圖片）則記錄 `Attachment.extraction_error`，**不會**中斷上傳，附件仍可正常儲存與下載，AI 讀取附件內容時會改用 `description` 備援（見 14.3 節）。

  **Response**（`AttachmentResponse`）：`{"id", "knowledge_base_id", "original_filename", "description", "has_extracted_content", "extraction_error", "tags", "classes", "content_type", "size", "created_by", "created_at", "updated_at"}`。`has_extracted_content`（布林值）表示是否已成功自動解析出檔案實際內容；為節省清單回應大小，`extracted_content` 全文本身**不會**透過此 API 回傳。
* `GET /api/attachments?knowledge_base_id=` — 列出指定知識庫的附件清單。**Response**：`{"items": [AttachmentResponse, ...], "total": N}`。
* `DELETE /api/attachments/{id}` — 刪除附件的 MongoDB 紀錄與磁碟實體檔案。**不會**級聯清除其他文件 chunk 上 `linked_attachments` 欄位裡對此 id 的參照；`POST /api/rag/chat` 於 `semantic_hybrid_attachment` 模式讀取附件時，對已不存在的 id 會靜默略過（記錄 warning log，不中斷串流）。**Response**：`{"status": "success", "message": "..."}`。
* `GET /api/attachments/{id}/download` — 下載附件實體檔案，回應為 `FileResponse`（`Content-Disposition: attachment`，非 ASCII 檔名以 RFC 5987 `filename*=UTF-8''...` 編碼還原原始檔名）。**此端點與其他附件端點一樣需要 `Authorization: Bearer <token>`**；前端因無法透過 `window.open()` 夾帶此標頭，改用 `api.get(url, {responseType:'blob'})` 取得檔案後以 `URL.createObjectURL` + 暫時 `<a download>` 觸發下載（見 `frontend/src/services/attachmentService.js` 的 `download()`）。

### 14.2 文件↔附件關聯

比照既有 `links_to`（檔案↔檔案關聯）機制新增 `linked_attachments`（檔案↔附件關聯）：

* `POST /api/retrieval/knowledge-bases/{knowledge_base_id}/files/update-attachments`（見 §4.7）將指定檔案（`filename`）底下所有向量點的 `linked_attachments` payload 欄位批次覆蓋為指定的 `Attachment._id` 清單。
* `GET /api/knowledge-bases/{id}/metadata` 回傳的 `structured_metadata` 每筆項目新增 `linked_attachments: List[str]`（比照既有 `links_to` 的彙整方式）。
* Qdrant Point 的 `metadata.linked_attachments`／`RetrievalMetadata.linked_attachments` 見 §4.1 說明。

### 14.3 RAG 對話整合

`POST /api/rag/chat`：`params.search_type = "semantic_hybrid_attachment"` 時：
1. 檢索邏輯與 `semantic_hybrid` 完全相同（`search_similar_two_step` + `RerankService.rerank`），差異僅在於檢索完成後，收集命中片段 `linked_attachments` 中出現過的所有附件 id（去重），查詢對應的 `Attachment` MongoDB 紀錄。
2. 不論 `params.read_attachment_content` 是否勾選，找到的附件一律會放進最終 `event: sources` 的 `attachments` 陣列（見 §3.1），提供 `original_filename`/`description`/`download_url` 供前端顯示下載點。
3. 若 `params.read_attachment_content` 為 `true`：
   - 對每個附件呼叫 `_get_attachment_effective_text()`（`backend/routers/rag.py`）取得**實際餵給 AI 的文字**：優先使用上傳時自動解析出的 `extracted_content`；只有在該檔案格式無法自動解析（`extraction_error` 非空）時才退回 `description` 備註；兩者皆無則明確標示無可讀取內容，不假裝有內容可讀（2026-07-06 修正——先前版本誤用 `description` 作為主要來源，見 `docs/DevelopmentProcess/NewFeatures.md` 同日條目）。
   - 先送出 `attachment_extraction` 這組 SSE step（見 §3.1），逐一列出本次找到的每個附件的檔名、Token 數與上述實際內容，並註明內容來源（自動擷取或退回備註），讓使用者能親眼確認 AI 實際讀取了哪些附件內容（純顯示用途，不影響回答內容）。
   - 再把每筆附件的實際內容當作一個摘要區塊，併入既有的 Map-Reduce 分批摘要機制（`ContextSummarizerService.maybe_summarize`，與 `context_summarize_trigger_tokens` 共用同一套門檻與 SSE 步驟事件，見 §3.1 分批摘要說明），使其內容能影響最終回答。
   為 `false` 時完全不會送出 `attachment_extraction` 步驟，附件內容也不會進入 LLM context，只作為下載點呈現。
4. 目前僅 `POST /api/rag/chat` 實作了「附件查詢＋內容摘要」的完整流程。`POST /api/retrieval/search`（§4.1）雖然 `search_type` 傳入 `semantic_hybrid_attachment` 時也會走雙階段關聯檢索，但**不會**額外查詢 `Attachment` collection 或組出 `attachments`/下載資訊；`POST /api/evaluation/run` 與檢索測試頁目前尚未串接此查詢法。

---

## 15. 文件圖片擷取、描述與檢索 API (Document Image Extraction, Captioning & Retrieval) 【新增，2026-07-07】

提供 PDF 與 Word (docx/dotx) 文件的內嵌圖片擷取、多模態 LLM 圖片描述自動生成，以及檢索時的圖片關聯呈現。

### 15.1 POST `/api/embedding/upload` — 上傳文件 (擴充)
**Request (multipart/form-data)**：
* `file`: 檔案本體
* `extract_images`: 布林值 (選填，預設 `false`)。若為 `true`，上傳 PDF 或 Word 檔案時將自動抽取其內嵌圖片，並呼叫地端多模態 AI 自動描述圖片內容。

**Response 200**：
```json
{
  "file_id": "string",
  "filename": "string",
  "content": "string",
  "page_count": 1,
  "char_count": 123,
  "images": [
    {
      "image_filename": "img_uuid.png",
      "page": 1,
      "description": "圖片的詳細中文描述",
      "caption_failed": false
    }
  ]
}
```

### 15.2 GET `/api/embedding/images/{stored_filename}` — 讀取擷取之圖片
**描述**：取得上傳文件時所擷取的圖片實體，回應為 `FileResponse`，前端可用於 `<img>` src 顯示或下載。

**Response 200**：圖片二進位檔案。

### 15.3 POST `/api/embedding/chunk` — 文本切分預覽 (擴充)
**Request Body**：
```json
{
  "file_id": "string (選填)",
  "filename": "string (選填)",
  "content": "文本內容",
  "params": {
    "chunk_size": 512,
    "chunk_overlap": 50,
    "separator": "\n\n",
    "chunk_mode": "standard | parent_child"
  },
  "images": [
    {
      "image_filename": "img_uuid.png",
      "page": 1,
      "description": "圖片的詳細描述"
    }
  ]
}
```
**描述**：若傳入 `images` 陣列，切分器會將這些圖片描述轉換成獨立的圖片 Chunk，併入切分結果中。圖片 Chunk 的 `metadata.chunk_type` 為 `"image"`，且 `metadata.image_filename` 與 `metadata.page` 會被保留以供檢索。

### 15.4 檢索結果中圖片 Metadata 與呈現
在 RAG 對話或向量檢索中，命中類型為圖片的 Chunk 時，其 `metadata` 會包含以下欄位：
```json
{
  "chunk_type": "image",
  "image_filename": "img_uuid.png",
  "page": 1
}
```
前端可偵測 `chunk_type == "image"` 並顯示圖片縮圖，且可提供圖片下載功能。

