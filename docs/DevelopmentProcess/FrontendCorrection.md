<!-- 前端修正紀錄 -->

## 2026-07-06 程式碼複查：向量管理頁附件關聯徽章改顯示實際檔名

### 問題描述
`frontend/src/components/embedding/VectorManagementTab.vue` 的「Linked Attachments Badges」區塊每個徽章文字都寫死「📎 附件關聯」，`title` 也只放原始 `Attachment._id`，使用者無法從畫面上一眼看出這個 chunk 到底關聯了哪個附件。

### 修改內容
1. `frontend/src/components/embedding/VectorManagementTab.vue`：新增 `getAttachmentName(attachmentId)`，對照既有的 `allAttachments` 清單還原成附件的 `original_filename`（找不到時 fallback 回原始 id），徽章文字改為 `📎 {{ getAttachmentName(aid) }}`。

### 驗證
- 程式碼審閱確認 `allAttachments` 已在 `onMounted`/知識庫切換時載入，徽章渲染時能正確對照到檔名。

### 對應規劃文件
`docs/DevelopmentProcess/AttachmentSemanticHybridSearchPlan.md` 第 8.5 節。

## 2026-07-06 程式碼複查：附件下載改用帶驗證的 blob 下載，取代 window.open

### 問題描述
配合後端恢復附件下載端點的身份驗證（見 `docs/DevelopmentProcess/BackendCorrection.md` 同日條目），原本 `MessageBubble.vue`／`AttachmentManagerTab.vue` 都是用 `window.open(url, '_blank')` 開新分頁下載，這種方式無法夾帶 SPA 的 `Authorization: Bearer <token>` 標頭，端點恢復驗證後會直接跳出 401 錯誤。

### 修改內容
1. `frontend/src/services/attachmentService.js`：新增 `download(id, filename)` 方法，改用 `api.get(url, { responseType: 'blob' })`（會經過既有 axios 攔截器自動夾帶 Bearer token）取得檔案內容，再用 `URL.createObjectURL` + 暫時的 `<a download>` 元素觸發瀏覽器另存新檔，完成後 `revokeObjectURL` 釋放資源。
2. `frontend/src/components/chat/MessageBubble.vue`：`downloadAttachment()` 改為呼叫 `attachmentService.download(id, filename)`，不再自行組字串呼叫 `window.open`。
3. `frontend/src/components/embedding/AttachmentManagerTab.vue`：`handleDownload()` 同上，改呼叫 `attachmentService.download(id, filename)`。

### 驗證
- 後端下載端點恢復驗證後，兩處下載按鈕仍能正常觸發瀏覽器下載，且下載檔名為附件原始檔名。

### 對應規劃文件
`docs/DevelopmentProcess/AttachmentSemanticHybridSearchPlan.md` 第 8.1 節。

## 2026-07-06 修正儲存附件關聯 (update-attachments) 請求回傳 404 Not Found 之問題

### 問題描述
使用者實測將附件與主檔案進行關聯時，點選儲存出現「儲存關聯附件失敗」的錯誤提示，且瀏覽器網路面板顯示 `POST http://localhost:53010/api/knowledge-bases/{kb_id}/files/update-attachments 404 Not Found`。
原因為後端將該端點定義於 `/api/retrieval` 路由群組下（完整路徑為 `/api/retrieval/knowledge-bases/{kb_id}/files/update-attachments`），但前端的 `retrievalService.js` 中呼叫此端點的 URL 漏掉了 `/retrieval` 前綴，導致發送了錯誤的路由請求。

### 修改內容
1. `frontend/src/services/retrievalService.js` (修改)：
   - 將 `updateAttachments` 中的請求路徑由 `/api/knowledge-bases/...` 修正為 `/api/retrieval/knowledge-bases/...`。
2. 執行 `npm run build` 重新編譯前端靜態資源。

### 驗證
- 重新建置前端後，附件關聯儲存功能可正常呼叫後端 API 並回傳成功。

## 2026-07-06 修正附件管理與向量管理中附件列表未渲染與刪除失敗之問題

### 問題描述
使用者實測發現，新上傳的附件沒有出現在清單中，且清單中會出現兩個空的 (NaN KB) 的無說明描述卡片，且點選刪除時會報錯 `DELETE /api/attachments/undefined 400 (Bad Request)`。
主要原因為：
1. **API 回傳結構映射錯誤**：後端 `/api/attachments` API 回傳的是 `AttachmentListResponse`（格式為 `{"items": [...], "total": N}`），但前端在 `AttachmentManagerTab.vue` 與 `VectorManagementTab.vue` 中，直接將 `attachmentService.list()` 回傳的整個 Response 物件指給 `attachments.value` 與 `allAttachments.value` 陣列，導致 `v-for` 迭代了 Response 物件的 `items` 和 `total` 兩個 key，造成渲染出兩個欄位全部為 `undefined` 且 ID 亦為 `undefined` 的空項目。
2. **檔案大小欄位綁定錯誤**：後端 `Attachment` 模型的檔案大小欄位名稱為 `size`，但前端樣板中誤寫為 `att.file_size`，造成檔案大小計算為 `NaN KB`。

### 修改內容
1. `frontend/src/components/embedding/AttachmentManagerTab.vue` (修改)：
   - `fetchAttachments` 方法改為將 `res.items || []` 賦值給 `attachments.value`。
   - 將樣板中的 `att.file_size` 修正為 `att.size`。
2. `frontend/src/components/embedding/VectorManagementTab.vue` (修改)：
   - `fetchAllAttachments` 方法改為將 `res.items || []` 賦值給 `allAttachments.value`。
3. 執行 `npm run build` 重新編譯前端靜態資源。

### 驗證
- 重新建置前端後，附件清單能正常渲染出已上傳的附件（包含正確的檔名、大小與描述），且點選刪除時能正常傳遞實體 ID 進行刪除。

## 2026-07-06 RAG 對話測試頁 Top-K 滑桿上限由 15 調整為 50

### 問題描述
上限 15 太低，不容易手動測出需要觸發 Map-Reduce 分批摘要（見 `ContextMapReduceSummaryPlan.md` 第 12.2 節）的高召回情境。

### 修改內容
`frontend/src/components/params/RagParamsPanel.vue` (修改)：Top-K 滑桿 `max` 由 `15` 改為 `50`（`min="1"` 不變）。`frontend/src/views/RetrievalTestView.vue` 的獨立 Top-K 滑桿（`max="20"`）未一併調整，範圍不同、非本次需求。

## 2026-07-06 「參考文檔引用」面板新增每個 Chunk 的 Token 數與總計/分批次數顯示

### 問題描述
後端 `sources` SSE 事件現在會夾帶 `context_summary`（總計 token、是否觸發分批摘要、切分次數/輪數）以及每個 chunk 的 `token_count`，前端需要接住並顯示，讓使用者一眼看出本次檢索的 token 使用狀況。

### 修改內容
1. `frontend/src/stores/chatStore.js` (修改)：`sources` 事件處理時把 `data.context_summary` 存進 `msg.contextSummary`；初始 assistant 訊息物件新增 `contextSummary: null`。
2. `frontend/src/components/chat/MessageBubble.vue` (修改)：`<SourceChunks>` 新增 `:context-summary="message.contextSummary"`。
3. `frontend/src/components/chat/SourceChunks.vue` (修改)：新增 `contextSummary` prop，在清單最上方顯示統計列（總計 Token；觸發時顯示「切分 N 次整理 / M 輪思考」，未觸發顯示「未超過門檻，未進行分批摘要」）；每個 chunk 項目在 `Similarity` 徽章旁新增 `Tokens: N` 徽章。

### 對應規劃文件
對應 `docs/DevelopmentProcess/ContextMapReduceSummaryPlan.md` 第 11 節。

## 2026-07-06 實作 Map-Reduce 檢索上下文分批摘要前端設定與 SSE 狀態動態呈現

### 問題描述
當 RAG 檢索召回的參考資料過多觸發後端 Map-Reduce 摘要時，前端需要能夠配置觸發門檻，且能在對話步驟區域中動態呈現 Map-Reduce 摘要的細部分批步驟與進度，以避免使用者面對超長上下文處理時無從知曉系統執行狀態。

### 修改內容
1. `frontend/src/stores/paramsStore.js` (修改)：
   - 新增 `contextSummarizeThreshold` 狀態值（預設 `50000`）。
2. `frontend/src/components/params/RagParamsPanel.vue` (修改)：
   - 在檢索設定區段中新增「分批摘要門檻 (Context Summarize Threshold)」輸入欄位與對應說明，引導使用者當檢索召回 tokens 超過此門檻時自動啟用 Map-Reduce。
3. `frontend/src/stores/chatStore.js` (修改)：
   - 變更 `sendQuestion()` 的 `steps` 初始化邏輯，所有查詢模式皆會預設初始化 `steps`，確保不管哪種模式觸發分批摘要都能有容器接收。
   - `sendQuestion()` 在發送對話 SSE 請求時，將 `context_summarize_trigger_tokens: paramsStore.contextSummarizeThreshold` 夾帶至 `params` 內送給後端。
   - 擴充對對話 SSE `event: step` 訊息的解析。如果收到後端發送的未知/動態 step 識別字（如 `context_summarize_r1_batch_1`），會動態將其 append 到 `steps` 陣列尾部，並即時更新狀態與進度說明，提供友善的互動體驗。

### 對應規劃文件
對應 `docs/DevelopmentProcess/ContextMapReduceSummaryPlan.md`。

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