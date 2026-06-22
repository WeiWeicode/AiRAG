這是一份為您的「公司內部測試 AiRAG 網頁應用」量身打造的完整產品需求文件 (PRD)。內容結構參考了業界標準，並針對 AI/RAG 工程師的實際使用場景進行了細化。

---

# 產品需求文件 (PRD)：公司內部測試 AiRAG 網頁應用

## 1. 文件資訊
* **專案名稱**：AiRAG 內部測試平台 (AiRAG Internal Testing Platform)
* **文件版本**：V 1.0
* **建立日期**：2026-06-18
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
  * **參數設定面板**：設定LLM Model (Qwen3.6-35B-A3B-FP8)、Temperature、Top-P、Max Tokens。
  * **RAG 參數設定**：可調整 Knowledge Base (知識庫) 選擇、Top-K (檢索數量)、Score Threshold (相似度閾值)。
  * **透明化展示**：回答生成時，必須展示「引用的來源文件 (Source Chunks)」及其相似度分數。
  * **串流輸出**：LLM 回答需支援 SSE (Server-Sent Events) 串流打字效果。
* **驗收標準**：使用者輸入問題後，系統能檢索知識庫並透過 LLM 生成帶有引用來源的串流回答。由工程師自行測試判斷回答品質是否符合預期。

### 4.2 向量搜尋測試 (Retrieval Testing)
**描述**：隔離 Generation 階段，專注於測試與調優向量檢索 (Retrieval) 的效果。
* **功能細節**：
  * **純檢索模式**：輸入 Query，不呼叫 LLM，僅返回向量搜尋結果。
  * **結果詳細資訊**：顯示 Top-K 個 Chunk 的完整內容、Metadata (如檔案名稱、頁碼、段落標題)、以及 Cosine Similarity / Distance 分數。
  * **檢索策略切換**：支援調整 Qdrant HNSW 索引參數 (如 `ef_search`, `m`) 或混合搜尋 (Hybrid Search: 向量 + BM25 關鍵字)。
  * **Query 轉換測試**：可測試 Query Rewriting (查詢重寫) 或 HyDE (假設性文件嵌入) 等進階檢索策略。
* **驗收標準**：工程師輸入 Query 後，能看到排序好的 Chunk 列表及每個 Chunk 的相似度分數。由工程師自行測試判斷檢索結果是否正確。

### 4.3 準確度評估 (Evaluation & Benchmarking)
**描述**：建立標準測試集，自動化評估 RAG 系統的整體表現。
* **功能細節**：
  * **測試集管理**：支援上傳/手動建立 Test Dataset (包含：Question, Ground Truth Answer, Relevant Contexts)。
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
  * **Context 注入區**：提供大型文字框，讓使用者手動貼上、編輯或從歷史檢索結果中勾選 Context。
  * **Prompt 模板編輯**：支援自訂 System Prompt 與 User Prompt 模板 (使用 `{context}` 和 `{question}` 變數)。
  * **變數替換預覽**：在發送給 LLM 前，可預覽最終組合完成的完整 Prompt。
  * **多參數 A/B 測試**：支援以不同參數組合 (如 Temperature、Prompt 模板) 並排顯示生成結果，方便比較調優效果。
* **驗收標準**：使用者貼上指定 Context 並輸入 Prompt 後，系統能精準替換變數並呼叫 LLM 生成回答。由工程師自行測試判斷生成品質。

### 4.5 自訂資料向量化 (Embedding & Indexing Testing)
**描述**：測試文件解析、文本切分 (Chunking) 與向量化 (Embedding) 的效果。
* **功能細節**：
  * **資料輸入**：支援純文字貼上，或上傳檔案 (PDF, DOCX, TXT, MD)。
  * **Chunking 策略設定**：可調整 Chunk Size (字元數/Token數)、Chunk Overlap (重疊字元數)、Separator (分隔符號，如 `\n\n`)。
  * **Embedding 模型**：目前使用 Qwen3-Embedding-8B-Q8_0.gguf，架構設計保留未來切換或新增其他 Embedding 模型的擴充彈性。
  * **結果預覽與除錯**：
    * 視覺化展示文本被切分後的 Chunk 邊界。
    * 顯示每個 Chunk 的 Token 數量。
    * (可選) 展示高維度向量的前 5 維數值或進行降維 (PCA/t-SNE) 視覺化預覽。
  * **寫入測試庫**：可選擇將這些 Chunk 寫入「測試用向量資料庫」，供 4.1 和 4.2 功能即時測試。
* **驗收標準**：上傳一份測試文件後，系統能完成切分與向量化，Chunk 邊界與 Token 數量正確顯示，且 Chunk 能成功寫入測試用向量資料庫。由工程師自行檢視切分結果是否符合預期。

### 4.6 人工回饋與標註 (Human Feedback & Annotation)
**描述**：AI 回答完成後，提供工程師對回答進行正確性標註的機制，並可填入正確答案，形成持續改善的回饋閉環。
* **功能細節**：
  * **正確性標記**：每則 AI 回答下方提供「正確 ✅ / 不正確 ❌」的標記按鈕，工程師可快速標註回答品質。
  * **正確答案填寫**：當標記為「不正確」時，展開輸入區域，讓工程師填入預期的正確答案 (Ground Truth)。
  * **錯誤分類 (可選)**：可選擇標記錯誤類型，如「幻覺 (Hallucination)」、「資訊不完整」、「引用來源錯誤」、「格式問題」等。
  * **回饋資料匯入測試集**：標註完成的 QA 對 (Question + Ground Truth) 可一鍵匯入 §4.3 的測試集，作為後續自動化評估的基準資料。
  * **標註歷史紀錄**：保留所有標註紀錄，支援篩選與匯出，方便追蹤 RAG 系統的改善趨勢。
* **驗收標準**：AI 回答後，工程師能標記正確/不正確；標記不正確時能填入正確答案並儲存；標註資料能成功匯入測試集。

---

## 5. 非功能需求 (Non-Functional Requirements)

### 5.1 效能需求 (Performance)
* **向量檢索回應時間**：單次 Query 的向量檢索結果應在合理時間內返回（目標 500ms 以內）。
* **串流回應延遲**：LLM 串流回答的首 Token 延遲 (TTFT) 應在 3 秒以內。
* **文件向量化處理**：10 頁以內的文件應在 60 秒內完成切分與向量化。

### 5.2 安全性與合規
* **存取控制**：採用簡易帳號密碼登入，密碼以加密形式儲存於後端環境變數 (`.env`)。
* **資料隱私**：明確標示並隔離「測試資料」與「正式生產資料」。使用公司內部部署的 LLM (vLLM, llama.cpp)，資料不外傳。

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
* **後端 (Backend)**：
  * 框架：Python **FastAPI** (最適合 AI 生態系，非同步效能佳)。
  * AI 框架：本地端AI llama.cpp使用Qwen3-Embedding-8B-Q8_0.gguf，vLLM使用Qwen3.6-35B-A3B-FP8。
* **資料庫與儲存**：
  * 向量資料庫：Qdrant。
  * 既有知識庫：SQL Server（唯讀連線，存取既有的 md 檔、附件等知識庫資料）。
  * 應用資料庫：MongoDB（儲存對話紀錄、設定、測試集、評估報告、回饋標註等）。
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
| **檔案解析 (PDF/Word) 格式錯亂** | 高 | 1. 引入專業的 Document Parser (如 Unstructured.io, LlamaParse)。<br>2. 在功能 5 提供「解析預覽」，讓使用者在切分前確認文字提取是否正確。 |

