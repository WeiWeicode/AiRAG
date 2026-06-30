這是一份為您的「公司內部測試 AiRAG 網頁應用」量身打造的完整產品需求文件 (PRD)。內容結構參考了業界標準，並針對 AI/RAG 工程師的實際使用場景進行了細化。

---

# 產品需求文件 (PRD)：公司內部測試 AiRAG 網頁應用

## 1. 文件資訊
* **專案名稱**：AiRAG 內部測試平台 (AiRAG Internal Testing Platform)
* **文件版本**：V 1.1 (最新更新)
* **建立日期**：2026-06-18
* **更新日期**：2026-06-30
* **目標受眾**：AI 工程師、後端工程師、產品經理、QA 測試人員

## 2. 專案概述
### 2.1 專案背景
公司正積極導入與開發 RAG (Retrieval-Augmented Generation) 技術。為了加速開發進程、確保模型輸出品質，並提供一個安全的內部環境進行參數調優 (Prompt tuning, Chunking strategy, Vector search tuning)，需要開發一套專屬的網頁應用，讓工程師能模組化地測試 RAG 的各個環節。

### 2.2 專案目標
1. **模組化測試**：將 RAG 拆解為 Embedding、Retrieval、Generation 階段，支援獨立測試與端到端測試。
2. **加速調優**：提供直觀的介面，讓工程師能快速調整參數 (如 Top-K, Chunk size) 並即時預覽結果。
3. **量化評估**：建立標準化的準確度評估機制，用數據證明 RAG 系統的效果與改善空間。

### 2.3 成功指標 (KPIs)
* 內部 AI 工程師使用率達 100%。
* 新 RAG 功能的測試與調優週期縮短 30%。
* 產出至少 3 份具備量化指標的 RAG 準確度評估報告。

---

## 3. 使用者角色 (User Personas)
* **AI/演算法工程師**：主要使用者。負責調整 Embedding 模型、Chunking 策略、Prompt 設計，並分析檢索與生成結果。
* **後端/系統工程師**：負責測試 API 串接效能、向量資料庫查詢效率、系統穩定性。
* **產品經理 (PM) / QA**：查看端到端 RAG 對話結果，執行準確度評估，確認產品是否達到上線標準。

---

## 4. 核心功能需求 (Functional Requirements)

### 4.1 RAG 功能測試 (End-to-End Testing)
**描述**：提供完整的 RAG 流程測試，模擬最終使用者的真實對話場景。
* **功能細節**：
  * **對話介面**：支援多輪對話 (Chat History)，支援 Markdown 渲染與程式碼高亮。
  * **參數設定面板**：設定 LLM Model (Qwen3.6-35B-A3B-FP8)、Temperature、Top-P、Max Tokens。
  * **RAG 參數設定**：可調整 Knowledge Base (知識庫) 選擇、Top-K (檢索數量)、Score Threshold (相似度閾值)。
  * **查詢模式切換**：提供 `vector` (純向量查詢)、`hybrid` (雙路混合查詢) 與 `semantic_hybrid` (語義混合查詢) 三種檢索模式。
  * **語義混合查詢工作流**：
    * 當使用 `semantic_hybrid` 時，原始提問先發送至地端 Instruct 語義化 AI（Qwen3VL-8B-Instruct）轉換為語義結構化 JSON（包含 `embeddings_input` 密集向量輸入與 `sparse_keywords` 稀疏關鍵字）。
    * 將此 JSON 用於密集向量生成與 FastEmbed 稀疏關鍵字生成，執行兩路融合檢索。
  * **即時管道步驟折疊顯示**：以玻璃擬物化折疊手風琴步驟元件（語義分析、向量資料查詢、思考中、結論），動態呈現對話串流的處理細節、產生之 JSON、召回文件來源與對應 RRF 相似度分數。
  * **透明化展示**：回答生成時，展示「引用的來源文件 (Source Chunks)」及其相似度分數。
  * **串流輸出**：LLM 回答與執行步驟皆支援 SSE (Server-Sent Events) 串流打字效果。
* **驗收標準**：使用者輸入問題後，系統能檢索知識庫並透過 LLM 生成帶有引用來源的串流回答。由工程師自行測試判斷回答品質與步驟管道顯示是否符合預期。

### 4.2 向量搜尋測試 (Retrieval Testing)
**描述**：隔離 Generation 階段，專注於測試與調優向量檢索 (Retrieval) 的效果。
* **功能細節**：
  * **純檢索模式**：輸入 Query，不呼叫 LLM，僅返回向量搜尋結果。
  * **雙路 RRF 混合檢索 (Hybrid)**：結合密集向量 (Dense Vector) 與 FastEmbed 生成的 SPLADE 稀疏關鍵字向量 (Sparse Vector)，利用 Qdrant 的 FusionQuery (Reciprocal Rank Fusion) 進行融合排序。
  * **語義混合檢索獨立端點**：支援單獨測試語義混合檢索，返回 `text_content` 作為原始文本。
  * **結果詳細資訊**：顯示 Top-K 個 Chunk 的完整內容、Metadata (如檔案名稱、頁碼、段落標題、自訂 class 分類標記)、Cosine Similarity / Distance / RRF 分數。
  * **向量 Points 管理與刪除**：
    * 提供檔案名稱過濾（向後端請求元資料，以檔案名稱下拉篩選檢索範圍）。
    * 支援在檢索結果中進行單筆點刪除、多選 checkbox 批次永久刪除 Qdrant Points，並同步扣除 MongoDB 知識庫中的 `chunk_count` 總數。
  * **Query 轉換測試**：可測試 Query Rewriting (查詢重寫) 或 HyDE (假設性文件嵌入) 等進階檢索策略。
* **驗收標準**：工程師輸入 Query 後，能看到排序好的 Chunk 列表及每個 Chunk 的相似度分數，並可對 Points 進行過濾與刪除操作。由工程師自行測試判斷。

### 4.3 準確度評估 (Evaluation & Benchmarking)
**描述**：建立標準測試集，自動化評估 RAG 系統的整體表現。
* **功能細節**：
  * **測試集管理**：支援上傳/手動建立/編輯 Test Dataset (包含：Question, Ground Truth Answer, Relevant Contexts)。
  * **自動化跑分**：批次執行測試集，並呼叫 LLM-as-a-Judge 進行評分。
  * **評估指標 (參考 RAGAS 框架)**：
    * *Faithfulness (忠實度)*：回答是否完全基於檢索到的 Context，有無幻覺。
    * *Answer Relevancy (回答相關性)*：回答是否直接解決了使用者的問題。
    * *Context Precision/Recall (上下文精確率/召回率)*：檢索到的 Context 是否包含足夠且正確的資訊。
  * **報表產出**：生成視覺化圖表 (雷達圖、長條圖)，支援匯出 CSV/JSON 格式的詳細評分報告。
* **驗收標準**：上傳測試集後，系統能自動執行並產出包含上述 4 項指標的平均分數與明細報表。由工程師自行驗證評估結果是否合理。

### 4.4 自訂 Context 生成回答 (Generation / Prompt Testing)
**描述**：繞過 Retrieval 階段，讓使用者手動注入 Context，專注於測試 LLM 的生成能力與 Prompt 遵循度。
* **功能細節**：
  * **Context 注入區**：提供大型文字框，讓使用者手動貼上、編輯，或**檢索並多選引用 Qdrant Chunks**（彈出知識庫檢索 Modal，以關鍵字搜尋 Chunks，勾選多個段落以 `\n---\n` 串接注入）。
  * **Prompt 模板編輯**：支援自訂 System Prompt 與 User Prompt 模板 (使用 `{context}` 和 `{question}` 變數)。
  * **預設/自訂範本載入**：後端預設自動載入「預設 RAG 助手」與「嚴格知識問答」兩款內建範本，前端支援一鍵載入與自訂範本 CRUD（保存至 MongoDB）。
  * **評估集問題/對答引用**：支援「引用評估集問題」Modal，點選載入問題，並可聯動將對應的標準答案 (Ground Truth) 與 relevant contexts 追加載入至 Context 區。
  * **A/B 測試歷史紀錄**：支援將 Variant A/B 的生成結果、參數與執行毫秒數儲存至 MongoDB 中，並能查看歷史紀錄以還原參數或進行刪除。
  * **變數替換預覽**：在發送給 LLM 前，可預覽最終組合完成的完整 Prompt 與 Token 估算。
  * **多參數 A/B 測試**：支援以不同參數組合並排顯示生成結果。
* **驗收標準**：使用者貼上或引用指定 Context 並輸入 Prompt 後，系統能組合變數並呼叫 LLM 生成回答。由工程師自行測試判斷生成品質。

### 4.5 自訂資料向量化 (Embedding & Indexing Testing)
**描述**：測試文件解析、文本切分 (Chunking) 與向量化 (Embedding) 的效果。
* **功能細節**：
  * **單一格式限制批次上傳**：限制批次上傳必須符合選定的單一副檔名，並自動載入推薦的客製化切分大小與重疊長度。
  * **多種檔案格式解析與雙層結構切分 (Parent-Child Retriever)**：
    * **Word (.docx, .doc, .dotx)**：將 Word 解析轉換為 Markdown，提取多層級 Heading 邊界作為 Parent Chunks，表格/清單格式化，子區塊前置注入標題階層路徑（例如 `[第一章 > 1.1 功能]`）並綁定 `parent_id`。對舊版 `.doc` 提供 pyodbc/textract/comtypes 降級解析。
    * **Markdown (.md)**：依據多層級標題切分 Parent，長度分割 Child，注入 header_path 首碼與 `parent_id`。
    * **Genero 4GL 原始碼**：依據 `MAIN...END MAIN`、`FUNCTION...END FUNCTION`、`REPORT...END REPORT` 與全域宣告切分為 Parent，子區塊以字元滑動窗口重疊切分，保留代碼結構。
    * **Genero 4FD 畫面檔**：以 namespace-insensitive ElementTree 解析 XML，將 Layout/FormItems/BindFiles/ScreenRecords 節點切分為 Parent，內部元件/欄位屬性切分為 Child Chunks，保留 XML 與屬性。
  * **資料庫匯入向量化 (DB Import)**：
    * **連線設定 & 快速選取**：輸入 IP/Port/資料庫/帳密進行連線測試，可存入 MongoDB 重複使用。
    * **安全 SQL 過濾**：僅允許執行 `SELECT` 或 `WITH` 開頭的唯讀 SQL，防範 SQL 注入與異動。
    * **三階段流程**：1. 查詢與樣品資料；2. 轉換公式（自然語言敘述或 Structured JSON 轉換模式）；3. Preview 樣品預覽。
    * **批次寫入**：自動分批 (每批 20 筆) 計算向量並寫入 Qdrant。
  * **分類標籤 (Tags) 與類別選項 (Classes) 管理**：
    * 標籤與類別陣列自 MongoDB 動態載入，支援即時新增儲存。
    * 寫入向量時，將選取之類別（classes）陣列寫入 Qdrant Point 點資料的 `"class"` Payload 中，便於檢索時過濾與呈現。
  * **重複檔案處理 (Deduplication)**：批次寫入支援「刪除重新上傳(覆蓋, overwrite)」與「舊檔案略過不覆蓋(跳過, skip)」設定，自動預查庫內已存在檔案清單。
* **驗收標準**：上傳文件或匯入 DB 資料後，系統能完成切分與向量化，並依設定將 Chunks 寫入 Qdrant 且同步更新 MongoDB。由工程師自行驗證。

### 4.6 人工回饋與標註 (Human Feedback & Annotation)
**描述**：AI 回答完成後，提供工程師對回答進行正確性標註的機制，並可填入正確答案，形成持續改善的回饋閉環。
* **功能細節**：
  * **正確性標記**：提供 ✅/❌ 按鈕，標記正確或不正確。
  * **正確答案填寫**：不正確時可填入預期正確答案 (Ground Truth)。
  * **錯誤分類**：可選擇標記錯誤類型，如「幻覺 (Hallucination)」、「資訊不完整」、「引用來源錯誤」、「格式問題」等。
  * **回饋資料匯入測試集**：標註資料可一鍵批次匯入測試集。
  * **標註紀錄清理**：支援在回饋標註歷史頁面進行單筆刪除與核取多選批次刪除，方便整理測試集。
* **驗收標準**：工程師能對回答進行標記、儲存，並支援單筆/批次刪除回饋紀錄與匯出。

---

## 5. 非功能需求 (Non-Functional Requirements)

### 5.1 效能需求 (Performance)
* **向量檢索回應時間**：單次 Query 的向量檢索結果應在合理時間內返回（目標 500ms 以內）。
* **串流回應延遲**：LLM 串流回答的首 Token 延遲 (TTFT) 應在 3 秒以內。
* **文件向量化處理**：10 頁以內的文件應在 60 秒內完成切分與向量化。

### 5.2 安全性與合規
* **存取控制**：採用簡易帳號密碼登入，密碼以加密形式儲存於後端環境變數 (`.env`)。
* **資料隱私**：明確標示並隔離「測試資料」與「正式生產資料」。使用公司內部部署的 LLM (vLLM, llama.cpp)，資料不外傳。
* **SQL Server & Oracle 查詢安全**：強制安全過濾限制，僅限唯讀 SQL 操作。

### 5.3 可用性 (UI/UX)
* **設計風格**：採用極簡、專業的 Dashboard 設計，支援 **深色模式 (Dark Mode)** (工程師偏好)。
* **響應式設計**：主要適配 PC/1080p螢幕。
* **快捷鍵支援**：提供常用快捷鍵 (如 `Ctrl+Enter` 發送、`Ctrl+K` 切換知識庫)。

---

## 6. 技術架構建議 (Technical Stack)

* **前端 (Frontend)**：
  * 框架：Vue 3 (vite)。
  * UI 套件： Tailwind CSS。
  * 狀態管理：Pinia。
  * 串流處理：原生 `fetch` + `ReadableStream` 或 SSE 客戶端。
  * Markdown 渲染：markdown-it + highlight.js。
* **後端 (Backend)**：
  * 框架：Python **FastAPI**。
  * AI 框架：本地端 AI llama.cpp（密集向量 Qwen3-Embedding-8B-Q8_0.gguf、地端語義化 AI Qwen3VL-8B-Instruct）、vLLM（生成 LLM Qwen3.6-35B-A3B-FP8）。
  * 稀疏向量：`fastembed>=0.3.0` (用於 SPLADE 稀疏關鍵字生成)。
* **資料庫與儲存**：
  * 向量資料庫：Qdrant (支援 HNSW 密集向量與 `sparse-text` 稀疏索引)。
  * 既有知識庫 / Oracle：SQL Server (唯讀，pyodbc)，Oracle Database (唯讀，oracledb Thin 模式)。
  * 應用資料庫：MongoDB (motor/beanie) (儲存對話、設定、測試集、評估、回饋標註、資料庫連線設定、標籤與類別選項、Prompt 測試歷史)。
* **基礎設施**：
  * Docker + Docker Compose (本地開發與部署)。

---

## 7. 專案時程與里程碑 (Roadmap)

預計總開發週期為 **8 週**，分為四個階段：

| 階段 | 週期 | 目標與交付物 | 包含功能 |
| :--- | :--- | :--- | :--- |
| **Phase 1: 基礎建設與資料處理** | 第 1-2 週 | 完成系統架構搭建、登入機制、資料向量化功能。 | §4.5 (自訂資料向量化)、基礎 UI 框架、簡易登入機制。 |
| **Phase 2: 核心 RAG 與檢索測試** | 第 3-4 週 | 完成端到端 RAG 對話，以及獨立的向量檢索測試。 | §4.1 (RAG 功能測試)、§4.2 (向量搜尋測試)。 |
| **Phase 3: 生成調優與評估系統** | 第 5-6 週 | 完成 Prompt 調優介面，並實作自動化準確度評估。 | §4.4 (自訂 Context 生成)、§4.3 (準確度評估)。 |
| **Phase 4: 優化、測試與上線** | 第 7-8 週 | 效能調優、UI/UX 細節打磨、內部 Beta 測試與Bug修復。 | 全面測試、深色模式優化、撰寫使用者手冊、正式上線。 |

---

## 8. 風險與對策 (Risks & Mitigations)

| 風險項目 | 影響程度 | 對策 / 緩解方案 |
| :--- | :---: | :--- |
| **向量資料庫查詢效能瓶頸** | 中 | 1. 在 Phase 1 進行壓力測試。<br>2. 確保索引 (Index) 參數 (如 HNSW 的 `ef_construction`) 經過調優。 |
| **準確度評估指標不符合業務預期** | 中 | 1. 評估初期，先讓 PM 與 AI 工程師共同定義「什麼是好回答」。<br>2. 除了自動化 LLM-as-a-Judge，保留「人工標記/打分」的功能作為輔助。 |
| **檔案解析 (PDF/Word) 格式錯亂** | 高 | 1. 引入雙層結構 Parent-Child 切分策略，解析標題、列表與表格，提高段落召回完整性。<br>2. 在功能 5 提供「解析預覽」，讓使用者在切分前確認文字提取是否正確。 |
