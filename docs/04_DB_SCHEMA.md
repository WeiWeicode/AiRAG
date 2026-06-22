# 資料庫結構設計文件 (Database Schema)

## 1. 文件資訊
* **專案名稱**：AiRAG 內部測試平台
* **文件版本**：V 1.1
* **建立日期**：2026-06-18
* **資料庫類型**：
  * **應用資料庫**：MongoDB（對話紀錄、設定、測試集、評估報告、回饋標註）
  * **既有知識庫**：SQL Server（唯讀連線，存取既有的 md 檔、附件等知識庫資料）
  * **向量資料庫**：Qdrant（文件 Chunks 向量儲存）

---

## 2. 資料架構總覽

```
┌─────────────────────────────────────────────────────────┐
│                  MongoDB (airag database)                │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │chat_sessions │  │chat_messages │  │  feedbacks   │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │test_datasets │  │ eval_reports │  │prompt_templates│ │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
│  ┌──────────────┐  ┌──────────────┐                    │
│  │knowledge_bases│ │  app_configs │                    │
│  └──────────────┘  └──────────────┘                    │
└─────────────────────────────────────────────────────────┘

┌─────────────────────┐     ┌─────────────────────┐
│  SQL Server (唯讀)   │     │   Qdrant (向量DB)    │
│  既有知識庫資料       │     │   Chunk Vectors      │
│  (md檔、附件等)      │     │                     │
└─────────────────────┘     └─────────────────────┘
```

---

## 3. MongoDB Collections

> **ODM 框架**：使用 `beanie` (基於 `motor`) 進行非同步 MongoDB 操作。

### 3.1 chat_sessions — 對話 Session

```json
{
  "_id": "ObjectId",
  "title": "string | null",
  "knowledge_base_id": "string | null",
  "params": {
    "model": "Qwen3.6-35B-A3B-FP8",
    "temperature": 0.7,
    "top_p": 0.9,
    "max_tokens": 2048,
    "top_k": 5,
    "score_threshold": 0.7
  },
  "created_by": "string | null",
  "created_at": "ISODate",
  "updated_at": "ISODate"
}
```

**索引**：
* `created_at: -1`（按時間排序查詢）
* `created_by: 1`（按使用者查詢）

---

### 3.2 chat_messages — 對話訊息

```json
{
  "_id": "ObjectId",
  "session_id": "ObjectId (ref → chat_sessions)",
  "role": "user | assistant",
  "content": "string",
  "source_chunks": [
    {
      "chunk_id": "string",
      "content": "string",
      "metadata": {
        "filename": "string",
        "page": 1,
        "section": "string"
      },
      "score": 0.92
    }
  ],
  "thinking_content": "string | null",
  "token_count": 500,
  "elapsed_ms": 2300,
  "created_at": "ISODate"
}
```

**索引**：
* `session_id: 1, created_at: 1`（查詢某 Session 的所有訊息並按時間排序）

---

### 3.3 feedbacks — 回饋標註 (§4.6)

```json
{
  "_id": "ObjectId",
  "chat_message_id": "ObjectId (ref → chat_messages)",
  "session_id": "ObjectId (ref → chat_sessions)",
  "question": "string (原始問題，冗餘存儲方便查詢)",
  "ai_answer": "string (AI 回答，冗餘存儲)",
  "is_correct": false,
  "correct_answer": "string | null",
  "error_type": "hallucination | incomplete | wrong_source | format_issue | other | null",
  "note": "string | null",
  "exported_to_dataset_id": "ObjectId | null",
  "created_by": "string | null",
  "created_at": "ISODate"
}
```

**索引**：
* `is_correct: 1`（篩選正確/不正確）
* `error_type: 1`（篩選錯誤類型）
* `created_at: -1`（按時間排序）

---

### 3.4 test_datasets — 測試集 (§4.3)

```json
{
  "_id": "ObjectId",
  "name": "string",
  "description": "string | null",
  "items": [
    {
      "question": "string",
      "ground_truth": "string",
      "relevant_contexts": ["string"],
      "source_feedback_id": "ObjectId | null"
    }
  ],
  "item_count": 50,
  "created_by": "string | null",
  "created_at": "ISODate",
  "updated_at": "ISODate"
}
```

> **設計決策**：測試集題目以嵌入文件 (Embedded Document) 方式存儲，因為題目與測試集強關聯且通常一起讀寫。若單個測試集超過 1000 題，可考慮拆為獨立 Collection。

**索引**：
* `name: 1`（按名稱查詢）
* `created_at: -1`

---

### 3.5 eval_reports — 評估報告 (§4.3)

```json
{
  "_id": "ObjectId",
  "dataset_id": "ObjectId (ref → test_datasets)",
  "dataset_name": "string (冗餘存儲)",
  "knowledge_base_id": "string | null",
  "model": "Qwen3.6-35B-A3B-FP8",
  "params": {
    "temperature": 0.3,
    "top_k": 5,
    "score_threshold": 0.7
  },
  "summary": {
    "faithfulness": 0.85,
    "answer_relevancy": 0.90,
    "context_precision": 0.78,
    "context_recall": 0.82
  },
  "details": [
    {
      "question": "string",
      "ground_truth": "string",
      "generated_answer": "string",
      "retrieved_contexts": ["string"],
      "scores": {
        "faithfulness": 0.9,
        "answer_relevancy": 0.85,
        "context_precision": 0.8,
        "context_recall": 0.75
      }
    }
  ],
  "status": "pending | running | completed | failed",
  "created_by": "string | null",
  "created_at": "ISODate",
  "completed_at": "ISODate | null"
}
```

> **設計決策**：評估明細嵌入報告文件中，因為報告一旦生成就不會修改，且通常整份讀取/匯出。

**索引**：
* `dataset_id: 1`（按測試集查詢報告）
* `status: 1`（查詢進行中的評估）
* `created_at: -1`

---

### 3.6 knowledge_bases — 知識庫

```json
{
  "_id": "ObjectId",
  "name": "string",
  "description": "string | null",
  "qdrant_collection_name": "string (unique)",
  "embedding_model": "Qwen3-Embedding-8B-Q8_0.gguf",
  "chunk_count": 150,
  "created_by": "string | null",
  "created_at": "ISODate",
  "updated_at": "ISODate"
}
```

**索引**：
* `qdrant_collection_name: 1` (unique)
* `name: 1`

---

### 3.7 prompt_templates — Prompt 模板 (§4.4)

```json
{
  "_id": "ObjectId",
  "name": "string",
  "system_prompt": "string | null",
  "user_prompt_template": "string",
  "is_default": false,
  "created_by": "string | null",
  "created_at": "ISODate",
  "updated_at": "ISODate"
}
```

**索引**：
* `is_default: 1`（快速查詢預設模板）

---

### 3.8 app_configs — 應用設定

```json
{
  "_id": "ObjectId",
  "key": "string (unique)",
  "value": "any (mixed type)",
  "description": "string | null",
  "updated_at": "ISODate"
}
```

> **用途**：儲存全域設定（如預設參數、UI 偏好等），鍵值對設計方便擴充。

**索引**：
* `key: 1` (unique)

---

## 4. SQL Server 既有知識庫 (唯讀)

> **說明**：此為公司既有的 SQL Server 資料庫，本系統僅進行**唯讀查詢**，不建立新表、不修改資料。

### 4.1 存取方式
* 使用 `pyodbc` / `aioodbc` 透過 ODBC 連線
* 僅執行 `SELECT` 查詢
* 連線字串配置於 `.env` 的 `SQLSERVER_CONNECTION_STRING`

### 4.2 預期查詢的資料
| 資料類型 | 說明 | 用途 |
|:---|:---|:---|
| md 文件 | Markdown 格式的知識文件 | 作為 RAG 知識來源，可匯入向量化 |
| 附件 | PDF、DOCX 等附件檔案 | 解析後進行 Chunking 與 Embedding |
| 相關 Metadata | 文件標題、分類、建立日期等 | 作為 Chunk 的 Metadata |

### 4.3 資料流
```
SQL Server (既有知識庫) 
    │ 唯讀查詢
    ▼
FastAPI Backend (document_parser.py)
    │ 解析 + Chunking
    ▼
llama.cpp (Embedding)
    │ 向量化
    ▼
Qdrant (寫入向量)
```

---

## 5. Qdrant 向量資料庫

### 5.1 Collection 設計

每個 **知識庫 (KnowledgeBase)** 對應一個 Qdrant **Collection**。

**Collection 建立參數**：
```json
{
  "collection_name": "kb_{knowledge_base_id}",
  "vectors": {
    "size": 4096,
    "distance": "Cosine"
  },
  "hnsw_config": {
    "m": 16,
    "ef_construct": 100
  }
}
```

> **向量維度**：`4096`（對應 Qwen3-Embedding-8B 模型的輸出維度）

### 5.2 Point 結構

```json
{
  "id": "uuid",
  "vector": [0.012, -0.034, ...],
  "payload": {
    "content": "Chunk 完整文字內容",
    "filename": "report.pdf",
    "page": 3,
    "section": "第二章 系統設計",
    "chunk_index": 5,
    "token_count": 128,
    "char_count": 450,
    "start_char": 2000,
    "end_char": 2449,
    "source": "sqlserver | upload",
    "created_at": "2026-06-18T10:00:00Z"
  }
}
```

### 5.3 索引策略
* **主要索引**：HNSW（Qdrant 預設）
* **Payload 索引**：`filename`、`page`、`source` 建立 Payload Index
* **混合搜尋**：啟用 BM25 全文搜尋索引（Hybrid Search）

---

## 6. 資料關聯摘要

| 關聯 | 儲存位置 | 類型 | 說明 |
|:---|:---|:---|:---|
| chat_sessions → chat_messages | MongoDB | 一對多 | 透過 `session_id` 關聯 |
| chat_messages → feedbacks | MongoDB | 一對一 | 透過 `chat_message_id` 關聯 |
| test_datasets.items | MongoDB | 嵌入文件 | 題目嵌入測試集文件中 |
| eval_reports.details | MongoDB | 嵌入文件 | 明細嵌入報告文件中 |
| feedbacks → test_datasets | MongoDB | 可選關聯 | 回饋可匯入為測試題目 |
| knowledge_bases ↔ Qdrant | MongoDB ↔ Qdrant | 一對一 | `qdrant_collection_name` 對應 |
| SQL Server → Qdrant | SQL Server → Qdrant | 唯讀→寫入 | 既有資料經解析後向量化寫入 |
