import logging
from arq.connections import RedisSettings
from config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("airag.worker")


async def process_ingest_task(ctx, payload: dict):
    """
    arq 背景任務進入點：處理 POST /api/external/ingest/trigger 排入的多應用 RAG 同步任務
    （見 MULTI_APP_RAG_SYNC_PLAN.md）。實際邏輯委派給 IngestService，維持 worker.py 只做
    任務註冊與生命週期管理。
    """
    from services.ingest_service import IngestService
    await IngestService.process(payload)


async def startup(ctx):
    """
    worker 行程獨立於 API 行程啟動，需自行初始化 MongoDB/Beanie 連線
    （沿用 main.py lifespan 使用的同一套 init_mongodb()）。
    """
    from models.mongodb import init_mongodb
    await init_mongodb()
    logger.info("arq worker 已啟動，MongoDB/Beanie 初始化完成。")


async def shutdown(ctx):
    logger.info("arq worker 準備關閉。")


class WorkerSettings:
    functions = [process_ingest_task]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings(host=settings.REDIS_HOST, port=settings.REDIS_PORT)
