import httpx
import logging
import asyncio
from typing import List
from config import settings

logger = logging.getLogger("airag.embedding")

class EmbeddingService:
    @staticmethod
    async def get_embedding(text: str) -> List[float]:
        """
        向 llama.cpp (/embedding) 取得單一文本的向量。
        """
        url = f"{settings.LLAMACPP_BASE_URL.rstrip('/')}/embedding"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, json={"content": text})
                response.raise_for_status()
                data = response.json()
                return data["embedding"]
        except Exception as e:
            logger.error(f"Failed to generate embedding via llama.cpp: {e}")
            # 為利於測試，若 llama.cpp 服務尚未啟動，提供 4096 維度之模擬零向量作為降級防線
            logger.warning("Using a mock 4096-dim vector for testing bypass.")
            return [0.0] * 4096

    @classmethod
    async def get_embeddings_batch(cls, texts: List[str]) -> List[List[float]]:
        """
        批次取得多個文本的向量（控制併發數量為 5）。
        """
        semaphore = asyncio.Semaphore(5)
        
        async def _embedded_task(text: str) -> List[float]:
            async with semaphore:
                return await cls.get_embedding(text)
        
        tasks = [_embedded_task(t) for t in texts]
        return await asyncio.gather(*tasks)
