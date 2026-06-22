<!-- 前端修正紀錄 -->

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