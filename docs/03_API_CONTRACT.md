# API 合約文件 (API Contract)

## 1. 文件資訊
* **專案名稱**：AiRAG 內部測試平台
* **文件版本**：V 1.1 (最新更新)
* **建立日期**：2026-06-18
* **更新日期**：2026-06-30
* **Base URL**：`http://<host>:8000/api`
* **認證方式**：JWT Bearer Token（除 `/api/auth/login` 外，所有 API 需帶 `Authorization: Bearer <token>`）

---

## 2. 認證 API (Auth)

### 2.1 POST `/api/auth/login` — 使用者登入
**描述**：驗證帳號密碼，回傳 JWT Token。

**Request Body**：
```json
{
  "username": "admin",
  "password": "your_password"
}
```

**Response 200**：
```json
{
  "access_token": "string (JWT)",
  "token_type": "bearer",
  "expires_in": 86400
}
```

---

## 3. RAG 功能測試 API (§4.1)

### 3.1 POST `/api/rag/chat` — RAG 對話（SSE 串流）
**描述**：端到端 RAG 對話，支援 `vector`、`hybrid` 與 `semantic_hybrid` 三種模式，透過 SSE 串流回傳執行步驟與 LLM 回答。

**Request Body**：
```json
{
  "question": "string",
  "knowledge_base_id": "string (PydanticObjectId)",
  "chat_history": [
    { "role": "user", "content": "string" },
    { "role": "assistant", "content": "string" }
  ],
  "params": {
    "model": "Qwen3.6-35B-A3B-FP8",
    "temperature": 0.7,
    "top_p": 0.9,
    "max_tokens": 2048,
    "top_k": 5,
    "score_threshold": 0.7,
    "search_type": "vector | hybrid | semantic_hybrid"
  }
}
```

**Response**：`text/event-stream` (SSE)
* **管道進度步驟 (event: step)**:
  ```
  event: step
  data: {"event": "semantic_analysis", "detail": "結構化 JSON 字串..."}
  
  event: step
  data: {"event": "retrieval", "detail": "向量檢索完成，召回 5 筆段落..."}
  ```
* **回答字元 (event: chunk)**:
  ```
  event: chunk
  data: {"content": "回答文字", "type": "content"}
  ```
* **引用的來源 (event: sources)**:
  ```
  event: sources
  data: {
    "sources": [
      {
        "chunk_id": "string",
        "content": "段落內容",
        "metadata": { "filename": "string", "page": 1 },
        "score": 0.85
      }
    ]
  }
  ```

### 3.2 GET `/api/rag/history` — 取得對話歷史
**Response 200**：
```json
{
  "total": 10,
  "items": [
    {
      "id": "string",
      "title": "對話標題",
      "created_at": "2026-06-30T10:00:00Z"
    }
  ]
}
```

### 3.3 DELETE `/api/rag/history/{session_id}` — 刪除對話
**Response 200**：
```json
{ "message": "刪除成功" }
```

---

## 4. 向量搜尋與 Point 管理 API (§4.2)

### 4.1 POST `/api/retrieval/search` — 純向量/混合檢索
**描述**：僅執行向量搜尋，不呼叫 LLM。

**Request Body**：
```json
{
  "query": "string",
  "knowledge_base_id": "string",
  "params": {
    "top_k": 5,
    "score_threshold": 0.5,
    "search_type": "vector | hybrid"
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
      "metadata": { "filename": "string", "page": 1, "class": ["string"] },
      "score": 0.95,
      "distance": 0.05
    }
  ],
  "elapsed_ms": 45
}
```

### 4.2 POST `/api/retrieval/semantic-hybrid-search` — 獨立語義混合搜尋
**描述**：獨立執行語義混合搜尋，不呼叫對話模型，回傳檢索結果。

**Request Body**：同 4.1。

**Response 200**：同 4.1 (其中 metadata 會額外傳回包含原始 `text_content`)。

### 4.3 POST `/api/retrieval/query-transform` — Query 轉換測試
**Request Body**：
```json
{
  "query": "string",
  "strategy": "rewrite | hyde",
  "knowledge_base_id": "string"
}
```

**Response 200**：
```json
{
  "original_query": "string",
  "transformed_query": "string",
  "strategy": "rewrite",
  "results": [...]
}
```

### 4.4 POST `/api/retrieval/knowledge-bases/{knowledge_base_id}/points/batch-delete` — 批次刪除向量點
**描述**：根據 Point UUID 列表，批次刪除 Qdrant 向量點，並更新 MongoDB 知識庫 counts。

**Request Body**：
```json
{
  "point_ids": ["uuid-1", "uuid-2"]
}
```

**Response 200**：
```json
{ "message": "已成功刪除 2 筆向量資料" }
```

### 4.5 POST `/api/retrieval/knowledge-bases/{knowledge_base_id}/files/delete-by-filename` — 依檔名刪除庫內資料
**Request Body**：
```json
{
  "filename": "your_file.pdf"
}
```

**Response 200**：
```json
{
  "message": "成功刪除檔案 'your_file.pdf' 的所有相關向量",
  "deleted_points_count": 25
}
```

---

## 5. 準確度評估 API (§4.3)

### 5.1 POST `/api/evaluation/datasets` — 上傳測試集
**Request Body (JSON)**：
```json
{
  "name": "測試集名稱",
  "items": [
    {
      "question": "string",
      "ground_truth": "string",
      "relevant_contexts": ["string"]
    }
  ]
}
```

**Response 201**：
```json
{
  "dataset_id": "string",
  "name": "測試集名稱",
  "item_count": 1
}
```

### 5.2 GET `/api/evaluation/datasets/{dataset_id}` — 取得特定測試集
**Response 200**：包含 `items` 詳細陣列。

### 5.3 PUT `/api/evaluation/datasets/{dataset_id}` — 修改測試集
**Request Body**：同 5.1。

**Response 200**：
```json
{ "message": "更新成功" }
```

### 5.4 POST `/api/evaluation/run` — 執行 RAG 評估跑分
**Response 200**：回傳包含 summary 與四項指標 (faithfulness, answer_relevancy, context_precision, context_recall) 的完整報告。

---

## 6. Prompt 測試、範本與歷史紀錄 API (§4.4)

### 6.1 POST `/api/prompt/generate` — 手動注入 Context 對話 (SSE)
**Request Body**：
```json
{
  "context": "手動貼上或引用的 Context",
  "question": "問題",
  "system_prompt": "System Prompt 內容",
  "user_prompt_template": "根據：\n{context}\n回答問題：{question}",
  "params": {
    "model": "Qwen3.6-35B-A3B-FP8",
    "temperature": 0.7
  }
}
```

**Response**：`text/event-stream`。

### 6.2 POST `/api/prompt/preview` — Prompt 渲染預覽
**Response 200**：回傳組合後的 `rendered_system_prompt`、`rendered_user_prompt` 與 Token 估算。

### 6.3 POST `/api/prompt/ab-test` — A/B 測試
**Request Body**：傳入 context、question 與 variants 陣列。
**Response 200**：回傳多個 Variant 的 answer 與執行時間。

### 6.4 GET/POST/DELETE `/api/prompt/templates` — 提示詞範本管理
* **`GET`**：取得範本列表（包含系統預設範本與自訂範本）。
* **`POST`** (建立範本)：
  * Request Body: `{"name": "...", "system_prompt": "...", "user_prompt_template": "..."}`
* **`DELETE /api/prompt/templates/{template_id}`**：刪除自訂範本。

### 6.5 GET/POST/DELETE `/api/prompt/records` — A/B 測試歷史存檔
* **`GET`**：取得測試歷史列表。
* **`POST`** (保存歷史紀錄)：
  * Request Body: 包含 A/B 測試的 template、參數、question、variant 回答、耗時等。
* **`DELETE /api/prompt/records/{record_id}`**：刪除歷史紀錄。

---

## 7. Embedding 向量化、標籤與類別 API (§4.5)

### 7.1 POST `/api/embedding/upload` — 上傳文件
**Request (multipart/form-data)**：傳入 `file` (PDF/Word/TXT/MD 等)。
**Response 200**：回傳解析後的純文字與字元數、頁數。

### 7.2 POST `/api/embedding/chunk` — 文本切分預覽
**Request Body**：
```json
{
  "filename": "string (選填，傳入以自動分流 4GL/4FD/Word/MD 客製切分)",
  "content": "文本內容",
  "params": {
    "chunk_size": 250,
    "chunk_overlap": 50,
    "chunk_mode": "standard | parent_child"
  }
}
```

**Response 200**：
```json
{
  "chunks": [
    {
      "index": 0,
      "content": "Child Chunk 內容",
      "token_count": 65,
      "char_count": 120,
      "metadata": {
        "parent_id": "uuid",
        "header_path": "Header1 > Header2",
        "parent_chunk_index_range": "0~4",
        "file_type": "docx"
      }
    }
  ],
  "total_chunks": 5
}
```

### 7.3 POST `/api/embedding/vectorize` — 向量化寫入 Qdrant
**Request Body**：傳入 chunks 陣列（含 metadata 如 classes、tags 陣列）與知識庫 ID。

**Response 200**：
```json
{
  "knowledge_base_id": "string",
  "inserted_count": 5
}
```

### 7.4 POST `/api/embedding/vectorize-json` — 地端 AI 語義 JSON 匯入
**Request Body**：
```json
{
  "knowledge_base_id": "string",
  "items": [
    {
      "id": "string (點 ID)",
      "embeddings_input": "用來生成密集向量的語義化文本",
      "text_content": "原始內容",
      "sparse_keywords": ["關鍵字1", "關鍵字2"],
      "classes": ["類別1"],
      "tags": ["標籤1"]
    }
  ]
}
```

**Response 200**：
```json
{
  "knowledge_base_id": "string",
  "inserted_count": 1,
  "elapsed_ms": 1200
}
```

### 7.5 GET/POST `/api/embedding/tags` — 分類標籤管理
* **`GET`**：取得 MongoDB 的動態標籤列表。
* **`POST`**: 傳入 `{"name": "新標籤"}` 建立標籤。

### 7.6 GET/POST `/api/embedding/classes` — 類別選項管理
* **`GET`**：取得 MongoDB 的動態類別列表。
* **`POST`**: 傳入 `{"name": "新類別"}` 建立類別。

---

## 8. 資料庫自訂匯入 API (§4.5)

### 8.1 GET/POST `/api/database-indexing/configs` — DB 連線設定檔管理
* **`GET`**：取得所有已存的 DB 連線設定（IP、Port、DB、帳密）。
* **`POST`**：建立新的連線設定檔。

### 8.2 PUT/DELETE `/api/database-indexing/configs/{config_id}` — 編輯/刪除設定檔

### 8.3 POST `/api/database-indexing/test-connection` — 連線測試
**Request Body**：
```json
{
  "db_type": "sqlserver | oracle",
  "host": "10.10.130.220",
  "port": 1433,
  "database": "ERP_DB",
  "username": "user",
  "password": "pwd"
}
```

**Response 200**：
```json
{ "status": "success", "message": "資料庫連線測試成功" }
```

### 8.4 POST `/api/database-indexing/fetch-metadata` — 讀取樣品欄位與資料
**描述**：驗證 SQL 唯讀安全限制，並回傳欄位清單與第一筆資料預覽。

**Request Body**：
```json
{
  "config_id": "string (或提供連線詳細資訊 connection)",
  "sql_query": "SELECT TOP 1 * FROM articles"
}
```

**Response 200**：
```json
{
  "columns": ["id", "title", "content"],
  "sample_row": { "id": 1, "title": "樣品標題", "content": "..." },
  "table_name": "articles"
}
```

### 8.5 POST `/api/database-indexing/ingest` — 執行資料庫向量化匯入
**描述**：由資料庫提取所有列，根據對照公式將資料欄位拼接為自然語言或 JSON 字串，分批（每批 20 筆）進行密集向量化寫入 Qdrant。支援覆蓋刪除同名舊資料（`DB_IMPORT_{table_name}`）。

**Request Body**：
```json
{
  "knowledge_base_id": "string",
  "config_id": "string",
  "sql_query": "SELECT * FROM articles",
  "ingestion_mode": "text | json",
  "one_chunk_per_row": true,
  "table_meaning": "公司技術文章表",
  "columns_config": {
    "title": { "enabled": true, "meaning": "標題" },
    "content": { "enabled": true, "meaning": "詳細內容" }
  }
}
```

**Response 200**：
```json
{
  "status": "success",
  "inserted_count": 150,
  "knowledge_base_id": "string",
  "elapsed_ms": 3200,
  "filename": "DB_IMPORT_articles"
}
```

---

## 9. 知識庫與檔案元資料 API

### 9.1 GET `/api/knowledge-bases/{id}/metadata` — 取得庫內檔案清單
**描述**：用於向量搜尋頁面中，依知識庫動態列出唯一的檔案名稱，方便進行篩選。

**Response 200**：
```json
{
  "files": ["report.pdf", "manual.docx", "DB_IMPORT_articles"]
}
```

---

## 10. 人工回饋 API (§4.6)

### 10.1 DELETE `/api/feedback/{feedback_id}` — 刪除單筆回饋

### 10.2 POST `/api/feedback/batch-delete` — 批次刪除回饋
**Request Body**：
```json
{
  "feedback_ids": ["id-1", "id-2"]
}
```

**Response 200**：
```json
{ "message": "成功刪除 2 筆回饋紀錄" }
```

---

## 11. 共用錯誤回應格式
所有 API 錯誤回應均維持標準格式：
```json
{
  "detail": "錯誤訊息描述",
  "error_code": "ERROR_CODE",
  "timestamp": "2026-06-30T10:00:00Z"
}
```
