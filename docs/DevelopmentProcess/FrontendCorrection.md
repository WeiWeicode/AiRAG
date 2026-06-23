<!-- 前端修正紀錄 -->

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