<!-- 後端修正紀錄 -->

## 2026-06-22 實現資料庫初始化引導種植 (Database Seeding)

### 修改內容
1. `backend/models/mongodb.py`:
   - 新增 `seed_default_knowledge_base` 異步方法。該方法會在 Beanie 初始化成功後執行。
   - 方法會查詢當前 `KnowledgeBase` 集合的文檔數，若數量為 0，則利用 `PydanticObjectId()` 生成新 ID，自動在 MongoDB 建立名為「預設知識庫」的項目，並透過 `QdrantService.create_collection` 在 Qdrant 中建立對應的 Collection，以保證系統運行時始終有至少一個可用的知識庫，提供前端正確的 ObjectId。

## 2026-06-22 修正外部服務連線設定與向量解析器相容性

### 修改內容
1. `docker-compose.yml`:
   - 移除 `backend` 服務下對 `VLLM_BASE_URL` 與 `LLAMACPP_BASE_URL` 的環境變數覆寫，以避免強行覆寫為 `host.docker.internal` 造成連線失敗，直接繼承並讀取 `.env` 檔案內設定的伺服器 IP `10.10.130.45`。
2. `backend/services/embedding_service.py`:
   - 重構 `EmbeddingService.get_embedding` 中的 JSON 解析器。
   - 使其支援多層級向量包裝格式，相容於列表型格式（如 `[{"embedding": [[...]]}]` 或 `[{"embedding": [...]}]`）、舊版字典格式、以及 OpenAI 規範 a 包裝結構，避免格式不一致導致解析拋出例外。

## 2026-06-22 實現向量檢索搜尋與查詢轉換服務

### 修改內容
1. `backend/schemas/retrieval.py` (新增檔案):
   - 定義向量搜尋與查詢重寫/HyDE 的 Pydantic 請求與回應 Schema（`RetrievalRequest`, `RetrievalResponse`, `QueryTransformRequest`, `QueryTransformResponse` 等），確保 API 完全符合合約定義。
2. `backend/services/llm_service.py` (新增檔案):
   - 建立對外部 vLLM（OpenAI 兼容接口）之 `LLMService`。
   - 實作端到端 Chat Completions 呼叫邏輯，包含非同步 Stream（串流）與一般 JSON 回傳支援。
   - 實作 `query_rewrite`（查詢重寫）與 `hyde_generation`（假設文檔生成）之 LLM Prompt 提示詞包裝方法。
3. `backend/routers/retrieval.py`:
   - 取代原有 Stub 路由，實作實際向量搜尋。
   - 藉由 `EmbeddingService` 將查詢向量化後，透過 `QdrantService.search_similar` 取得相似 Chunks 並回傳詳細 Metadata 與 Score。
   - 實作 `query-transform` 路由，執行 `rewrite`（重寫）或 `hyde` 策略生成轉換查詢後，呼叫 Qdrant 進行語意搜尋並回傳結果。