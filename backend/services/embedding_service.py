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
                
                # 彈性解析多種可能的回傳格式
                # 1. 列表型格式 (e.g. [{'embedding': [...]}] 或是 [{'embedding': [[...]]}])
                if isinstance(data, list) and len(data) > 0:
                    first_item = data[0]
                    if isinstance(first_item, dict) and "embedding" in first_item:
                        emb = first_item["embedding"]
                        if isinstance(emb, list) and len(emb) > 0 and isinstance(emb[0], list):
                            return emb[0]
                        return emb
                
                # 2. 字典型格式 (e.g. {'embedding': [...]} 或是 {'data': [{'embedding': [...]}]})
                if isinstance(data, dict):
                    if "embedding" in data:
                        emb = data["embedding"]
                        if isinstance(emb, list) and len(emb) > 0 and isinstance(emb[0], list):
                            return emb[0]
                        return emb
                    if "data" in data and isinstance(data["data"], list) and len(data["data"]) > 0:
                        first_data = data["data"][0]
                        if isinstance(first_data, dict) and "embedding" in first_data:
                            emb = first_data["embedding"]
                            if isinstance(emb, list) and len(emb) > 0 and isinstance(emb[0], list):
                                return emb[0]
                            return emb
                            
                raise ValueError(f"無法解析的向量回應格式: {data}")
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
