<!-- BUG修正 -->

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
