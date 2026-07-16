import asyncio
import logging
import time
import uuid
from typing import List, Dict, Any, Optional, Set
from qdrant_client import AsyncQdrantClient, models
from config import settings

logger = logging.getLogger("airag.qdrant")

class QdrantService:
    _client: Optional[AsyncQdrantClient] = None
    _metadata_cache: Dict[str, Dict[str, Any]] = {}
    _METADATA_CACHE_TTL = 600  # 秒，作為主動 invalidate 遺漏時的保底

    @classmethod
    def get_client(cls) -> AsyncQdrantClient:
        if cls._client is None:
            # 建立非同步 Qdrant 客戶端連線
            cls._client = AsyncQdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
        return cls._client

    @classmethod
    async def create_collection(cls, collection_name: str, vector_size: int = 4096) -> bool:
        """
        若 Collection 不存在則建立，設定向量維度（預設為 4096），使用 Cosine 相似度。
        並新增 sparse-text 稀疏向量空間支援。
        """
        client = cls.get_client()
        try:
            exists = await client.collection_exists(collection_name)
            if not exists:
                await client.create_collection(
                    collection_name=collection_name,
                    vectors_config=models.VectorParams(
                        size=vector_size,  # 動態對齊模型維度
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
                logger.info(f"Qdrant collection '{collection_name}' created successfully with size {vector_size}.")
            
            # 確保 'content' 欄位有建立全文檢索 Text Index，以支援 Exact keyword MatchText 查詢（採用 MULTILINGUAL 支援多語言/中文分詞）
            try:
                await client.create_payload_index(
                    collection_name=collection_name,
                    field_name="content",
                    field_schema=models.TextIndexParams(
                        type="text",
                        tokenizer=models.TokenizerType.MULTILINGUAL,
                        lowercase=True
                    )
                )
                logger.info(f"Ensured MULTILINGUAL payload text index on 'content' for collection '{collection_name}'.")
            except Exception as e_idx:
                logger.warning(f"Failed or skipped ensuring payload index: {e_idx}")
                
            return True
        except Exception as e:
            logger.error(f"Failed to create Qdrant collection '{collection_name}': {e}")
            return False

    @classmethod
    async def ensure_all_collections_payload_index(cls) -> None:
        """
        遍歷 Qdrant 內所有 Collection，確保均已套用 MULTILINGUAL 分詞器建立 'content' 文字索引。
        此方法於系統啟動時呼叫，自動將既有舊 Collection 的文字索引升級重建。
        """
        client = cls.get_client()
        try:
            res = await client.get_collections()
            for c in res.collections:
                try:
                    await client.create_payload_index(
                        collection_name=c.name,
                        field_name="content",
                        field_schema=models.TextIndexParams(
                            type="text",
                            tokenizer=models.TokenizerType.MULTILINGUAL,
                            lowercase=True
                        )
                    )
                    logger.info(f"Ensured MULTILINGUAL payload text index on 'content' for collection '{c.name}'.")
                except Exception as e_c:
                    logger.warning(f"Failed to update payload index for collection '{c.name}': {e_c}")
        except Exception as e:
            logger.error(f"Failed to retrieve collections for payload index update: {e}")


    @classmethod
    async def upsert_semantic_json_chunks(
        cls,
        collection_name: str,
        items: List[Dict[str, Any]],
        dense_vectors: List[List[float]],
        vector_size: int = 4096
    ) -> int:
        """
        批次將地端 AI 生成的語義 JSON 資料與其 Dense/Sparse 向量寫入 Qdrant。
        """
        client = cls.get_client()
        from datetime import datetime
        # 確保 Collection 存在，使用指定的 Dense 向量長度
        await cls.create_collection(collection_name, vector_size=vector_size)
        
        # 批次生成 Chunks 的稀疏向量 (使用其 sparse_keywords 串接的文本)
        from services.sparse_embedding_service import SparseEmbeddingService
        sparse_texts = [" ".join(item.get("sparse_keywords", [])) for item in items]
        sparse_vectors = SparseEmbeddingService.get_sparse_vectors_batch(sparse_texts)
        
        points = []
        for i, item in enumerate(items):
            point_id = str(uuid.uuid4())
            
            meta = item.get("metadata", {})
            tags_val = meta.get("tags") or ([meta.get("category")] if meta.get("category") else [])
            class_val = meta.get("class") or meta.get("classes") or []
            if isinstance(class_val, str):
                class_val = [class_val] if class_val else []
            links_val = meta.get("links_to") or meta.get("links") or []
            if isinstance(links_val, str):
                links_val = [links_val] if links_val else []
                
            # 建立 metadata payload
            payload = {
                "content": item.get("text_content", ""),
                "embeddings_input": item.get("embeddings_input", ""),
                "filename": meta.get("source_file", "unknown"),
                "page": meta.get("page_number", 1),
                "section": meta.get("category", ""),
                "tags": tags_val,
                "class": class_val,
                "links_to": links_val,
                "custom_id": item.get("id"),
                "sparse_keywords": item.get("sparse_keywords", []),
                "source": "json_semantic",
                "created_at": meta.get("created_at") or datetime.utcnow().isoformat()
            }
            # 合併原 metadata 中的其他屬性
            for k, v in meta.items():
                if k not in ["source_file", "page_number", "category", "created_at", "tags", "class", "classes", "links_to", "links"]:
                    payload[k] = v
                    
            points.append(
                models.PointStruct(
                    id=point_id,
                    vector={
                        "": dense_vectors[i],
                        "sparse-text": sparse_vectors[i]
                    },
                    payload=payload
                )
            )
            
        try:
            await client.upsert(
                collection_name=collection_name,
                points=points
            )
            logger.info(f"Upserted {len(points)} semantic points into Qdrant collection '{collection_name}'.")
            return len(points)
        except Exception as e:
            error_str = str(e)
            if "sparse-text" in error_str:
                logger.warning("Fallback: upserting semantic points with dense vectors only.")
                points_dense_only = []
                for i, p in enumerate(points):
                    points_dense_only.append(
                        models.PointStruct(
                            id=p.id,
                            vector=dense_vectors[i],
                            payload=p.payload
                        )
                    )
                await client.upsert(
                    collection_name=collection_name,
                    points=points_dense_only
                )
                return len(points_dense_only)
            else:
                logger.error(f"Failed to upsert semantic points to Qdrant: {e}")
                raise e

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

    @staticmethod
    def _extract_dense_vector(vector: Any) -> Optional[List[float]]:
        """
        從 Qdrant 回傳的 point.vector 取出預設密集向量。
        本 collection 同時設定了預設密集向量（未命名）與具名的 sparse-text 稀疏向量，
        當 with_vectors 帶超過一個向量空間時，point.vector 會是 dict（如 {"": [...], "sparse-text": ...}）。
        """
        if vector is None:
            return None
        if isinstance(vector, dict):
            return vector.get("")
        return vector

    @classmethod
    def _cosine_similarity(cls, vec1: List[float], vec2: List[float]) -> float:
        dot = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = sum(a * a for a in vec1) ** 0.5
        norm2 = sum(b * b for b in vec2) ** 0.5
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot / (norm1 * norm2)

    @classmethod
    def _compute_semantic_score(cls, res: Any, query_vector: Optional[List[float]]) -> Optional[float]:
        """
        重新計算候選點位與查詢向量的 cosine 相似度，作為與 score_threshold 同尺度的可比較分數。
        供 RRF 融合路徑使用——RRF 分數本身量級遠低於 score_threshold 的 cosine 相似度尺度，
        詳見 docs/DevelopmentProcess/NewFeaturesPlan_RRFScoreThresholdMismatchPlan.md。
        """
        if query_vector is None:
            return None
        dense_vector = cls._extract_dense_vector(getattr(res, "vector", None))
        if not dense_vector:
            return None
        return cls._cosine_similarity(dense_vector, query_vector)

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
        disable_parent_merge: bool = False,
        sparse_keywords: Optional[List[str]] = None
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
            
            # 排除語義資料庫查詢法 (Semantic DB Query) 的查詢設定檔向量，避免混入一般文件檢索結果。
            # 既有資料的 source 欄位從未出現過此值，此條件對既有查詢結果零影響。
            query_filter = models.Filter(
                must=must_conditions if must_conditions else None,
                must_not=[
                    models.FieldCondition(
                        key="source",
                        match=models.MatchValue(value="db_query_profile")
                    )
                ]
            )

            # 若需要進行 parent 去重合併，應擴大從 Qdrant 查詢點位的數量限制，以免去重後數量不足 top_k
            search_limit = top_k if disable_parent_merge else max(top_k * 4, 20)

            # 是否為 RRF 融合路徑：RRF score 與 score_threshold 尺度不同，需另外重算 semantic_score
            is_rrf_fusion = False

            if search_type in ["hybrid", "semantic_hybrid"] and query_vector is not None and query_text is not None and query_text.strip():
                try:
                    from services.sparse_embedding_service import SparseEmbeddingService
                    query_sparse = SparseEmbeddingService.get_sparse_vector(query_text)
                    
                    prefetch_dense = models.Prefetch(
                        query=query_vector,
                        using="",  # 預設密集向量空間
                        limit=search_limit * 2,
                        filter=query_filter
                    )
                    
                    prefetch_sparse = models.Prefetch(
                        query=query_sparse,
                        using="sparse-text",  # 稀疏向量空間
                        limit=search_limit * 2,
                        filter=query_filter
                    )
                    
                    # 針對程式碼識別碼/關鍵字進行 Exact keyword Match text 搜尋加速
                    # 優先使用語義層已抽取的 sparse_keywords（含中文），否則退回正則抽取英數詞彙
                    keywords = cls._extract_exact_keywords(query_text, sparse_keywords)

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
                            limit=search_limit * 2,
                            filter=exact_filter
                        )
                        prefetch_list.append(prefetch_exact)
                        logger.info(f"Hybrid search exact keyword boost active for keywords: {keywords}")
                    
                    # Qdrant 雙路或三路召回與 RRF 融合
                    # with_vectors=[""] 只取回預設密集向量，用於後續重算 semantic_score；
                    # 不可用 with_vectors=True，否則會連 sparse-text 向量一併拉回，且 point.vector 會變成 dict。
                    response = await client.query_points(
                        collection_name=collection_name,
                        prefetch=prefetch_list,
                        query=models.FusionQuery(
                            fusion=models.Fusion.RRF
                        ),
                        limit=search_limit,
                        with_vectors=[""]
                    )
                    results = response.points
                    is_rrf_fusion = True
                    logger.info("Hybrid search executed successfully via Qdrant RRF (with exact keyword boost).")
                except Exception as he:
                    logger.warning(f"Hybrid search failed, falling back to pure vector search: {he}")
                    # 安全降級：純密集向量檢索
                    response = await client.query_points(
                        collection_name=collection_name,
                        query=query_vector,
                        limit=search_limit,
                        score_threshold=score_threshold,
                        query_filter=query_filter
                    )
                    results = response.points
            elif query_vector is None:
                # 執行無向量條件的 Scroll 查詢
                scroll_result = await client.scroll(
                    collection_name=collection_name,
                    limit=search_limit,
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
                    limit=search_limit,
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
                # semantic_score：與 score_threshold 同尺度的可比較分數。
                # RRF 融合路徑重算 cosine；純向量路徑本身即為 cosine，直接沿用 score；無查詢向量則為 None。
                if is_rrf_fusion:
                    semantic_score = cls._compute_semantic_score(res, query_vector)
                elif query_vector is not None:
                    semantic_score = score
                else:
                    semantic_score = None
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
                        "class": payload.get("class", []),
                        "parent_id": payload.get("parent_id"),
                        "parent_content": payload.get("parent_content"),
                        "parent_chunk_index_range": payload.get("parent_chunk_index_range"),
                        "function_name": payload.get("function_name"),
                        "type": payload.get("type"),
                        "links_to": payload.get("links_to", []),
                        "linked_attachments": payload.get("linked_attachments", []),
                        "chunk_type": payload.get("chunk_type"),
                        "image_filename": payload.get("image_filename"),
                        "is_confidential": payload.get("is_confidential", False),
                        "confidential_level": payload.get("confidential_level"),
                        "confidential_departments": payload.get("confidential_departments", [])
                    },
                    "score": score,
                    "semantic_score": semantic_score,
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
            
            # 2.5 限制去重後的結果最多為 top_k 筆，避免回傳過多 Context
            deduped_results = deduped_results[:top_k]
            
            # 3. 處理 Parent-Child 的還原與合併 (使用 asyncio.gather 併行處理)
            async def _process_item_parent(item):
                meta = item["metadata"]
                parent_id = meta.get("parent_id")
                
                if parent_id:
                    is_image_chunk = meta.get("chunk_type") == "image"
                    parent_content = meta.get("parent_content")
                    parent_range = meta.get("parent_chunk_index_range")
                    image_chunks = []
 
                    # 情況 A：若元資料中沒有預存的 parent_content，則從資料庫中撈取所有兄弟節點進行合併 (相容舊資料)
                    if not parent_content:
                        parent_content, parent_range, image_chunks = await cls.get_siblings_and_merge(
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
                        # 為取得同 parent_id 下的圖片，只需要撈取圖片型兄弟節點，不需要重複執行文字合併運算
                        image_chunks = await cls.get_image_siblings(collection_name, parent_id)
 
                    if is_image_chunk:
                        # 圖片 chunk 本身被命中時：圖片描述若因過長被切成多個片段，命中的可能只是其中一段，
                        # 換成同一張圖片重組後的完整描述，而不是只顯示命中的那一小段
                        self_image_filename = meta.get("image_filename")
                        self_entry = next(
                            (ic for ic in image_chunks if ic.get("metadata", {}).get("image_filename") == self_image_filename),
                            None
                        )
                        if self_entry:
                            item["content"] = self_entry["content"]
                        # 圖片自己不需要出現在自己的「同段落圖片」清單中
                        image_chunks = [
                            ic for ic in image_chunks
                            if ic.get("metadata", {}).get("image_filename") != self_image_filename
                        ]
                        # 額外保留周邊純文字內容於 metadata 中，供 RAG router 併入 LLM 提示詞脈絡中
                        if parent_content:
                            item["metadata"]["parent_content"] = parent_content
                    elif parent_content:
                        item["content"] = parent_content
                    if parent_range:
                        item["metadata"]["chunk_index"] = parent_range
                    item["metadata"]["image_chunks"] = image_chunks
 
                return item

            final_results = await asyncio.gather(*[_process_item_parent(item) for item in deduped_results])
            return list(final_results)
        except Exception as e:
            logger.error(f"Failed to search similarity in Qdrant collection '{collection_name}': {e}")
            return []

    @classmethod
    async def search_similar_two_step(
        cls,
        collection_name: str,
        query_vector: Optional[List[float]] = None,
        query_text: Optional[str] = None,
        search_type: str = "vector",
        top_k: int = 5,
        score_threshold: float = 0.7,
        filter_tags: Optional[List[str]] = None,
        filter_filename: Optional[str] = None,
        disable_parent_merge: bool = False,
        neighbor_limit: int = 10,
        neighbor_score_threshold: float = 0.1,
        sparse_keywords: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        雙階段關聯檢索 (Two-Step Hybrid Retrieval)：
        第一階段：核心實體檢索 (1st-hop Search)，撈出與問題最相關的點位。
        第二階段：一階鄰居關係拉取 (2nd-hop Search)，利用相似度/混合檢索在關聯點位中進行二次搜尋，只挑選高相關段落。
        鄰居屬於補充性關聯內容，門檻獨立於核心搜尋的 score_threshold，預設較寬鬆（neighbor_score_threshold），
        避免與核心搜尋同等嚴格的門檻把大部分鄰居過濾掉，導致 Two-Step 檢索的第二階段形同虛設。
        最後進行去重與合併，回傳精準的 Context。
        """
        # 第一步：進行核心 Hybrid 搜尋
        raw_results = await cls.search_similar(
            collection_name=collection_name,
            query_vector=query_vector,
            query_text=query_text,
            search_type=search_type,
            top_k=top_k,
            score_threshold=score_threshold,
            filter_tags=filter_tags,
            filter_filename=filter_filename,
            disable_parent_merge=disable_parent_merge,
            sparse_keywords=sparse_keywords
        )

        if not raw_results:
            return []

        # 第二步：解析 links_to 欄位，獲取所有關聯名稱/ID
        all_links = []
        for item in raw_results:
            links = item.get("metadata", {}).get("links_to") or []
            if isinstance(links, str):
                links = [links]
            for link in links:
                if link and link not in all_links:
                    all_links.append(link)

        # 第三步：如果有關聯，拉取與查詢相關的關聯點位 (2nd-hop Search)
        neighbor_results = []
        if all_links:
            client = cls.get_client()
            try:
                # 建立 Filter 條件：限制只能在關聯檔案/ID範圍內搜尋
                should_conditions = [
                    models.FieldCondition(key="filename", match=models.MatchAny(any=all_links)),
                    models.FieldCondition(key="custom_id", match=models.MatchAny(any=all_links))
                ]
                scroll_filter = models.Filter(
                    should=should_conditions,
                    must_not=[
                        models.FieldCondition(
                            key="source",
                            match=models.MatchValue(value="db_query_profile")
                        )
                    ]
                )
                
                points = []
                # 是否為 RRF 融合路徑：RRF score 與 score_threshold 尺度不同，需另外重算 semantic_score
                is_rrf_fusion = False
                # 情況 A：若啟用 Hybrid / Semantic Hybrid，且有向量與查詢文字，則進行帶 Filter 的混合檢索
                if search_type in ["hybrid", "semantic_hybrid"] and query_vector is not None and query_text is not None and query_text.strip():
                    try:
                        from services.sparse_embedding_service import SparseEmbeddingService
                        query_sparse = SparseEmbeddingService.get_sparse_vector(query_text)
                        
                        prefetch_dense = models.Prefetch(
                            query=query_vector,
                            using="",  # 預設密集向量空間
                            limit=neighbor_limit * 2,
                            score_threshold=neighbor_score_threshold,
                            filter=scroll_filter
                        )
                        prefetch_sparse = models.Prefetch(
                            query=query_sparse,
                            using="sparse-text",  # 稀疏向量空間
                            limit=neighbor_limit * 2,
                            filter=scroll_filter
                        )
                        
                        # Exact keyword match text prefetch boost
                        keywords = cls._extract_exact_keywords(query_text, sparse_keywords)

                        prefetch_list = [prefetch_dense, prefetch_sparse]
                        if keywords:
                            exact_should = []
                            for kw in keywords:
                                exact_should.append(models.FieldCondition(key="content", match=models.MatchText(text=kw)))
                                exact_should.append(models.FieldCondition(key="function_name", match=models.MatchValue(value=kw)))
                                exact_should.append(models.FieldCondition(key="parent_id", match=models.MatchValue(value=kw)))
                            
                            exact_filter = models.Filter(
                                should=exact_should,
                                must=scroll_filter.should
                            )
                            prefetch_exact = models.Prefetch(
                                query=query_sparse,
                                using="sparse-text",
                                limit=neighbor_limit * 2,
                                filter=exact_filter
                            )
                            prefetch_list.append(prefetch_exact)
                        
                        response = await client.query_points(
                            collection_name=collection_name,
                            prefetch=prefetch_list,
                            query=models.FusionQuery(fusion=models.Fusion.RRF),
                            limit=neighbor_limit,
                            with_vectors=[""]
                        )
                        points = response.points
                        is_rrf_fusion = True
                        logger.info(f"Two-step neighbor search successfully executed hybrid query for links: {all_links}")
                    except Exception as he:
                        logger.warning(f"Neighbor hybrid search failed, falling back to pure vector search: {he}")
                        response = await client.query_points(
                            collection_name=collection_name,
                            query=query_vector,
                            limit=neighbor_limit,
                            score_threshold=neighbor_score_threshold,
                            query_filter=scroll_filter
                        )
                        points = response.points
                # 情況 B：若僅為純向量檢索，則進行帶 Filter 的密集向量查詢
                elif query_vector is not None:
                    response = await client.query_points(
                        collection_name=collection_name,
                        query=query_vector,
                        limit=neighbor_limit,
                        score_threshold=neighbor_score_threshold,
                        query_filter=scroll_filter
                    )
                    points = response.points
                # 情況 C：無查詢向量，則降級為 Scroll
                else:
                    scroll_result = await client.scroll(
                        collection_name=collection_name,
                        scroll_filter=scroll_filter,
                        limit=neighbor_limit,
                        with_payload=True,
                        with_vectors=False
                    )
                    points = scroll_result[0]

                # 包裝為與核心檢索結果一致的結構
                for p in points:
                    score = getattr(p, "score", 0.0)
                    if score is None:
                        score = 0.0
                    # semantic_score：與 search_similar() 一致的映射規則，見該函式內對應註解
                    if is_rrf_fusion:
                        semantic_score = cls._compute_semantic_score(p, query_vector)
                    elif query_vector is not None:
                        semantic_score = score
                    else:
                        semantic_score = None
                    payload = p.payload or {}
                    neighbor_results.append({
                        "chunk_id": str(p.id),
                        "content": payload.get("content", ""),
                        "metadata": {
                            "filename": payload.get("filename"),
                            "page": payload.get("page"),
                            "section": payload.get("section"),
                            "chunk_index": payload.get("chunk_index"),
                            "tags": payload.get("tags", []),
                            "class": payload.get("class", []),
                            "parent_id": payload.get("parent_id"),
                            "parent_content": payload.get("parent_content"),
                            "parent_chunk_index_range": payload.get("parent_chunk_index_range"),
                            "function_name": payload.get("function_name"),
                            "type": payload.get("type"),
                            "links_to": payload.get("links_to", []),
                            "linked_attachments": payload.get("linked_attachments", []),
                            "chunk_type": payload.get("chunk_type"),
                            "image_filename": payload.get("image_filename"),
                            "is_confidential": payload.get("is_confidential", False),
                            "confidential_level": payload.get("confidential_level"),
                            "confidential_departments": payload.get("confidential_departments", [])
                        },
                        "score": score,
                        "semantic_score": semantic_score,
                        "distance": 1.0 - score,
                        "is_neighbor": True
                    })
            except Exception as e:
                logger.error(f"Failed to query neighbor points for links {all_links}: {e}")

        # 第四步：若鄰居點位有 parent_id 且未禁用合併，亦執行 parent-child 合併
        final_neighbors = []
        if neighbor_results:
            # 依 parent_id 去重鄰居 (避免重複合併同個 parent 的多個 chunk)
            seen_parents = set()
            deduped_neighbors = []
            for item in neighbor_results:
                pid = item["metadata"].get("parent_id")
                if pid:
                    if pid in seen_parents:
                        continue
                    seen_parents.add(pid)
                deduped_neighbors.append(item)

            if not disable_parent_merge:
                async def _process_neighbor_parent(item):
                    meta = item["metadata"]
                    parent_id = meta.get("parent_id")
                    if parent_id:
                        is_image_chunk = meta.get("chunk_type") == "image"
                        parent_content = meta.get("parent_content")
                        parent_range = meta.get("parent_chunk_index_range")
                        image_chunks = []
                        if not parent_content:
                            parent_content, parent_range, image_chunks = await cls.get_siblings_and_merge(
                                collection_name=collection_name,
                                parent_id=parent_id,
                                orig_content=item["content"],
                                metadata=meta
                            )
                        else:
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
                            # 為取得同 parent_id 下的圖片，只需要撈取圖片型兄弟節點，不需要重複執行文字合併運算
                            image_chunks = await cls.get_image_siblings(collection_name, parent_id)
                        if is_image_chunk:
                            # 圖片 chunk 本身被命中時，換成同一張圖片重組後的完整描述，而非命中的單一片段
                            self_image_filename = meta.get("image_filename")
                            self_entry = next(
                                (ic for ic in image_chunks if ic.get("metadata", {}).get("image_filename") == self_image_filename),
                                None
                            )
                            if self_entry:
                                item["content"] = self_entry["content"]
                            image_chunks = [
                                ic for ic in image_chunks
                                if ic.get("metadata", {}).get("image_filename") != self_image_filename
                            ]
                        elif parent_content:
                            item["content"] = parent_content
                        if parent_range:
                            item["metadata"]["chunk_index"] = parent_range
                        item["metadata"]["image_chunks"] = image_chunks
                    return item

                final_neighbors = list(await asyncio.gather(*[_process_neighbor_parent(item) for item in deduped_neighbors]))
            else:
                final_neighbors = deduped_neighbors

        # 第五步：與核心片段合併，並執行內容去重
        seen_contents = set()
        merged_results = []

        for item in raw_results:
            content_strip = item["content"].strip()
            if content_strip not in seen_contents:
                seen_contents.add(content_strip)
                merged_results.append(item)

        for item in final_neighbors:
            content_strip = item["content"].strip()
            if content_strip not in seen_contents:
                seen_contents.add(content_strip)
                merged_results.append(item)

        return merged_results

    @staticmethod
    def _extract_exact_keywords(query_text: Optional[str], sparse_keywords: Optional[List[str]] = None) -> List[str]:
        """
        萃取用於 Exact keyword boost 的關鍵字清單。
        若已有語義層抽取的 sparse_keywords（含中英文），優先使用；否則退回對 query_text 的正則抽取（僅支援英數）。
        英數關鍵字需長度 >=3 且非純數字；含中文或其他非 ASCII 字元的關鍵字則需長度 >=2，避免單字誤傷。
        """
        import re
        if sparse_keywords:
            candidates = [kw.strip() for kw in sparse_keywords if isinstance(kw, str) and kw.strip()]
        elif query_text:
            candidates = re.findall(r'[a-zA-Z0-9_]{3,}', query_text)
        else:
            candidates = []

        keywords = []
        for kw in candidates:
            if re.fullmatch(r'[a-zA-Z0-9_]+', kw):
                if len(kw) >= 3 and not kw.isdigit():
                    keywords.append(kw)
            elif len(kw) >= 2:
                keywords.append(kw)
        return keywords

    @classmethod
    def invalidate_metadata_cache(cls, collection_name: str) -> None:
        """
        清除指定 Collection 的結構化元資料快取（於任何寫入/刪除向量的操作後呼叫）。
        """
        cls._metadata_cache.pop(collection_name, None)

    @classmethod
    async def get_unique_metadata(cls, collection_name: str) -> Dict[str, Any]:
        """
        從向量庫集合中提取所有唯一的檔案名稱、標籤與結構化關聯元資料。
        結果會依 Collection 快取（TTL 保底 + 寫入操作主動 invalidate），避免每次查詢都重新 scroll 全量資料。
        """
        cached = cls._metadata_cache.get(collection_name)
        if cached and (time.time() - cached["cached_at"]) < cls._METADATA_CACHE_TTL:
            logger.info(f"[Qdrant] 使用快取的結構化元資料 - collection: {collection_name}")
            return cached["data"]

        client = cls.get_client()
        try:
            exists = await client.collection_exists(collection_name)
            if not exists:
                empty_result = {"filenames": [], "tags": [], "structured_metadata": []}
                cls._metadata_cache[collection_name] = {"data": empty_result, "cached_at": time.time()}
                return empty_result

            filenames = set()
            tags = set()
            structured_map = {}
            
            offset = None
            while True:
                # 分頁捲動取得點，包含檔名、標籤、類別、關聯與機密權限欄位
                scroll_result = await client.scroll(
                    collection_name=collection_name,
                    limit=1000,
                    offset=offset,
                    with_payload=[
                        "filename", "tags", "class", "links_to", "linked_attachments",
                        "is_confidential", "confidential_level", "confidential_departments"
                    ],
                    with_vectors=False
                )
                
                points, next_offset = scroll_result
                for p in points:
                    payload = p.payload or {}
                    fn = payload.get("filename")
                    if fn:
                        filenames.add(fn)
                        if fn not in structured_map:
                            structured_map[fn] = {
                                "filename": fn,
                                "classes": set(),
                                "tags": set(),
                                "links_to": set(),
                                "linked_attachments": set(),
                                "is_confidential": False,
                                "confidential_level": None,
                                "confidential_departments": []
                            }
                        
                        # 機密權限設定
                        if payload.get("is_confidential"):
                            structured_map[fn]["is_confidential"] = True
                        if payload.get("confidential_level") is not None:
                            structured_map[fn]["confidential_level"] = payload.get("confidential_level")
                        if payload.get("confidential_departments"):
                            structured_map[fn]["confidential_departments"] = payload.get("confidential_departments")

                        # class
                        c_val = payload.get("class")
                        if isinstance(c_val, list):
                            structured_map[fn]["classes"].update([c for c in c_val if c])
                        elif isinstance(c_val, str) and c_val:
                            structured_map[fn]["classes"].add(c_val)
                            
                        # tags
                        t_list = payload.get("tags")
                        if isinstance(t_list, list):
                            for t in t_list:
                                if t:
                                    tags.add(t)
                                    structured_map[fn]["tags"].add(t)
                                    
                        # links_to
                        l_list = payload.get("links_to")
                        if isinstance(l_list, list):
                            structured_map[fn]["links_to"].update([l for l in l_list if l])

                        # linked_attachments
                        la_list = payload.get("linked_attachments")
                        if isinstance(la_list, list):
                            structured_map[fn]["linked_attachments"].update([la for la in la_list if la])

                if not next_offset:
                    break
                offset = next_offset
            
            structured_list = []
            for fn, data in structured_map.items():
                structured_list.append({
                    "filename": fn,
                    "class": sorted(list(data["classes"])),
                    "tags": sorted(list(data["tags"])),
                    "links_to": sorted(list(data["links_to"])),
                    "linked_attachments": sorted(list(data["linked_attachments"])),
                    "is_confidential": data["is_confidential"],
                    "confidential_level": data["confidential_level"],
                    "confidential_departments": data["confidential_departments"]
                })
                
            result = {
                "filenames": sorted(list(filenames)),
                "tags": sorted(list(tags)),
                "structured_metadata": sorted(structured_list, key=lambda x: x["filename"])
            }
            cls._metadata_cache[collection_name] = {"data": result, "cached_at": time.time()}
            return result
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
            # 1. 刪除前先取得即將被刪除的 points 的 payload
            image_filenames = set()
            try:
                records = await client.retrieve(
                    collection_name=collection_name,
                    ids=point_ids,
                    with_payload=True,
                    with_vectors=False
                )
                payloads = [r.payload for r in records if r.payload is not None]
                image_filenames = cls._get_image_filenames_from_payloads(payloads)
            except Exception as pe:
                logger.warning(f"Failed to retrieve payloads before deleting points: {pe}")

            # 2. 執行刪除
            await client.delete(
                collection_name=collection_name,
                points_selector=models.PointIdsList(
                    points=point_ids
                )
            )
            logger.info(f"Successfully deleted {len(point_ids)} points from collection '{collection_name}'.")

            # 3. 刪除成功後，清理孤立圖片檔案
            if image_filenames:
                await cls._cleanup_orphaned_image_files(collection_name, image_filenames)

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
            # 1. 先 Scroll 獲取該 filename 的所有點以計算數量，並取得 ID 進行刪除，同時獲取 payload
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
                with_payload=True,
                with_vectors=False
            )
            points = scroll_result[0]
            count = len(points)
            
            if count > 0:
                payloads = [p.payload for p in points if p.payload is not None]
                image_filenames = cls._get_image_filenames_from_payloads(payloads)
                
                point_ids = [p.id for p in points]
                await client.delete(
                    collection_name=collection_name,
                    points_selector=models.PointIdsList(points=point_ids)
                )
                logger.info(f"Successfully deleted {count} points for filename '{filename}' from collection '{collection_name}'.")

                # 2. 刪除成功後，清理孤立圖片檔案
                if image_filenames:
                    await cls._cleanup_orphaned_image_files(collection_name, image_filenames)
            return count
        except Exception as e:
            logger.error(f"Failed to delete points by filename '{filename}' from collection '{collection_name}': {e}")
            raise e

    @staticmethod
    def _get_image_filenames_from_payloads(payloads: List[dict]) -> Set[str]:
        """
        從一批 payload 中挑出圖片 chunk 的 image_filename，回傳去重集合。
        """
        image_filenames = set()
        for payload in payloads:
            if payload and payload.get("chunk_type") == "image":
                img_fn = payload.get("image_filename")
                if img_fn:
                    image_filenames.add(img_fn)
        return image_filenames

    @classmethod
    async def _cleanup_orphaned_image_files(cls, collection_name: str, image_filenames: Set[str]) -> None:
        """
        對每個檔名做「是否仍被引用」的 Qdrant 查詢，沒有才刪除實體檔案，單一檔案例外不中斷其餘檔案的清理。
        """
        import os
        from config import settings
        
        if not image_filenames:
            return
            
        client = cls.get_client()
        image_dir = os.path.abspath(os.path.join(settings.FILE_ATTACHMENTS_DIR, settings.FILE_ATTACHMENTS_IMAGE_SUBDIR))
        
        for filename in image_filenames:
            try:
                # 用 client.scroll() 確認是否還有其他 point 仍引用這個檔名
                scroll_result = await client.scroll(
                    collection_name=collection_name,
                    scroll_filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="image_filename",
                                match=models.MatchValue(value=filename)
                            )
                        ]
                    ),
                    limit=1,
                    with_payload=False,
                    with_vectors=False
                )
                remaining_points = scroll_result[0]
                if not remaining_points:
                    # 沒有其他 point 引用了，比照 embedding.py 進行路徑安全驗證並刪除
                    file_path = os.path.abspath(os.path.join(image_dir, filename))
                    # Check directory traversal
                    if not file_path.startswith(image_dir + os.sep) and file_path != image_dir:
                        logger.warning(f"Path traversal detected and blocked for image file: {filename}")
                        continue
                        
                    if os.path.exists(file_path) and os.path.isfile(file_path):
                        os.remove(file_path)
                        logger.info(f"Successfully deleted orphaned image file: {filename}")
                    else:
                        logger.warning(f"Orphaned image file not found on disk: {filename}")
                else:
                    logger.info(f"Image file {filename} is still referenced by {len(remaining_points)}+ points. Skipping deletion.")
            except Exception as e:
                # 檔案刪除是 best-effort，單一檔案例外不影響其他檔案
                logger.warning(f"Failed to cleanup image file '{filename}': {e}")

    @classmethod
    async def update_links_to_by_filename(cls, collection_name: str, filename: str, links_to: List[str]) -> int:
        """
        更新指定 Collection 中所有匹配該檔案名稱的 Points 的 links_to 欄位，並回傳更新的數量。
        """
        client = cls.get_client()
        try:
            # 1. 先 Scroll 獲取該 filename 的所有點以取得 ID
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
                await client.set_payload(
                    collection_name=collection_name,
                    payload={"links_to": links_to},
                    points=point_ids
                )
                logger.info(f"Successfully updated links_to for {count} points of filename '{filename}' in collection '{collection_name}'.")
            return count
        except Exception as e:
            logger.error(f"Failed to update links_to by filename '{filename}' in collection '{collection_name}': {e}")
            raise e

    @classmethod
    async def update_attachments_by_filename(cls, collection_name: str, filename: str, attachment_ids: List[str]) -> int:
        """
        更新指定 Collection 中所有匹配該檔案名稱的 Points 的 linked_attachments 欄位，並回傳更新的數量。
        """
        client = cls.get_client()
        try:
            # 1. 先 Scroll 獲取該 filename 的所有點以取得 ID
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
                await client.set_payload(
                    collection_name=collection_name,
                    payload={"linked_attachments": attachment_ids},
                    points=point_ids
                )
                logger.info(f"Successfully updated linked_attachments for {count} points of filename '{filename}' in collection '{collection_name}'.")
            return count
        except Exception as e:
            logger.error(f"Failed to update linked_attachments by filename '{filename}' in collection '{collection_name}': {e}")
            raise e

    @classmethod
    async def update_permissions_by_filename(
        cls,
        collection_name: str,
        filename: str,
        is_confidential: bool,
        confidential_level: Optional[int],
        confidential_departments: List[str]
    ) -> int:
        """
        更新指定 Collection 中所有匹配該檔案名稱的 Points 的機密權限欄位 (is_confidential, confidential_level, confidential_departments)。
        """
        client = cls.get_client()
        try:
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
                limit=10000,
                with_payload=False,
                with_vectors=False
            )
            points = scroll_result[0]
            count = len(points)
            
            if count > 0:
                point_ids = [p.id for p in points]
                await client.set_payload(
                    collection_name=collection_name,
                    payload={
                        "is_confidential": is_confidential,
                        "confidential_level": confidential_level if is_confidential else None,
                        "confidential_departments": confidential_departments if is_confidential else []
                    },
                    points=point_ids
                )
                logger.info(f"Successfully updated permissions for {count} points of filename '{filename}' in collection '{collection_name}'.")
            return count
        except Exception as e:
            logger.error(f"Failed to update permissions by filename '{filename}' in collection '{collection_name}': {e}")
            raise e

    @classmethod
    async def upsert_db_query_profile(
        cls,
        collection_name: str,
        profile_id: str,
        composed_description: str,
        dense_vector: List[float],
        knowledge_base_id: str,
        table_name: str,
        existing_point_id: Optional[str] = None,
        vector_size: int = 4096,
        is_default: bool = False
    ) -> str:
        """
        寫入/更新一個「語義資料庫查詢法」查詢設定檔向量。
        與一般文件 Chunk 存在同一個 Collection，但 payload.source 固定為 "db_query_profile"，
        並在 search_similar()/search_similar_two_step() 中被 must_not 排除，不會混入一般文件檢索結果。
        """
        client = cls.get_client()
        from datetime import datetime
        await cls.create_collection(collection_name, vector_size=vector_size)

        from services.sparse_embedding_service import SparseEmbeddingService
        sparse_vector = SparseEmbeddingService.get_sparse_vector(composed_description)

        point_id = existing_point_id or str(uuid.uuid4())
        payload = {
            "content": composed_description,
            "filename": f"DB_QUERY_PROFILE_{table_name}",
            "source": "db_query_profile",
            "profile_id": profile_id,
            "knowledge_base_id": knowledge_base_id,
            "table_name": table_name,
            "is_default": is_default,
            "created_at": datetime.utcnow().isoformat()
        }

        point = models.PointStruct(
            id=point_id,
            vector={
                "": dense_vector,
                "sparse-text": sparse_vector
            },
            payload=payload
        )

        try:
            await client.upsert(collection_name=collection_name, points=[point])
        except Exception as e:
            error_str = str(e)
            if "sparse-text" in error_str:
                logger.warning("Fallback: upserting db query profile point with dense vector only.")
                await client.upsert(
                    collection_name=collection_name,
                    points=[models.PointStruct(id=point_id, vector=dense_vector, payload=payload)]
                )
            else:
                logger.error(f"Failed to upsert db query profile point to Qdrant: {e}")
                raise e

        cls.invalidate_metadata_cache(collection_name)
        return point_id

    @classmethod
    async def delete_db_query_profile_point(cls, collection_name: str, point_id: str) -> None:
        """
        刪除指定查詢設定檔對應的 Qdrant point。
        """
        try:
            await cls.delete_points(collection_name, [point_id])
        except Exception as e:
            logger.error(f"Failed to delete db query profile point '{point_id}': {e}")

    @classmethod
    async def search_db_query_profiles(
        cls,
        collection_name: str,
        query_text: str,
        query_vector: List[float],
        knowledge_base_id: str,
        score_threshold: float,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        在指定 Collection 中，僅針對 source == "db_query_profile" 的查詢設定檔向量做 Hybrid RRF 搜尋，
        並依 knowledge_base_id 過濾範圍。回傳分數 >= score_threshold 的候選清單（依分數排序）。
        """
        client = cls.get_client()
        try:
            exists = await client.collection_exists(collection_name)
            if not exists:
                return []

            profile_filter = models.Filter(
                must=[
                    models.FieldCondition(key="source", match=models.MatchValue(value="db_query_profile")),
                    models.FieldCondition(key="knowledge_base_id", match=models.MatchValue(value=knowledge_base_id))
                ]
            )

            fetch_limit = max(limit * 3, 10)
            try:
                from services.sparse_embedding_service import SparseEmbeddingService
                query_sparse = SparseEmbeddingService.get_sparse_vector(query_text)

                response = await client.query_points(
                    collection_name=collection_name,
                    prefetch=[
                        models.Prefetch(query=query_vector, using="", limit=fetch_limit, filter=profile_filter),
                        models.Prefetch(query=query_sparse, using="sparse-text", limit=fetch_limit, filter=profile_filter)
                    ],
                    query=models.FusionQuery(fusion=models.Fusion.RRF),
                    limit=fetch_limit
                )
                points = response.points
            except Exception as he:
                logger.warning(f"Profile hybrid search failed, falling back to pure vector search: {he}")
                response = await client.query_points(
                    collection_name=collection_name,
                    query=query_vector,
                    limit=fetch_limit,
                    query_filter=profile_filter
                )
                points = response.points

            results = []
            for p in points:
                score = getattr(p, "score", 0.0) or 0.0
                if score < score_threshold:
                    continue
                payload = p.payload or {}
                results.append({
                    "profile_id": payload.get("profile_id"),
                    "table_name": payload.get("table_name"),
                    "content": payload.get("content", ""),
                    "score": score
                })

            results.sort(key=lambda x: x["score"], reverse=True)
            return results[:limit]
        except Exception as e:
            logger.error(f"Failed to search db query profiles in collection '{collection_name}': {e}")
            return []

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
                        "type": payload.get("type"),
                        "chunk_type": payload.get("chunk_type"),
                        "image_filename": payload.get("image_filename"),
                        "is_confidential": payload.get("is_confidential", False),
                        "confidential_level": payload.get("confidential_level"),
                        "confidential_departments": payload.get("confidential_departments", [])
                    }
                })
            
            # 依據 chunk_index 排序
            results.sort(key=lambda x: x["metadata"].get("chunk_index") or 0)
            return results
        except Exception as e:
            logger.error(f"Failed to get points by parent_id '{parent_id}': {e}")
            return []

    @staticmethod
    def _strip_structured_content_prefix(content: str) -> str:
        """
        去除結構化 Prompt 樣板前綴（[檔案名稱].../[主要內容]\n...），還原成純粹的段落內容。
        文字與圖片兄弟節點的內容清洗共用同一套邏輯。
        """
        for marker in ["[主要內容]\n", "[主要內容]\r\n"]:
            idx = content.find(marker)
            if idx != -1:
                return content[idx + len(marker):]
        return content

    @staticmethod
    def _merge_overlap_texts(pieces: list) -> str:
        """
        依序把多段文字去重拼接（解決切分時 overlap 造成的重複文字問題）。
        文字段落合併與圖片描述片段合併共用同一套邏輯。
        """
        if not pieces:
            return ""

        def merge_two_strings_with_overlap(s1: str, s2: str) -> str:
            max_overlap = min(len(s1), len(s2), 200)
            for i in range(max_overlap, 4, -1):
                if s1[-i:] == s2[:i]:
                    return s1 + s2[i:]
            return s1 + "\n" + s2

        merged = pieces[0]
        for next_piece in pieces[1:]:
            merged = merge_two_strings_with_overlap(merged, next_piece)
        return merged

    @classmethod
    def _group_and_merge_image_siblings(cls, image_siblings: list) -> list:
        """
        圖片描述若因過長被切成多個片段，同一張圖片的所有片段會共用同一個 parent_id，
        依 image_filename 分組、組內依 chunk_index 排序後合併回完整描述，
        確保每個 image_filename 只對應一筆內容完整的 image_chunks 項目
        （前端與檢索端的自我排除邏輯皆假設一個 image_filename = 一筆完整內容）。
        """
        groups: dict = {}
        order: list = []
        for sib in image_siblings:
            filename = sib["metadata"].get("image_filename")
            if filename not in groups:
                groups[filename] = []
                order.append(filename)
            groups[filename].append(sib)

        merged_chunks = []
        for filename in order:
            group = sorted(groups[filename], key=lambda s: s["metadata"].get("chunk_index") or 0)
            pieces = [cls._strip_structured_content_prefix(sib.get("content") or "") for sib in group]
            first = group[0]
            merged_chunks.append({
                "chunk_id": first.get("chunk_id"),
                "content": cls._merge_overlap_texts(pieces),
                "metadata": {
                    "filename": first["metadata"].get("filename"),
                    "page": first["metadata"].get("page"),
                    "chunk_type": "image",
                    "image_filename": filename,
                    # 沿用該圖片自己切出的片段範圍（第 11 節既有欄位），供前端顯示段落編號，
                    # 避免顯示端因為讀不到 chunk_index 而落到預設值 "?"
                    "chunk_index": first["metadata"].get("parent_chunk_index_range") or first["metadata"].get("chunk_index")
                }
            })
        return merged_chunks

    @classmethod
    async def get_image_siblings(cls, collection_name: str, parent_id: str) -> list:
        """
        只取得同一個 parent_id 下的圖片型兄弟節點並依 image_filename 重組（不執行文字去重合併運算）。
        供已有快取 parent_content、只需要補上 image_chunks 顯示用途的情境使用，
        避免重複跑一次 get_siblings_and_merge() 的完整文字合併計算。
        """
        siblings = await cls.get_by_parent_id(collection_name, parent_id)
        image_siblings = [sib for sib in siblings if sib["metadata"].get("chunk_type") == "image"]
        return cls._group_and_merge_image_siblings(image_siblings)

    @classmethod
    async def get_siblings_and_merge(cls, collection_name: str, parent_id: str, orig_content: str, metadata: dict) -> tuple:
        """
        撈取 parent_id 的所有兄弟節點並去重合併，還原完整的 Parent Content，且分離出圖片段落（不進行文字合併）。
        """
        siblings = await cls.get_by_parent_id(collection_name, parent_id)
        if not siblings:
            return orig_content, str(metadata.get("chunk_index") or ""), []

        # 分離文字與圖片兄弟節點
        text_siblings = [sib for sib in siblings if sib["metadata"].get("chunk_type") != "image"]
        image_siblings = [sib for sib in siblings if sib["metadata"].get("chunk_type") == "image"]

        # 收集圖片資訊：同一張圖片若因過長被切成多個片段，依 image_filename 分組重組回完整描述
        # （content 一併去除結構化樣板前綴，與文字兄弟節點使用同一套清洗邏輯，
        # 避免啟用「結構化 Prompt 強化」時圖片描述預覽多出重複的檔名/段落編號/標籤樣板文字）
        image_chunks = cls._group_and_merge_image_siblings(image_siblings)

        if not text_siblings:
            return orig_content, str(metadata.get("chunk_index") or ""), image_chunks

        indices = [sib["metadata"].get("chunk_index") for sib in text_siblings if sib["metadata"].get("chunk_index") is not None]
        if indices:
            min_idx = min(indices)
            max_idx = max(indices)
            parent_range = f"{min_idx}~{max_idx}" if min_idx != max_idx else str(min_idx)
        else:
            parent_range = str(metadata.get("chunk_index") or "")

        raw_contents = [cls._strip_structured_content_prefix(sib["content"]) for sib in text_siblings]
        if not raw_contents:
            return orig_content, parent_range, image_chunks
        
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
            
        return display_content, parent_range, image_chunks

