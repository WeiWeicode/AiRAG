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

async def seed_default_datasets():
    """
    如果資料庫中沒有任何測試集，則建立預設的測試集項目。
    """
    try:
        count = await TestDataset.count()
        if count == 0:
            logger.info("No test datasets found in database. Seeding default datasets...")
            from datetime import datetime
            from models.test_dataset import DatasetItem
            
            # Technical dataset
            tech_items = [
                DatasetItem(
                    question="什麼是 AiRAG 平台？",
                    ground_truth="AiRAG 是一個專為公司內部測試設計的網頁應用，支援 Embedding、Retrieval、Generation 等 RAG 模組的獨立與端到端測試，以協助工程師進行參數調優與量化評估。",
                    relevant_contexts=["AiRAG 是一個專為公司內部測試設計的網頁應用。它模組化地拆解了 RAG 流程，包括 Embedding、Retrieval、Generation 等階段，幫助工程師在內部安全地調優 Prompt 與參數。"]
                ),
                DatasetItem(
                    question="系統支援哪些向量檢索策略？",
                    ground_truth="系統支援純向量檢索、混合搜尋（向量 + BM25 關鍵字搜尋），並支援 Query Rewriting（查詢重寫）與 HyDE（假設性文件嵌入）等進階檢索策略。",
                    relevant_contexts=["向量搜尋測試模組中，工程師可切換純檢索模式，並設定 Top-K、相似度閾值等參數。系統亦支援 Hybrid Search（混合搜尋）、查詢重寫 (Query Rewriting) 以及假想文檔生成 (HyDE) 的評估與比對。"]
                )
            ]
            tech_dataset = TestDataset(
                name="技術規格測試集",
                description="用於評估技術規格文件 RAG 準確度的預設測試集",
                items=tech_items,
                item_count=len(tech_items),
                created_by="system",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            await tech_dataset.insert()
            
            # HR dataset
            hr_items = [
                DatasetItem(
                    question="公司員工請假規定為何？",
                    ground_truth="公司特休請假需提前三天於系統送出申請，並經部門主管審查同意；病假需於當天早上九點前通知並提供就醫證明。",
                    relevant_contexts=["人事規章請假管理辦法：同仁特休假應於三天前於差勤系統填寫假單送審。如遇突發病假，同仁應於當天上午九點前口頭或訊息通知主管，並於銷假後兩日內補傳就醫收據或診斷書。"]
                ),
                DatasetItem(
                    question="年終獎金的發放資格與標準是什麼？",
                    ground_truth="年終獎金依據員工當年度考績與在職比例發放，發放基準為 1 至 3 個月基本薪資，且發放當日員工必須在職。",
                    relevant_contexts=["薪酬福利與獎金發放準則：年終獎金之核發依同仁年度績效考核結果評定（優等為 3 個月，甲等為 2 個月，乙等為 1 個月）。獎金依當年度實際在職月數比例折算，發放當日需符合在職狀態始具備領取資格。"]
                )
            ]
            hr_dataset = TestDataset(
                name="人事規章測試集",
                description="用於評估人事規章 RAG 準確度的預設測試集",
                items=hr_items,
                item_count=len(hr_items),
                created_by="system",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            await hr_dataset.insert()
            
            logger.info("Default datasets seeded successfully.")
    except Exception as e:
        logger.error(f"Failed to seed default datasets: {e}")

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
        await seed_default_datasets()
        
    except Exception as e:
        logger.error(f"Failed to initialize MongoDB/Beanie: {e}")
        raise e

