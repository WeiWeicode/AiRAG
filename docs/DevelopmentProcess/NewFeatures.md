<!-- 新功能紀錄(最新紀錄放最前面) -->
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
