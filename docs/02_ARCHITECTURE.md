# 系統架構設計文件 (Architecture Design Document)

## 1. 文件資訊
* **專案名稱**：AiRAG 內部測試平台
* **文件版本**：V 1.1 (最新更新)
* **建立日期**：2026-06-18
* **更新日期**：2026-06-30
* **對應 PRD**：01_RPD.md

---

## 2. 架構總覽

### 2.1 系統架構圖

```
┌─────────────────────────────────────────────────────────────┐
│                    使用者 (瀏覽器)                            │
│                  Vue 3 + Tailwind CSS                        │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTP / SSE
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                  FastAPI Backend (Python)                     │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌─────────────────────┐  │
│  │ Auth   │ │ RAG    │ │ Eval   │ │ Embedding Service   │  │
│  │ Module │ │Pipeline│ │ Engine │ │ (Dense + Sparse)    │  │
│  │        │ │(Step-by│ │        │ │                     │  │
│  │        │ │ -Step) │ │        │ │                     │  │
│  └────────┘ └────────┘ └────────┘ └─────────────────────┘  │
│  ┌────────┐ ┌──────────┐ ┌──────────────────────────────┐  │
│  │Feedback│ │ Retrieval│ │ Prompt Template Engine       │  │
│  │Service │ │ Service  │ │ (Templates & Records)        │  │
│  └────────┘ └──────────┘ └──────────────────────────────┘  │
│  ┌─────────────────────┐ ┌──────────────────────────────┐  │
│  │ Database Indexing   │ │ Parent-Child Chunker         │  │
│  │ Service (SQL/Oracle)│ │ (Word, MD, 4GL, 4FD)         │  │
│  └─────────────────────┘ └──────────────────────────────┘  │
└─────┬──────────┬────────────┬──────────────┬───────────────┘
      │          │            │              │
      ▼          ▼            ▼              ▼
┌────────┐ ┌────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐
│SQL     │ │MongoDB │ │ Qdrant   │ │ vLLM     │ │ llama.cpp    │
│Server  │ │(App DB)│ │(VectorDB)│ │ (LLM)    │ │ (Embedding & │
│Oracle  │ │        │ │          │ │          │ │  Instruct)   │
└────────┘ └────────┘ └──────────┘ └──────────┘ └──────────────┘
```

### 2.2 架構風格
採用 **分層式架構 (Layered Architecture)** 搭配 **模組化設計**：
* **展示層**：Vue 3 SPA 前端
* **應用層**：FastAPI 路由 + 業務邏輯
* **服務層**：RAG Pipeline、Embedding、Evaluation、Database Indexing、Parent-Child Chunker 等核心服務
* **資料存取層**：MongoDB (motor/beanie) + SQL Server & Oracle (唯讀) + Qdrant Client (雙向量命名空間)
* **外部服務層**：vLLM、llama.cpp、地端語義化 AI (Instruct)

---

## 3. 前端架構

### 3.1 技術棧
| 項目 | 技術選型 | 說明 |
|:---|:---|:---|
| 框架 | Vue 3 (Composition API) | 搭配 Vite 建構工具 |
| UI 套件 | Tailwind CSS | 工具類優先 CSS 框架 |
| 狀態管理 | Pinia | Vue 3 官方推薦 |
| 路由 | Vue Router 4 | SPA 頁面路由 |
| HTTP 客戶端 | Axios / Fetch API | API 呼叫與服務對接 |
| 串流處理 | 原生 `fetch` + `ReadableStream` | SSE 串流接收與折疊步驟解析 |
| Markdown 渲染 | markdown-it + highlight.js | 回答內容渲染與結構化 JSON 代碼區塊高亮 |

### 3.2 頁面與組件結構

```
src/
├── views/
│   ├── LoginView.vue              # 登入頁面
│   ├── DashboardView.vue          # 儀表板首頁
│   ├── RagTestView.vue            # §4.1 RAG 功能測試
│   ├── RetrievalTestView.vue      # §4.2 向量搜尋測試 (含 Points 刪除)
│   ├── EvaluationView.vue         # §4.3 準確度評估
│   ├── PromptTestView.vue         # §4.4 自訂 Context 生成 (含歷史記錄、Chunks 檢索)
│   ├── EmbeddingTestView.vue      # §4.5 資料向量化 (含 DB 匯入、批次上傳)
│   └── FeedbackView.vue           # §4.6 回饋標註歷史
├── components/
│   ├── chat/
│   │   ├── ChatWindow.vue         # 對話視窗 (支援語義混合查詢按鈕)
│   │   ├── MessageBubble.vue      # 訊息氣泡 (含玻璃擬物化折疊手風琴步驟元件)
│   │   ├── SourceChunks.vue       # 引用來源展示
│   │   ├── StreamRenderer.vue     # 串流文字渲染
│   │   └── FeedbackPanel.vue      # §4.6 標記面板
│   ├── params/
│   │   ├── LlmParamsPanel.vue     # LLM 參數設定
│   │   ├── RagParamsPanel.vue     # RAG 參數設定 (包含語義混合查詢模式)
│   │   └── ChunkingParams.vue     # Chunking 策略設定 (含文字結構化開關)
│   ├── eval/
│   │   ├── TestSetManager.vue     # 測試集管理
│   │   ├── ScoreBoard.vue         # 評分看板
│   │   └── ReportChart.vue        # 圖表元件
│   ├── embedding/
│   │   ├── FileUploader.vue       # 檔案上傳
│   │   ├── ChunkPreview.vue       # Chunk 預覽
│   │   ├── TokenCounter.vue       # Token 計數
│   │   ├── SemanticJSONTab.vue    # 地端 AI 語義 JSON 匯入分頁 [NEW]
│   │   └── BatchIndexingTab.vue   # 自動分批寫入面板 (含雙層切分、Word 支援) [UPDATED]
│   └── common/
│       ├── AppSidebar.vue         # 側邊導航列
│       ├── AppHeader.vue          # 頂部導航列
│       ├── DarkModeToggle.vue     # 深色模式切換
│       └── KnowledgeBaseSelector.vue
├── stores/
│   ├── authStore.js
│   ├── chatStore.js               # 支援對話串流與 SSE step 事件解析 [UPDATED]
│   ├── paramsStore.js             # 支援 enableStructuring 文字結構化設定 [UPDATED]
│   └── feedbackStore.js           # 支援刪除與批次刪除 actions [UPDATED]
├── services/
│   ├── api.js                     # Axios 實例
│   ├── ragService.js
│   ├── retrievalService.js        # 支援 points 批次刪除與檔案過濾 [UPDATED]
│   ├── embeddingService.js        # 支援標籤、類別與 JSON 匯入 [UPDATED]
│   ├── databaseIndexingService.js # 資料庫匯入 API [NEW]
│   ├── evalService.js
│   └── feedbackService.js
└── router/
    └── index.js
```

---

## 4. 後端架構

### 4.1 技術棧
| 項目 | 技術選型 | 說明 |
|:---|:---|:---|
| Web 框架 | FastAPI | Python 非同步框架 |
| 應用資料庫 | motor + beanie | MongoDB 非同步 ODM |
| 既有知識庫 | pyodbc / aioodbc | SQL Server 唯讀連線 |
| Oracle 庫 | oracledb | Oracle Database 唯讀連線 (Thin 模式) |
| 向量 DB 客戶端 | qdrant-client | Qdrant SDK (支援密集與稀疏索引) |
| 稀疏向量生成 | fastembed | SPLADE (sparse-text) 稀疏關鍵字生成 |
| LLM 呼叫 | openai (vLLM 相容) | OpenAI 相容 API |
| Embedding | HTTP Client | llama.cpp server API |
| 文件解析 | python-docx / textract | PDF、DOCX、DOC、DOTX、MD 解析 |
| XML 解析 | xml.etree.ElementTree | Genero .4fd 畫面檔解析 |
| 串流回應 | sse-starlette | Server-Sent Events (SSE) 狀態發送 |

### 4.2 專案結構

```
backend/
├── main.py                        # FastAPI 入口 (註冊 database_indexing 路由)
├── config.py                      # 新增地端語義化 AI 環境變數配置 [UPDATED]
├── .env                           # 環境變數 (含 DenseVector 配置)
├── routers/
│   ├── auth.py                    # 登入認證
│   ├── rag.py                     # RAG 測試 (新增 SSE step 事件回傳) [UPDATED]
│   ├── retrieval.py               # 向量搜尋 (新增語義檢索、Points 批次刪除與刪檔) [UPDATED]
│   ├── evaluation.py              # 準確度評估
│   ├── prompt.py                  # Prompt 測試 (新增範本與測試歷史 CRUD) [UPDATED]
│   ├── embedding.py               # Embedding (新增標籤/類別與 JSON 匯入) [UPDATED]
│   ├── feedback.py                # 人工回饋 (新增單筆與批次刪除) [UPDATED]
│   ├── knowledge_base.py          # 知識庫管理
│   ├── database_indexing.py       # 自訂資料庫匯入向量化 [NEW]
│   └── sqlserver.py               # 既有 SQL Server 文章查詢與導入
├── services/
│   ├── llm_service.py             # vLLM 封裝
│   ├── embedding_service.py       # llama.cpp 封裝 (新增語義結構 JSON 分析) [UPDATED]
│   ├── sparse_embedding_service.py # fastembed 封裝 (SPLADE 稀疏向量) [NEW]
│   ├── qdrant_service.py          # Qdrant 操作 (支援 RRF 混合與 Points 刪除) [UPDATED]
│   ├── chunking_service.py        # 文本切分
│   ├── document_parser.py         # 文件解析 (整合 Word 與 4GL 格式) [UPDATED]
│   ├── word_parent_child_chunker.py # Word 結構化與雙層切分服務 [NEW]
│   ├── markdown_parent_child_chunker.py # MD 雙層標題路徑切分工具 [NEW]
│   ├── parent_child_chunker.py    # 4GL 與 4FD 語法/結構雙層切分 [NEW]
│   ├── eval_service.py            # 評估引擎
│   ├── feedback_service.py        # 回饋業務邏輯
│   └── prompt_engine.py           # Prompt 模板引擎
├── models/                        # MongoDB Document Models (beanie)
│   ├── mongodb.py                 # 初始化 Beanie 模型註冊 [UPDATED]
│   ├── sqlserver.py               # SQL Server 連線
│   ├── database_config.py         # 資料庫連線配置模型 [NEW]
│   ├── tag.py                     # 分類標籤模型 [NEW]
│   ├── class_option.py            # 自訂類別選項模型 [NEW]
│   ├── prompt_test_record.py      # Prompt 測試歷史與結果模型 [NEW]
│   ├── prompt_template.py         # Prompt 模板 (新增預設種子載入) [UPDATED]
│   ├── chat_session.py
│   ├── chat_message.py
│   ├── test_dataset.py
│   ├── eval_report.py
│   ├── feedback.py
│   └── app_config.py
├── schemas/                       # Pydantic Schema
│   ├── auth.py
│   ├── rag.py
│   ├── retrieval.py               # 新增 Points 刪除與過濾 Schema [UPDATED]
│   ├── evaluation.py
│   ├── embedding.py               # 新增標籤、類別與語義 JSON 寫入 Schema [UPDATED]
│   ├── feedback.py
│   └── database_indexing.py       # 新增資料庫向量化 Schema [NEW]
├── middleware/
│   ├── auth_middleware.py
│   └── cors.py
└── utils/
    ├── security.py                # bcrypt + JWT
    └── helpers.py
```

---

## 5. 核心管道資料流

### 5.1 RAG 與 語義混合檢索流程 (Semantic Hybrid Search)

當使用者在前端啟用「**語義混合查詢 (semantic_hybrid)**」時，系統資料流如下：

```
Query (原始提問) 
  │
  ▼
[地端語義化 AI: Qwen3VL-8B-Instruct] (/v1/chat/completions)
  │ (解析出結構化語義 JSON)
  ▼
Structured JSON { "embeddings_input": "...", "sparse_keywords": [...] } 
  ├── embeddings_input ──► [llama.cpp] ──► Dense Vector (4096 維)
  └── sparse_keywords  ──► [fastembed] ──► Sparse Vector (SPLADE)
                                                 │
                                                 ▼
                                        [Qdrant Prefetch]
                                          ├── Dense Search
                                          └── Sparse Search (using "sparse-text")
                                                 │
                                                 ▼
                                     [Fusion Query: RRF 融合]
                                                 │
                                                 ▼
                                         [召回段落排序]
                                                 │
                                                 ▼
                                     [vLLM: Qwen3.6-35B-A3B-FP8]
                                                 │
                                                 ▼
                                        回答與步驟 (SSE 串流)
```

### 5.2 步驟進度 SSE 發送事件
對話串流中，後端會依序透過 `event: step` 回傳處理進度：
1. **`semantic_analysis`**：回傳地端 AI 生成的結構化 JSON。
2. **`retrieval`**：回傳檢索到的 Chunks、檔案來源與 RRF 分數。
3. **`thinking`**：回傳 LLM 的思考過程（如有）。
4. **`done`**：完成標記。

### 5.3 外部服務通訊

| 服務 | 協定 | 端點 | 用途 |
|:---|:---|:---|:---|
| vLLM | HTTP | `http://<host>:8000/v1/chat/completions` | LLM 生成回答 |
| llama.cpp (Embedding) | HTTP | `http://<host>:8081/embedding` | 生成密集向量 (Dense Vector) |
| llama.cpp (Instruct) | HTTP | `http://<host>:8082/v1/chat/completions` | 提問語義解析轉 JSON |
| Qdrant | HTTP / gRPC | `http://<host>:6333` | 雙路向量檢索與管理 |
| MongoDB | TCP | `mongodb://<host>:27017` | 讀寫應用資料、設定與歷史紀錄 |
| SQL Server | ODBC | `mssql+pyodbc://...` | 唯讀查詢既有知識與導入 |
| Oracle Database | TCP (Thin) | `oracledb Thin` 連線 | 唯讀查詢自訂 DB 欄位與導入 |

---

## 6. 部署與配置

### 6.1 環境變數 (.env)

```env
# 認證
AUTH_USERNAME=admin
AUTH_PASSWORD_HASH=<bcrypt-hashed-password>

# vLLM
VLLM_BASE_URL=http://<vllm-host>:8000/v1
VLLM_MODEL=Qwen3.6-35B-A3B-FP8

# llama.cpp (密集向量)
LLAMACPP_BASE_URL=http://localhost:8081
EMBEDDING_MODEL=Qwen3-Embedding-8B-Q8_0.gguf

# llama.cpp (Instruct 語義化 AI) [NEW]
DenseVector_LLAMACPP_BASE_URL=http://localhost:8082
DenseVector_INSTRUCT_MODEL=Qwen3VL-8B-Instruct-Q4_K_M.gguf

# Qdrant
QDRANT_HOST=localhost
QDRANT_PORT=6333

# MongoDB
MONGODB_URL=mongodb://localhost:27017
MONGODB_DATABASE=airag

# SQL Server (唯讀)
SQLSERVER_CONNECTION_STRING=mssql+pyodbc://<user>:<pwd>@<host>/<db>?driver=ODBC+Driver+17+for+SQL+Server
```
