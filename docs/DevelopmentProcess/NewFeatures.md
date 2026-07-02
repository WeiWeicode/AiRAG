<!-- 新功能紀錄(最新紀錄放最前面) -->
## 2026-07-02 新增「語義混合回饋查詢法」並補上人工回饋→檢索來源的資料鏈路

### 功能描述
補完 RPD 4.6「人工回饋與標註歷史」的資料閉環：過去 `Feedback` 只記錄問答文字，並未記錄該次回答引用了哪些檢索片段，導致回饋資料無法回頭影響檢索排序。本次新增後，標註時會一併儲存來源片段（`filename` + `chunk_index`），並新增一種檢索模式 `semantic_hybrid_feedback`（語義混合回饋查詢法），在既有語義混合（Two-Step Hybrid + Instruct 語義分析 + RRF + LLM Rerank）流程最後，依歷史人工回饋對命中片段做分數加權重排。

### 實作內容
1. **回饋資料模型擴充**：
   - 修改 `backend/models/feedback.py`：新增內嵌模型 `FeedbackSourceChunk`（`filename`/`chunk_index`），`Feedback` 新增 `source_chunks`、`knowledge_base_id` 欄位，並新增 `source_chunks.filename` 索引。
   - 修改 `backend/routers/feedback.py`：`FeedbackCreate` 新增對應欄位，`create_feedback()` 寫入時一併儲存。
2. **前端送出回饋時夾帶來源片段**：
   - 修改 `frontend/src/components/chat/ChatWindow.vue`：`openFeedbackModal()` 額外取出當次回答的 `sources`，傳給 `FeedbackPanel`。
   - 修改 `frontend/src/components/chat/FeedbackPanel.vue`：新增 `sources` prop，送出回饋時組出 `source_chunks` 與 `knowledge_base_id`（取自 `paramsStore.knowledgeBaseId`）。
3. **回饋加權服務**：
   - 新增 `backend/services/feedback_boost_service.py`：`FeedbackBoostService.apply_feedback_boost()`，依 `(filename, chunk_index)` 統計歷史回饋正確/不正確次數，`boost = (正確-不正確)/(正確+不正確)`，套用 `final_score = score × (1 + FEEDBACK_BOOST_WEIGHT × boost)` 後重新排序；任何錯誤皆優雅降級為保留原排序，比照 `RerankService` 的寫法。
   - 修改 `backend/config.py`：新增可調參數 `FEEDBACK_BOOST_WEIGHT`（預設 `0.2`）。
4. **三處檢索路由接上新 search_type**：
   - 修改 `backend/routers/retrieval.py`（`search()`、`semantic_hybrid_search()`）、`backend/routers/rag.py`（`rag_chat_stream()`）、`backend/routers/evaluation.py`（評估執行迴圈）：`search_type in ("semantic_hybrid", "semantic_hybrid_feedback")` 時走既有語義混合流程，呼叫 Qdrant 服務時固定傳字面值 `"semantic_hybrid"`（Qdrant 層完全不修改），rerank 後若為 `semantic_hybrid_feedback` 則多套用一次 `FeedbackBoostService`。`rag.py` 額外在 SSE `vector_search` step 內容附註「已套用歷史回饋加權」。
5. **前端新增檢索模式選項**：
   - 修改 `frontend/src/components/params/RagParamsPanel.vue`、`frontend/src/views/RetrievalTestView.vue`、`frontend/src/components/eval/TestSetManager.vue`：新增「語義混合回饋查詢法 (Semantic Hybrid + Feedback)」選項；`RetrievalTestView.vue` 的 `handleSearch()` 路由判斷（打哪個端點、是否顯示語義分析步驟 UI）一併涵蓋新選項。

### 修改檔案
- `backend/models/feedback.py`
- `backend/routers/feedback.py`
- `backend/services/feedback_boost_service.py`（新增）
- `backend/config.py`
- `backend/routers/retrieval.py`
- `backend/routers/rag.py`
- `backend/routers/evaluation.py`
- `frontend/src/components/chat/ChatWindow.vue`
- `frontend/src/components/chat/FeedbackPanel.vue`
- `frontend/src/components/params/RagParamsPanel.vue`
- `frontend/src/views/RetrievalTestView.vue`
- `frontend/src/components/eval/TestSetManager.vue`

## 2026-07-01 向量管理頁面新增關聯檔案 (links_to) 管理與顯示功能

### 功能描述
在向量管理頁面中，點選主要檔案後可額外選取多個關聯檔案，並批次寫入對應點位的 `links_to` 欄位中，以便支援雙階段檢索（Two-Step Hybrid Retrieval），同時在段落列表上顯示關聯檔案徽章。

### 實作內容
1. **後端 Qdrant 批次更新**：
   - 修改 `backend/services/qdrant_service.py`：新增 `update_links_to_by_filename` 類別方法，利用 Scroll API 拉取該檔案所有 Chunks 的 Point ID，再呼叫 `set_payload` API 批次更新這些點位的 `links_to` 欄位。
2. **後端 API 路由與 Schema**：
   - 修改 `backend/schemas/retrieval.py`：新增 `UpdateLinksRequest` 模型。
   - 修改 `backend/routers/retrieval.py`：新增 `/knowledge-bases/{knowledge_base_id}/files/update-links` POST 端點。
3. **前端 API 與 UI 串接**：
   - 修改 `frontend/src/services/retrievalService.js`：新增 `updateLinks` 方法調用。
   - 修改 `frontend/src/components/embedding/VectorManagementTab.vue`：
     - 新增多選關聯檔案編輯區（Links To），自動從 Metadata 中讀取並同步既有之關聯檔案關係。
     - 在 Chunks 列表上為具備 `links_to` 的 Chunk 繪製藍色關聯徽章。

### 修改檔案
- `backend/services/qdrant_service.py`
- `backend/schemas/retrieval.py`
- `backend/routers/retrieval.py`
- `frontend/src/services/retrievalService.js`
- `frontend/src/components/embedding/VectorManagementTab.vue`

## 2026-07-01 新增雙階段關聯檢索與防幻想語意分析層系統

### 功能描述
實作具備 Graph RAG 概念的「雙階段關聯檢索」與「防幻想語意分析層」系統，優化語意混合檢索的上下文命中率與抗幻想能力。

### 實作內容
1. **語意分析層 (Query Rewriter) Prompt 優化**：
   - 修改 `backend/services/embedding_service.py`：在 `query_to_semantic_json` 的 System Prompt 中加入嚴格的反幻想限制宣告，並提供對比鮮明的 3 個 Few-Shot 範例（Good/Bad），使重寫後的 `embeddings_input` 與 `sparse_keywords` 專注於核心實體檢索特徵，避免模型擅自腦補背景。
2. **Qdrant Indexing / Payload 關聯欄位擴充**：
   - 修改 `backend/services/qdrant_service.py` (`upsert_semantic_json_chunks`) 與 `backend/routers/embedding.py` (`/vectorize` 路由)：寫入 Qdrant 點位時，手動在 Payload 中寫入 `links_to` (關聯檔案名稱或自訂 Point ID) 與 `class` 清單。
3. **雙階段檢索機制 (Two-Step Hybrid Retrieval) 實作**：
   - 修改 `backend/services/qdrant_service.py`：新增 `search_similar_two_step` 類別方法。第一階段呼叫 `search_similar` 取得 core point；第二階段提取點位的 `links_to` 陣列，使用 Qdrant Scroll API 拉取這些關聯的一階鄰居點位 (2nd-hop Search)。最後對鄰居點位執行 parent_id 合併還原，並與 core points 合併進行嚴格的內容 `.strip()` 去重後回傳。
4. **API 與 RAG 流程整合**：
   - 修改 `backend/schemas/retrieval.py`：在 `RetrievalMetadata` 中新增 `links_to` 欄位。
   - 修改 `backend/routers/rag.py` 的對話串流與 `backend/routers/retrieval.py` 的 `/search`、`/semantic-hybrid-search` 路由，當啟用語義混合查詢 (`search_type == "semantic_hybrid"`) 時，調用 `search_similar_two_step` 取代原本的一階段 hybrid 檢索，並將關聯欄位輸出。
5. **單元測試建立**：
   - 新增 `tests/test_two_step_search.py` 測試檔案，對雙階段檢索進行 Mock 測試，模擬無 link、有 link 及重複內容去重的各種檢索情境，確保功能完整性。

### 修改檔案
- `backend/services/embedding_service.py`
- `backend/services/qdrant_service.py`
- `backend/routers/embedding.py`
- `backend/routers/rag.py`
- `backend/routers/retrieval.py`
- `backend/schemas/retrieval.py`
- `tests/test_two_step_search.py` (新設)
