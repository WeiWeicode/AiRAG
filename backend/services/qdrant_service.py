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
        query_vector: Optional[List[float]] = None, 
        top_k: int = 5, 
        score_threshold: float = 0.7,
        filter_tags: Optional[List[str]] = None,
        filter_filename: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        依據向量相似度檢索資料塊（若無向量則執行 Scroll 查詢）。
        """
        client = cls.get_client()
        try:
            exists = await client.collection_exists(collection_name)
            if not exists:
                logger.warning(f"Collection '{collection_name}' does not exist.")
                return []
            
            must_conditions = []
            if filter_tags:
                must_conditions.append(
                    models.FieldCondition(
                        key="tags",
                        match=models.MatchAny(any=filter_tags)
                    )
                )
            if filter_filename:
                must_conditions.append(
                    models.FieldCondition(
                        key="filename",
                        match=models.MatchValue(value=filter_filename)
                    )
                )
            
            query_filter = None
            if must_conditions:
                query_filter = models.Filter(must=must_conditions)
            
            if query_vector is None:
                # 執行無向量條件的 Scroll 查詢
                scroll_result = await client.scroll(
                    collection_name=collection_name,
                    limit=top_k,
                    scroll_filter=query_filter,
                    with_payload=True,
                    with_vectors=False
                )
                results = scroll_result[0]
            else:
                response = await client.query_points(
                    collection_name=collection_name,
                    query=query_vector,
                    limit=top_k,
                    score_threshold=score_threshold,
                    query_filter=query_filter
                )
                results = response.points
            
            search_results = []
            for res in results:
                score = getattr(res, "score", 0.0)
                if score is None:
                    score = 0.0
                search_results.append({
                    "chunk_id": str(res.id),
                    "content": res.payload.get("content", ""),
                    "metadata": {
                        "filename": res.payload.get("filename"),
                        "page": res.payload.get("page"),
                        "section": res.payload.get("section"),
                        "chunk_index": res.payload.get("chunk_index"),
                        "tags": res.payload.get("tags", [])
                    },
                    "score": score,
                    "distance": 1.0 - score
                })
            return search_results
        except Exception as e:
            logger.error(f"Failed to search similarity in Qdrant collection '{collection_name}': {e}")
            return []

    @classmethod
    async def get_unique_metadata(cls, collection_name: str) -> Dict[str, List[str]]:
        """
        從向量庫集合中提取所有唯一的檔案名稱與標籤。
        """
        client = cls.get_client()
        try:
            exists = await client.collection_exists(collection_name)
            if not exists:
                return {"filenames": [], "tags": []}
                
            filenames = set()
            tags = set()
            
            # 捲動取得點，僅需要 filename 與 tags 欄位，加快效率
            scroll_result = await client.scroll(
                collection_name=collection_name,
                limit=10000,
                with_payload=["filename", "tags"],
                with_vectors=False
            )
            
            points = scroll_result[0]
            for p in points:
                payload = p.payload or {}
                fn = payload.get("filename")
                if fn:
                    filenames.add(fn)
                t_list = payload.get("tags")
                if t_list and isinstance(t_list, list):
                    for t in t_list:
                        if t:
                            tags.add(t)
                            
            return {
                "filenames": sorted(list(filenames)),
                "tags": sorted(list(tags))
            }
        except Exception as e:
            logger.error(f"Failed to scroll unique metadata from Qdrant: {e}")
            return {"filenames": [], "tags": []}
