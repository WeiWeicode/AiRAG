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
    # arq 預設 job_timeout 只有 300 秒，含大量內嵌圖片的 Word/PDF 會在圖片描述階段被
    # 判定 TimeoutError 而整份文件同步失敗，這裡改為可由環境變數調整
    job_timeout = settings.INGEST_JOB_TIMEOUT
    max_tries = settings.INGEST_JOB_MAX_TRIES
    # arq 預設可同時跑 10 個任務，而圖片描述併發是每個任務各自計算的，
    # 不設限時多份文件同步會讓地端 vLLM 被 10 × IMAGE_CAPTION_CONCURRENCY 個請求塞爆
    max_jobs = settings.ARQ_MAX_JOBS
