# API 測試指南 (API Testing Guide)

## 1. 文件資訊
* **專案名稱**：AiRAG 內部測試平台
* **文件版本**：V 1.2 (最新更新)
* **建立日期**：2026-06-18
* **更新日期**：2026-07-06
* **說明**：本指南為開發人員及 QA 測試工程師提供實用的 API 測試腳本與 cURL 指令，用以獨立驗證系統新舊端點。
* **基本設定**：
  * API Base URL: `http://localhost:8000/api`
  * 請預先呼叫登入 API 取得 Bearer Token，並在後續的 API Header 中帶入 `Authorization: Bearer <your_token>`。

---

## 2. 認證與準備工作

### 2.1 使用者登入取得 Token
```bash
curl -X POST "http://localhost:8000/api/auth/login" \
     -H "Content-Type: application/json" \
     -d "{\"username\": \"admin\", \"password\": \"your_password_hash_matching_env\"}"
```
*預期回傳*：
```json
{
  "access_token": "eyJhbG...",
  "token_type": "bearer",
  "expires_in": 86400
}
```
*備註*：將取得的 `access_token` 值導出為環境變數 `TOKEN`：
`export TOKEN="eyJhbG..."` (Linux/macOS) 或 `$TOKEN="eyJhbG..."` (PowerShell)。

---

## 3. §4.1 RAG 與 語義混合檢索測試

### 3.1 測試語義混合查詢 RAG 對話 (Stream SSE)
* **API 端點**：`POST /api/rag/chat`
```bash
curl -N -X POST "http://localhost:8000/api/rag/chat" \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "question": "公司特休天數如何計算？",
       "knowledge_base_id": "649c12e4f5b9d3118c8bcf2f",
       "chat_history": [],
       "params": {
         "search_type": "semantic_hybrid",
         "temperature": 0.2,
         "top_k": 5
       }
     }'
```
*預期串流內容*：
* 會先回傳 `event: step` 帶有 `semantic_analysis`（地端語義化 AI 解析提問出的 JSON）與 `vector_search`（召回來源，語義混合模式下為雙階段關聯檢索）。實際事件欄位為 `step`/`status`/`content`。
* 隨後以 `event: chunk` 串流輸出對答字元（`type: reasoning|content|done`）。
* `event: sources` 內每個 chunk 會附帶 `token_count`，並新增 `context_summary`（總計 token 數、是否觸發分批摘要、切分次數/輪數）。

### 3.1a 測試 Map-Reduce 分批摘要（Context 超長保護）
把 `top_k` 調高、`context_summarize_trigger_tokens` 調低，較容易在測試環境中人為觸發分批摘要（不需要真的準備超大知識庫）：
```bash
curl -N -X POST "http://localhost:8000/api/rag/chat" \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "question": "列出所有相關內容並詳細說明",
       "knowledge_base_id": "649c12e4f5b9d3118c8bcf2f",
       "chat_history": [],
       "params": {
         "search_type": "semantic_hybrid",
         "top_k": 50,
         "context_summarize_trigger_tokens": 2000
       }
     }'
```
*預期串流內容*：若召回的上下文 token 總數超過 `context_summarize_trigger_tokens`（此例故意調到很低的 2000 以方便觸發），會看到多個
`context_summarize_r1_batch_1`、`context_summarize_r1_batch_2`...、`context_summarize_r1_reduce` 等動態 `event: step`，
`content` 附帶分批的原始內容與整理結果；若某批呼叫 LLM 失敗，會看到 `context_summarize_error`（`status: failed`），
但串流仍會正常走到 `llm_thinking`/`conclusion`/`sources`/`chunk: done`，不會中斷。詳見 `docs/DevelopmentProcess/ContextMapReduceSummaryPlan.md`。

### 3.2 測試獨立語義混合檢索 (Semantic Hybrid Search)
* **API 端點**：`POST /api/retrieval/semantic-hybrid-search`
```bash
curl -X POST "http://localhost:8000/api/retrieval/semantic-hybrid-search" \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "query": "請假福利",
       "knowledge_base_id": "649c12e4f5b9d3118c8bcf2f",
       "params": {
         "top_k": 3,
         "score_threshold": 0.3
       }
     }'
```

---

## 4. §4.2 Qdrant Points 管理與過濾

### 4.1 取得特定知識庫已上傳檔案清單 (元資料)
* **API 端點**：`GET /api/knowledge-bases/{id}/metadata`
```bash
curl -X GET "http://localhost:8000/api/knowledge-bases/649c12e4f5b9d3118c8bcf2f/metadata" \
     -H "Authorization: Bearer $TOKEN"
```
*回傳範例*：`{"files": ["規則說明書.docx", "DB_IMPORT_articles"]}`

### 4.2 依據檔案名稱刪除向量點
* **API 端點**：`POST /api/retrieval/knowledge-bases/{kb_id}/files/delete-by-filename`
```bash
curl -X POST "http://localhost:8000/api/retrieval/knowledge-bases/649c12e4f5b9d3118c8bcf2f/files/delete-by-filename" \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"filename": "規則說明書.docx"}'
```

### 4.3 批次指定 Point ID 永久刪除
* **API 端點**：`POST /api/retrieval/knowledge-bases/{kb_id}/points/batch-delete`
```bash
curl -X POST "http://localhost:8000/api/retrieval/knowledge-bases/649c12e4f5b9d3118c8bcf2f/points/batch-delete" \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"point_ids": ["c0a80101-0000-0000-0000-000000000001", "c0a80101-0000-0000-0000-000000000002"]}'
```

---

## 5. §4.5 資料庫自訂匯入與向量化 (Database Indexing)

### 5.1 測試資料庫連線
* **API 端點**：`POST /api/database-indexing/test-connection`
```bash
curl -X POST "http://localhost:8000/api/database-indexing/test-connection" \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "db_type": "sqlserver",
       "host": "10.10.130.220",
       "port": 1433,
       "database": "ERP_DB",
       "username": "sa",
       "password": "your_db_password"
     }'
```

### 5.2 讀取資料庫 SQL 查詢預覽與安全限制
* **API 端點**：`POST /api/database-indexing/fetch-metadata`
```bash
curl -X POST "http://localhost:8000/api/database-indexing/fetch-metadata" \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "connection": {
         "db_type": "sqlserver",
         "host": "10.10.130.220",
         "port": 1433,
         "database": "ERP_DB",
         "username": "sa",
         "password": "your_db_password"
       },
       "sql_query": "SELECT TOP 1 ITEM_ID, ITEM_NAME, SPEC FROM dbo.products"
     }'
```
*備註：若查詢語句中包含 `INSERT` 或 `DROP` 等寫入指令，系統將拋出 `400 Bad Request` 唯讀安全攔截錯誤。*

### 5.3 執行一鍵資料庫匯入向量化 (DB Ingest)
* **API 端點**：`POST /api/database-indexing/ingest`
```bash
curl -X POST "http://localhost:8000/api/database-indexing/ingest" \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "knowledge_base_id": "649c12e4f5b9d3118c8bcf2f",
       "connection": {
         "db_type": "sqlserver",
         "host": "10.10.130.220",
         "port": 1433,
         "database": "ERP_DB",
         "username": "sa",
         "password": "your_db_password"
       },
       "sql_query": "SELECT ITEM_ID, ITEM_NAME, SPEC FROM dbo.products",
       "ingestion_mode": "natural_language",
       "one_chunk_per_row": true,
       "table_meaning": "ERP 品號規格對照表",
       "columns_config": {
         "ITEM_ID": { "enabled": true, "meaning": "品號" },
         "ITEM_NAME": { "enabled": true, "meaning": "品名" },
         "SPEC": { "enabled": true, "meaning": "規格描述" }
       }
     }'
```

---

## 6. §4.4 Prompt 範本與 A/B 測試歷史管理

### 6.1 獲取所有 Prompt 範本 (包含系統預設)
* **API 端點**：`GET /api/prompt/templates`
```bash
curl -X GET "http://localhost:8000/api/prompt/templates" \
     -H "Authorization: Bearer $TOKEN"
```

### 6.2 儲存 A/B 測試歷史紀錄
* **API 端點**：`POST /api/prompt/records`
```bash
curl -X POST "http://localhost:8000/api/prompt/records" \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "name": "請假規則 A/B 測試 - 2026-06-30",
       "system_prompt": "你是一個專業助手...",
       "user_prompt_template": "根據：\n{context}\n回答問題：{question}",
       "context": "說明書內容...",
       "question": "事假怎麼請？",
       "results": [
         {
           "label": "A組 - 低溫",
           "answer": "回答內容...",
           "params": { "temperature": 0.1 },
           "elapsed_ms": 1200
         }
       ]
     }'
```

---

## 7. §4.5 標籤與類別選項動態配置

### 7.1 建立與查詢分類標籤 (Tags)
* **建立** (`POST /api/embedding/tags`)：
  ```bash
  curl -X POST "http://localhost:8000/api/embedding/tags" \
       -H "Authorization: Bearer $TOKEN" \
       -H "Content-Type: application/json" \
       -d '{"name": "機密等級A"}'
  ```
* **查詢** (`GET /api/embedding/tags`)：
  ```bash
  curl -X GET "http://localhost:8000/api/embedding/tags" \
       -H "Authorization: Bearer $TOKEN"
  ```
