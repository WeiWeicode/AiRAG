# 資料庫結構設計文件 (Database Schema)

## 1. 文件資訊
* **專案名稱**：AiRAG 內部測試平台
* **文件版本**：V 1.2 (最新更新)
* **建立日期**：2026-06-18
* **更新日期**：2026-06-30
* **資料庫類型**：
  * **應用資料庫**：MongoDB（對話紀錄、設定、測試集、評估報告、回饋標註、資料庫連線設定、標籤與類別選項、Prompt 測試歷史紀錄）
  * **既有知識庫 / 自訂 DB**：SQL Server & Oracle Database（唯讀連線，存取既有的 md 檔、表單欄位等資料）
  * **向量資料庫**：Qdrant（密集與稀疏雙向量混合儲存）

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
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │knowledge_bases│ │  app_configs │  │database_configs│ │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │     tags     │  │class_options │  │prompt_test_records│
│  └──────────────┘  └──────────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────────┘

┌─────────────────────┐     ┌─────────────────────┐
│SQL Server / Oracle  │     │   Qdrant (向量DB)    │
│  既有與自訂資料庫    │     │   - Dense Vectors   │
│   (唯讀連線查詢)    │     │   - Sparse Vectors  │
└─────────────────────┘     └─────────────────────┘
```

---

## 3. MongoDB Collections

> **ODM 框架**：使用 `beanie` (基於 `motor`) 進行非同步 MongoDB 操作。

### 3.1 chat_sessions — 對話 Session
*同 V1.1*，儲存 `title`、`knowledge_base_id`、`params` 與時間戳記。

### 3.2 chat_messages — 對話訊息
*同 V1.1*，儲存 `session_id`、`role`、`content`、`source_chunks`、`thinking_content`、`elapsed_ms` 等。

### 3.3 feedbacks — 回饋標註
*同 V1.1*，新增支援單筆與批次刪除清理。

### 3.4 test_datasets — 測試集
*同 V1.1*，儲存問題集、標準答案與引用 Contexts。

### 3.5 eval_reports — 評估報告
*同 V1.1*，儲存自動化跑分 Faithfulness、Answer Relevancy、Context Precision、Context Recall 結果。

### 3.6 knowledge_bases — 知識庫
*同 V1.1*，儲存向量庫關聯 collection 名稱、Embedding 模型與 Chunks 總量。

### 3.7 prompt_templates — Prompt 模板
*新增設計*：於系統啟動時，若資料庫為空，會自動寫入「預設 RAG 助手」與「嚴格知識問答」兩款內建種子範本。
```json
{
  "_id": "ObjectId",
  "name": "string (範本名稱)",
  "system_prompt": "string | null",
  "user_prompt_template": "string (支援 {context} 與 {question} 變數)",
  "is_default": false,
  "created_by": "string | null",
  "created_at": "ISODate",
  "updated_at": "ISODate"
}
```

### 3.8 database_configs — 資料庫連線配置 [NEW]
**用途**：儲存使用者自訂的 SQL Server 或 Oracle Database 連線配置，以便於向量化匯入時快速套用。
```json
{
  "_id": "ObjectId",
  "name": "string (設定檔名稱)",
  "db_type": "sqlserver | oracle",
  "host": "string (資料庫主機 IP)",
  "port": 1433,
  "database": "string (資料庫名稱 / Service Name)",
  "username": "string (登入帳號)",
  "password": "string (加密/明文密碼)",
  "created_at": "ISODate",
  "updated_at": "ISODate"
}
```

### 3.9 tags — 分類標籤 [NEW]
**用途**：儲存知識庫 Chunks 分類標籤，供使用者於匯入資料時一鍵勾選。
```json
{
  "_id": "ObjectId",
  "name": "string (標籤名稱，Unique 索引)",
  "created_at": "ISODate"
}
```

### 3.10 class_options — 自訂類別選項 [NEW]
**用途**：儲存使用者自行建立的類別屬性（如：前端、後端、系統），可用於 Qdrant Points 的 `"class"` payload 寫入以利多維度過濾檢索。
```json
{
  "_id": "ObjectId",
  "name": "string (類別名稱，Unique 索引)",
  "created_at": "ISODate"
}
```

### 3.11 prompt_test_records — Prompt 測試歷史與結果 [NEW]
**用途**：儲存 Prompt A/B 測試的輸入參數、模板與 Variant 生成答案，供調優對照與參數還原。
```json
{
  "_id": "ObjectId",
  "name": "string (測試紀錄標題)",
  "system_prompt": "string (System Prompt)",
  "user_prompt_template": "string (User Prompt Template)",
  "context": "string (測試上下文)",
  "question": "string (測試問題)",
  "results": [
    {
      "label": "string (Variant 標籤名稱，例如 A組-低溫)",
      "answer": "string (生成回答)",
      "params": {
        "temperature": 0.1,
        "top_p": 0.9,
        "max_tokens": 2048
      },
      "elapsed_ms": 1500
    }
  ],
  "created_by": "string | null",
  "created_at": "ISODate"
}
```

---

## 4. Qdrant 向量資料庫設計

### 4.1 Collection 與雙向量配置
本專案採用密集向量與稀疏關鍵字雙路向量混合儲存：

```json
{
  "collection_name": "kb_{knowledge_base_id}",
  "vectors": {
    // 1. 密集向量 (Dense Vector) 空間：用以偵測與儲存語義密集向量
    "size": 4096, // 自適應大小 (預設為 Qwen 3 的 4096 維度)
    "distance": "Cosine"
  },
  "sparse_vectors": {
    // 2. 稀疏向量 (Sparse Vector) 空間：用於 SPLADE 關鍵字词頻匹配
    "sparse-text": {
      "index": {
        "on_disk": true
      }
    }
  }
}
```

### 4.2 Point 結構與 Payload 定義
```json
{
  "id": "uuid",
  "vector": {
    "": [0.012, -0.034, ...], // 密集向量數值 (4096 維)
    "sparse-text": {
      "indices": [34, 102, 5903], // 稀疏向量字詞索引
      "values": [0.45, 0.12, 0.89] // 詞頻權重數值
    }
  },
  "payload": {
    "content": "Chunk 完整內容 (或轉成 JSON/自然語言的 ERP 欄位描述)",
    "filename": "report.pdf", // 檔案名稱，自訂 DB 匯入時固定為 "DB_IMPORT_{tableName}"
    "page": 1,
    "section": "段落標題",
    "chunk_index": 0,
    "token_count": 128,
    "char_count": 450,
    "source": "upload | database | json",
    "tags": ["標籤1", "標籤2"], // 分類標籤陣列
    "class": ["類別1"], // 類別選項陣列
    
    // 以下為大小雙層檢索 (Parent-Child Retriever) 專屬關聯元資料 [NEW]
    "parent_id": "uuid (對應 Parent Chunk 的唯一 ID)",
    "parent_chunk_index_range": "0~4 (對應該 Parent Block 分切的所有 Child Chunks 索引區間)",
    "file_type": "docx | md | 4gl | 4fd", // 原始檔案類型
    "header_path": "Header1 > Header2 (Word / MD 的層級標題階層首碼)",
    "function_name": "func_name (4GL 原始碼的函數名稱)",
    
    "created_at": "2026-06-30T10:00:00Z"
  }
}
```

### 4.3 向量索引與檢索策略
* **HNSW 索引**：對密集向量進行餘弦相似度 (Cosine) 索引。
* **稀疏索引**：對 `"sparse-text"` 啟用 SPLADE 稀疏點陣索引，加速精確關鍵字及型號召回。
* **Payload 過濾索引**：針對 `filename`、`source` 與 `class` 欄位建立 Key Payload Index，提供極速檔案名稱過濾查詢與 Points 清理。
