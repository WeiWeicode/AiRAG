<!-- 後端修正紀錄 -->

## 2026-06-23 新增預設 RAG 智慧對話 Prompt 範本測試紀錄 (PromptTestRecord)

### 修改內容
1. `backend/models/prompt_test_record.py`:
   - 新增 `seed_default_records` 異步方法。該方法會檢查 MongoDB 中是否已存在名為「預設 RAG 智慧對話範本」的 `PromptTestRecord`。若不存在，則自動寫入該紀錄（包含最新的 `rag.py` 系統設定、使用者範本、測試 Context 與測試問題），方便在「自訂 Context 生成」頁面中直接從歷史紀錄中載入並選取。
2. `backend/models/mongodb.py`:
   - 於 `init_mongodb` 的資料庫引導種植階段呼叫 `seed_default_records()`。
   - 於 `seed_default_prompt_templates` 中同步更新預設 RAG 助手 `PromptTemplate` 的系統設定，同樣新增文檔與段落引用規則。

## 2026-06-23 修正 RAG 智慧對話 Prompt 以強制要求 AI 引用文檔段落編號

### 修改內容
1. `backend/routers/rag.py`:
   - 於向量檢索完成組裝 `context_parts` 時，在提示詞中併入段落編號 `meta.get("chunk_index")` 與檔名。
   - 重構 RAG 的 `system_prompt`，於規則中新增第 4 點，明確要求 AI 必須在回答的開頭或結尾指出參考了哪些來源文件與段落，並指定固定格式為：「依據 [文件名] 段落: #段落編號 做出以下結論：」或是「（參考來源：[文件名] 段落: #段落編號）」，並給予多重引用之頓號分隔範例。

## 2026-06-23 修正無向量條件之 Scroll 檢索產生的 Record 物件無 score 屬性錯誤

### 修改內容
1. `backend/services/qdrant_service.py`:
   - 於 `search_similar` 中，對無向量條件下使用 `client.scroll` 檢索回傳的 `Record` 列表，改以 `getattr(res, "score", 0.0)` 安全讀取 `score`，解決 `Record` 無 `score` 屬性引發 `AttributeError` 崩潰並造成回傳空資料的 Bug。

## 2026-06-23 實作 A/B 測試平行異步串流、知識庫元數據接口與 Qdrant 檔案篩選

### 修改內容
1. `backend/services/qdrant_service.py`:
   - **過濾檔案與標籤條件**：擴充 `search_similar` 方法以支援額外的 `filter_filename` 參數。如果提供，它會與標籤過濾一起被包裝為 Qdrant 的 `must` 篩選條件。若 `query_vector` 為 `None`，則透過 `client.scroll` 進行純篩選查詢。
   - **元數據提取功能**：新增 `get_unique_metadata` 方法。該方法使用 Qdrant client 的 `scroll` 功能（只抓取 payload 中的 "filename" 與 "tags" 以取得最大效能，關閉 vector 載入），遍歷收集並回傳所有唯一的檔案名稱與標籤。
2. `backend/schemas/retrieval.py`:
   - 在 `SearchParams` 類中新增可選的 `filter_filename: Optional[str]` schema 屬性。
3. `backend/routers/retrieval.py`:
   - 在 `/search` 路由的 Qdrant 檢索中傳遞 `filter_filename` 參數。若 `query` 參數為空則跳過向量生成，直接執行無向量 Scroll 檢索。
4. `backend/routers/knowledge_base.py`:
   - 新增 `GET /knowledge-bases/{id}/metadata` 路由。在檢索到指定的知識庫後，調用 `QdrantService.get_unique_metadata` 回傳集合內所有的唯一 filename 與 tags 陣列。
5. `backend/routers/prompt.py`:
   - **A/B 測試平行異步串流**：
     - 重構 `POST /ab-test` 路由以回傳 `StreamingResponse`。
     - 內部實作異步 `ab_test_stream_generator()` 產生器，使用 `asyncio.Queue` 搭配 `asyncio.create_task` 在背景平行執行 Variant A 與 Variant B 的 LLM 對答流式推論。
     - 各任務取得 `delta` 區塊時（包含 content 與 reasoning_content 等），寫入 queue 中。產生器持續從 queue 取出資料，以標準 Server-Sent Events (SSE) 格式推送到前端。

## 2026-06-23 實作自訂 Context 與多參數 A/B 測試 Prompt 端點功能

### 修改內容
1. `backend/routers/prompt.py`:
   - 重構原 Stub 端點，定義 `PreviewRequest`、`PreviewResponse`、`ABTestRequest` 與 `ABTestResponse` 等 Pydantic models。
   - 於 `/preview` 中，實作安全字串替換，組合出最終的 user prompt，並套用 `(len(sys) + len(user)) * 1.3` 的 token 估計規則回傳。
   - 於 `/ab-test` 中，解析 variants 的超參數列表，呼叫 `LLMService.chat_completion` 完成真實 LLM 推論生成，並以毫秒精準統計耗時，回傳各 variants 的比較回答。

## 2026-06-23 實作自動化評估即時串流 (SSE Streaming) 與問答上限限制

### 修改內容
1. `backend/routers/evaluation.py`:
   - 修改 `POST /run` 評估路由。限制評估問答項目最大上限為 5 筆（使用 `dataset.items[:5]`），並回傳 `StreamingResponse`。
   - `StreamingResponse` 中定義 `event_generator()` 異步產生器，以 Server-Sent Events (SSE) 協議向前端推送狀態事件：
     - `event: init`：發送評估總筆數與測試集名稱。
     - `event: progress`：發送當前正在評估的問答索引與問題文字。
     - `event: item_done`：發送當前問題經 RAG 向量檢索、AI對答生成及 LLM-as-a-Judge 評分完成後之詳細結果（含有 generated_answer 與每項評分 metrics）。
     - `event: result`：發送最終評估總分數與所有明細，並將評估報告持久化儲存至 MongoDB。

## 2026-06-23 實作 RAG 準確度評估自動化系統

### 修改內容
1. `backend/models/mongodb.py`:
   - 新增 `seed_default_datasets` 異步方法。在系統啟動時若發現資料庫無測試集資料，則自動寫入「技術規格測試集」與「人事規章測試集」，以供使用者立即開始進行 RAG 評估。
2. `backend/routers/evaluation.py`:
   - 將原本的 Stub 接口重構為實質功能。
   - `GET /datasets`：返回測試集清單，並依測試集名稱將 ID 動態轉為 `"dataset_tech"` 與 `"dataset_hr"` 以對接前端的硬編碼設定。
   - `POST /datasets`：實作測試集新增與匯入功能，並寫入 MongoDB `test_datasets` 集合。
   - `POST /run`：解析傳入的測試集與知識庫 ID（支援 dummy ID 與真實 ID 解析）。針對每筆測試問答執行真實 RAG 向量檢索與生成，再呼叫後端 LLM 執行 LLM-as-a-Judge 計算 Faithfulness、Relevancy、Precision 與 Recall，最終計算平均分並保存為 `EvalReport` 紀錄返回。
   - `GET /reports/{report_id}`：實作讀取指定評估報告詳情。

## 2026-06-23 修正無參考資料時 AI 的回覆規則

### 修改內容
1. `backend/routers/rag.py`:
   - 修改 `system_prompt` 邏輯。當 `context_str` 為空（無參考資料）時，設定 System Prompt 強制要求 AI 僅直接回答『知識庫沒有相關資訊。』。
   - 當 `context_str` 不為空但參考資料不足以回答問題時，亦要求 AI 直接回答『知識庫沒有相關資訊。』，禁止使用既有知識回答或編造內容。

## 2026-06-22 新增 Qdrant 標籤 (Tags) 寫入與過濾功能

### 修改內容
1. `backend/services/qdrant_service.py`:
   - 擴充 `search_similar` 方法，新增 `filter_tags` 參數。若有指定標籤篩選，則動態構建 Qdrant 的 `models.Filter(must=[FieldCondition(key="tags", match=MatchAny(any=filter_tags))])` 篩選條件，實現高效 Pre-filtering。
   - 在搜尋回傳的 metadata 中加入 `tags` 欄位。
2. `backend/schemas/retrieval.py`:
   - 於 `SearchParams` 中新增 `filter_tags: Optional[List[str]]`。
   - 於 `RetrievalMetadata` 中新增 `tags: Optional[List[str]]`。
3. `backend/routers/retrieval.py`:
   - 在 `/search` 與 `/query-transform` 路由中，將 `filter_tags` 傳入 `search_similar`，並將回傳的標籤對應至回應。
4. `backend/routers/rag.py`:
   - 於 `ChatParams` 中新增 `filter_tags: Optional[List[str]]`，並在 RAG 串流中傳入相似度檢索，並隨 `sources` 回傳給前端。
5. `backend/routers/embedding.py`:
   - 修正向量化寫入時遺漏標籤之 Bug：在將 Chunks payload 寫入 Qdrant 以前，顯式自 `chunk.metadata` 提取 `tags` 寫入 Qdrant 的 payload。

## 2026-06-22 支援 vLLM 思考模式/推理解析

### 修改內容
1. `backend/routers/rag.py`:
   - 調整 `rag_chat_stream` 產生器，在提取 `choices[0].delta` 時，支援從 `reasoning_content`、`thought` 或 `reasoning` 多個欄位提取思考區塊，確保對不同 vLLM 版本或推論引擎具有最大相容性。
   - 若有思考區塊，會以符合 SSE 協議之 `event: chunk` 流式推送 `type: 'reasoning'` 的 JSON 片段給前端，讓前端能夠獨立呈現思考過程。

## 2026-06-22 實現 RAG 串接真實 vLLM 推論與 Qdrant 檢索服務

### 修改內容
1. `backend/routers/rag.py`:
   - 移除原有的模擬對話產生器 (`mock_chat_stream`)，改用真實的對話流 `rag_chat_stream`。
   - 整合 `EmbeddingService` 提問向量化與 `QdrantService.search_similar` 向量檢索：如果請求包含 `knowledge_base_id` 則自動從對應 Collection 檢索相似文檔區塊 (Chunks) 並整合成 Context。
   - 串接 `LLMService.chat_completion(..., stream=True)`：將組裝好的 Prompt (含 Context) 與聊天歷史併同呼叫外部 vLLM 服務（`.env` 指定的 `10.10.130.45:8080/v1`），實現即時串流生成回答。
   - 以符合 SSE 協議之 `event: chunk` 與 `event: sources` 流式推送字元片段及參考來源引用給前端。

## 2026-06-22 實現 RAG 對話串流模擬 (Mock SSE Stream)


### 修改內容
1. `backend/routers/rag.py`:
   - 定義 `ChatRequest`、`ChatHistoryItem`、`ChatParams` 等 Pydantic Schema，符合 `/api/rag/chat` 的請求規格。
   - 實作符合 Server-Sent Events (SSE) 規格之 `mock_chat_stream` 產生器，能根據使用者問題（例如含有「分機」時回傳 Markdown 團隊分機表，其他則回傳參數摘要與問候）提供模擬的回答與參考文檔引用 (Sources)。
   - 回傳 `StreamingResponse` 搭配 `text/event-stream` 格式，讓前端 `chatStore` 可正確以串流形式接收並渲染，提供高保真的 RAG 端到端介面測試。
   - 新增 `DELETE /history/{session_id}` 模擬路由以符合刪除歷史對話 API 合約。


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