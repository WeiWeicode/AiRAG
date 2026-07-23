import logging
from typing import Optional
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from config import settings

logger = logging.getLogger("airag.services.arq_pool")


class ArqPool:
    """
    arq 背景佇列的連線池（Lazy Singleton，與 QdrantService.get_client() 相同的模式），
    供 API 行程端 (main.py) 呼叫端點時將 ingest 任務推入佇列使用。
    """
    _pool: Optional[ArqRedis] = None

    @classmethod
    async def get_pool(cls) -> ArqRedis:
        if cls._pool is None:
            cls._pool = await create_pool(
                RedisSettings(host=settings.REDIS_HOST, port=settings.REDIS_PORT)
            )
            logger.info(f"arq Redis pool connected: {settings.REDIS_HOST}:{settings.REDIS_PORT}")
        return cls._pool
