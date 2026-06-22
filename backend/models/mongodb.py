import logging
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
from config import settings

# 動態補丁：修復 Beanie 與 Motor 在 append_metadata 方法上的相容性問題
if not hasattr(AsyncIOMotorClient, "append_metadata"):
    def _append_metadata(self, metadata):
        if hasattr(self.delegate, "append_metadata"):
            try:
                self.delegate.append_metadata(metadata)
            except Exception:
                pass
    AsyncIOMotorClient.append_metadata = _append_metadata

# 載入所有 Beanie 模型
from models.app_config import AppConfig
from models.knowledge_base import KnowledgeBase
from models.prompt_template import PromptTemplate
from models.chat_session import ChatSession
from models.chat_message import ChatMessage
from models.feedback import Feedback
from models.test_dataset import TestDataset
from models.eval_report import EvalReport

logger = logging.getLogger("airag.mongodb")

async def init_mongodb():
    try:
        logger.info(f"Connecting to MongoDB at: {settings.MONGODB_URL}")
        client = AsyncIOMotorClient(settings.MONGODB_URL)
        
        await init_beanie(
            database=client[settings.MONGODB_DATABASE],
            document_models=[
                AppConfig,
                KnowledgeBase,
                PromptTemplate,
                ChatSession,
                ChatMessage,
                Feedback,
                TestDataset,
                EvalReport
            ]
        )
        logger.info("MongoDB and Beanie ODM initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize MongoDB/Beanie: {e}")
        raise e
