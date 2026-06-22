# 系統架構設計文件 (Architecture Design Document)

## 1. 文件資訊
* **專案名稱**：AiRAG 內部測試平台
* **文件版本**：V 1.0
* **建立日期**：2026-06-18
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
│  │ Module │ │Pipeline│ │ Engine │ │                     │  │
│  └────────┘ └────────┘ └────────┘ └─────────────────────┘  │
│  ┌────────┐ ┌──────────┐ ┌──────────────────────────────┐  │
│  │Feedback│ │ Retrieval│ │ Prompt Template Engine       │  │
│  │Service │ │ Service  │ │                              │  │
│  └────────┘ └──────────┘ └──────────────────────────────┘  │
└─────┬──────────┬────────────┬──────────────┬───────────────┘
      │          │            │              │
      ▼          ▼            ▼              ▼
┌────────┐ ┌────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐
│SQL     │ │MongoDB │ │ Qdrant   │ │ vLLM     │ │ llama.cpp    │
│Server  │ │(App DB)│ │(VectorDB)│ │ (LLM)    │ │ (Embedding)  │
│(唯讀)  │ │        │ │          │ │          │ │              │
└────────┘ └────────┘ └──────────┘ └──────────┘ └──────────────┘
```

### 2.2 架構風格
採用 **分層式架構 (Layered Architecture)** 搭配 **模組化設計**：
* **展示層**：Vue 3 SPA 前端
* **應用層**：FastAPI 路由 + 業務邏輯
* **服務層**：RAG Pipeline、Embedding、Evaluation 等核心服務
* **資料存取層**：MongoDB (motor/beanie) + SQL Server (唯讀) + Qdrant Client
* **外部服務層**：vLLM、llama.cpp

---

## 3. 前端架構

### 3.1 技術棧
| 項目 | 技術選型 | 說明 |
|:---|:---|:---|
| 框架 | Vue 3 (Composition API) | 搭配 Vite 建構工具 |
| UI 套件 | Tailwind CSS | 工具類優先 CSS 框架 |
| 狀態管理 | Pinia | Vue 3 官方推薦 |
| 路由 | Vue Router 4 | SPA 頁面路由 |
| HTTP 客戶端 | Axios / Fetch API | API 呼叫 |
| 串流處理 | 原生 `fetch` + `ReadableStream` | SSE 串流接收 |
| Markdown 渲染 | markdown-it + highlight.js | 回答內容渲染 |

### 3.2 頁面結構

```
src/
├── views/
│   ├── LoginView.vue              # 登入頁面
│   ├── DashboardView.vue          # 儀表板首頁
│   ├── RagTestView.vue            # §4.1 RAG 功能測試
│   ├── RetrievalTestView.vue      # §4.2 向量搜尋測試
│   ├── EvaluationView.vue         # §4.3 準確度評估
│   ├── PromptTestView.vue         # §4.4 自訂 Context 生成
│   ├── EmbeddingTestView.vue      # §4.5 資料向量化
│   └── FeedbackView.vue           # §4.6 回饋標註歷史
├── components/
│   ├── API/
│   │   ├── api_connector.js       # API 連線管理
│   │   ├── auth_api.js            # 認證 API
│   │   ├── rag_api.js             # RAG API
│   │   ├── retrieval_api.js       # 向量搜尋 API
│   │   ├── evaluation_api.js      # 評估 API
│   │   ├── prompt_api.js          # Prompt API
│   │   └── embedding_api.js       # Embedding API
│   ├── chat/
│   │   ├── ChatWindow.vue         # 對話視窗
│   │   ├── MessageBubble.vue      # 訊息氣泡
│   │   ├── SourceChunks.vue       # 引用來源展示
│   │   ├── StreamRenderer.vue     # 串流文字渲染
│   │   └── FeedbackPanel.vue      # §4.6 標記面板
│   ├── params/
│   │   ├── LlmParamsPanel.vue     # LLM 參數設定
│   │   ├── RagParamsPanel.vue     # RAG 參數設定
│   │   └── ChunkingParams.vue     # Chunking 策略設定
│   ├── eval/
│   │   ├── TestSetManager.vue     # 測試集管理
│   │   ├── ScoreBoard.vue         # 評分看板
│   │   └── ReportChart.vue        # 圖表元件
│   ├── embedding/
│   │   ├── FileUploader.vue       # 檔案上傳
│   │   ├── ChunkPreview.vue       # Chunk 預覽
│   │   └── TokenCounter.vue       # Token 計數
│   └── common/
│       ├── AppSidebar.vue         # 側邊導航列
│       ├── AppHeader.vue          # 頂部導航列
│       ├── DarkModeToggle.vue     # 深色模式切換
│       └── KnowledgeBaseSelector.vue
├── stores/
│   ├── authStore.js
│   ├── chatStore.js
│   ├── paramsStore.js
│   └── feedbackStore.js
├── services/
│   ├── api.js                     # Axios instance
│   ├── ragService.js
│   ├── retrievalService.js
│   ├── embeddingService.js
│   ├── evalService.js
│   └── feedbackService.js
└── router/
    └── index.js
```

### 3.3 深色模式策略
* 使用 Tailwind CSS `dark:` 前綴
* 偏好設定儲存於 `localStorage`
* 預設啟用深色模式

---

## 4. 後端架構

### 4.1 技術棧
| 項目 | 技術選型 | 說明 |
|:---|:---|:---|
| Web 框架 | FastAPI | Python 非同步框架 |
| 應用資料庫 | motor + beanie | MongoDB 非同步 ODM |
| 既有知識庫 | pyodbc / aioodbc | SQL Server 唯讀連線 |
| 向量 DB 客戶端 | qdrant-client | Qdrant SDK |
| LLM 呼叫 | openai (vLLM 相容) | OpenAI 相容 API |
| Embedding | HTTP Client | llama.cpp server API |
| 文件解析 | Unstructured / PyMuPDF | PDF、DOCX 解析 |
| 串流回應 | sse-starlette | Server-Sent Events |

### 4.2 專案結構

```
backend/
├── main.py                        # FastAPI 入口
├── config.py                      # 設定管理
├── .env                           # 環境變數 (含加密密碼)
├── routers/
│   ├── auth.py                    # 登入認證
│   ├── rag.py                     # §4.1 RAG 測試
│   ├── retrieval.py               # §4.2 向量搜尋
│   ├── evaluation.py              # §4.3 準確度評估
│   ├── prompt.py                  # §4.4 Prompt 測試
│   ├── embedding.py               # §4.5 Embedding
│   └── feedback.py                # §4.6 人工回饋
├── services/
│   ├── llm_service.py             # vLLM 封裝
│   ├── embedding_service.py       # llama.cpp 封裝
│   ├── qdrant_service.py          # Qdrant 操作
│   ├── chunking_service.py        # 文本切分
│   ├── document_parser.py         # 文件解析
│   ├── eval_service.py            # 評估引擎
│   ├── feedback_service.py        # 回饋業務邏輯
│   └── prompt_engine.py           # Prompt 模板引擎
├── models/                        # MongoDB Document Models (beanie)
│   ├── mongodb.py                 # MongoDB 連線管理
│   ├── sqlserver.py               # SQL Server 唯讀連線
│   ├── chat_session.py            # 對話 Session
│   ├── chat_message.py            # 對話訊息
│   ├── test_dataset.py            # 測試集
│   ├── eval_report.py             # 評估報告
│   ├── feedback.py                # 回饋標註
│   ├── prompt_template.py         # Prompt 模板
│   └── app_config.py              # 應用設定
├── schemas/                       # Pydantic Schema
│   ├── auth.py
│   ├── rag.py
│   ├── retrieval.py
│   ├── evaluation.py
│   ├── embedding.py
│   └── feedback.py
├── middleware/
│   ├── auth_middleware.py
│   └── cors.py
└── utils/
    ├── security.py                # bcrypt + JWT
    └── helpers.py
```

### 4.3 RAG Pipeline 流程 (§4.1)

```
Query → Query Embedding (llama.cpp)
          → Vector Search (Qdrant, Top-K, Threshold)
            → Context Assembly (Chunks + Chat History)
              → Prompt Building (System + Context + Question)
                → LLM Generation (vLLM, SSE 串流)
                  → Response + Source Chunks
```

### 4.4 人工回饋流程 (§4.6)

```
AI 回答完成 → 工程師標記 ✅/❌
  ├── ✅ 正確 → 儲存標註紀錄
  └── ❌ 不正確 → 填入正確答案 + 錯誤分類
                   → 儲存至 Feedback 表
                   → 可一鍵匯入 §4.3 測試集
```

---

## 5. 資料流

### 5.1 各功能模組資料流

| 功能 | 輸入 | 處理 | 輸出 |
|:---|:---|:---|:---|
| §4.1 RAG 測試 | Query + 參數 | Embed → Search → LLM | 串流回答 + Sources |
| §4.2 向量搜尋 | Query + 檢索參數 | Embed → Search | Chunk 列表 + 分數 |
| §4.3 準確度評估 | 測試集 | 批次 RAG → LLM Judge | 評分報告 + 圖表 |
| §4.4 Prompt 測試 | Context + Prompt | 變數替換 → LLM | 生成結果 |
| §4.5 向量化 | 文件/文字 | Parse → Chunk → Embed | Chunk 預覽 + 寫入 |
| §4.6 人工回饋 | 回答 + 標註 | 儲存 + 可匯入測試集 | 標註歷史 |

### 5.2 外部服務通訊

| 服務 | 協定 | 端點 | 用途 |
|:---|:---|:---|:---|
| vLLM | HTTP (OpenAI 相容) | `http://<host>:8000/v1/chat/completions` | LLM 推論 |
| llama.cpp | HTTP | `http://<host>:8080/embedding` | 向量化 |
| Qdrant | HTTP / gRPC | `http://<host>:6333` | 向量存取 |
| MongoDB | TCP | `mongodb://<host>:27017` | 應用資料（讀寫） |
| SQL Server | ODBC | `mssql+pyodbc://...` | 既有知識庫（唯讀） |

---

## 6. 部署架構

### 6.1 Docker Compose 服務

```yaml
services:
  frontend:
    build: ./frontend
    ports: ["53010:80"]
    depends_on: [backend]

  backend:
    build: ./backend
    ports: ["53020:53020"]
    env_file: .env
    depends_on: [mongodb, qdrant]

  mongodb:
    image: mongo:7
    ports: ["27017:27017"]
    volumes: ["mongo_data:/data/db"]
    environment:
      MONGO_INITDB_DATABASE: airag

  qdrant:
    image: qdrant/qdrant:latest
    ports: ["6333:6333", "6334:6334"]
    volumes: ["qdrant_data:/qdrant/storage"]

# vLLM、llama.cpp、SQL Server 為既有服務，不在此 Compose 管理
```

### 6.2 環境變數 (.env)

```env
# 認證
AUTH_USERNAME=admin
AUTH_PASSWORD_HASH=<bcrypt-hashed-password>

# vLLM
VLLM_BASE_URL=http://<vllm-host>:8000/v1
VLLM_MODEL=Qwen3.6-35B-A3B-FP8

# llama.cpp
LLAMACPP_BASE_URL=http://<llamacpp-host>:8080
EMBEDDING_MODEL=Qwen3-Embedding-8B-Q8_0.gguf

# Qdrant
QDRANT_HOST=qdrant
QDRANT_PORT=6333

# MongoDB (應用資料)
MONGODB_URL=mongodb://mongodb:27017
MONGODB_DATABASE=airag

# SQL Server (既有知識庫，唯讀)
SQLSERVER_CONNECTION_STRING=mssql+pyodbc://<user>:<pwd>@<host>/<db>?driver=ODBC+Driver+17+for+SQL+Server

# 預設參數
DEFAULT_TOP_K=5
DEFAULT_SCORE_THRESHOLD=0.7
DEFAULT_CHUNK_SIZE=512
DEFAULT_CHUNK_OVERLAP=50
```

---

## 7. 安全架構

### 7.1 認證流程

```
使用者 → POST /api/auth/login (帳號+密碼)
  → 後端比對 .env 中 bcrypt 雜湊
    → 成功 → 回傳 JWT Token → 前端存 localStorage
    → 失敗 → 401 錯誤
  → 後續請求帶 Authorization: Bearer <token>
```

### 7.2 安全措施
* 密碼使用 **bcrypt** 雜湊存儲於 `.env`
* API 使用 **JWT Token** 認證
* CORS 限制為前端域名
* 所有 AI 推論在內網完成，資料不外傳
