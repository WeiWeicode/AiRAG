# API 合約文件 (API Contract)

## 1. 文件資訊
* **專案名稱**：AiRAG 內部測試平台
* **文件版本**：V 1.0
* **建立日期**：2026-06-18
* **Base URL**：`http://<host>:8000/api`
* **認證方式**：JWT Bearer Token（除 `/api/auth/login` 外，所有 API 需帶 `Authorization: Bearer <token>`）

---

## 2. 認證 API (Auth)

### 2.1 POST `/api/auth/login` — 使用者登入

**描述**：驗證帳號密碼，回傳 JWT Token。

**Request Body**：
```json
{
  "username": "string",
  "password": "string"
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

**Response 401**：
```json
{
  "detail": "帳號或密碼錯誤"
}
```

---

## 3. RAG 功能測試 API (§4.1)

### 3.1 POST `/api/rag/chat` — RAG 對話（SSE 串流）

**描述**：端到端 RAG 對話，透過 SSE 串流回傳 LLM 回答。

**Request Body**：
```json
{
  "question": "string",
  "knowledge_base_id": "string (UUID)",
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
    "score_threshold": 0.7
  }
}
```

**Response**：`text/event-stream` (SSE)
```
event: chunk
data: {"content": "部分回答文字", "type": "content"}

event: chunk
data: {"content": "", "type": "done"}

event: sources
data: {
  "sources": [
    {
      "chunk_id": "string",
      "content": "Chunk 內容",
      "metadata": {
        "filename": "string",
        "page": 1,
        "section": "string"
      },
      "score": 0.92
    }
  ]
}
```

### 3.2 GET `/api/rag/history` — 取得對話歷史

**Query Parameters**：
| 參數 | 類型 | 必填 | 說明 |
|:---|:---|:---:|:---|
| `page` | int | 否 | 頁碼，預設 1 |
| `page_size` | int | 否 | 每頁筆數，預設 20 |

**Response 200**：
```json
{
  "total": 50,
  "items": [
    {
      "id": "string (UUID)",
      "question": "string",
      "answer": "string",
      "sources": [...],
      "params": {...},
      "created_at": "2026-06-18T10:00:00Z"
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

## 4. 向量搜尋測試 API (§4.2)

### 4.1 POST `/api/retrieval/search` — 純向量檢索

**描述**：僅執行向量搜尋，不呼叫 LLM。

**Request Body**：
```json
{
  "query": "string",
  "knowledge_base_id": "string (UUID)",
  "params": {
    "top_k": 10,
    "score_threshold": 0.5,
    "search_type": "vector | hybrid",
    "hnsw_ef_search": 128
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
      "content": "Chunk 完整內容",
      "metadata": {
        "filename": "string",
        "page": 1,
        "section": "string",
        "chunk_index": 3
      },
      "score": 0.95,
      "distance": 0.05
    }
  ],
  "elapsed_ms": 123
}
```

### 4.2 POST `/api/retrieval/query-transform` — Query 轉換測試

**描述**：測試 Query Rewriting 或 HyDE 策略。

**Request Body**：
```json
{
  "query": "string",
  "strategy": "rewrite | hyde",
  "knowledge_base_id": "string (UUID)"
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

---

## 5. 準確度評估 API (§4.3)

### 5.1 POST `/api/evaluation/datasets` — 上傳測試集

**描述**：上傳或建立測試集。

**Request Body** (`multipart/form-data` 或 JSON)：
```json
{
  "name": "string",
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
  "dataset_id": "string (UUID)",
  "name": "string",
  "item_count": 50,
  "created_at": "2026-06-18T10:00:00Z"
}
```

### 5.2 GET `/api/evaluation/datasets` — 取得測試集列表

**Response 200**：
```json
{
  "items": [
    {
      "dataset_id": "string (UUID)",
      "name": "string",
      "item_count": 50,
      "created_at": "2026-06-18T10:00:00Z"
    }
  ]
}
```

### 5.3 POST `/api/evaluation/run` — 執行評估

**描述**：對指定測試集執行批次評估，回傳評分報告。

**Request Body**：
```json
{
  "dataset_id": "string (UUID)",
  "knowledge_base_id": "string (UUID)",
  "params": {
    "model": "Qwen3.6-35B-A3B-FP8",
    "temperature": 0.3,
    "top_k": 5
  }
}
```

**Response 200**：
```json
{
  "report_id": "string (UUID)",
  "dataset_id": "string (UUID)",
  "summary": {
    "faithfulness": 0.85,
    "answer_relevancy": 0.90,
    "context_precision": 0.78,
    "context_recall": 0.82
  },
  "details": [
    {
      "question": "string",
      "generated_answer": "string",
      "ground_truth": "string",
      "scores": {
        "faithfulness": 0.9,
        "answer_relevancy": 0.85,
        "context_precision": 0.8,
        "context_recall": 0.75
      }
    }
  ],
  "created_at": "2026-06-18T10:30:00Z"
}
```

### 5.4 GET `/api/evaluation/reports/{report_id}` — 取得評估報告

**Response 200**：同 5.3 Response 結構。

### 5.5 GET `/api/evaluation/reports/{report_id}/export` — 匯出報告

**Query Parameters**：
| 參數 | 類型 | 必填 | 說明 |
|:---|:---|:---:|:---|
| `format` | string | 是 | `csv` 或 `json` |

**Response 200**：檔案下載 (`application/octet-stream`)

---

## 6. Prompt 測試 API (§4.4)

### 6.1 POST `/api/prompt/generate` — 自訂 Context 生成

**描述**：手動注入 Context，測試 LLM 生成能力（SSE 串流）。

**Request Body**：
```json
{
  "context": "string (手動貼上的 Context)",
  "question": "string",
  "system_prompt": "string (System Prompt 模板)",
  "user_prompt_template": "根據以下資訊回答：\n{context}\n\n問題：{question}",
  "params": {
    "model": "Qwen3.6-35B-A3B-FP8",
    "temperature": 0.7,
    "top_p": 0.9,
    "max_tokens": 2048
  }
}
```

**Response**：`text/event-stream` (SSE)，格式同 §3.1。

### 6.2 POST `/api/prompt/preview` — Prompt 變數替換預覽

**描述**：預覽最終組合的完整 Prompt，不呼叫 LLM。

**Request Body**：
```json
{
  "context": "string",
  "question": "string",
  "system_prompt": "string",
  "user_prompt_template": "string"
}
```

**Response 200**：
```json
{
  "rendered_system_prompt": "string",
  "rendered_user_prompt": "string",
  "total_estimated_tokens": 1500
}
```

### 6.3 POST `/api/prompt/ab-test` — 多參數 A/B 測試

**描述**：以不同參數組合同時生成回答進行比較。

**Request Body**：
```json
{
  "context": "string",
  "question": "string",
  "variants": [
    {
      "label": "低溫度",
      "system_prompt": "string",
      "user_prompt_template": "string",
      "params": { "temperature": 0.1, "top_p": 0.9, "max_tokens": 2048 }
    },
    {
      "label": "高溫度",
      "system_prompt": "string",
      "user_prompt_template": "string",
      "params": { "temperature": 0.9, "top_p": 0.9, "max_tokens": 2048 }
    }
  ]
}
```

**Response 200**：
```json
{
  "results": [
    {
      "label": "低溫度",
      "answer": "string",
      "params": {...},
      "elapsed_ms": 2300
    },
    {
      "label": "高溫度",
      "answer": "string",
      "params": {...},
      "elapsed_ms": 2500
    }
  ]
}
```

---

## 7. Embedding 測試 API (§4.5)

### 7.1 POST `/api/embedding/upload` — 上傳文件

**描述**：上傳文件進行解析。

**Request** (`multipart/form-data`)：
| 欄位 | 類型 | 說明 |
|:---|:---|:---|
| `file` | File | PDF, DOCX, TXT, MD |

**Response 200**：
```json
{
  "file_id": "string (UUID)",
  "filename": "string",
  "content": "string (解析後純文字)",
  "page_count": 10,
  "char_count": 15000
}
```

### 7.2 POST `/api/embedding/chunk` — 文本切分

**描述**：對文件內容執行切分，回傳 Chunk 預覽。

**Request Body**：
```json
{
  "file_id": "string (UUID)",
  "content": "string (或直接貼上純文字)",
  "params": {
    "chunk_size": 512,
    "chunk_overlap": 50,
    "separator": "\n\n"
  }
}
```

**Response 200**：
```json
{
  "chunks": [
    {
      "index": 0,
      "content": "Chunk 內容",
      "token_count": 128,
      "char_count": 450,
      "start_char": 0,
      "end_char": 449
    }
  ],
  "total_chunks": 30,
  "avg_token_count": 120
}
```

### 7.3 POST `/api/embedding/vectorize` — 向量化並寫入 Qdrant

**描述**：將切分好的 Chunks 向量化並寫入測試用向量資料庫。

**Request Body**：
```json
{
  "chunks": [
    { "index": 0, "content": "string", "metadata": {} }
  ],
  "knowledge_base_id": "string (UUID)",
  "embedding_model": "Qwen3-Embedding-8B-Q8_0.gguf"
}
```

**Response 200**：
```json
{
  "knowledge_base_id": "string (UUID)",
  "inserted_count": 30,
  "embedding_model": "Qwen3-Embedding-8B-Q8_0.gguf",
  "elapsed_ms": 5000
}
```

---

## 8. 知識庫管理 API

### 8.1 GET `/api/knowledge-bases` — 取得知識庫列表

**Response 200**：
```json
{
  "items": [
    {
      "id": "string (UUID)",
      "name": "string",
      "description": "string",
      "chunk_count": 150,
      "created_at": "2026-06-18T10:00:00Z"
    }
  ]
}
```

### 8.2 POST `/api/knowledge-bases` — 建立知識庫

**Request Body**：
```json
{
  "name": "string",
  "description": "string"
}
```

**Response 201**：
```json
{
  "id": "string (UUID)",
  "name": "string",
  "description": "string",
  "created_at": "2026-06-18T10:00:00Z"
}
```

### 8.3 DELETE `/api/knowledge-bases/{id}` — 刪除知識庫

**Response 200**：
```json
{ "message": "刪除成功" }
```

---

## 9. 人工回饋 API (§4.6)

### 9.1 POST `/api/feedback` — 提交回饋標註

**描述**：對 AI 回答標記正確/不正確，並可填入正確答案。

**Request Body**：
```json
{
  "chat_message_id": "string (UUID)",
  "is_correct": false,
  "correct_answer": "string (當 is_correct=false 時填寫)",
  "error_type": "hallucination | incomplete | wrong_source | format_issue | other",
  "note": "string (備註，可選)"
}
```

**Response 201**：
```json
{
  "feedback_id": "string (UUID)",
  "chat_message_id": "string (UUID)",
  "is_correct": false,
  "error_type": "hallucination",
  "created_at": "2026-06-18T10:00:00Z"
}
```

### 9.2 GET `/api/feedback` — 取得回饋標註列表

**Query Parameters**：
| 參數 | 類型 | 必填 | 說明 |
|:---|:---|:---:|:---|
| `is_correct` | bool | 否 | 篩選正確/不正確 |
| `error_type` | string | 否 | 篩選錯誤類型 |
| `page` | int | 否 | 頁碼 |
| `page_size` | int | 否 | 每頁筆數 |

**Response 200**：
```json
{
  "total": 100,
  "items": [
    {
      "feedback_id": "string (UUID)",
      "question": "string",
      "ai_answer": "string",
      "is_correct": false,
      "correct_answer": "string",
      "error_type": "hallucination",
      "created_at": "2026-06-18T10:00:00Z"
    }
  ]
}
```

### 9.3 POST `/api/feedback/export-to-dataset` — 匯入測試集

**描述**：將不正確的回饋標註批次匯入 §4.3 的測試集。

**Request Body**：
```json
{
  "feedback_ids": ["string (UUID)"],
  "target_dataset_id": "string (UUID，可選，不填則建立新測試集)",
  "new_dataset_name": "string (當建立新測試集時)"
}
```

**Response 200**：
```json
{
  "dataset_id": "string (UUID)",
  "imported_count": 15,
  "message": "成功匯入 15 筆回饋至測試集"
}
```

### 9.4 GET `/api/feedback/export` — 匯出回饋紀錄

**Query Parameters**：
| 參數 | 類型 | 必填 | 說明 |
|:---|:---|:---:|:---|
| `format` | string | 是 | `csv` 或 `json` |

**Response 200**：檔案下載

---

## 10. 共用錯誤回應格式

所有 API 的錯誤回應統一格式：

```json
{
  "detail": "錯誤訊息描述",
  "error_code": "ERROR_CODE",
  "timestamp": "2026-06-18T10:00:00Z"
}
```

| HTTP 狀態碼 | 說明 |
|:---|:---|
| 400 | 請求格式錯誤 / 參數驗證失敗 |
| 401 | 未認證 / Token 過期 |
| 404 | 資源不存在 |
| 422 | 請求內容無法處理 |
| 500 | 伺服器內部錯誤 |
| 503 | 外部服務不可用 (vLLM / llama.cpp / Qdrant) |
