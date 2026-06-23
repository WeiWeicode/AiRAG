<!-- 新增功能紀錄 -->

## 2026-06-23 新增 Qdrant 雙路召回與 RRF 混合檢索 (Hybrid Search) 功能

### 功能描述
實作結合「密集語意向量 (Dense Vector) 檢索」與「稀疏關鍵字向量 (Sparse Vector / SPLADE) 檢索」的雙路融合檢索（Hybrid Search）。以 Qdrant 的 Reciprocal Rank Fusion (RRF) 整合兩路檢索結果，顯著提升專有名詞與精確型號、關鍵字的查詢準確度。

### 實作內容
1. **依賴管理**：
   - 於 `backend/requirements.txt` 中新增 `fastembed>=0.3.0` 套件依賴，以高效地生成語意與詞頻稀疏向量。
2. **稀疏向量產生模組**：
   - 新建 `backend/services/sparse_embedding_service.py`，封裝 `fastembed.SparseTextEmbedding` (預設為 SPLADE) 生成器，支援單筆與批次文字的稀疏向量生成。
3. **向量庫 Schema 與寫入更新**：
   - 修改 `backend/services/qdrant_service.py`：
     - `create_collection`：在建立 Collection 時定義命名空間 `"sparse-text"` 及其對應的稀疏索引。
     - `upsert_chunks`：變更資料寫入的 Vector 結構，呼叫 `SparseEmbeddingService` 自動批次計算並儲存對應的稀疏向量。
4. **雙路檢索與安全降級 (Fallback)**：
   - 修改 `search_similar` 介面：支援 `search_type` 與原始 `query_text` 參數。
   - 當 `search_type` 為 `"hybrid"` 時，同時預檢索 Dense 與 Sparse 兩路，再利用 Qdrant `FusionQuery(fusion=models.Fusion.RRF)` 計算最佳綜合排序。
   - 增加安全降級防線：若因舊 Collection 不支援或其他未知異常，會自動捕捉例外並降級為常規純向量搜尋，保障高可用性。
5. **RAG 對話與檢索 API 銜接**：
   - 修改 `backend/routers/retrieval.py` 與 `backend/routers/rag.py` 路由，將前端發送的 `search_type`（混合/向量）參數穿透傳遞給底層檢索引擎，使對話串流與獨立檢索都支援 Hybrid 模式。

### 修改檔案
- `backend/requirements.txt`
- `backend/services/sparse_embedding_service.py` (新設)
- `backend/services/qdrant_service.py`
- `backend/routers/retrieval.py`
- `backend/routers/rag.py`

## 2026-06-23 新增人工回饋紀錄單筆刪除與批次刪除功能

### 功能描述
為「人工回饋與標註歷史」頁面擴充紀錄清理與刪除功能，支援單筆回饋紀錄刪除，以及多選核取方塊後的批次刪除，以便於管理與整理匯入測試集前的標註數據。

### 實作內容
1. **後端刪除 API 實作**：
   - 實作 `DELETE /api/feedback/{feedback_id}` 端點，用於刪除指定的單一回饋紀錄。
   - 實作 `POST /api/feedback/batch-delete` 端點，以接收包含多個 ID 的 payload，進行安全的 MongoDB 批次刪除。
2. **前端 Store 狀態對接**：
   - 在 Pinia Store (`feedbackStore.js`) 中新增 `deleteFeedback` 與 `batchDeleteFeedbacks` Actions 以連接後端刪除端點。
3. **前端 UI 與操作交互**：
   - 在 `FeedbackView.vue` 列表的標題操作列新增「刪除選取」按鈕，並於多選 checkbox 有勾選時啟用，點擊後會彈出確認視窗，執行完成後清空選取狀態並重新載入列表。
   - 在表格每行末尾新增一個「操作」欄位，擺放紅色的垃圾桶按鈕以支援單筆刪除。

### 修改檔案
- `backend/routers/feedback.py`
- `frontend/src/stores/feedbackStore.js`
- `frontend/src/views/FeedbackView.vue`

## 2026-06-23 新增 Prompt 測試多源引用與 A/B 測試結果歷史存檔系統

### 功能描述
為「Prompt 測試」頁面擴充四項大幅提升調優效率之進階功能，支援範本與測試結果的 MongoDB 歷史存檔、引導載入預設 RAG 範本、針對 Qdrant 知識庫執行即時向量檢索多選注入、以及引用評估集問題（並能聯動載入標準答案與相關上下文）。

### 實作內容
1. **測試歷史與範本存檔**：
   - 後端新增 `PromptTestRecord` MongoDB 資料模型，紀錄 System Prompt、User Template、Context、Question 與 A/B 測試 Variant 的生成 answer、elapsed_ms 與 parameters。
   - 提供 `GET /api/prompt/records`、`POST /api/prompt/records`、`DELETE /api/prompt/records/{id}` 對應 API。
   - 前端點擊「儲存本次測試與結果」可為本次結果命名存檔；點擊「檢視歷史紀錄」彈出暗色玻璃擬物 Modal，顯示歷史列表，並提供「還原參數」與「刪除」功能。
2. **預設/自訂範本引用機制**：
   - 後端在 `mongodb.py` 初始化中實作 `seed_default_prompt_templates()`，若資料庫為空則自動載入「預設 RAG 助手」與「嚴格知識問答」兩款內建範本。
   - 提供 `GET /api/prompt/templates`、`POST /api/prompt/templates`、`DELETE /api/prompt/templates/{id}` 等範本 API。
   - 前端 System Prompt 設定上方新增「載入範本」與「儲存為範本」按鈕。點選載入可彈出視窗並套用範本，非預設範本可執行刪除。
3. **Qdrant 知識庫 Chunk 段落多選引用**：
   - 前端 Context 上方新增「檢索並引用 Qdrant Chunks」按鈕。
   - 點選彈出 Modal 視窗，使用者可選擇系統內現有 Knowledge Base，輸入關鍵字後呼叫後端 `/api/retrieval/search` 進行真實向量檢索。
   - 以相似度排序顯示 Chunks，支援多選 Checkbox，確認後自動將所選段落附帶檔名與頁碼以 `\n---\n` 串接注入 Context 輸入框。
4. **評估集問題引用**：
   - 前端 User Query 上方新增「引用評估集問題」按鈕。
   - 點選彈出 Modal 視窗，使用者可選擇測試集並自動加載問答清單。
   - 點擊特定項目即填入問題，並提示是否一併將該問答對應的標準答案 (Ground Truth) 與 relevant contexts 追加載入 Context 輸入框。

### 修改檔案
- `backend/models/prompt_test_record.py` (新設)
- `backend/models/mongodb.py`
- `backend/routers/prompt.py`
- `frontend/src/views/PromptTestView.vue`