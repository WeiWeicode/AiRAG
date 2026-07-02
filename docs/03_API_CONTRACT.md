# API 合約文件 (API Contract)

## 1. 文件資訊
* **專案名稱**：AiRAG 內部測試平台
* **文件版本**：V 1.2（依實際程式碼校正）
* **建立日期**：2026-06-18
* **更新日期**：2026-07-02
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
**描述**：端到端 RAG 對話，支援 `vector`、`hybrid`、`semantic_hybrid` 三種模式。當 `search_type == "semantic_hybrid"` 時，實際呼叫的是**雙階段關聯檢索** `search_similar_two_step`（見 `02_ARCHITECTURE.md` §5.1），而非單純的雙路混合搜尋。

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
    "search_type": "vector | hybrid | semantic_hybrid"
  }
}
```
> 注意：`params` 內**沒有** `top_p` 欄位（此為前一版文件的錯誤）。上方數值為程式碼中未帶入時使用的預設值。

**Response**：`text/event-stream` (SSE)，事件如下（實際欄位為 `step` / `status` / `content`，並非 `event` / `detail`）：

* **`event: step`** — 管道進度：
  ```
  event: step
  data: {"step": "semantic_analysis", "status": "running | success | failed", "content": "..."}
  ```
  `step` 依序為 `semantic_analysis` → `vector_search` → `llm_thinking` → `conclusion`；`status` 為 `running`、`success`、`failed` 或（`conclusion` 步驟固定送出一次）`pending`。
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
          "links_to": ["string"]
        },
        "score": 0.85
      }
    ]
  }
  ```

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
        "function_name": "string", "type": "string", "links_to": ["string"]
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
