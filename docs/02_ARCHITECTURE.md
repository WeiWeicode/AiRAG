# 系統架構設計文件 (Architecture Design Document)

## 1. 文件資訊
* **專案名稱**：AiRAG 內部測試平台
* **文件版本**：V 1.2（依實際程式碼校正）
* **建立日期**：2026-06-18
* **更新日期**：2026-07-02
* **對應 PRD**：01_RPD.md

> 本版本已對照 `backend/`、`frontend/src/` 實際目錄與 `docs/DevelopmentProcess/*.md` 修改紀錄校正專案結構與核心資料流，移除前一版文件中尚未實作的檔案（`middleware/`、`eval_service.py`、`feedback_service.py`、`prompt_engine.py`、`helpers.py`），並補上 2026-07-01 新增的雙階段關聯檢索（Two-Step Hybrid Retrieval）與知識庫關聯地圖機制。

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
│  │ Router │ │ Router │ │ Router │ │ (Dense + Sparse)    │  │
│  │        │ │(Step-by│ │(SSE)   │ │                     │  │
│  │        │ │ -Step) │ │        │ │                     │  │
│  └────────┘ └────────┘ └────────┘ └─────────────────────┘  │
│  ┌────────┐ ┌──────────┐ ┌──────────────────────────────┐  │
│  │Feedback│ │ Retrieval│ │ Prompt Router                │  │
│  │Router  │ │ Router   │ │ (Templates & Records CRUD)   │  │
│  └────────┘ └──────────┘ └──────────────────────────────┘  │
│  ┌─────────────────────┐ ┌──────────────────────────────┐  │
│  │ Database Indexing   │ │ Parent-Child Chunker         │  │
│  │ Router (SQL/Oracle) │ │ (Word, MD, 4GL, 4FD)         │  │
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

> 圖中的業務邏輯目前實際位於各 `routers/*.py` 內（例如評估、回饋、Prompt 邏輯直接寫在對應 router），並非獨立的 `services/eval_service.py` 等模組——詳見 §4.2 專案結構。

### 2.2 架構風格
採用 **分層式架構 (Layered Architecture)** 搭配 **模組化設計**：
* **展示層**：Vue 3 SPA 前端
* **應用層**：FastAPI 路由（含大部分業務邏輯，見 §4.2 說明）
* **服務層**：`services/` 內的 RAG 檢索、Embedding、Chunking 等可重用核心服務
* **資料存取層**：MongoDB (motor/beanie) + SQL Server & Oracle (唯讀) + Qdrant Client (雙向量命名空間)
* **外部服務層**：vLLM、llama.cpp（Embedding + Instruct 語義化 AI）

---

## 3. 前端架構

### 3.1 技術棧
| 項目 | 技術選型 | 說明 |
|:---|:---|:---|
| 框架 | Vue 3 (Composition API) | 搭配 Vite 建構工具 |
| UI 套件 | Tailwind CSS | 工具類優先 CSS 框架 |
| 狀態管理 | Pinia | Vue 3 官方推薦 |
| 路由 | Vue Router 4 | SPA 頁面路由，除 `/login` 外皆需 `requiresAuth` |
| HTTP 客戶端 | Axios | 封裝於 `src/services/api.js` |
| 串流處理 | 原生 `fetch` + `ReadableStream` | SSE 串流接收與折疊步驟解析 |
| Markdown 渲染 | markdown-it + highlight.js | 回答內容渲染與結構化 JSON 代碼區塊高亮 |

> `vite.config.js` 僅註冊 `@vitejs/plugin-vue`，未設定 dev-server proxy 或路徑別名；API base URL 直接寫在 `src/services/api.js`。目前未設定 ESLint/Prettier 與 `lint`/`test` script。

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
│   ├── API/                       # ⚠️ 與 services/ 重複的舊版 API 模組，非實際使用中的 API 層
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
│   │   ├── SingleIndexingTab.vue  # 單筆索引面板
│   │   ├── SemanticJSONTab.vue    # 地端 AI 語義 JSON 匯入分頁
│   │   ├── BatchIndexingTab.vue   # 自動分批寫入面板 (含雙層切分、Word 支援)
│   │   ├── DatabaseIndexingTab.vue # 資料庫連線匯入分頁
│   │   └── VectorManagementTab.vue # 向量管理頁面 (含 links_to 關聯檔案管理與徽章顯示)
│   └── common/
│       ├── AppSidebar.vue         # 側邊導航列
│       ├── AppHeader.vue          # 頂部導航列
│       ├── DarkModeToggle.vue     # 深色模式切換
│       └── KnowledgeBaseSelector.vue
├── stores/
│   ├── authStore.js
│   ├── chatStore.js               # 支援對話串流與 SSE step 事件解析
│   ├── paramsStore.js             # 支援 enableStructuring 文字結構化設定
│   └── feedbackStore.js           # 支援刪除與批次刪除 actions
├── services/                      # 實際使用中的 Axios API 層
│   ├── api.js                     # Axios 實例
│   ├── ragService.js
│   ├── retrievalService.js        # 支援 points 批次刪除、檔案過濾與 updateLinks
│   ├── embeddingService.js        # 支援標籤、類別與 JSON 匯入
│   ├── databaseIndexingService.js # 資料庫匯入 API
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
| 既有知識庫 | pyodbc | SQL Server 唯讀連線 |
| Oracle 庫 | oracledb | Oracle Database 唯讀連線（優先 Thick Mode，載入 Instant Client 失敗則自動降級 Thin Mode） |
| 向量 DB 客戶端 | qdrant-client | Qdrant SDK（支援密集與稀疏索引） |
| 稀疏向量生成 | fastembed | SPLADE (sparse-text) 稀疏關鍵字生成 |
| LLM 呼叫 | httpx（OpenAI 相容 API） | 呼叫 vLLM `/v1/chat/completions` |
| Embedding | httpx Client | llama.cpp server API |
| 文件解析 | pymupdf / python-docx | PDF、DOCX、DOC、DOTX、MD 解析 |
| XML 解析 | xml.etree.ElementTree | Genero .4fd 畫面檔解析（namespace-insensitive） |
| 串流回應 | sse-starlette / 原生 `StreamingResponse` | Server-Sent Events (SSE) 狀態發送 |

### 4.2 專案結構

```
backend/
├── main.py                        # FastAPI 入口，註冊所有 routers，CORS 全開（開發階段）
├── config.py                      # Settings：認證、vLLM、llama.cpp(x2)、Qdrant、MongoDB、SQL Server 環境變數
├── .env                           # 環境變數（git-ignored，無 .env.example）
├── routers/
│   ├── auth.py                    # 登入認證（唯一不需 Bearer Token 的 router）
│   ├── rag.py                     # RAG 對話 SSE（step/chunk/sources 事件）
│   ├── retrieval.py               # 向量搜尋、語義混合搜尋、Points 批次刪除/刪檔/更新關聯
│   ├── evaluation.py               # 測試集 CRUD + SSE 評估跑分（含 structured_metadata 傳遞）
│   ├── prompt.py                  # Prompt 預覽/A-B測試(SSE)/範本/歷史 CRUD（/generate 為 stub）
│   ├── embedding.py               # 上傳/切分預覽/向量化/JSON匯入/標籤/類別
│   ├── feedback.py                # 人工回饋刪除與批次刪除
│   ├── knowledge_base.py          # 知識庫 CRUD 與檔案元資料/結構化地圖
│   ├── database_indexing.py       # 自訂資料庫（SQL Server/Oracle）連線與匯入向量化
│   └── sqlserver.py               # 既有 SQL Server 文章分頁查詢與導入
├── services/
│   ├── llm_service.py             # vLLM 封裝
│   ├── embedding_service.py       # llama.cpp 封裝，含 query_to_semantic_json（語義結構 JSON 分析 + 反幻想 Prompt + 結構化地圖注入）
│   ├── sparse_embedding_service.py # fastembed 封裝 (SPLADE 稀疏向量)
│   ├── qdrant_service.py          # Qdrant 操作：建立/刪除 collection、RRF 混合搜尋 (search_similar)、雙階段關聯檢索 (search_similar_two_step)、取得結構化 metadata (get_unique_metadata)、更新 links_to (update_links_to_by_filename)、Points 刪除、Parent-Child 動態拼接還原 (get_siblings_and_merge)
│   ├── chunking_service.py        # 標準文本切分
│   ├── document_parser.py         # 文件解析 (整合 Word 與 4GL 格式)
│   ├── word_parent_child_chunker.py # Word 結構化與雙層切分服務
│   ├── markdown_parent_child_chunker.py # MD 雙層標題路徑切分工具
│   └── parent_child_chunker.py    # 4GL 與 4FD 語法/結構雙層切分
├── models/                        # MongoDB Document Models (beanie)
│   ├── mongodb.py                 # init_beanie 註冊清單 + 啟動 seed 邏輯（預設 KB/測試集/範本/A-B紀錄）
│   ├── sqlserver.py               # SQL Server 連線輔助函式（非 beanie Document）
│   ├── database_config.py         # 資料庫連線配置模型
│   ├── tag.py                     # 分類標籤模型
│   ├── class_option.py            # 自訂類別選項模型
│   ├── prompt_test_record.py      # Prompt 測試歷史與結果模型
│   ├── prompt_template.py         # Prompt 模板
│   ├── chat_session.py
│   ├── chat_message.py
│   ├── test_dataset.py
│   ├── eval_report.py
│   ├── feedback.py
│   └── app_config.py
├── schemas/                       # Pydantic Schema（僅部分模組使用獨立檔案，其餘定義於各 router 內）
│   ├── auth.py
│   ├── retrieval.py                # SearchParams / RetrievalMetadata(含 links_to) / UpdateLinksRequest 等
│   ├── embedding.py
│   ├── knowledge_base.py
│   ├── database_indexing.py
│   └── sqlserver.py
│   # 註：rag / evaluation / prompt / feedback 的 request/response 模型目前定義於對應 routers/*.py 內，未拆分至 schemas/
└── utils/
    └── security.py                # bcrypt + JWT (verify_password / create_access_token / get_current_user)
```

> **與前一版文件的差異**：`middleware/`（`auth_middleware.py`/`cors.py`）、`services/eval_service.py`、`services/feedback_service.py`、`services/prompt_engine.py`、`utils/helpers.py` 於目前程式碼中**皆不存在**，對應邏輯已內聯在各 router 檔案中，不應視為獨立模組。

---

## 5. 核心管道資料流

### 5.1 RAG 與雙階段關聯檢索流程 (Two-Step Hybrid Retrieval)

當使用者在前端啟用「**語義混合查詢 (semantic_hybrid)**」時（`/api/rag/chat`、`/api/retrieval/search`、`/api/retrieval/semantic-hybrid-search`、`/api/evaluation/run` 皆共用同一套邏輯），系統資料流如下：

```
Query (原始提問)
  │
  ▼
[取得知識庫結構化地圖] QdrantService.get_unique_metadata()
  └─► { filenames, tags, structured_metadata: [{filename, class, tags, links_to}, ...] }
  │
  ▼
[地端語義化 AI: Qwen3VL-8B-Instruct] (/v1/chat/completions)
  │ EmbeddingService.query_to_semantic_json(question, structured_metadata=...)
  │ 內建「反幻想 (防腦補)」規則與 Few-Shot 範例，並注入知識庫結構地圖引導精確關鍵字比對
  ▼
Structured JSON { "embeddings_input": "...", "sparse_keywords": [...] }
  ├── embeddings_input ──► [llama.cpp Embedding, :8081] ──► Dense Vector (4096 維)
  └── sparse_keywords  ──► [fastembed] ──► Sparse Vector (SPLADE)
                                                 │
                                                 ▼
                          [Qdrant 第一階段：核心實體檢索 (1st-hop)]
                            search_similar()：Dense + Sparse Prefetch → RRF 融合
                                                 │
                                                 ▼
                     解析召回結果的 links_to 欄位，收集所有關聯檔名/ID
                                                 │
                        ┌────────────────────────┴────────────────────────┐
                        │ 有 links_to                                     │ 無 links_to
                        ▼                                                 ▼
      [Qdrant 第二階段：一階鄰居檢索 (2nd-hop)]                    直接使用第一階段結果
      以 filename/custom_id 過濾關聯範圍，
      用同一組 query_vector/query_text 進行
      密集+稀疏 Hybrid 檢索（含 score_threshold
      門檻過濾與 exact-keyword boost），
      neighbor_limit 預設 10
                        │
                        ▼
        鄰居結果依 parent_id 去重、
        呼叫 get_siblings_and_merge 動態拼接還原
                        │
                        ▼
        與第一階段結果合併，依內容 .strip() 去重
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

**設計動機**（見 `docs/DevelopmentProcess/BugFix.md` 2026-07-01）：早期版本的第二階段對 `links_to` 關聯檔案直接用無差別 `scroll` 撈出全部（最多 50 筆）Chunks，會造成大量無關段落稀釋 Context；現行版本改為「有查詢向量時使用語意/關鍵字混合搜尋 + `score_threshold` 過濾」，僅在無查詢向量時（如單元測試）才降級為 `scroll`。

`vector`、`hybrid` 兩種模式仍呼叫單階段的 `search_similar()`，不會觸發雙階段鄰居搜尋。

### 5.2 步驟進度 SSE 發送事件
`/api/rag/chat` 對話串流中，後端依序透過 `event: step` 回傳處理進度，實際欄位為 `step` / `status` / `content`：
1. `step: "semantic_analysis"`（`status: running → success`）：語義分析結構化 JSON 與密集向量生成過程。
2. `step: "vector_search"`（`status: running → success/failed`）：向量檢索過程與召回摘要。
3. `step: "llm_thinking"`（`status: running`）：固定送出一次「正在整理思緒...」。
4. `step: "conclusion"`（`status: pending`）：固定送出一次的佔位事件。

隨後以 `event: chunk`（`type: reasoning/content/done`）串流 LLM 輸出，並在 `done` 之前送出一次 `event: sources`。詳細事件格式見 `03_API_CONTRACT.md` §3.1。

### 5.3 外部服務通訊

| 服務 | 協定 | 端點 | 用途 |
|:---|:---|:---|:---|
| vLLM | HTTP | `http://<host>:8000/v1/chat/completions` | LLM 生成回答 |
| llama.cpp (Embedding) | HTTP | `http://<host>:8081/embedding` | 生成密集向量 (Dense Vector) |
| llama.cpp (Instruct) | HTTP | `http://<host>:8082/v1/chat/completions` | 提問語義解析轉 JSON |
| Qdrant | HTTP / gRPC | `http://<host>:6333` | 雙路向量檢索與管理 |
| MongoDB | TCP | `mongodb://<host>:27017` | 讀寫應用資料、設定與歷史紀錄 |
| SQL Server | ODBC | `mssql+pyodbc://...` | 唯讀查詢既有知識與導入 |
| Oracle Database | TCP (Thick/Thin) | `oracledb` 連線 | 唯讀查詢自訂 DB 欄位與導入 |

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

# llama.cpp (Instruct 語義化 AI)
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

### 6.2 Docker Compose 服務
根目錄 `docker-compose.yml` 定義 4 個服務：`backend`（port 53020）、`mongodb`（mongo:7, 27017）、`qdrant`（qdrant/qdrant:latest, 6333/6334）、`frontend`（nginx:alpine 靜態託管 `frontend/dist`，port 53010，透過根目錄 `nginx.conf` 反向代理 `/api` 與 `/health` 至 backend）。`backend/Dockerfile` 額外安裝 Oracle Instant Client（依主機 CPU 架構放置對應 zip，見 `docs/DeploymentTroubleshooting.md`）與 unixODBC/FreeTDS。
