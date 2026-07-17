<!-- 前端修正紀錄(最新紀錄放最前面) -->

## 2026-07-17 外部 API 測試頁面 (External API Test) 前端實作

### 背景
依據 [`NewFeaturesPlan_ExternalApiTestPlan.md`](NewFeaturesPlan_ExternalApiTestPlan.md) 規劃實作。新增「外部 API 測試」頁面，重用「RAG 功能測試」既有的檢索/生成參數表單，額外提供自訂總結提示詞與即時 API JSON 預覽，送出後沿用同一套對話視窗查看 SSE 處理過程。

### 變更內容
- `frontend/src/composables/useChatStream.js`（新檔）：從 `chatStore.js` 抽出 fetch + SSE 事件（`step`/`chunk`/`sources`/`message`）解析邏輯，改吃 `{ endpoint, headers, payload, messages, assistantMessageId, setLoading }` 參數，供內部與外部對話 store 共用，避免同一段複雜邏輯維護兩份。
- `frontend/src/stores/chatStore.js`：`_streamChat()` 改為組好 payload 後呼叫 `streamChat()`，移除原本內嵌的 fetch/SSE 解析程式碼（純重構，行為不變）。
- `frontend/src/stores/paramsStore.js`：新增 `customSystemPrompt: ''` 欄位（內部 RAG 測試頁 payload 組裝本來就不會讀取，不影響既有行為）。
- `frontend/src/stores/externalChatStore.js`（新檔）：獨立於 `chatStore.js` 的對話狀態（`messages`/`isLoading`），實作 `sendQuestion()`/`clearMessages()`/`selectDbQueryProfile()` 三個同名介面；並匯出 `buildExternalChatPayload()` 純函式（供 `ApiJsonPreviewPanel.vue` 共用同一份 payload 組裝邏輯，避免預覽與實際送出各自組一次造成不一致）。`_streamChat()` 呼叫 `POST /api/external/chat`，不帶 `Authorization` 標頭。
- `frontend/src/components/chat/ChatWindow.vue`：新增可選 `store` prop（`const chatStore = props.store || useChatStore()`），元件內原有 6 處 `chatStore.*` 引用（取得 store、`isLoading`×3、`messages`、`clearMessages()`、`selectDbQueryProfile()`）皆自動改讀取注入的 store，模板與其餘邏輯不變。
- `frontend/src/components/params/CustomSystemPromptPanel.vue`（新檔）：自訂總結提示詞 `<textarea>`，`v-model="paramsStore.customSystemPrompt"`，留空則使用系統預設模板，僅放在外部 API 測試頁（未加進共用的 `LlmParamsPanel.vue`）。
- `frontend/src/components/params/ApiJsonPreviewPanel.vue`（新檔）：顯示端點網址、Headers 說明、即時組出的 Request JSON（含複製按鈕）與逐欄位白話說明，供未來提供給外部應用開發者參考。
- `frontend/src/views/ExternalApiTestView.vue`（新檔）：版面比照 `RagTestView.vue`，左側 `ChatWindow`（注入 `externalChatStore`）、右側依序排列 `RagParamsPanel`／`LlmParamsPanel`／`CustomSystemPromptPanel`／`ApiJsonPreviewPanel`。
- `frontend/src/router/index.js`：新增 `/external-api-test` 路由（`meta: { requiresAuth: true }`，此測試工具頁仍需登入內部系統才能使用）。
- `frontend/src/components/common/AppSidebar.vue`：新增「外部 API 測試 (External API)」導覽項目。

### 驗證
- `npm run build` 通過，無編譯錯誤。
- 尚待使用者於瀏覽器手動驗證實際對話流程、JSON 預覽內容與複製功能（依專案慣例不由 AI 開瀏覽器驗證）。

---

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
