import logging
import uuid
from typing import List, Dict, Any, Optional
from qdrant_client import AsyncQdrantClient, models
from config import settings

logger = logging.getLogger("airag.qdrant")

class QdrantService:
    _client: Optional[AsyncQdrantClient] = None

    @classmethod
    def get_client(cls) -> AsyncQdrantClient:
        if cls._client is None:
            # 建立非同步 Qdrant 客戶端連線
            cls._client = AsyncQdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
        return cls._client

    @classmethod
    async def create_collection(cls, collection_name: str) -> bool:
        """
        若 Collection 不存在則建立，設定向量維度為 4096，使用 Cosine 相似度。
        """
        client = cls.get_client()
        try:
            exists = await client.collection_exists(collection_name)
            if not exists:
                await client.create_collection(
                    collection_name=collection_name,
                    vectors_config=models.VectorParams(
                        size=4096,  # 配合 Qwen3-Embedding-8B
                        distance=models.Distance.COSINE
                    ),
                    hnsw_config=models.HnswConfigDiff(
                        m=16,
                        ef_construct=100
                    )
                )
                logger.info(f"Qdrant collection '{collection_name}' created successfully.")
            return True
        except Exception as e:
            logger.error(f"Failed to create Qdrant collection '{collection_name}': {e}")
            return False

    @classmethod
    async def delete_collection(cls, collection_name: str) -> bool:
        """
        刪除指定的 Qdrant Collection。
        """
        client = cls.get_client()
        try:
            exists = await client.collection_exists(collection_name)
            if exists:
                await client.delete_collection(collection_name=collection_name)
                logger.info(f"Qdrant collection '{collection_name}' deleted successfully.")
            return True
        except Exception as e:
            logger.error(f"Failed to delete Qdrant collection '{collection_name}': {e}")
            return False

    @classmethod
    async def upsert_chunks(
        cls, 
        collection_name: str, 
        chunks: List[Dict[str, Any]], 
        vectors: List[List[float]]
    ) -> int:
        """
        批次將切分好的區塊與對應向量寫入 Qdrant。
        """
        client = cls.get_client()
        # 確保 Collection 存在
        await cls.create_collection(collection_name)
        
        points = []
        for i, chunk in enumerate(chunks):
            point_id = str(uuid.uuid4())
            points.append(
                models.PointStruct(
                    id=point_id,
                    vector=vectors[i],
                    payload=chunk
                )
            )
        
        try:
            await client.upsert(
                collection_name=collection_name,
                points=points
            )
            logger.info(f"Upserted {len(points)} points into Qdrant collection '{collection_name}'.")
            return len(points)
        except Exception as e:
            logger.error(f"Failed to upsert points to Qdrant collection '{collection_name}': {e}")
            raise e

    @classmethod
    async def search_similar(
        cls, 
        collection_name: str, 
        query_vector: List[float], 
        top_k: int = 5, 
        score_threshold: float = 0.7
    ) -> List[Dict[str, Any]]:
        """
        依據向量相似度檢索資料塊。
        """
        client = cls.get_client()
        try:
            exists = await client.collection_exists(collection_name)
            if not exists:
                logger.warning(f"Collection '{collection_name}' does not exist.")
                return []
            
            results = await client.search(
                collection_name=collection_name,
                query_vector=query_vector,
                limit=top_k,
                score_threshold=score_threshold
            )
            
            search_results = []
            for res in results:
                search_results.append({
                    "chunk_id": str(res.id),
                    "content": res.payload.get("content", ""),
                    "metadata": {
                        "filename": res.payload.get("filename"),
                        "page": res.payload.get("page"),
                        "section": res.payload.get("section"),
                        "chunk_index": res.payload.get("chunk_index")
                    },
                    "score": res.score,
                    "distance": 1.0 - res.score
                })
            return search_results
        except Exception as e:
            logger.error(f"Failed to search similarity in Qdrant collection '{collection_name}': {e}")
            return []
