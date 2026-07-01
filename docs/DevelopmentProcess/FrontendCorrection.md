<!-- 前端修正紀錄 -->

## 2026-07-01 向量管理頁面新增關聯檔案 (links_to) 管理與徽章顯示

### 修改內容
1. `frontend/src/services/retrievalService.js` (修改):
   - **新增 `updateLinks` 方法**：封裝對 `/api/retrieval/knowledge-bases/{knowledgeBaseId}/files/update-links` 端點的呼叫。
2. `frontend/src/components/embedding/VectorManagementTab.vue` (修改):
   - **新增關聯檔案選擇器**：在主檔案名稱下方，加入「設定關聯檔案 (Links To)」面板，提供多選框讓使用者挑選同個知識庫中的其他檔案建立關聯，並於修改後呼叫 `retrievalService.updateLinks` 儲存。
   - **動態狀態預載**：當選取主檔案或點選儲存後，會自動在知識庫 Metadata 中查找並還原既有的 `links_to` 關聯列表。
   - **關聯徽章渲染**：在段落列表（Chunks List）中，若該 Chunk 攜帶關聯檔案的 `links_to` 元資料，會對應渲染藍色的 `🔗 關聯檔案名稱` 徽章，以直觀展示關聯結構。