<!-- 前端修正紀錄 -->

## 2026-06-23 於回饋歷史頁面新增單筆與批次刪除操作

### 修改內容
1. `frontend/src/stores/feedbackStore.js`:
   - 在 Pinia store 中新增 `deleteFeedback(feedbackId)` 與 `batchDeleteFeedbacks(feedbackIds)` 兩個 API 請求 actions。
2. `frontend/src/views/FeedbackView.vue`:
   - 新增 `handleDelete(id)` 與 `handleBatchDelete()` 方法，分別實行帶確認提示的單筆與批次刪除。
   - 列表標題操作欄新增「刪除選取 (N)」按鈕（使用 rose 紅色主題與 shadow），在無項目被勾選時設為 disabled。
   - 資料表格新增「操作」欄位，並為每筆回饋項目末端新增紅色的垃圾桶圖示按鈕，提供快速的單筆刪除管道。
   - 更新載入中與無數據時的 `colspan` 設定為 `6`，確保表格佈局正常對齊。

## 2026-06-23 修正回饋歷史篩選下拉式選單選項文字看不清之問題

### 修改內容
1. `frontend/src/views/FeedbackView.vue`:
   - 在篩選錯誤分類的 `<select>` 下拉選單中，為各 `<option>` 標籤添加 `class="bg-[#111827] text-white"`。以避免瀏覽器在原生渲染下拉選單時，因為繼承父級 `text-white` 而在預設的白色背景中顯示白字，導致選項文字看不清的問題。
   - 執行 `npm run build` 重新編譯前端發布資源。

## 2026-06-23 修正回饋提交載荷以包含問題與回答內容

### 修改內容
1. `frontend/src/components/chat/FeedbackPanel.vue`:
   - 修改 `handleSave` 函式。在呼叫 `feedbackStore.submitFeedback` 時，除了原先傳送的 `chat_message_id`、`is_correct`、`correct_answer`、`error_type` 與 `note` 外，主動加上 `question`（帶入 `props.query`）與 `ai_answer`（帶入 `props.content`）欄位，使後端在對話歷史無狀態下亦能獲取並儲存完整的回饋問答比對內容。

## 2026-06-23 新增對話引用來源 Chunks 內容懸浮視窗 (Tooltip)

### 修改內容
1. `frontend/src/components/chat/SourceChunks.vue`:
   - 於列表項目外層加上 `group relative cursor-help` 樣式。
   - 新增一個精美的 CSS/Tailwind 懸浮視窗 (Tooltip) 元件，當滑鼠懸停於 Chunks 項目時顯示，呈現該段落的 Qdrant 原始文本內容 (`source.content`)，具備深色透明背景、邊框、柔和陰影與指向箭頭。
   - **滑鼠移入滾動優化**：將懸浮視窗調整為無縫連貼的 `pointer-events-auto` 雙層結構（外層 wrapper 使用 `pb-2` 建立透明熱區橋接間距，內層呈現內容與滾動條），使滑鼠能流暢移入視窗中進行內容滾動、全選與複製，且移出後視窗會正常消失。

## 2026-06-23 修正對話引用來源顯示為段落編號 (chunk_index)

### 修改內容
1. `frontend/src/components/chat/SourceChunks.vue`:
   - 修改參考文檔引用顯示，將原先的頁碼 `頁碼: P.{{ ... }}` 改為顯示段落編號 `段落: #{{ ... }}`，並使用安全的三元運算子妥善讀取 `chunk_index` 或 `metadata.chunk_index` 以處理零（0）值索引之呈現。

## 2026-06-23 新增 Prompt 測試預設值回復按鈕

### 修改內容
1. `frontend/src/views/PromptTestView.vue`:
   - 於「Prompt 參數與 Context 注入測試」面板標題欄右側新增「🔄 回復預設值」按鈕。
   - 定義初始值常量 `DEFAULT_SYSTEM_PROMPT`、`DEFAULT_USER_PROMPT_TEMPLATE`、`DEFAULT_MANUAL_CONTEXT` 與 `DEFAULT_TEST_QUESTION`。
   - 實作 `resetToDefaults` 函數，在點擊該按鈕時一鍵重設系統設定、使用者範本、參考資料、測試問題為初始值，並清空歷史預覽、A/B 測試結果及數據集標準答案 (Ground Truth) 引用狀態。

## 2026-06-23 修正 Qdrant Chunks 引用行為由附加改為直接覆蓋

### 修改內容
1. `frontend/src/views/PromptTestView.vue`:
   - 於 `confirmQdrantReference` 中，將原本選取的 Qdrant 段落內容「附加（append）到原有參考資料 (Context)」的邏輯，修正為直接「覆蓋（overwrite）」原有的參考資料內容，滿足使用者直接覆蓋舊資料的測試需求。

## 2026-06-23 實作 A/B 測試即時串流與 Qdrant 檔案、標籤篩選與 chunk_index 排序

### 修改內容
1. `frontend/src/views/PromptTestView.vue`:
   - **A/B 測試即時串流 (SSE Streaming)**：
     - 重構 `handleABTest` 方法，替換原本的單次請求為 SSE 串流。
     - 當點選生成時，立即初始化 Variant A 與 Variant B 的 placeholder 卡片（顯示「思考中...」與載入動畫），並利用原生 `fetch` 配合 `reader.read()` 解析 Server-Sent Events。
     - 支援實時串流 `type: 'reasoning'` (思考過程) 與 `type: 'content'` (答案)，並解析答案中夾帶之 `<think>` 或 `<thought>` 區塊，呈現於專屬思考過程折疊式面板中。
   - **組合 Prompt 預覽高度限制**：
     - 為 System Prompt 與 User Prompt 預覽 `<pre>` 元素加上 `max-h-[250px]`、`max-h-[300px]` 與 `overflow-y-auto` 樣式，限制超長 Prompt 撐爆頁面高度，增強操作體驗。
   - **Qdrant 檢索篩選 filename 與 tags**：
     - 新增狀態變數 `qdrantSearchFilename`、`uniqueFilenames`、`uniqueTags` 與 `selectedFilterTags`。
     - 點開檢索彈窗時自動呼叫後端 `/api/knowledge-bases/{id}/metadata`，動態載入該知識庫之所有唯一檔案與標籤清單。
     - 於檢索 Dialog 中新增支援 datalist 自動提示的檔案輸入框以及 clickable 的標籤多選氣泡徽章。
     - 重構 `searchQdrantChunks`，將所選之 filename 與 tags 作為過濾參數送至後端向量搜尋。
   - **選取匯入依 chunk_index 排序**：
     - 重構 `confirmQdrantReference` 方法，在勾選匯入 chunks 時，會先依據 `metadata.chunk_index` 對所選 chunks 進行遞增排序，再行拼接注入至參考資料輸入框。

## 2026-06-23 擴充 Qdrant 檢索全選與評估集 Ground Truth 對照顯示功能

### 修改內容
1. `frontend/src/views/PromptTestView.vue`:
   - **檢索結果全選功能**：在「檢索並引用 Qdrant Chunks」彈窗的檢索結果頂部，新增「全選 / 全不選」Checkbox 與計算屬性 `isAllChunksSelected`，點擊可一鍵切換所有搜尋結果的勾選狀態。
   - **標準答案對照顯示與 A/B 測試聯動**：
     - 在「測試問題 (User Query)」輸入框下方新增 `selectedQuestionGroundTruth` 標準答案卡片，點擊引用評估集問題時，會自動將 Ground Truth 載入至該處（不再強制塞入 Context），並提供一鍵「清除引用」功能。
     - 在 A/B 測試結果對照區域，若有引用之標準答案 (Ground Truth)，會自動切換為三欄網格（`md:grid-cols-3`），並將 Ground Truth 作為專屬紫色主題卡片併排呈現，便於使用者直接將兩組 Variant 答案與標準答案進行並列比對。

## 2026-06-23 新增 Prompt 測試頁面存檔與引用互動 UI 功能

### 修改內容
1. `frontend/src/views/PromptTestView.vue`:
   - 擴充並導入 `onMounted` 生命週期函數，在掛載時獲取範本、歷史紀錄、知識庫清單與測試集。
   - 新增儲存紀錄、套用紀錄、刪除紀錄、載入既有範本、儲存自訂範本、刪除範本、知識庫 Chunk 檢索引用、以及評估集測試問題與 GT/Context 引用等完整前端 Logic。
   - 於 Template 中新增：
     - 頂部「📂 檢視歷史紀錄」按鈕與對應之暗色玻璃擬物 Modal 彈窗。
     - 系統設定區「📂 載入範本」與「💾 儲存為範本」連結與範本管理 Modal 彈窗。
     - 參考資料區「🔍 檢索並引用 Qdrant Chunks」連結與檢索 Modal 彈窗。
     - 測試問題區「🎯 引用評估集問題」連結與問答多選引用 Modal 彈窗。
     - 操作列新增「💾 儲存本次測試與結果」按鈕。
   - 修正 Vue 語法：移除重複 class 屬性並刪除普通 div 元素上不正確的 `v-slot:loading` 指令，確保生產環境打包 (Vite build) 順暢通過。

## 2026-06-23 修正 Prompt 測試頁面 API 請求前綴以正常連線

### 修改內容
1. `frontend/src/views/PromptTestView.vue`:
   - 修正 `handlePreview` 方法中的 API 請求，由 `/prompt/preview` 改為 `/api/prompt/preview`。
   - 修正 `handleABTest` 方法中的 API 請求，由 `/prompt/ab-test` 改為 `/api/prompt/ab-test`。
2. `frontend/src/components/API/prompt_api.js`:
   - 同步修正 `/prompt/generate`、`/prompt/preview` 與 `/prompt/ab-test` 的請求前綴，全面補上 `/api`。

## 2026-06-23 實作自動化評估即時串流 (SSE Streaming) 與問答上限提示

### 修改內容
1. `frontend/src/views/EvaluationView.vue`:
   - 引入並註冊 `authStore` 以讀取使用者權限 token。
   - 重構 `startEvaluation` 方法，將 `evalService.runEvaluation` 呼叫替換為原生 `fetch` 配合 `reader.read()` 來接收後端傳回的 SSE 串流。
   - 解析四種事件類型：
     - `init`：取得總筆數。
     - `progress`：更新當前評分進度索引。
     - `item_done`：實時將該筆問答對比細節推入表格明細陣列中，提供跑分過程之即時畫面渲染。
     - `result`：當評估全部完成，載入最終總分並刷新全部元件與雷達圖。
   - 更新進度條 UI。移除 `animate-pulse` 改為顯示當前進度如 `已完成 2 / 5 筆問答`，並利用比例百分比更新進度條寬度。
2. `frontend/src/components/eval/TestSetManager.vue`:
   - 在控制面板底部新增顯目的 Amber (琥珀色) 警告提示 Banner，警示使用者「因推理模型生成較慢，每次評估上限強制為 5 筆，防範連線逾時斷線」。

## 2026-06-23 實作前端測試集匯入與即時微調編輯器

### 修改內容
1. `frontend/src/services/evalService.js`:
   - 新增 `getDatasetDetails(datasetId)` API 方法，用於向後端請求單個測試集的問答明細。
   - 新增 `updateDataset(datasetId, payload)` API 方法，用於更新已有測試集的名稱、描述與問答清單。
2. `frontend/src/components/eval/TestSetManager.vue`:
   - 在控制面版頂部新增「匯入測試集」按鈕。
   - 實作「匯入新測試集」的 Modal 彈窗，支援輸入測試集名稱、描述與粘貼 JSON 格式的問答陣列，點擊確認後上傳後端並自動重新整理下拉選單且選取最新匯入之測試集。
   - 當下拉選單載入完畢或切換時，觸發並傳遞 `select-dataset` 事件，確保頁面載入時能自動綁定初始測試集。
3. `frontend/src/views/EvaluationView.vue`:
   - 於 `TestSetManager` 下方新增「測試集項目微調」主面板。
   - 面板能響應選取事件，向後端獲取詳細資料，並以精美的玻璃擬物卡片呈現各項問答的輸入框 (Question & Ground Truth)。
   - 提供「新增問答項目」與「刪除此項目」的動態編輯按鈕，以及「儲存修改」按鈕。
   - 在點選「開始自動評估」時，若檢測到本地有正在編輯微調的項目，會在啟動後端跑分前**自動先儲存修改**，確保評估使用的是最新的微調資料。

## 2026-06-22 實作 Qdrant 分類標籤寫入、篩選參數面板及檢索結果呈現

### 修改內容
1. `frontend/src/views/EmbeddingTestView.vue`:
   - 新增 `tagsString` 狀態。
   - 於文本編輯區下方新增玻璃擬物化「分類標籤」輸入框，支援英文逗號分隔多個標籤。
   - 於 `triggerVectorization` 寫入時，將逗號分隔字串切分為陣列，並填入 chunk 的 `metadata.tags` 中。
2. `frontend/src/stores/paramsStore.js` & `chatStore.js`:
   - 於檢索參數 store 新增全域狀態 `filterTagsString`。
   - 於 `sendQuestion` 時，將篩選標籤字串切割為陣列並加入 `filter_tags` 參數傳遞給後端。
3. `frontend/src/components/params/RagParamsPanel.vue` & `views/RetrievalTestView.vue`:
   - 於對話設定邊欄及向量檢索頁面邊欄中，新增「標籤過濾篩選 (Filter Tags)」輸入框。
   - 於 `RetrievalTestView.vue` 搜尋結果呈現列表中，將回傳之段落標籤渲染成精緻的小標籤氣泡 (Tag Badges)。

## 2026-06-22 新增「檔案名稱」輸入欄位以解決向量化檔案名稱為 unknown 問題

### 修改內容
1. `frontend/src/views/EmbeddingTestView.vue`:
   - 新增 `filename` reactive 狀態變數，預設值為 `'unknown'`。
   - 上傳檔案成功後（`handleUploadSuccess`），自動提取並填入檔案的真實檔名。
   - 在編輯文本區域上方，新增具 premium 玻璃擬物風格的「檔案名稱」輸入欄位，使用者可即時檢視或任意修改。
   - 於 `triggerVectorization` 組裝 payload 時，將 `filename` 帶入各 chunk 的 `metadata` 屬性中發送給後端。

## 2026-06-22 新增「新對話」按鈕以清空對話紀錄

### 修改內容
1. `frontend/src/stores/chatStore.js`:
   - 新增 `clearMessages()` action，點擊時將對話訊息重設為預設的歡迎語，並清空歷史對話。
2. `frontend/src/components/chat/ChatWindow.vue`:
   - 在對話框頂部新增一個精美的 Header 欄位，左側帶有狀態呼吸燈，右側放置紫色玻璃感設計之「新對話」按鈕，點擊觸發 `clearMessages()` 以重置對話視窗。

## 2026-06-22 實現對話視窗「思考中...」折疊式選單以看思考過程

### 修改內容
1. `frontend/src/stores/chatStore.js`:
   - 初始化助手訊息中的 `thinking` 及 `isThinking` 狀態。
   - 優化對話串流的 JSON 區塊解析器：
     - 若收到 `type: 'reasoning'` 的 SSE 事件，將其儲存於 `reasoningAccumulator` 中。
     - 若收到 `type: 'content'` 的事件，將其儲存於 `rawContentAccumulator` 中，並實作即時 parser 同時解析可能存在的 `<think>...</think>` 及 `<thought>...</thought>` 標籤，動態切割出思考內容與最終答案。
     - 即時計算並設定 `msg.thinking`、`msg.content` 與 `msg.isThinking` 旗標。
2. `frontend/src/components/chat/MessageBubble.vue`:
   - 在 AI 回答上方，新增基於 Tailwind CSS 的玻璃擬物化「思考過程」折疊式元件 (Accordion)。
   - 提供流線型動畫的旋轉箭頭與「思考中.../已完成思考」狀態，點選即可隨時展開或折疊詳細思考過程，並在思考中預設展開以便即時預覽。

## 2026-06-22 修正自訂資料向量化參數面板與知識庫選取器

### 修改內容
1. `frontend/src/components/params/ChunkingParams.vue`:
   - 引入並渲染 `KnowledgeBaseSelector` 元件，讓自訂資料切分與向量化頁面可以選擇儲存的目標知識庫。
2. `frontend/src/components/common/KnowledgeBaseSelector.vue`:
   - 調整 `fetchKnowledgeBases` 方法，在載入知識庫清單後，比對當前 Pinia store 中儲存的 `knowledgeBaseId` 是否有效。若為無效/不存在的 ID（如預設的 `'hr_docs'`），則自動 fallback 為清單中的第一個合法知識庫 ID，以防止因未點選而傳送錯誤的 ID 格式。

## 2026-06-22 於向量搜尋測試頁面新增檢索參數說明卡片

### 修改內容
1. `frontend/src/views/RetrievalTestView.vue`:
   - 在右側檢索參數邊欄的最下方，新增一個美觀的「檢索參數說明」玻璃擬物化卡片（Card）。
   - 針對 `Top-K`、`Score Threshold`、`Search Type`、`HNSW ef_search` 進行詳細的中文化技術說明與調優指引，提升使用者的產品易用性與診斷體驗。
   - 執行 `npm run build` 重新編譯前端發布資源，由 Nginx 即時映射生效。