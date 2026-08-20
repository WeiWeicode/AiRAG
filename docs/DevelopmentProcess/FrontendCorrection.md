<!-- 前端修正紀錄(最新紀錄放最前面) -->

## 2026-08-20 圖片檔案稽核頁面：自訂每頁筆數與一鍵清除全部孤兒檔

### 背景
孤兒檔多達數千筆，固定每頁 20 筆且只能逐頁勾選刪除，實務上無法清空。

### 變更內容
- `frontend/src/views/ImageAuditView.vue`：
  - 以 `pageSize`（可選 20/50/100/200，預設 20）取代固定的 `PAGE_SIZE`；切換筆數時自動回到第 1 頁並補載縮圖。
  - 分頁列改為只要清單非空就顯示，新增「第一頁 / 最後一頁」按鈕與「共 N 筆」顯示。
  - 孤兒檔工具列新增「一鍵清除全部 (N)」按鈕（N 為目前允許刪除的孤兒檔數，近期檔案需勾選「允許勾選近期檔案」才計入）；沿用原本輸入 `DELETE` 的二次確認彈窗，並依 `deleteMode` 切換標題與說明（一鍵清除模式改顯示範圍說明與耗時提醒，不列檔名清單）。
  - 縮圖載入由逐張 `await` 改為每批 6 張並行，並以 `thumbLoadToken` 中止換頁後的過期載入、回收已產生的 blob URL（每頁 200 筆時逐張載入過慢）。
- `frontend/src/services/imageAuditService.js`：`cleanup(filenames, includeRecent)` 帶出 `include_recent`；新增 `cleanupAll(includeRecent)` 呼叫 `delete_all_orphans=true`（不需把數千筆檔名送上去）。
  - 附帶修正：原本「允許勾選近期檔案」只放行前端勾選，後端仍一律以 `recent_file` 跳過，勾了也刪不掉；現在該狀態會傳給後端。

### 驗證
- 執行 `npm run build` 成功編譯，無範本或語法錯誤。


## 2026-08-18 新增圖片檔案稽核頁面 (`/image-audit`)

### 背景
配合 [NewFeaturesPlan_ImageFileAuditPlan.md](NewFeaturesPlan_ImageFileAuditPlan.md)，
新增比對 Qdrant 圖片段落與地端圖片資料夾的維運頁面。設計決策見
[NewFeatures.md](NewFeatures.md) 2026-08-18 條目。

### 變更內容
- `frontend/src/services/imageAuditService.js`（新增）：`scan(refresh)` / `cleanup(filenames)`。
- `frontend/src/views/ImageAuditView.vue`（新增）：
  - 四張統計卡（磁碟檔案 / 向量引用 / 孤兒檔 / 遺失檔）。「向量引用」刻意同時顯示
    **檔名數與段落數**——同一張圖可被多個 point 引用，只顯示一個數字會對不起來。
  - 三個分頁：孤兒檔（可勾選 + 批次刪除）、遺失檔（唯讀，附「複製 Point ID」）、正常（唯讀，
    引用數 > 1 可展開看全部引用）。每頁 20 筆。
  - **縮圖必須走 blob URL**：`/api/embedding/images/{filename}` 掛在 `embedding` router 下，
    有 `Depends(get_current_user)`，`<img src>` 直接指過去瀏覽器不會帶 Authorization header → 401。
    因此改用既有的 `imageService.fetchImageBlobUrl()`（axios 帶 token），只載入當前分頁的縮圖，
    切分頁 / `onUnmounted` 時 `revokeObjectURL()`。遺失檔分頁不發請求（必然 404），顯示佔位方塊。
  - `is_recent` 的檔案（mtime 在保護期內，可能是進行中的向量化任務產物）預設 checkbox disabled，
    需另外勾「允許勾選近期檔案」才放行；關掉該開關時會一併移除已選取的近期檔案。
  - 掃描回傳的 `errors[]` 非空時顯示琥珀色警示並**停用刪除按鈕**（孤兒判定不完整時不准清理）。
  - 刪除二次確認 modal 要求手動輸入 `DELETE`（比照 `KnowledgeBaseSettingsView.vue` 的
    `confirmInput` 做法），列出前 10 筆檔名；完成後依後端回傳的 `skipped` 分類明確提示
    「N 筆在確認期間被重新引用」「N 筆無法複驗」「N 筆為近期檔案」。
  - **不提供「一鍵刪除全部孤兒檔」的無確認捷徑。**
- `frontend/src/router/index.js`：新增 `/image-audit` route（`requiresAuth: true`）。
- `frontend/src/components/common/AppSidebar.vue`：`menuItems` 新增「圖片檔案稽核 (Image Audit)」，
  置於「知識庫管理」之後。

### 驗證
`npm run build` 通過（427 modules）。實際頁面行為由使用者手動測試。

---

## 2026-07-30 新增集團知識庫混合查詢法 (`KB_hybrid`) 前端介面支援

### 背景
配合 [NewFeaturesPlan_KBHybridPlan.md](NewFeaturesPlan_KBHybridPlan.md) 規劃，在對話參數設定、
檢索測試、API 預覽與測試集管理介面加入 `KB_hybrid` 檢索模式。

### 變更內容
- `frontend/src/components/params/RagParamsPanel.vue`：
  - 檢索模式下拉選單新增 `<option value="KB_hybrid">集團知識庫混合查詢 (KB Hybrid)</option>`，
    位置緊接 `KB_semantic_hybrid` 之後。
  - 「多輪對話指代消解／手動鎖定檔案」面板的 `v-if` 清單加入 `KB_hybrid`，但面板內的
    **「自動指代消解」與「指代消解歷史則數」兩個欄位各自加上 `v-if="searchMode !== 'KB_hybrid'"`**：
    自動指代消解是把對話歷史帶進語義 JSON 轉換步驟，`KB_hybrid` 已無該步驟故勾了不會有作用，
    隱藏以免誤解；而「手動鎖定檔案」對應的 `filter_filename` 在後端是不分模式的通用邏輯，
    對 `KB_hybrid` 仍然有效，因此保留顯示（依使用者確認之決策）。
- `frontend/src/views/RetrievalTestView.vue`：
  - 下拉選單新增 `KB_hybrid` 選項。
  - 分數標籤與 Distance 顯示判斷清單加入 `KB_hybrid`（該模式確實走 RRF 融合，應顯示 RRF Score）。
  - **未**加入 `isSemanticHybridFamily`／`semanticSteps` 清單：`KB_hybrid` 維持呼叫
    `retrievalService.search()`（對應 `/api/retrieval/search`），不顯示語義分析步驟卡片。
- `frontend/src/components/params/ApiJsonPreviewPanel.vue`：
  - `fieldDocs` 的 `params.search_type` 說明文字加入 `KB_hybrid`。
- `frontend/src/components/eval/TestSetManager.vue`：
  - 下拉選單新增 `KB_hybrid` 選項（僅供測試集標記，批次評估邏輯未串接）。

### 未修改
- `frontend/src/stores/chatStore.js`：`search_type`／`pinned_filename` 本來就無條件依
  `paramsStore` 送出，不需為新模式增加分支。

### 驗證
- ⚠️ 介面顯示與 JSON Payload 待使用者手動測試確認。

---

## 2026-07-24 新增集團知識庫專用語義混合查詢法 (`KB_semantic_hybrid`) 前端介面支援

### 背景
配合 [NewFeaturesPlan_KBSemanticHybridPlan.md](NewFeaturesPlan_KBSemanticHybridPlan.md) 規劃，在前端對話參數設定、檢索測試、API 預覽與測試集管理介面中加入 `KB_semantic_hybrid` 檢索模式選單與邏輯支援。

### 變更內容
- `frontend/src/components/params/RagParamsPanel.vue`：
  - 檢索模式下拉選單新增 `<option value="KB_semantic_hybrid">集團知識庫語義混合查詢 (KB Semantic Hybrid)</option>`。
  - 將 `KB_semantic_hybrid` 加入 `isSemanticHybridFamily` 判斷，自動為該模式開啟指代消解與手動鎖定檔案面板。
- `frontend/src/views/RetrievalTestView.vue`：
  - 下拉選單新增 `KB_semantic_hybrid` 選項。
  - 更新語義分析步驟 (Steps) 載入條件與分數標籤 (RRF Score) 顯示。
- `frontend/src/components/params/ApiJsonPreviewPanel.vue`：
  - `fieldDocs` 的 `params.search_type` 加入 `KB_semantic_hybrid` 註解。
- `frontend/src/components/eval/TestSetManager.vue`：
  - 下拉選單新增 `KB_semantic_hybrid`。

### 驗證
- 對話與檢索測試頁面可順利選擇 `KB_semantic_hybrid` 模式並產生正確之 JSON Payload。

---

### 背景
當單獨重啟或升級後端容器 (`docker-compose up --build -d backend`) 時，後端容器獲得新的容器 IP。但因 `nginx.conf` 原先直接撰寫 `proxy_pass http://backend:53020;`，Nginx 在啟動時靜態快取了舊 IP，導致 Nginx 無法連線至新 IP 的後端服務而回傳 `502 Bad Gateway`。

### 變更內容
- `nginx.conf`：
  - 加入 Docker 內建 DNS 伺服器解析器設定：`resolver 127.0.0.11 valid=10s ipv6=off;`。
  - 將 `/api` 與 `/health` location 的 `proxy_pass` 改為透過變數 `set $backend_upstream http://backend:53020; proxy_pass $backend_upstream;`，確保 Nginx 每次連線時皆能動態解析最新容器 IP。

### 驗證
- `docker exec airag-frontend nginx -t` 語法測試通過。
- `docker exec airag-frontend nginx -s reload` 設定重新載入成功。
- `curl http://localhost:53010/health` 測試成功回傳 `200 OK {"status":"healthy"}`。

---

## 2026-07-23 「已向量化資料管理」元資料強制刷新與重新整理按鈕優化

### 背景
外部 Ingest API 寫入檔案後，前端「已向量化資料管理與刪除」頁面因預設使用快取的 `GET /metadata` 端點，且「重新整理 / 載入」按鈕原本僅綁定點位載入 (`loadManagementPoints`)，導致點擊按鈕或外部寫入後下拉選單無法即時出現新檔名。

### 變更內容
- `frontend/src/components/embedding/VectorManagementTab.vue`：
  - `fetchManagementMetadata(refresh = false)`：支援 `refresh: bool` 參數，帶入 `true` 時請求 `/api/knowledge-bases/{id}/metadata?refresh=true` 強制後端清空快取掃描 Qdrant。
  - 新增 `handleReload()` 處理函式，當點擊「重新整理 / 載入」按鈕時同時刷新檔案下拉選單與已選選單點位。
  - 將「重新整理 / 載入」按鈕的 `:disabled` 限制改為僅 `isLoadingManagement` 時禁用，允許使用者在未選擇檔案前即可點擊刷新下拉選單。

### 驗證
- 變更已編譯通過。

---

## 2026-07-17 外部 API 真實使用者身分、API Key 管理介面前端實作

### 背景
依據 [`NewFeaturesPlan_ExternalApiTestPlan.md`](NewFeaturesPlan_ExternalApiTestPlan.md) 第 8～12 節實作。外部 API 測試頁改用真實使用者身分欄位取代模擬使用者 ID，並新增 API Key 管理介面。

### 變更內容
- `frontend/src/services/userService.js`：`createDepartment(name, code)` 新增代號參數。
- `frontend/src/services/externalApiKeyService.js`（新檔）：`list()`/`create(name)`/`remove(id)` 對應 `/api/external-api-keys` CRUD。
- `frontend/src/views/RoleSettingsView.vue`：
  - 部門新增表單加上「部門代號」輸入欄位，部門 Chip 顯示代號。
  - 新增「外部 API 金鑰管理」區塊（Panel 3）：建立金鑰表單、清單表格（名稱/前綴/狀態/建立時間/最後使用時間）、刪除按鈕；新建立的金鑰明碼以醒目提示框顯示一次並提醒立即保存。
- `frontend/src/components/embedding/VectorManagementTab.vue`：`fetchDepartments()` 改保留 `{name, code}` 物件；「可讀取部門限制」複選框 `value` 改綁部門代號（畫面仍顯示名稱）。
- `frontend/src/stores/paramsStore.js`：新增 `externalEmployeeId`/`externalEmployeeName`/`externalDepartmentCode`/`externalDepartmentName`/`externalJobTitleName`/`externalJobTitleLevel`/`externalApiKey` 七個欄位（外部 API 測試頁專用）。
- `frontend/src/stores/externalChatStore.js`：`buildExternalChatPayload()` 移除 `simulated_user_id`，改組出 `params.external_user` 物件；`_streamChat()` 的 fetch headers 新增 `X-API-Key`（取代原本「不帶 Authorization」的註解與寫法）；歡迎訊息文字同步更新。
- `frontend/src/components/params/ExternalUserInfoPanel.vue`（新檔）：API Key 輸入框與 6 個使用者身分欄位表單，僅放在外部 API 測試頁。
- `frontend/src/views/ExternalApiTestView.vue`：側欄加入 `ExternalUserInfoPanel`。
- `frontend/src/components/params/ApiJsonPreviewPanel.vue`：Header 說明改為 `X-API-Key` 驗證方式；欄位說明列表移除 `simulated_user_id`，新增 `external_user` 及其 6 個子欄位說明。

### 驗證
- `npm run build` 通過，無編譯錯誤。
- 尚待使用者手動驗證：建立/刪除 API 金鑰、部門代號新增與機密權限勾選畫面、外部頁面實際送出帶 `external_user`/`X-API-Key` 的請求（依專案慣例不由 AI 開瀏覽器驗證）。

---

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
