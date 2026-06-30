前端修正

## 2026-06-30 修正資料庫連線與測試連線發送參數之空白修剪

### 修改內容
1. `frontend/src/components/embedding/DatabaseIndexingTab.vue` (修改):
   - **`handleSaveDbConfig` 函數**：在呼叫 API 儲存資料庫設定檔前，對主機 IP/Port 以及帳號進行 `.trim()`，防止儲存帶有尾隨空格的資料。
   - **`handleTestDbConnection` 函數**：在進行連線測試前，同樣對 `host`、`database`、`username` 進行 `.trim()` 處理，確保發送乾淨無空格的參數。

## 2026-06-29 新增 Genero .4fd 畫面定義檔批次選取與切分參數綁定

### 修改內容
1. `frontend/src/components/embedding/BatchIndexingTab.vue`:
   - **新增 .4fd 下拉選單選項**：在限制上傳副檔名 `<select>` 下拉選單中加入 `Genero Form (.4fd)`，以支援使用者批次上傳與寫入 `.4fd` XML 畫面定義檔。
   - **自動配置大小雙層切分參數**：擴充 `watch(selectedExtension)`，當偵測到選取為 `.4gl` 或 `.4fd` 時，自動將切分模式 `batchChunkModeExt` 設為大小雙層切分 `'parent_child'`，並重置相關重疊大小與切分大小。

## 2026-06-29 優化資料庫匯入自然語言轉換與預覽格式

### 修改內容
1. **優化自然語言轉換規則 (前端與後端同步)**：
   - 於 `DatabaseIndexingTab.vue` 的 `dbPreviewText` 計算屬性與後端 `backend/routers/database_indexing.py` 的 SQL 資料轉換段落中，實施結構化的自然語言轉換機制。
   - **空值欄位保留與合併邏輯**：
     - 若欄位為空值（`None`、空字串、`null`、`none`），但使用者**有填寫「欄位中文意義描述」**，則視為重要欄位，**不進行末尾合併**，而是保留在主體敘述中。格式化為：
       - 若描述包含「為」或「是」，輸出為：`{描述}（{欄位名}=空值）`。
       - 其餘一般描述，輸出為：`{描述}（{欄位名}）為空值`。
     - 若欄位為空值且**沒有填寫「欄位中文意義描述」**（為空或與欄位名稱相同），則統一收集到句尾合併格式化為 `，(GAB05)、(GAB12)皆為空值，未做描述。`，以精簡非重要資訊。
   - **非空值欄位語意對應**：
     - 若欄位中文描述為空或與欄位名稱相同，直接輸出為：`{欄位名}為「{值}」`。
     - 若欄位中文描述包含「為」或「是」（例如「目前狀態為已啟用」），則輸出為：`{描述}（{欄位名}={值}）`。
     - 其他一般描述，輸出為：`{描述}（{欄位名}）為「{值}」`。
   - 格式化首句主體描述 `這是 ERP 的{表單意義}表單（{表單代碼}）。此筆資料的...`，全面提高向量資料庫檢索時的語意完整度。其餘文字、優化向量化空間並提升檢索效果。
   - **非空值欄位語意對應**：
     - 若欄位中文描述為空或與欄位名稱相同，直接輸出為：`{欄位名}為「{值}」`。
     - 若欄位中文描述包含「為」或「是」（例如「目前狀態為已啟用」），則輸出為：`{描述}（{欄位名}={值}）`。
     - 其他一般描述，輸出為：`{描述}（{欄位名}）為「{值}」`。
   - 格式化首句主體描述 `這是 ERP 的{表單意義}表單（{表單代碼}）。此筆資料的...`，全面提高向量資料庫檢索時的語意完整度。

## 2026-06-29 重構自訂資料向量化頁面 (EmbeddingTestView.vue)

### 修改內容
1. **模組化重構 Vue 視圖**：
   將原先龐大（約 2,000 行以上）的單一視圖 `frontend/src/views/EmbeddingTestView.vue`，依功能拆分為四個獨立的子分頁組件，並放置於 `frontend/src/components/embedding/` 目錄下：
   - `SingleIndexingTab.vue`：負責單筆資料切分與向量化寫入（Tab 1）的所有邏輯與狀態。
   - `BatchIndexingTab.vue`：負責自動分批檔案寫入與佇列管理（Tab 2）的非同步計時器與處理邏輯。
   - `DatabaseIndexingTab.vue`：負責資料庫連線、唯讀 SQL 分析與向量對應對照寫入（Tab 3）的連線管理與樣品預覽。
   - `VectorManagementTab.vue`：負責已向量化資料之檔案檢索、多選與批次刪除管理（Tab 4）的管理邏輯。
2. **優化側邊欄預覽容器佈局與修復 Unmount 衝突**：
   - 原先在 `EmbeddingTestView.vue` 右側定義單一 `#tab-sidebar-content` 容器，供複數 Tab 組件共同 Teleport。然而，當使用者切換 Tab 時，由於舊組件的卸載（Unmount）與新組件的掛載（Mount）在同一 DOM 容器中發生，易引發 Vue 3 的 Virtual DOM 協調衝突，導致主程式噴出 `Cannot read properties of null (reading 'parentNode')` 的 unmount 崩潰錯誤。
   - **解決方案**：在 `EmbeddingTestView.vue` 的右側欄，拆分為獨立的側邊欄容器：`<div id="sidebar-single-indexing">` 與 `<div id="sidebar-batch-indexing">`，並使用 `v-show` 隨 `activeTab` 進行可見性切換。
   - 修改 `SingleIndexingTab.vue` 與 `BatchIndexingTab.vue` 中的 Teleport 標籤，使其各自投射到獨立且穩定的 DOM 節點上（並加入 `defer` 屬性確保目標掛載），徹底排除 unmount 協調衝突。
3. **重構前端發布**：執行 `npm run build` 確認前端資源順暢編譯。

## 2026-06-29 修正資料庫自訂資料向量化連線表單欄位背景色與字型顏色看不清之問題

### 修改內容
1. `frontend/src/views/EmbeddingTestView.vue`:
   - **修正欄位背景色**：將資料庫連線設定表單中所有輸入框及下拉選單的無效 Tailwind 背景色類別 `bg-white/3` 修改為標準合法的 `bg-white/5`。這能使瀏覽器正確渲染半透明暗灰色背景，避免因 fallback 至預設瀏覽器樣式而產生白底與白字重合、導致輸入文字看不清的問題。
   - **重構前端發布**：執行 `npm run build` 確認前端資源順暢編譯。

## 2026-06-26 配合批次副檔名上傳過濾與 MongoDB 分類標籤、自訂類別更新前端 UI 與服務

### 修改內容
1. `frontend/src/services/embeddingService.js`:
   - 新增 `getTags()`, `createTag(name)`, `getClasses()`, `createClass(name)`，對接後端 MongoDB 資料庫之標籤與類別選項讀寫。
2. `frontend/src/views/EmbeddingTestView.vue`:
   - **新增副檔名客製化切分設定與過濾**：
     - 新增 `selectedExtension` (限制上傳副檔名) 雙向綁定 ref，並監聽其變化，自動為選定的副檔名載入預設的 chunk size、overlap 與 separator，同時在副檔名改變時自動清空上傳佇列。
     - 修改 `addFilesToQueue` 方法，在上傳前比對副檔名，不符合 `selectedExtension` 的檔案將跳過並彈出警告提示。
     - 於「批次寫入設定」面板中加入副檔名限制選擇下拉選單。
     - 於 Dropzone 卡片動態綁定 `:accept="selectedExtension"`，並更新說明文字。
   - **引入 MongoDB 標籤與類別選項選擇面板**：
     - 新增 `allTags`、`allClasses` 狀態，在 `onMounted` 生命週期中從後端載入。
     - 於單筆編輯 (Tab 1) 中，移除原有 `tagsString` 純文字輸入框，改為渲染「分類標籤 (Tags)」與「類別選項 (Class)」動態選擇氣泡群組，並提供即時新增之微型輸入欄位與 `+` 按鈕。
     - 於自動分批寫入 (Tab 2) 的「批次寫入設定」面板中，同步引入「分類標籤」與「類別選項」的動態 Checkbox 核取氣泡，方便在批次上傳多個檔案時一鍵附加對應標籤與類別，並隨 Chunks metadata 發送至後端向量化 API。

## 2026-06-25 調整自動分批寫入之設定版面為單行單功能佈局

### 修改內容
1. `frontend/src/views/EmbeddingTestView.vue`:
   - **調整設定面板版面**：將「批次寫入設定」面板下的設定欄位（分類標籤、重複檔案處理、向量寫入批次大小）容器由原先的三欄網格（`grid grid-cols-1 md:grid-cols-3 gap-4`）修改為垂直單列堆疊（`flex flex-col gap-3`），使每個設定功能獨占一行顯示，改善操作體驗與易讀性。

## 2026-06-25 於自訂資料分批寫入功能中新增重複檔案處理模式（覆蓋與略過設定）

### 修改內容
1. `frontend/src/views/EmbeddingTestView.vue`:
   - **新增 `batchDuplicateMode` 狀態**：於 batch indexing state 中新增 `batchDuplicateMode` 的 ref（預設值為 `overwrite`），用以記錄使用者對重複檔案的處理偏好（蓋過/略過）。
   - **新增庫內檔案重名檢查與略過機制**：在 `startBatchProcessing` 佇列處理引擎中，啟動前先非同步取得當前知識庫元資料（檔案名稱列表）。在佇列迴圈中，若重名處理設定為 `skip` 且佇列內檔名已存在於庫中，則不調用上傳及向量化 API，直接標記狀態為 `success`、進度為 `100`，並顯示「檔案已存在於向量庫中，已自動略過不覆蓋。」且略過該檔案。
   - **成功寫入後動態更新清單**：檔案在批次寫入成功時，動態將新檔名 push 到已存在檔名清單中，防止同批次後續檔案重複寫入。
   - **新增重複檔案處理 UI 選單**：在批次寫入設定卡片中新增「重複檔案處理」`<select>` 下拉式選單，且將網格版面由 `md:grid-cols-2` 調整為 `md:grid-cols-3` 以實現精緻美觀的水平排列。

## 2026-06-25 於自訂資料向量化頁面實作自動分批寫入 Tab 與非同步佇列管理

### 修改內容
1. `frontend/src/services/retrievalService.js`:
   - 新增2. `frontend/src/views/EmbeddingTestView.vue`:
   - **新增 Tab 分頁**：整合新增 `batch_indexing` 分頁，提供專屬的批次文件寫入功能。
   - **佇列管理狀態與函數**：新增 `batchFiles`（檔案佇列陣列）、`batchChunkSize`（向量寫入批次大小）、`batchTagsString`（佇列標籤）等狀態。實作 `addFilesToQueue`, `removeBatchFile`, `clearCompletedBatchFiles` 與 `clearAllBatchFiles` 方法，支援流暢的佇列編輯與進度清除操作。
   - **拖曳上傳 Dropzone**：於批次分頁實現拖拽上傳區塊，可動態獲取拖放之多檔案並加入佇列。
   - **進度指示器與狀態徽章**：開發了基於 computed 的 global 佇列進度百分比條。在 table 列表中針對每個檔案渲染微型進度條，並設計旋轉 loader 以及綠色 check/紅色 warning 圖示用以呈現非同步階段狀態。
   - **非同步非阻塞執行引擎**：設計並實作 `startBatchProcessing`。使用 async/await 依序將檔案執行：API 上傳與文字提取、前端文本切分、重複檔名向量清理、多 Chunks 分批次向後端傳送向量化寫入（提供批次分流限制 Payload 大小以提高成功率）並響應式更新 UI。
   - **精確執行耗時統計**：新增 `batchTotalElapsedTime` (全域累積時間) 與 `currentFileStartTime` (當前檔案開始時間) 狀態。實作 `startBatchTimer` 與 `stopBatchTimer`。使用 `setInterval` 每 100ms 動態更新目前正在處理檔案的耗時與總體累積耗時。
   - **耗時資料視覺化呈現**：於整體進度卡片上新增「累積耗時」指示，在佇列列表 Table 中加入「耗時」欄位，以動態顯示每份檔案解析及寫入時所用秒數，並在右側摘要邊欄顯示累積總耗時，顯著優化人機互動體驗。頁實現拖拽上傳區塊，可動態獲取拖放之多檔案並加入佇列。
   - **進度指示器與狀態徽章**：開發了基於 computed 的 global 佇列進度百分比條。在 table 列表中針對每個檔案渲染微型進度條，並設計旋轉 loader 以及綠色 check/紅色 warning 圖示用以呈現非同步階段狀態。
   - **非同步非阻塞執行引擎**：設計並實作 `startBatchProcessing`。使用 async/await 依序將檔案執行：API 上傳與文字提取、前端文本切分、重複檔名向量清理、多 Chunks 分批次向後端傳送向量化寫入（提供批次分流限制 Payload 大小以提高成功率）並響應式更新 UI。

## 2026-06-25 於 RAG 對話視窗與自動化評估頁面整合向量與混合查詢選項並優化顯示

### 修改內容
1. `frontend/src/stores/chatStore.js`:
   - 在 `sendQuestion` API 請求參數中，將 `paramsStore.searchMode` 作為 `search_type` 夾帶於 payload 中發送給後端，實現對話檢索與檢索模式設定的串接。
2. `frontend/src/components/chat/ChatWindow.vue`:
   - 於對話視窗頂部 Header 整合磨砂玻璃風格的切換按鈕群組，供使用者一鍵切換「向量查詢」與「混合查詢」，並即時同步至 `paramsStore.searchMode` 全域狀態中。
3. `frontend/src/components/params/RagParamsPanel.vue`:
   - 在右側 RAG 檢索參數設定邊欄中，新增「檢索模式 (Search Mode)」下拉選單，與頂部 Header 欄位保持雙向同步，提供靈活的參數調整管道。
4. `frontend/src/components/eval/TestSetManager.vue`:
   - 新增 `searchType` 狀態，並在面板中新增「檢索模式 (Search Type)」下拉選單。
   - 更新開始評估按鈕的點擊發送事件，將選取之 `searchType` 傳送予父頁面。
5. `frontend/src/views/EvaluationView.vue`:
   - 接收 `start-eval` 事件傳送來的 `searchType` 參數，並將其填入 payload.params.search_type 發送給後端自動化評估 API。
6. `frontend/src/views/RetrievalTestView.vue`:
   - 在檢索結果卡片中，針對 `searchType` 為 `hybrid` (混合搜尋) 的情境，將原本固定顯示的 `Score` 標題動態調整為 `RRF Score`。
   - 隱藏混合搜尋下沒有實際物理意義的 `Distance`（距離）徽章（該數值在混合搜尋下是基於 RRF 排名分數計算的 `1 - score`，容易對使用者產生誤導），僅在純向量搜尋（`vector`）模式下顯示 `Distance` 徽章。

## 2026-06-24 於自訂資料向量化頁面新增「清空與重置」按鈕

### 修改內容
1. `frontend/src/views/EmbeddingTestView.vue`:
   - **新增重設狀態函式 `resetFields`**：實作狀態重置邏輯，將上傳檔案 ID、文字內容、檔案名稱（回復預設 `unknown`）、標籤欄位、切分預覽陣列以及向量化統計狀態一鍵清空/還原。
   - **按鈕 UI 佈局整合**：於主編輯區下方的動作按鈕列（Action Buttons Container）最右側，新增一個紅字/紅框半透明的「🔄 清空與重置」按鈕，並使用 `ml-auto` 使其與主要功能按鈕保持適當的視覺區隔。

## 2026-06-24 於自訂資料向量化頁面實作段落文字結構化 (Structured Chunks) 控制與格式整合

### 修改內容
1. `frontend/src/stores/paramsStore.js`:
   - 新增 `enableStructuring: true` 到 Pinia params store 中，用於全域控制與保存是否啟用文字結構化切分。
2. `frontend/src/components/params/ChunkingParams.vue`:
   - 於切分參數邊欄的「切分符號」下方，新增磨砂玻璃風格的「啟用文字結構化 (Structure Text)」Checkbox 核取方塊，實現開關狀態與 store 的雙向綁定。
3. `frontend/src/views/EmbeddingTestView.vue`:
   - **自訂 Token 估算函式 `estimateTokens`**：實作與後端一致的 CJK / 英文 / 其它字元 Token 比例計算機制，以精確估算結構化後段落的真實 Token 數。
   - **切分內容重組邏輯**：於 `triggerChunking` 中獲取後端原始切分 chunks 後，若 `enableStructuring` 為真，自動將各 chunk 的 content 重組成含有 `[檔案名稱]`、`[段落編號]`（1-based 遞增）、`[分類標籤]` 與 `[主要內容]` 的結構化 Markdown 文字段落，並同步覆寫其字元數與 Token 數，使用戶預覽與最終寫入 Qdrant 的向量段落能完全對齊一致。

## 2026-06-24 提升 E2E 測試對話之 SSE Stream 串流與來源資料 Chunks 解析穩定度

### 修改內容
1. `frontend/src/stores/chatStore.js` 與 `frontend/src/views/EvaluationView.vue`:
   - **重構 `currentEvent` 作用域**：將原本宣告在 `while (true)` 迴圈內部的 `let currentEvent = null` 移至迴圈**外部**。
   - **原因分析**：當大封包（如 `sources` JSON）因網路延遲被切分在多個 `reader.read()` 區塊時，先前做法會在每一輪讀取開頭將 `currentEvent` 重置為 `null`，使得後續讀取到的 `data:` 行無法配對上一個區塊的 `event:` 狀態，導致來源資料被前端靜默忽略。移至迴圈外部宣告可使 event 狀態跨 TCP 封包邊界持久存在。
   - **緩衝區處理強固**：重構串流讀取循環 `while(true)` 中的 buffer 截斷與分行解析邏輯。優化為在 `done` 狀態為 true 時，不再粗暴 break 迴圈，而是清空 `buffer` 前將其最後一行（即便沒有以 `\n` 結尾）也納入 complete lines 的處理中，並將 `if (done) break` 移至迴圈末尾，保證在任何網路分包或 Proxy (Nginx) 情境下，所有事件均被完整讀取。

## 2026-06-24 於準確度評估頁面新增生成最大 Token 數 (max_tokens) 調整拉桿

### 修改內容
1. `frontend/src/components/eval/TestSetManager.vue`:
   - 新增 `maxTokens` ref，預設為 `2048`。
   - 在測試集選擇下拉選單下方，新增一個具備質感玻璃磨砂底座的 Range Slider (橫條拉桿)，支援範圍從 512 到 8192（步進 256），並動態顯示目前選取的 Token 數。
   - 修改「開始自動評估」的 click 觸發，向父元件 emit 包含 `datasetId` 與 `maxTokens` 的物件。
2. `frontend/src/views/EvaluationView.vue`:
   - 修改 `startEvaluation` 接收參數以相容解構傳入的 `maxTokens`。
   - 將 `maxTokens` 夾帶於 API 呼叫的 `params.max_tokens` Payload 中，順利傳遞至後端以調整產出限制。

## 2026-06-24 於自訂資料向量化頁面整合「已向量化資料管理與刪除」分頁

### 修改內容
1. `frontend/src/views/EmbeddingTestView.vue`:
   - **新增分頁 (Tabs)**：在左側主編輯區頂部新增分頁切換器，支援「資料切分與向量化寫入 (indexing)」與「已向量化資料管理與刪除 (management)」兩個分頁。
   - **資料加載與篩選**：在「已向量化資料管理與刪除」分頁中，新增動態檔案名稱下拉選單。選擇檔案後，可向後端發送空搜尋請求（藉此觸發 backend 進行 Qdrant Scroll 檢索），撈出該檔案於指定知識庫中的所有向量 Point 段落。
   - **獨立刪除與批次刪除**：在此分頁中同步提供「全選」Checkbox 與「批次刪除選取 (N)」按鈕，並在每個向量段落卡片右上角放置單筆刪除按鈕，實現點對點的高效管理。
   - **右側欄佈局優化**：當處於管理分頁時，自動隱藏無關的「切分預覽 (Chunks Preview)」面板，維持操作介面的專注度。

## 2026-06-24 於向量搜尋測試頁面新增檔案過濾選單與多選刪除功能


### 修改內容
1. `frontend/src/services/retrievalService.js`:
   - 新增 `batchDeletePoints(knowledgeBaseId, pointIds)` 方法，串接後端批次刪除 Points API。
2. `frontend/src/views/RetrievalTestView.vue`:
   - **狀態與資料加載**：導入 `watch` 與 `computed`。新增 `filenames`（唯一檔案清單）、`filterFilename`（目前選取的篩選檔案）以及 `selectedChunkIds`（目前勾選的 Points 列表）等 refs。監聽 `paramsStore.knowledgeBaseId` 以自動請求 `/api/knowledge-bases/{id}/metadata` 來更新當前知識庫的所有可用檔案。
   - **檢索負載更新**：在 `/api/retrieval/search` 的 payload 參數中附加 `filter_filename`，配合下拉選單即時篩選特定檔案。
   - **單筆與批次刪除 UI 整合**：
     - 在檢索結果列表的每一張卡片右上角加上紅色垃圾桶按鈕，點擊觸發 `handleDeleteSingle(pointId)` 安全單筆刪除。
     - 在卡片左側加入 checkbox 進行多選核取。
     - 列表統計區域旁新增「全選」Checkbox 與動態顯示勾選數量的「刪除所選 (N)」按鈕，點擊觸發 `handleBatchDelete()` 完成 Qdrant 資料點之批次清理。
     - 刪除成功後，即時從前端 local states 清除已刪除的數據以流暢響應 UI。

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