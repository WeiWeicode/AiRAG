# 資料庫結構設計文件 (Database Schema)

## 1. 文件資訊
* **專案名稱**：AiRAG 內部測試平台
* **文件版本**：V 1.6（依實際程式碼校正）
* **建立日期**：2026-06-18
* **更新日期**：2026-07-08（修正 `source == "db_query_profile"` 隔離規則的查詢法計數，補上 `semantic_hybrid_attachment`）
* **資料庫類型**：
  * **應用資料庫**：MongoDB（對話紀錄、設定、測試集、評估報告、回饋標註、資料庫連線設定、標籤與類別選項、Prompt 測試歷史紀錄）
  * **既有知識庫 / 自訂 DB**：SQL Server & Oracle Database（唯讀連線，存取既有的文章與表單欄位等資料）
  * **向量資料庫**：Qdrant（密集與稀疏雙向量混合儲存）

> 本版本已對照 `backend/models/mongodb.py` 的 `init_beanie(document_models=[...])` 註冊清單與 `backend/services/qdrant_service.py` 的實際寫入程式碼校正。

---

## 2. 資料架構總覽

```
┌───────────────────────────────────────────────────────────────────┐
│                     MongoDB (airag database)                       │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐             │
│  │chat_sessions │  │chat_messages │  │  feedbacks   │             │
│  └──────────────┘  └──────────────┘  └──────────────┘             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐             │
│  │test_datasets │  │ eval_reports │  │prompt_templates│           │
│  └──────────────┘  └──────────────┘  └──────────────┘             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐             │
│  │knowledge_bases│ │  app_configs │  │database_configs│           │
│  └──────────────┘  └──────────────┘  └──────────────┘             │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐       │
│  │     tags     │  │class_options │  │prompt_test_records │       │
│  └──────────────┘  └──────────────┘  └────────────────────┘       │
│  ┌──────────────┐  ┌──────────────┐                               │
│  │db_query_profiles│ │ attachments │                              │
│  └──────────────┘  └──────────────┘                               │
└───────────────────────────────────────────────────────────────────┘

┌─────────────────────┐     ┌─────────────────────┐
│SQL Server / Oracle  │     │   Qdrant (向量DB)    │
│  既有與自訂資料庫    │     │   - Dense Vectors   │
│   (唯讀連線查詢)    │     │   - Sparse Vectors  │
└─────────────────────┘     └─────────────────────┘
```

15 個 MongoDB Collection 皆透過 `backend/models/mongodb.py` 的 `init_beanie()` 註冊：`AppConfig`、`KnowledgeBase`、`PromptTemplate`、`PromptTestRecord`、`ChatSession`、`ChatMessage`、`Feedback`、`TestDataset`、`EvalReport`、`Tag`、`ClassOption`、`DatabaseConfig`、`DBQueryProfile`、`Attachment`（2026-07-06 新增，見第 3.13 節）、`RetrievalStats`（2026-07-09 新增，見第 3.14 節）。應用程式啟動時會自動 seed：
* 若尚無知識庫，建立一個預設知識庫並同步建立對應 Qdrant collection。
* 若尚無測試集，寫入 2 筆預設 `TestDataset`。
* 若尚無 Prompt 範本，寫入「預設 RAG 助手」與「嚴格知識問答」兩筆內建範本。
* 若尚無 A/B 測試歷史，寫入 1 筆預設 `PromptTestRecord`（"預設 RAG 智慧對話範本"）。

---

## 3. MongoDB Collections

> **ODM 框架**：使用 `beanie`（基於 `motor`）進行非同步 MongoDB 操作。`sqlserver.py` 內僅為 pyodbc 連線輔助函式，非 beanie Document。

### 3.1 app_configs — 系統設定值【前一版文件遺漏此 Collection】
```json
{
  "_id": "ObjectId",
  "key": "string (Unique 索引)",
  "value": "Any",
  "description": "string | null",
  "updated_at": "ISODate"
}
```

### 3.2 chat_sessions — 對話 Session
```json
{
  "_id": "ObjectId",
  "title": "string | null",
  "knowledge_base_id": "string | null",
  "params": {
    "model": "Qwen3.6-35B-A3B-FP8",
    "temperature": 0.7, "top_p": 0.9, "max_tokens": 2048,
    "top_k": 5, "score_threshold": 0.7
  },
  "created_by": "string | null",
  "created_at": "ISODate", "updated_at": "ISODate"
}
```
索引：`-created_at`、`created_by`。
> 注意：目前 `GET /api/rag/history`、`DELETE /api/rag/history/{id}` 為 stub，尚未實際讀寫此 Collection（見 `03_API_CONTRACT.md` §3.2/3.3）。

### 3.3 chat_messages — 對話訊息
```json
{
  "_id": "ObjectId",
  "session_id": "ObjectId",
  "role": "user | assistant",
  "content": "string",
  "source_chunks": [
    { "chunk_id": "string", "content": "string",
      "metadata": { "filename": "string|null", "page": "int|null", "section": "string|null", "chunk_index": "any|null" },
      "score": 0.9, "distance": 0.1 }
  ],
  "thinking_content": "string | null",
  "token_count": "int | null",
  "elapsed_ms": "int | null",
  "created_at": "ISODate"
}
```
索引：複合索引 `(session_id, created_at)`。

### 3.4 feedbacks — 回饋標註
```json
{
  "_id": "ObjectId",
  "chat_message_id": "string (索引)",
  "session_id": "string | null",
  "question": "string",
  "ai_answer": "string",
  "is_correct": "bool",
  "correct_answer": "string | null",
  "error_type": "hallucination | incomplete | wrong_source | format_issue | other | null",
  "note": "string | null",
  "exported_to_dataset_id": "ObjectId | null",
  "created_by": "string | null",
  "created_at": "ISODate"
}
```
索引：`is_correct`、`error_type`、`-created_at`、`chat_message_id`。

### 3.5 test_datasets — 測試集
```json
{
  "_id": "ObjectId",
  "name": "string",
  "description": "string | null",
  "items": [
    { "question": "string", "ground_truth": "string", "relevant_contexts": ["string"], "source_feedback_id": "ObjectId | null" }
  ],
  "item_count": 0,
  "created_by": "string | null",
  "created_at": "ISODate", "updated_at": "ISODate"
}
```
索引：`name`、`-created_at`。

### 3.6 eval_reports — 評估報告
```json
{
  "_id": "ObjectId",
  "dataset_id": "ObjectId",
  "dataset_name": "string",
  "knowledge_base_id": "string | null",
  "model": "Qwen3.6-35B-A3B-FP8",
  "params": { "temperature": 0.3, "top_k": 5, "score_threshold": 0.7, "max_tokens": 1024, "search_type": "vector" },
  "summary": { "faithfulness": 0.0, "answer_relevancy": 0.0, "context_precision": 0.0, "context_recall": 0.0 },
  "details": [
    { "question": "string", "ground_truth": "string", "generated_answer": "string",
      "retrieved_contexts": ["string"], "scores": { "faithfulness": 0.0, "answer_relevancy": 0.0, "context_precision": 0.0, "context_recall": 0.0 } }
  ],
  "status": "pending | running | completed | failed",
  "created_by": "string | null",
  "created_at": "ISODate", "completed_at": "ISODate | null"
}
```
索引：`dataset_id`、`status`、`-created_at`。
> 注意：`POST /api/evaluation/run` 目前僅評估測試集前 5 筆（程式碼硬編碼上限），見 `03_API_CONTRACT.md` §5.5。

### 3.7 knowledge_bases — 知識庫
```json
{
  "_id": "ObjectId",
  "name": "string",
  "description": "string | null",
  "qdrant_collection_name": "string (Unique 索引，格式 kb_{id})",
  "embedding_model": "Qwen3-Embedding-8B-Q8_0.gguf",
  "chunk_count": 0,
  "created_by": "string | null",
  "created_at": "ISODate", "updated_at": "ISODate"
}
```
索引：`name`、`-created_at`、`qdrant_collection_name`（unique）。

### 3.8 prompt_templates — Prompt 模板
系統啟動時若資料庫為空，自動寫入「預設 RAG 助手」與「嚴格知識問答」兩款內建種子範本。
```json
{
  "_id": "ObjectId",
  "name": "string",
  "system_prompt": "string | null",
  "user_prompt_template": "string (支援 {context} 與 {question} 變數)",
  "is_default": false,
  "created_by": "string | null",
  "created_at": "ISODate", "updated_at": "ISODate"
}
```
索引：`is_default`。

### 3.9 database_configs — 資料庫連線配置
```json
{
  "_id": "ObjectId",
  "name": "string",
  "db_type": "sqlserver | oracle",
  "host": "string", "port": 1433, "database": "string",
  "username": "string",
  "password": "string (⚠️ 目前為明文儲存，無加密)",
  "created_at": "ISODate", "updated_at": "ISODate"
}
```
> 無自訂索引。⚠️ `password` 欄位目前以明文儲存並在對應 API 回應中原樣回傳，未做加密或遮罩處理。

### 3.10 tags — 分類標籤
```json
{ "_id": "ObjectId", "name": "string (Unique 索引)", "created_at": "ISODate" }
```

### 3.11 class_options — 自訂類別選項
```json
{ "_id": "ObjectId", "name": "string (Unique 索引)", "created_at": "ISODate" }
```

### 3.9a db_query_profiles — 語義資料庫查詢法之查詢設定檔【新增，2026-07-03】
```json
{
  "_id": "ObjectId",
  "name": "string",
  "database_config_id": "string (關聯 database_configs._id)",
  "knowledge_base_id": "string (關聯 knowledge_bases._id，決定 Profile 向量實際存放的 Qdrant collection)",
  "platform_description": "string",
  "table_name": "string",
  "table_purpose": "string",
  "columns": [
    { "column_name": "string", "enabled": true, "meaning": "string", "max_length": "int | null (大型欄位如 nvarchar(max) 的自訂截斷長度)" }
  ],
  "is_default": "bool (2026-07-03 新增；必定查詢：問題與任何設定檔都無明顯關聯時，此設定檔仍會被強制加入候選查詢清單)",
  "composed_description": "string (自動組合的自然語言描述，即拿去 embedding 的文字)",
  "qdrant_point_id": "string | null",
  "created_by": "string | null",
  "created_at": "ISODate", "updated_at": "ISODate"
}
```
索引：`knowledge_base_id`、`database_config_id`。

### 3.12 prompt_test_records — Prompt 測試歷史與結果
```json
{
  "_id": "ObjectId",
  "name": "string",
  "system_prompt": "string",
  "user_prompt_template": "string",
  "context": "string",
  "question": "string",
  "results": [
    { "label": "string", "answer": "string", "params": { "temperature": 0.1, "top_p": 0.9, "max_tokens": 2048 }, "elapsed_ms": 1500 }
  ],
  "created_by": "string | null",
  "created_at": "ISODate"
}
```
索引：`created_at`。

### 3.13 attachments — 附件 metadata（語義混合附件查詢法）【新增，2026-07-06】
```json
{
  "_id": "ObjectId",
  "knowledge_base_id": "string (關聯 knowledge_bases._id)",
  "original_filename": "string (使用者上傳時的原始檔名，可能含中文/特殊字元)",
  "stored_filename": "string (落地於 FILE_ATTACHMENTS_DIR 的重新編碼檔名，格式為 {uuid4().hex}{副檔名})",
  "description": "string (使用者填寫的備註，僅供顯示參考；2026-07-06 起不再是 AI 讀取附件內容的主要來源)",
  "extracted_content": "string | null (2026-07-06 新增；上傳時自動用 DocumentParser.parse_file() 解析出的檔案實際文字內容，AI 讀取附件內容時優先使用此欄位)",
  "extraction_error": "string | null (2026-07-06 新增；自動解析失敗原因，例如不支援的檔案格式；失敗不影響附件上傳/下載，僅代表 AI 讀取附件內容時會退回使用 description)",
  "tags": ["string"],
  "classes": ["string"],
  "content_type": "string | null",
  "size": "int (位元組)",
  "created_by": "string | null",
  "created_at": "ISODate", "updated_at": "ISODate"
}
```
索引：`knowledge_base_id`、`-created_at`。
> 附件**不會**寫入 Qdrant 做向量搜尋，僅存這裡的 metadata + 磁碟實體檔案（`backend/FileAttachments/`，`stored_filename` 為實際檔名）。附件與已向量化文件的關聯存放在 Qdrant Point payload 的 `linked_attachments` 欄位（見 4.2 節），而非這個 collection 本身；刪除附件（`DELETE /api/attachments/{id}`）不會級聯清除其他文件 Point 上對此 id 的參照。
> `extracted_content`／`extraction_error` 為 2026-07-06 修正新增（見 `docs/DevelopmentProcess/NewFeatures.md` 同日條目）：此修正前上傳的既有附件沒有 `extracted_content`，AI 讀取附件內容時會自動退回 `description`；需重新上傳該檔案才會補上實際解析內容。

### 3.14 retrieval_stats — 檢索命中統計（檢索命中分析儀表板）【新增，2026-07-09】
```json
{
  "_id": "ObjectId",
  "knowledge_base_id": "string | null (關聯 knowledge_bases._id)",
  "search_type": "string (vector/hybrid/semantic_hybrid/semantic_hybrid_feedback/semantic_hybrid_attachment；semantic_db_query 不記錄)",
  "question": "string",
  "top_k": "int",
  "score_threshold": "float",
  "retrieved_scores": ["float (本次所有候選片段的 semantic_score，與 score_threshold 同尺度，非原始 RRF score)"],
  "hit_count": "int (semantic_score >= score_threshold 的筆數)",
  "total_candidates": "int (去重合併後的候選總數)",
  "avg_score": "float | null",
  "min_score": "float | null",
  "max_score": "float | null",
  "elapsed_ms": "int | null (目前一律為 null，本次未實作計時)",
  "session_id": "string | null",
  "created_at": "ISODate"
}
```
索引：`knowledge_base_id`、`search_type`、`-created_at`、`(knowledge_base_id, -created_at)` 複合索引。
> 由 `rag_chat_stream()` 完成檢索後以 best-effort 方式寫入（`backend/services/retrieval_stats_service.py`），寫入失敗只記錄 warning、不影響 SSE 對話主流程。與 `chat_messages.source_chunks` 資料重疊但服務不同目的（此 collection 專供聚合統計查詢），兩者皆為獨立寫入、無關聯。詳見 [`NewFeaturesPlan_RetrievalStatsDashboardPlan.md`](DevelopmentProcess/NewFeaturesPlan_RetrievalStatsDashboardPlan.md) 與 [`03_API_CONTRACT.md`](03_API_CONTRACT.md) 第 16 節。

---

## 4. Qdrant 向量資料庫設計

### 4.1 Collection 與雙向量配置
```json
{
  "collection_name": "kb_{knowledge_base_id}",
  "vectors": {
    "size": 4096,
    "distance": "Cosine"
  },
  "sparse_vectors": {
    "sparse-text": { "index": { "on_disk": true } }
  },
  "hnsw_config": { "m": 16, "ef_construct": 100 }
}
```
> 密集向量儲存在**未命名的預設向量空間**（Qdrant 內部鍵名為空字串 `""`），並非命名為 `"dense"`。查詢時 `Prefetch(using="")` 即代表密集向量空間。

**Payload 文字索引**：collection 建立時會額外對 `content` 欄位建立 `TextIndexParams`（`tokenizer=WORD, lowercase=True`），用以支援 `MatchText` 精確關鍵字比對（見雙階段檢索的 exact-keyword boost）。

### 4.2 Point 結構與 Payload 定義

**每次寫入必定包含**（`backend/routers/embedding.py` 的 `upsert_chunks` 主要寫入路徑，SQL Server 匯入路徑 `database_indexing.py` 僅寫入前 9 項、不含 `tags`/`class`/`links_to`）：
```json
{
  "content": "Chunk 完整內容（或轉成 JSON/自然語言的 ERP 欄位描述）",
  "filename": "report.pdf",
  "page": 1,
  "section": "段落標題",
  "chunk_index": 0,
  "token_count": 128,
  "char_count": 450,
  "source": "upload | database | json_semantic | db_query_profile (2026-07-03 新增，語義資料庫查詢法的查詢設定檔向量)",
  "tags": ["標籤1", "標籤2"],
  "class": ["類別1"],
  "links_to": ["關聯檔名或 Point ID"],
  "created_at": "2026-07-02T10:00:00 (ISO 字串，非 BSON 日期)"
}
```

**條件性透傳欄位**（僅當來源 Chunker 的 `metadata` dict 中含有對應 key 時才會寫入，並非所有 Point 都保證存在，取決於檔案類型與切分策略）：
```json
{
  "parent_id": "uuid（對應 Parent Chunk 的唯一 ID，Word/MD/4GL/4FD 雙層切分才有）",
  "parent_chunk_index_range": "0~4（該 Parent Block 分切出的 Child Chunks 索引區間）",
  "file_type": "docx | md | 4gl | 4fd",
  "header_path": "Header1 > Header2（Word / MD 的層級標題階層首碼）",
  "function_name": "func_name（4GL 原始碼的函數名稱）",
  "chunk_type": "image | text（標記 Point 類型，文件內嵌圖片之描述為 image，一般文本段落為 text/空值，2026-07-07 新增）",
  "image_filename": "stored_image_filename.png（類型為 image 時，對應在 backend/FileAttachments/image/ 目錄下儲存的圖片檔名，透過 GET /api/embedding/images/{stored_filename} 讀取，2026-07-07 新增）"
}
```
> `parent_content`、`type` 兩個欄位在檢索程式碼中會被防禦性讀取（`payload.get(...)`），但目前的寫入程式碼路徑中**找不到明確的寫入來源**，可能僅存在於語義 JSON 匯入路徑或歷史遺留資料，撰寫新功能時不應假設其必然存在。

**`links_to` 用途**：由 `POST /api/retrieval/knowledge-bases/{id}/files/update-links` 批次寫入（見 `03_API_CONTRACT.md` §4.6），或於向量化時直接帶入。是 §5 雙階段關聯檢索（Two-Step Hybrid Retrieval）的核心欄位——第一階段召回的 Point 若帶有 `links_to`，第二階段會據此在 `filename`/`custom_id` 命中的關聯點位中做進一步的語意/混合搜尋。

**`linked_attachments` 用途**【新增，2026-07-06】：內容為 `attachments` collection（見 3.13 節）的 `Attachment._id` 字串清單。與 `links_to` 不同的是，這個欄位**不會**在 `backend/routers/embedding.py` 的向量化寫入路徑時自動帶入，只會透過 `POST /api/retrieval/knowledge-bases/{id}/files/update-attachments`（見 `03_API_CONTRACT.md` §4.7）事後批次覆蓋指定檔名底下所有 Point 的這個欄位；未呼叫過此端點的既有 Point 不會有這個 key（`get_unique_metadata()`／檢索程式碼皆以 `payload.get("linked_attachments", [])` 防禦性讀取，缺欄位時視為空陣列，不影響既有資料）。是「語義混合附件查詢法」（`search_type == "semantic_hybrid_attachment"`）的核心欄位——命中片段若帶有 `linked_attachments`，`backend/routers/rag.py` 會據此查詢 `attachments` collection 並在回答中附上附件下載點（可選擇是否讓 AI 讀取附件描述內容），詳見 `03_API_CONTRACT.md` 第 14 節。

**`source == "db_query_profile"` 的隔離規則**【新增，2026-07-03】：`QdrantService.search_similar()`/`search_similar_two_step()` 固定加上 `must_not: source == "db_query_profile"` 過濾條件，因此語義資料庫查詢法的 Profile 向量雖與一般文件 Chunk 共存於同一個 KnowledgeBase collection，但永遠不會出現在 `vector`/`hybrid`/`semantic_hybrid`/`semantic_hybrid_feedback`/`semantic_hybrid_attachment` 這五種既有查詢法的結果中；反之，`QdrantService.search_db_query_profiles()` 只搜尋 `source == "db_query_profile"` 的點位。

### 4.3 向量索引與檢索策略
* **HNSW 索引**：對密集向量做餘弦相似度 (Cosine) 索引，`m=16`、`ef_construct=100`。
* **稀疏索引**：對 `"sparse-text"` 啟用 SPLADE 稀疏點陣索引，加速精確關鍵字召回。
* **Payload 文字索引**：`content` 欄位建有 `text` 型別索引，支援 `MatchText` 精確關鍵字比對。
* **Payload 過濾索引**：`filename`、`source`、`class` 欄位可用於 Key Payload 過濾查詢與 Points 清理；雙階段檢索另外使用 `filename`/`custom_id` 做 `MatchAny` 過濾。
