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

async def seed_default_knowledge_base():
    """
    如果資料庫中沒有任何知識庫項目，則建立預設的知識庫與向量資料庫 Collection。
    """
    try:
        count = await KnowledgeBase.count()
        if count == 0:
            logger.info("No knowledge bases found in database. Seeding a default one...")
            from datetime import datetime
            from beanie import PydanticObjectId
            from services.qdrant_service import QdrantService
            
            kb_id = PydanticObjectId()
            qdrant_collection_name = f"kb_{str(kb_id)}"
            
            qdrant_success = await QdrantService.create_collection(qdrant_collection_name)
            if qdrant_success:
                kb = KnowledgeBase(
                    id=kb_id,
                    name="預設知識庫",
                    description="系統自動建立的預設知識庫",
                    qdrant_collection_name=qdrant_collection_name,
                    embedding_model="Qwen3-Embedding-8B-Q8_0.gguf",
                    chunk_count=0,
                    created_by="system",
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                await kb.insert()
                logger.info(f"Default knowledge base seeded successfully: {kb_id}")
            else:
                logger.error("Failed to create Qdrant collection for the default knowledge base.")
    except Exception as e:
        logger.error(f"Failed to seed default knowledge base: {e}")

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
        
        # 進行資料庫引導種植
        await seed_default_knowledge_base()
        
    except Exception as e:
        logger.error(f"Failed to initialize MongoDB/Beanie: {e}")
        raise e

