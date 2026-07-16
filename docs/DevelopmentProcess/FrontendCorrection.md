<!-- 前端修正紀錄(最新紀錄放最前面) -->

## 2026-07-16 手動建立與選擇 Qdrant 知識庫 (Knowledge Base / Collections) 實作

### 背景
依據 [`NewFeaturesPlan_ManualKnowledgeBaseCollectionsPlan.md`](NewFeaturesPlan_ManualKnowledgeBaseCollectionsPlan.md) 規劃實作前端介面與共用選單修正。

### 變更內容
- `frontend/src/stores/paramsStore.js`：將 `knowledgeBaseId` 預設值由 `'hr_docs'` 修正為 `null`，避免非法 ObjectId 字串發送造成後端 400。
- `frontend/src/components/common/KnowledgeBaseSelector.vue`：將無可用知識庫時的空選項 `value` 修正為 `''`。
- `frontend/src/components/eval/TestSetManager.vue` & `frontend/src/views/EvaluationView.vue`：引進 `KnowledgeBaseSelector` 元件，並修正評估 payload 綁定 `paramsStore.knowledgeBaseId`。
- `frontend/src/views/FeedbackView.vue`：歷史回饋表格新增「知識庫」欄位，顯示 `item.knowledge_base_name || '未指定'`。
- `frontend/src/services/knowledgeBaseService.js`（新檔）：API 客戶端封裝 `list()`、`create()`、`remove()` 知識庫操作。
- `frontend/src/views/KnowledgeBaseSettingsView.vue`（新檔）：實作知識庫建立表單、清單與已向量化段落數統計、刪除確認彈窗（包含輸入檔名二次確認），並於刪除當前選用知識庫時連動重置全域 `paramsStore.knowledgeBaseId`。
- `frontend/src/router/index.js` & `frontend/src/components/common/AppSidebar.vue`：註冊 `/knowledge-base-settings` 路由，並於側邊欄新增「知識庫管理 (Knowledge Base)」與 Database 意象 SVG 圖示。

---

## 2026-07-16 文件機密權限控管 (Confidential Document Access Control) 實作

### 背景
依據 [`NewFeaturesPlan_ConfidentialAccessControlPlan.md`](NewFeaturesPlan_ConfidentialAccessControlPlan.md) 規劃實作前端介面。新增「角色與權限設定」管理視頁與全檔「機密權限控管設定」卡片，並於 RAG / 檢索測試面板加入「模擬使用者權限測試」開關。

### 變更內容
- `frontend/src/services/userService.js`（新檔）：API 客戶端封裝部門與使用者 CRUD。
- `frontend/src/services/retrievalService.js`：新增 `updatePermissions()` 端點呼叫。
- `frontend/src/stores/paramsStore.js`：新增 `simulatedUserEnabled` 與 `simulatedUserId` 全域狀態。
- `frontend/src/router/index.js`：註冊 `/role-settings` 路由。
- `frontend/src/components/common/AppSidebar.vue`：加入「角色與權限設定」側邊欄項目。
- `frontend/src/views/RoleSettingsView.vue`（新檔）：實現部門主檔新增/刪除與模擬使用者名冊 CRUD UI（修正：對齊帶有 id 之部門物件，並於部門 Chip 加入 ✕ 刪除按鈕連結 `userService.deleteDepartment`；移除內部重複嵌入的 `<AppSidebar />` 與全頁 layout 容器，對齊全站單一 SideBar/Header 結構）。
- `frontend/src/components/embedding/VectorManagementTab.vue`：實現全檔「機密權限控管設定」卡片與 🔒 點位徽章（修正：`handleSavePermissions` 接收後端 `updated_count` 並比對全檔 `managementPoints` 總筆數，若有筆數落差主動提示警示說明，防止舊世代點位漏掃未覆蓋隱患）。
- `frontend/src/components/params/RagParamsPanel.vue` / `frontend/src/views/RetrievalTestView.vue` / `frontend/src/stores/chatStore.js`：實現模擬使用者切換選單，於請求發送 `simulated_user_id`，並渲染 `excluded_items` 隱私中繼資料摘要卡片。

---

## 2026-07-14 AI 總結門檻審查問題修正 (8.1 Early Exit 警示渲染)

### 背景
依據 [`NewFeaturesPlan_SimilaritySummaryThresholdPlan.md`](NewFeaturesPlan_SimilaritySummaryThresholdPlan.md) 8.1 審查項修復。當觸發門檻 Hard Cutoff 跳過總結時，後端以 `event: message` 送出警示訊息，但前端之前遺漏此事件處理，導致訊息泡泡為空白。

### 變更內容
- `frontend/src/stores/chatStore.js`：
  - 於 `_streamChat()` 事件處理鏈新增 `else if (currentEvent === 'message')` 分支。
  - 將接收到的 `data.delta` 設定給 `msg.content`，並同步將 conclusion 步驟設為 `success` 及填入內容，確保對話主泡泡與步驟面板皆能完整呈現「⚠️ 未執行 AI 總結...」警示說明。

---

## 2026-07-13 AI 總結相似度門檻與拒絕生成機制實作

### 背景
依據 [`NewFeaturesPlan_SimilaritySummaryThresholdPlan.md`](NewFeaturesPlan_SimilaritySummaryThresholdPlan.md) 規劃，於前端「檢索設定 (Retrieval)」新增「AI 總結門檻 (AI Summary Threshold)」獨立 Slider 控制項，並為對話視窗參考文章標記「已採納」/「未採納」狀態。

### 變更內容
- `frontend/src/stores/paramsStore.js`：
  - 新增 `aiSummaryScoreThreshold`（預設 `0.60`）與 `aiSummaryScoreThresholdEnabled`（預設 `true`）狀態。
- `frontend/src/components/params/RagParamsPanel.vue`：
  - 於「相似度閾值 (Score Threshold)」下方新增獨立的 AI 總結門檻控制項（包含啟用/關閉 Checkbox、Slider 及說明文字）。
- `frontend/src/stores/chatStore.js`：
  - 於 API 請求 payload (`/api/rag/chat`) 之 `params` 中帶入 `ai_summary_score_threshold`。若使用者關閉該控制項則自動傳遞 `0.0`（代表全部允許）。
- `frontend/src/components/chat/SourceChunks.vue`：
  - 讀取每筆 chunk metadata 之 `included_in_ai_context` 狀態，為達標項目加上「已採納」綠色徽章，未達標項目加上「未採納」紅色徽章與半透明標示。

### 驗證
- 執行 `npm run build` 成功編譯，無範本或語法錯誤。
