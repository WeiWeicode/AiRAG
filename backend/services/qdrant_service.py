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
        並新增 sparse-text 稀疏向量空間支援。
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
                    sparse_vectors_config={
                        "sparse-text": models.SparseVectorParams(
                            index=models.SparseIndexParams(
                                on_disk=True
                            )
                        )
                    },
                    hnsw_config=models.HnswConfigDiff(
                        m=16,
                        ef_construct=100
                    )
                )
                logger.info(f"Qdrant collection '{collection_name}' created successfully.")
            
            # 確保 'content' 欄位有建立全文檢索 Text Index，以支援 Exact keyword MatchText 查詢
            try:
                await client.create_payload_index(
                    collection_name=collection_name,
                    field_name="content",
                    field_schema=models.TextIndexParams(
                        type="text",
                        tokenizer=models.TokenizerType.WORD,
                        lowercase=True
                    )
                )
                logger.info(f"Ensured payload text index on 'content' for collection '{collection_name}'.")
            except Exception as e_idx:
                logger.warning(f"Failed or skipped ensuring payload index: {e_idx}")
                
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
        批次將切分好的區塊與對應向量寫入 Qdrant（包含密集向量與稀疏向量）。
        """
        client = cls.get_client()
        # 確保 Collection 存在
        await cls.create_collection(collection_name)
        
        # 批次生成 Chunks 的稀疏向量
        from services.sparse_embedding_service import SparseEmbeddingService
        texts = [chunk.get("content", "") for chunk in chunks]
        sparse_vectors = SparseEmbeddingService.get_sparse_vectors_batch(texts)
        
        points = []
        for i, chunk in enumerate(chunks):
            point_id = str(uuid.uuid4())
            points.append(
                models.PointStruct(
                    id=point_id,
                    vector={
                        "": vectors[i],                       # 預設密集向量
                        "sparse-text": sparse_vectors[i]      # 稀疏向量
                    },
                    payload=chunk
                )
            )
        
        try:
            await client.upsert(
                collection_name=collection_name,
                points=points
            )
            logger.info(f"Upserted {len(points)} points into Qdrant collection '{collection_name}' with sparse vectors.")
            return len(points)
        except Exception as e:
            error_str = str(e)
            if "Not existing vector name error: sparse-text" in error_str or "sparse-text" in error_str:
                logger.warning(f"Collection '{collection_name}' does not support sparse vectors. Falling back to dense vector only upsert.")
                points_dense_only = []
                for i, chunk in enumerate(chunks):
                    point_id = points[i].id
                    points_dense_only.append(
                        models.PointStruct(
                            id=point_id,
                            vector=vectors[i],  # 純密集向量
                            payload=chunk
                        )
                    )
                try:
                    await client.upsert(
                        collection_name=collection_name,
                        points=points_dense_only
                    )
                    logger.info(f"Successfully upserted {len(points_dense_only)} points with dense vectors only.")
                    return len(points_dense_only)
                except Exception as ex_dense:
                    logger.error(f"Fallback dense-only upsert failed: {ex_dense}")
                    raise ex_dense
            else:
                logger.error(f"Failed to upsert points to Qdrant collection '{collection_name}': {e}")
                raise e

    @classmethod
    async def search_similar(
        cls, 
        collection_name: str, 
        query_vector: Optional[List[float]] = None, 
        query_text: Optional[str] = None,
        search_type: str = "vector",
        top_k: int = 5, 
        score_threshold: float = 0.7,
        filter_tags: Optional[List[str]] = None,
        filter_filename: Optional[str] = None,
        disable_parent_merge: bool = False
    ) -> List[Dict[str, Any]]:
        """
        依據向量相似度檢索資料塊（可切換純向量或 Hybrid 雙路 RRF 混合檢索）。
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
            
            if search_type == "hybrid" and query_vector is not None and query_text is not None and query_text.strip():
                try:
                    from services.sparse_embedding_service import SparseEmbeddingService
                    query_sparse = SparseEmbeddingService.get_sparse_vector(query_text)
                    
                    prefetch_dense = models.Prefetch(
                        query=query_vector,
                        using="",  # 預設密集向量空間
                        limit=top_k * 2,
                        filter=query_filter
                    )
                    
                    prefetch_sparse = models.Prefetch(
                        query=query_sparse,
                        using="sparse-text",  # 稀疏向量空間
                        limit=top_k * 2,
                        filter=query_filter
                    )
                    
                    # 針對程式碼識別碼/關鍵字進行 Exact keyword Match text 搜尋加速
                    import re
                    # 提取長度大於等於3個字元、且非純數字的英數底線詞彙 (例如: p_zz_q)
                    keywords = [kw for kw in re.findall(r'[a-zA-Z0-9_]{3,}', query_text) if not kw.isdigit()]
                    
                    prefetch_list = [prefetch_dense, prefetch_sparse]
                    
                    if keywords:
                        exact_should = []
                        for kw in keywords:
                            # 1. 內容包含該字詞
                            exact_should.append(
                                models.FieldCondition(
                                    key="content",
                                    match=models.MatchText(text=kw)
                                )
                            )
                            # 2. 函數名稱精確匹配
                            exact_should.append(
                                models.FieldCondition(
                                    key="function_name",
                                    match=models.MatchValue(value=kw)
                                )
                            )
                            # 3. 父節點 ID 精確匹配
                            exact_should.append(
                                models.FieldCondition(
                                    key="parent_id",
                                    match=models.MatchValue(value=kw)
                                )
                            )
                        
                        exact_filter = models.Filter(
                            should=exact_should,
                            must=must_conditions if must_conditions else None
                        )
                        
                        # 第三路 prefetch：只針對包含 exact keywords 的區塊，進行稀疏向量排序
                        prefetch_exact = models.Prefetch(
                            query=query_sparse,
                            using="sparse-text",
                            limit=top_k * 2,
                            filter=exact_filter
                        )
                        prefetch_list.append(prefetch_exact)
                        logger.info(f"Hybrid search exact keyword boost active for keywords: {keywords}")
                    
                    # Qdrant 雙路或三路召回與 RRF 融合
                    response = await client.query_points(
                        collection_name=collection_name,
                        prefetch=prefetch_list,
                        query=models.FusionQuery(
                            fusion=models.Fusion.RRF
                        ),
                        limit=top_k
                    )
                    results = response.points
                    logger.info("Hybrid search executed successfully via Qdrant RRF (with exact keyword boost).")
                except Exception as he:
                    logger.warning(f"Hybrid search failed, falling back to pure vector search: {he}")
                    # 安全降級：純密集向量檢索
                    response = await client.query_points(
                        collection_name=collection_name,
                        query=query_vector,
                        limit=top_k,
                        score_threshold=score_threshold,
                        query_filter=query_filter
                    )
                    results = response.points
            elif query_vector is None:
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
                # 執行常規純密集向量檢索
                response = await client.query_points(
                    collection_name=collection_name,
                    query=query_vector,
                    limit=top_k,
                    score_threshold=score_threshold,
                    query_filter=query_filter
                )
                results = response.points
            
            # 1. 轉換並提取資訊
            temp_results = []
            for res in results:
                score = getattr(res, "score", 0.0)
                if score is None:
                    score = 0.0
                payload = res.payload or {}
                temp_results.append({
                    "chunk_id": str(res.id),
                    "content": payload.get("content", ""),
                    "metadata": {
                        "filename": payload.get("filename"),
                        "page": payload.get("page"),
                        "section": payload.get("section"),
                        "chunk_index": payload.get("chunk_index"),
                        "tags": payload.get("tags", []),
                        "parent_id": payload.get("parent_id"),
                        "parent_content": payload.get("parent_content"),
                        "parent_chunk_index_range": payload.get("parent_chunk_index_range"),
                        "function_name": payload.get("function_name"),
                        "type": payload.get("type")
                    },
                    "score": score,
                    "distance": 1.0 - score
                })
            
            if disable_parent_merge:
                return temp_results
            
            # 2. 根據 parent_id 進行去重 (保留分數高者)
            seen_parents = set()
            deduped_results = []
            for item in temp_results:
                parent_id = item["metadata"].get("parent_id")
                if parent_id:
                    if parent_id in seen_parents:
                        continue
                    seen_parents.add(parent_id)
                deduped_results.append(item)
            
            # 3. 處理 Parent-Child 的還原與合併
            final_results = []
            for item in deduped_results:
                meta = item["metadata"]
                parent_id = meta.get("parent_id")
                
                if parent_id:
                    parent_content = meta.get("parent_content")
                    parent_range = meta.get("parent_chunk_index_range")
                    
                    # 情況 A：若元資料中沒有預存的 parent_content，則從資料庫中撈取所有兄弟節點進行合併 (相容舊資料)
                    if not parent_content:
                        parent_content, parent_range = await cls.get_siblings_and_merge(
                            collection_name=collection_name,
                            parent_id=parent_id,
                            orig_content=item["content"],
                            metadata=meta
                        )
                    else:
                        # 情況 B：若元資料中已有 parent_content，若原內容是結構化的，需重新包裝成結構化樣式
                        if item["content"].startswith("[檔案名稱]"):
                            filename = meta.get("filename") or "unknown"
                            tags = ", ".join(meta.get("tags", [])) or "一般"
                            parent_content = (
                                f"[檔案名稱] {filename}\n"
                                f"[段落編號] 第 {parent_range} 段\n"
                                f"[分類標籤] {tags}\n"
                                f"[主要內容]\n"
                                f"{parent_content}"
                            )
                    
                    if parent_content:
                        item["content"] = parent_content
                    if parent_range:
                        item["metadata"]["chunk_index"] = parent_range
                        
                final_results.append(item)
                
            return final_results
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

    @classmethod
    async def delete_points(cls, collection_name: str, point_ids: List[str]) -> bool:
        """
        從指定 Collection 中批次刪除特定的 Points (向量節點)
        """
        client = cls.get_client()
        try:
            await client.delete(
                collection_name=collection_name,
                points_selector=models.PointIdsList(
                    points=point_ids
                )
            )
            logger.info(f"Successfully deleted {len(point_ids)} points from collection '{collection_name}'.")
            return True
        except Exception as e:
            logger.error(f"Failed to delete points from collection '{collection_name}': {e}")
            return False

    @classmethod
    async def delete_by_filename(cls, collection_name: str, filename: str) -> int:
        """
        從指定 Collection 中刪除所有匹配該檔案名稱的 Points (向量節點)，並回傳刪除的數量。
        """
        client = cls.get_client()
        try:
            # 1. 先 Scroll 獲取該 filename 的所有點以計算數量，並取得 ID 進行刪除
            scroll_result = await client.scroll(
                collection_name=collection_name,
                scroll_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="filename",
                            match=models.MatchValue(value=filename)
                        )
                    ]
                ),
                limit=10000,  # 預期單個檔案的 Chunks 不會超過 10000
                with_payload=False,
                with_vectors=False
            )
            points = scroll_result[0]
            count = len(points)
            
            if count > 0:
                point_ids = [p.id for p in points]
                await client.delete(
                    collection_name=collection_name,
                    points_selector=models.PointIdsList(points=point_ids)
                )
                logger.info(f"Successfully deleted {count} points for filename '{filename}' from collection '{collection_name}'.")
            return count
        except Exception as e:
            logger.error(f"Failed to delete points by filename '{filename}' from collection '{collection_name}': {e}")
            raise e

    @classmethod
    async def get_by_parent_id(cls, collection_name: str, parent_id: str) -> List[Dict[str, Any]]:
        """
        透過 parent_id 獲取同一 Parent Block 下的所有 Child Chunks。
        """
        client = cls.get_client()
        try:
            scroll_result = await client.scroll(
                collection_name=collection_name,
                scroll_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="parent_id",
                            match=models.MatchValue(value=parent_id)
                        )
                    ]
                ),
                limit=1000,
                with_payload=True,
                with_vectors=False
            )
            points = scroll_result[0]
            
            results = []
            for p in points:
                payload = p.payload or {}
                results.append({
                    "chunk_id": str(p.id),
                    "content": payload.get("content", ""),
                    "metadata": {
                        "filename": payload.get("filename"),
                        "page": payload.get("page"),
                        "section": payload.get("section"),
                        "chunk_index": payload.get("chunk_index"),
                        "tags": payload.get("tags", []),
                        "parent_id": payload.get("parent_id"),
                        "parent_content": payload.get("parent_content"),
                        "parent_chunk_index_range": payload.get("parent_chunk_index_range"),
                        "function_name": payload.get("function_name"),
                        "type": payload.get("type")
                    }
                })
            
            # 依據 chunk_index 排序
            results.sort(key=lambda x: x["metadata"].get("chunk_index") or 0)
            return results
        except Exception as e:
            logger.error(f"Failed to get points by parent_id '{parent_id}': {e}")
            return []

    @classmethod
    async def get_siblings_and_merge(cls, collection_name: str, parent_id: str, orig_content: str, metadata: dict) -> tuple:
        """
        撈取 parent_id 的所有兄弟節點並去重合併，還原完整的 Parent Content。
        """
        siblings = await cls.get_by_parent_id(collection_name, parent_id)
        if not siblings:
            return orig_content, str(metadata.get("chunk_index") or "")
        
        indices = [sib["metadata"].get("chunk_index") for sib in siblings if sib["metadata"].get("chunk_index") is not None]
        if indices:
            min_idx = min(indices)
            max_idx = max(indices)
            parent_range = f"{min_idx}~{max_idx}" if min_idx != max_idx else str(min_idx)
        else:
            parent_range = str(metadata.get("chunk_index") or "")
            
        def clean_and_extract_content(content: str) -> str:
            for marker in ["[主要內容]\n", "[主要內容]\r\n"]:
                idx = content.find(marker)
                if idx != -1:
                    return content[idx + len(marker):]
            return content
        
        raw_contents = [clean_and_extract_content(sib["content"]) for sib in siblings]
        if not raw_contents:
            return orig_content, parent_range
        
        # 進行去重拼接 (解決 overlap 造成的重複文字問題)
        def merge_two_strings_with_overlap(s1: str, s2: str) -> str:
            max_overlap = min(len(s1), len(s2), 200)
            for i in range(max_overlap, 4, -1):
                if s1[-i:] == s2[:i]:
                    return s1 + s2[i:]
            return s1 + "\n" + s2
            
        merged_raw = raw_contents[0]
        for next_content in raw_contents[1:]:
            merged_raw = merge_two_strings_with_overlap(merged_raw, next_content)
            
        # 若原內容是結構化輸出，則重新拼裝結構化 Header
        if orig_content.startswith("[檔案名稱]"):
            filename = metadata.get("filename") or "unknown"
            tags = ", ".join(metadata.get("tags", [])) or "一般"
            display_content = (
                f"[檔案名稱] {filename}\n"
                f"[段落編號] 第 {parent_range} 段\n"
                f"[分類標籤] {tags}\n"
                f"[主要內容]\n"
                f"{merged_raw}"
            )
        else:
            display_content = merged_raw
            
        return display_content, parent_range

