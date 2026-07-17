import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

# 載入資料庫初始化邏輯
from models.mongodb import init_mongodb

# 載入所有路由模組
from routers import (
    auth,
    embedding,
    knowledge_base,
    rag,
    retrieval,
    evaluation,
    prompt,
    feedback,
    sqlserver,
    database_indexing,
    ai_db_query,
    attachment,
    dashboard,
    users,
    external,
    external_api_keys
)

# 設定日誌
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("airag.main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    應用程式生命週期管理，負責啟動時的資源初始化。
    """
    logger.info("Initializing AiRAG API Service...")
    await init_mongodb()
    logger.info("AiRAG API Service initialized successfully.")
    yield
    logger.info("Shutting down AiRAG API Service...")

app = FastAPI(
    title="AiRAG Testbed API",
    description="AiRAG 內部測試平台後端 API 服務",
    version="1.0",
    lifespan=lifespan
)

# 跨來源資源共用 (CORS) 設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 開發階段允許所有來源，生產環境應調整
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 註冊所有子模組路由
app.include_router(auth.router, prefix="/api")
app.include_router(embedding.router, prefix="/api")
app.include_router(knowledge_base.router, prefix="/api")
app.include_router(rag.router, prefix="/api")
app.include_router(retrieval.router, prefix="/api")
app.include_router(evaluation.router, prefix="/api")
app.include_router(prompt.router, prefix="/api")
app.include_router(feedback.router, prefix="/api")
app.include_router(sqlserver.router, prefix="/api")
app.include_router(database_indexing.router, prefix="/api")
app.include_router(ai_db_query.router, prefix="/api")
app.include_router(attachment.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(external.router, prefix="/api")
app.include_router(external_api_keys.router, prefix="/api")

@app.get("/health")
async def health_check():
    """
    健康檢查端點。
    """
    return {"status": "healthy", "service": "AiRAG Testbed API"}
