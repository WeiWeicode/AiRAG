<!-- BUG修正 -->

## 2026-06-23 修正無向量條件之 Scroll 檢索產生的 Record 物件無 score 屬性錯誤 (導致檔名/標籤純篩選查不到資料)

### 問題描述
在「Prompt 測試」或檢索搜尋時，若未輸入查詢關鍵字（即 Query 為空）但有設定「篩選檔案名稱」或「篩選標籤」，後端會跳過向量生成並執行 Qdrant 的 `client.scroll`。由於 `client.scroll` 回傳的點為 `Record` 物件而非向量檢索的 `ScoredPoint` 物件，而 `Record` 物件本身並無 `.score` 屬性，導致後端存取 `res.score` 時拋出 `AttributeError: 'Record' object has no attribute 'score'` 異常，最後使檢索結果回傳空陣列（查不到資料）。

### 解決方案
1. **安全讀取屬性**：修改 `backend/services/qdrant_service.py` 中的 `search_similar` 邏輯，對於每一個點物件使用 `getattr(res, "score", 0.0)` 進行安全讀取，並在值為 `None` 時 fallback 至 `0.0`。
2. **計算 distance**：利用安全讀取到的 `score` 重新計算 `distance = 1.0 - score`，避免直接存取無屬性的 `res.score` 造成系統崩潰。

### 修改檔案
- `backend/services/qdrant_service.py`

## 2026-06-23 修正 Prompt A/B 測試 Variant 生成長度受限 1024 Token 問題

### 問題描述
在「Prompt 測試」中，即使使用者透過右側參數面板（LlmParamsPanel）設定最大 Token 數（Max Tokens）為更高值（如 32768），A/B 測試時的回答依然會在達到 1024 tokens 時發生截斷/停住。此原因在於 `PromptTestView.vue` 的 `handleABTest` 中，傳入後端的 variants 參數裡的 `max_tokens` 被寫死（hardcoded）為 `1024`。

### 解決方案
1. **引用 paramsStore 的動態設定**：
   - 於 `frontend/src/views/PromptTestView.vue` 導入 `useParamsStore` 並進行實例化。
   - 將 `handleABTest` 中 Variant A 與 Variant B 的 payload 參數調整為 `max_tokens: paramsStore.maxTokens`，使 A/B 測試能直接讀取使用者於面板拉動的 Max Tokens 長度。

## 2026-06-23 修正 Prompt 測試與 A/B 測試預覽/生成無法連線與 Stub 模擬問題

### 問題描述
在「Prompt 測試」頁面中，點擊「預覽組合 Prompt」或「A/B 參數對照生成」會拋出連線失敗之錯誤，原因為前端 API 請求路徑（`/prompt/preview` 與 `/prompt/ab-test`）遺漏了統一的 `/api` 前綴，導致請求無法正確對接到後端對應端點；且後端 `backend/routers/prompt.py` 中該兩項 API 僅為 Stub 模擬空值，無實際渲染與 LLM 生成功能。

### 解決方案
1. **補全前端 API 前綴**：
   - 修改 `frontend/src/views/PromptTestView.vue`，將預覽組合與 A/B 參數對照的 API 請求路徑分別補正為 `/api/prompt/preview` 與 `/api/prompt/ab-test`（以 `/api` 為首）。
   - 修改 `frontend/src/components/API/prompt_api.js` 的 path，補齊 `/api` 前綴。
2. **後端實作 Prompt 渲染與估計**：
   - 重構 `backend/routers/prompt.py`，定義相關 Pydantic schemas。
   - 於 `POST /api/prompt/preview` 端點中，將 template 中的 `{context}` 與 `{question}` 以實際內容替換，並以 `length * 1.3` 作為 token 估計標準（與前端一致）返回給前端渲染。
3. **後端實作 A/B 測試大模型對比生成**：
   - 於 `POST /api/prompt/ab-test` 端點中，讀取多個 variants 參數，分別套用不同的 `system_prompt`、`user_prompt`、`temperature` 及 `max_tokens` 參數，呼叫 `LLMService.chat_completion` 取得各組大模型生成的回答，並計算與返回耗時。

### 修改檔案
- `frontend/src/views/PromptTestView.vue`
- `frontend/src/components/API/prompt_api.js`
- `backend/routers/prompt.py`

## 2026-06-23 修正 Python 3.11 環境下 Evaluation API 產生的 f-string 語法錯誤

### 問題描述
後端 Docker 容器在啟動時（採用 Python 3.11 運作環境），Uvicorn 啟動失敗並拋出 `SyntaxError: unterminated string literal`。
原因是在 `backend/routers/evaluation.py` 的第 376 行 `event: result` 的 `yield` 語句中，於雙引號 f-string（`f"..."`）中巢狀撰寫了多行的 `{json.dumps({...})}` 字典字面量，且內部包含單引號。在 Python 3.12 之前的版本中，f-string 不支援內嵌運算式跨多行或 quotes 解析限制，因此在 3.11 中編譯失敗。

### 解決方案
1. **獨立 JSON 字典宣告**：將 `result_data` 字典字面量從 f-string 運算式中完全抽離，在 `yield` 之前宣告為常規的多行 Python 字典物件。
2. **簡化 f-string 傳參**：將序列化後的 `json.dumps(result_data, ensure_ascii=False)` 以單個變數傳入 f-string，避免多行與巢狀引號衝突，維持完美的向下相容性。

### 修改檔案
- `backend/routers/evaluation.py`

## 2026-06-23 修正大模型評估指標分數全部為 0.00 之異常 (LLM-as-a-Judge 針對 Reasoning 模型的 JSON 提取異常修正)

### 問題描述
在自動化 RAG 評估執行時，雖然 LLM 生成了正常的回答，但四項指標打分（忠實度、相關性、精確率、召回率）全部呈現 `0.00`。
經診斷，後端所串接的本地 vLLM 大模型 `Qwen3.6-35B-A3B-FP8` 是一隻具有內建思考過程的 Reasoning 模型。由於 Reasoning 模型的思考鏈極其冗長，且 vLLM 預設將思考過程寫在 `choice.message.reasoning` 欄位中，導致：
1. 原本設定的 `max_tokens=256` 導致生成在思考階段就觸發長度限制中斷，`choice.message.content` 返回 `null`。
2. 即使調大 token，真正的 JSON 仍有可能寫在 `reasoning` 欄位中，而舊版 JSON 解析器只能解析 `content` 且無法容忍 JSON 外包覆的大量思考文字。

### 解決方案
1. **vLLM 思考欄位 Fallback**：修改 `backend/services/llm_service.py`，當請求非串流完成時，若 `content` 為空或 `null`，則自動 Fallback 到 `reasoning` 或 `reasoning_content` 的文字內容作為 LLM 的輸出返回。
2. **調高 Judge 最大生成長度**：在 `backend/routers/evaluation.py` 中，將 LLM-as-a-Judge 的 `max_tokens` 由 `256` 上調至 `1536`，給予充足的 Token 生成完整思考鏈及 JSON 指標。
3. **優化 JSON 提取器**：重構 `parse_judge_json` 方法，導入更強韌 (Robust) 的解析策略。先進行常規 JSON 解析，若失敗則使用正則表達式定位包含 `"faithfulness"` 欄位的完整 `{...}` JSON 結構，成功從冗長混雜的思考文字中精準擷取出打分 JSON。

### 修改檔案
- `backend/services/llm_service.py`
- `backend/routers/evaluation.py`

## 2026-06-23 修正無參考資料或參考資料不足時 AI 產生幻覺/回答既有知識之問題

### 問題描述
當 RAG 系統未檢索到任何相關參考資料，或檢索到的參考資料中不包含問題答案時，AI 仍會使用其既有知識回答，未符合僅針對知識庫內容回答的限制。

### 解決方案
1. **調整 System Prompt 規則**：
   - 修改 `backend/routers/rag.py`。當 `context_str` 為空時，System Prompt 設定為強制要求 AI 直接回覆『知識庫沒有相關資訊。』，不可輸出其他回答。
   - 當 `context_str` 有內容但資料不足以回答問題時，同樣要求 AI 直接回答『知識庫沒有相關資訊。』，防止產生幻覺或使用外部既有知識回答。

### 修改檔案
- `backend/routers/rag.py`

## 2026-06-22 自訂資料向量化失敗修正 (400 Bad Request)

### 問題描述
在「自訂資料向量化」頁面中，點擊「向量化並寫入資料庫」會拋出 `400 Bad Request` 錯誤。原因在於該頁面未提供選取知識庫的 UI，且 Pinia 中的 `knowledgeBaseId` 預設為字串 `'hr_docs'`，後端嘗試以 `PydanticObjectId` 轉換時引發格式錯誤。

### 解決方案
1. **新增知識庫選擇元件**：
   - 於 `frontend/src/components/params/ChunkingParams.vue` 引入並渲染 `<KnowledgeBaseSelector />` 元件，使自訂向量化頁面可以選擇目標知識庫。
2. **防呆自動選取與無知識庫狀態處理**：
   - 修改 `frontend/src/components/common/KnowledgeBaseSelector.vue`。獲取清單後若無可用知識庫，將選單設為 disabled 並預設為無可用知識庫提示；若有可用知識庫但目前 Pinia store 的 `knowledgeBaseId` 不存在於列表中（例如預設的 `'hr_docs'`），則自動將其設定為清單中的第一個合法知識庫 ID。
3. **後端資料庫引導種植 (Database Seeding)**：
   - 修改 `backend/models/mongodb.py`，於系統初始化時檢查 `KnowledgeBase` 集合。若其數量為 0（例如乾淨系統或測試後已清理），則自動建立一個「預設知識庫」並同步於向量資料庫 Qdrant 中建立對應的 Collection。

- `frontend/src/components/params/ChunkingParams.vue`
- `frontend/src/components/common/KnowledgeBaseSelector.vue`
- `backend/models/mongodb.py`

## 2026-06-22 修正 llama.cpp 連線設定與回傳格式解析問題

### 問題描述
當 `llama.cpp` 服務重新啟動後，本機 Docker 容器依然拋出 `Failed to generate embedding via llama.cpp: All connection attempts failed` 錯誤。原因有二：
1. `docker-compose.yml` 中的 `LLAMACPP_BASE_URL` 仍被強制覆寫為 `http://host.docker.internal:8081`（指向本機），而非使用 `.env` 中指定的外部伺服器 IP `10.10.130.45`。
2. 即使連線成功，由於新版 `llama.cpp` 的 `/embedding` 端點回傳格式為列表類型（例如 `[{"embedding": [[...]]}]`），而後端代碼中硬編碼使用 `data["embedding"]` 去取得向量，這會導致 Python 拋出 `TypeError: list indices must be integers or slices, not str`，進而觸發模擬降級防線（產出全零向量）。

### 解決方案
1. **修正 Docker Compose 覆寫**：
   - 移除 `docker-compose.yml` 下對 `VLLM_BASE_URL` 與 `LLAMACPP_BASE_URL` 的環境變數覆寫，使其直接讀取並套用 `backend/.env` 所設定的真實外部 IP（`10.10.130.45`）。
2. **重構向量解析邏輯**：
   - 修改 `backend/services/embedding_service.py` 中的 `get_embedding` 方法，加入彈性且強健的格式解析邏輯。相容於以下三種結構：
     - 新版列表包裝結構：`[{"embedding": [[...]]}]` 或 `[{"embedding": [...]}]`
     - 舊版物件包裝結構：`{"embedding": [...]}`
     - OpenAI 兼容的 vLLM 結構：`{"data": [{"embedding": [...]}]}`

- `docker-compose.yml`
- `backend/services/embedding_service.py`

## 2026-06-22 修正 AsyncQdrantClient 無 search 屬性錯誤

### 問題描述
在向量檢索搜尋測試中，後端拋出錯誤：`Failed to search similarity in Qdrant collection 'kb_...': 'AsyncQdrantClient' object has no attribute 'search'`。這是因為當前後端依賴的 `qdrant-client` 庫為較新版本，在該版本中，非同步客戶端已棄用且移除了舊版的 `.search` 方法。

### 解決方案
1. **重構搜尋 API 方法**：
   - 修改 `backend/services/qdrant_service.py` 中的 `search_similar` 方法。
   - 將原本的 `client.search` 替換為 Qdrant 新版推薦的統一查詢介面 `client.query_points`。
   - 提取回傳的 `QueryResponse` 物件中的 `points` 屬性，其內之 `ScoredPoint` 結構與舊版完全相容，維持了業務邏輯與回傳格式的完整性。

### 修改檔案
- `backend/services/qdrant_service.py`
