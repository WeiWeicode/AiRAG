<!-- 前端修正紀錄 -->

## 2026-07-02 對話視窗移除重複的檢索模式切換、補上回饋查詢法的步驟顯示

### 問題描述
1. `ChatWindow.vue` 標題列有一組「向量查詢/混合查詢/語義混合查詢」切換按鈕，與右側 `RagParamsPanel.vue` 的「檢索模式 (SEARCH MODE)」下拉選單重複（兩者皆綁定同一個 `paramsStore.searchMode`），且未同步新增的 `semantic_hybrid_feedback` 選項。
2. `chatStore.js` 的 `sendQuestion()` 僅在 `paramsStore.searchMode === 'semantic_hybrid'` 時才初始化 `steps` 陣列，導致選用「語義混合回饋查詢法」時不會顯示語義分析/檢索/思考/結論等步驟過程。

### 修改內容
1. `frontend/src/components/chat/ChatWindow.vue` (修改)：移除標題列的檢索模式切換按鈕群組，改為單純顯示「對話視窗」標籤，統一由右側 `RagParamsPanel.vue` 的下拉選單選擇查詢方式；同步移除此檔案中已無用的 `useParamsStore` 匯入。
2. `frontend/src/stores/chatStore.js` (修改)：`sendQuestion()` 判斷是否初始化 `steps` 的條件由 `searchMode === 'semantic_hybrid'` 改為 `['semantic_hybrid', 'semantic_hybrid_feedback'].includes(searchMode)`，使回饋查詢法在對話視窗中比照語義混合查詢法顯示完整的分析步驟過程（後端 `rag.py` 對此 search_type 本就會送出完整的 SSE step 事件，只是前端先前沒有建立對應的 `steps` 容器）。

## 2026-07-02 新增語義混合回饋查詢法前端串接（人工回饋與標註歷史）

### 修改內容
1. `frontend/src/components/chat/ChatWindow.vue` (修改)：`openFeedbackModal()` 額外取出該次回答的 `sources`，透過新的 `sources` prop 傳給 `FeedbackPanel`。
2. `frontend/src/components/chat/FeedbackPanel.vue` (修改)：新增 `sources` prop；送出回饋時組出 `source_chunks`（`filename`/`chunk_index`）與 `knowledge_base_id`（取自 `paramsStore.knowledgeBaseId`）一併送至後端，供回饋加權比對使用。
3. `frontend/src/components/params/RagParamsPanel.vue`、`frontend/src/views/RetrievalTestView.vue`、`frontend/src/components/eval/TestSetManager.vue` (修改)：檢索模式選單新增「語義混合回饋查詢法 (Semantic Hybrid + Feedback)」選項；`RetrievalTestView.vue` 的 `handleSearch()` 路由判斷（打 `/semantic-hybrid-search` 端點、顯示語義分析步驟 UI）同步涵蓋新選項。

### 對應規劃文件
詳細功能描述見 `docs/DevelopmentProcess/NewFeatures.md` 2026-07-02「新增語義混合回饋查詢法並補上人工回饋→檢索來源的資料鏈路」條目。

## 2026-07-01 向量管理頁面新增關聯檔案 (links_to) 管理與徽章顯示

### 修改內容
1. `frontend/src/services/retrievalService.js` (修改):
   - **新增 `updateLinks` 方法**：封裝對 `/api/retrieval/knowledge-bases/{knowledgeBaseId}/files/update-links` 端點的呼叫。
2. `frontend/src/components/embedding/VectorManagementTab.vue` (修改):
   - **新增關聯檔案選擇器**：在主檔案名稱下方，加入「設定關聯檔案 (Links To)」面板，提供多選框讓使用者挑選同個知識庫中的其他檔案建立關聯，並於修改後呼叫 `retrievalService.updateLinks` 儲存。
   - **動態狀態預載**：當選取主檔案或點選儲存後，會自動在知識庫 Metadata 中查找並還原既有的 `links_to` 關聯列表。
   - **關聯徽章渲染**：在段落列表（Chunks List）中，若該 Chunk 攜帶關聯檔案的 `links_to` 元資料，會對應渲染藍色的 `🔗 關聯檔案名稱` 徽章，以直觀展示關聯結構。