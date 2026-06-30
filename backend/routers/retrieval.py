import time
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from beanie import PydanticObjectId

from datetime import datetime
from schemas.retrieval import (
    RetrievalRequest, RetrievalResponse, RetrievalResultItem, RetrievalMetadata,
    QueryTransformRequest, QueryTransformResponse, BatchDeleteRequest, DeleteByFilenameRequest
)
from services.embedding_service import EmbeddingService
from services.qdrant_service import QdrantService
from services.llm_service import LLMService
from models.knowledge_base import KnowledgeBase
from utils.security import get_current_user

logger = logging.getLogger("airag.retrieval_router")
router = APIRouter(prefix="/retrieval", tags=["Retrieval"], dependencies=[Depends(get_current_user)])

@router.post("/search", response_model=RetrievalResponse)
async def search(request: RetrievalRequest):
    """
    僅執行向量檢索搜尋，不進行 LLM 回答生成。
    """
    start_time = time.time()
    try:
        kb_id = PydanticObjectId(request.knowledge_base_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="無效的知識庫 ID 格式"
        )
        
    kb = await KnowledgeBase.get(kb_id)
    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="指定的知識庫不存在"
        )
        
    try:
        # 1. 取得查詢字串的向量 (有輸入關鍵字才計算向量)
        query_vector = None
        has_query = bool(request.query and request.query.strip())
        if has_query:
            query_vector = await EmbeddingService.get_embedding(request.query)
        
        # 2. 向 Qdrant 進行雙路融合檢索、純向量檢索或直接 Scroll
        raw_results = await QdrantService.search_similar(
            collection_name=kb.qdrant_collection_name,
            query_vector=query_vector,
            query_text=request.query,
            search_type=request.params.search_type,
            top_k=request.params.top_k,
            score_threshold=request.params.score_threshold if has_query else 0.0,
            filter_tags=request.params.filter_tags,
            filter_filename=request.params.filter_filename,
            disable_parent_merge=request.params.disable_parent_merge
        )
        
        # 3. 包裝為回應格式
        results = []
        for item in raw_results:
            meta = item.get("metadata", {})
            results.append(
                RetrievalResultItem(
                    chunk_id=item.get("chunk_id"),
                    content=item.get("content", ""),
                    metadata=RetrievalMetadata(
                        filename=meta.get("filename"),
                        page=meta.get("page"),
                        section=meta.get("section"),
                        chunk_index=meta.get("chunk_index"),
                        tags=meta.get("tags", []),
                        class_list=meta.get("class", []),
                        parent_id=meta.get("parent_id"),
                        function_name=meta.get("function_name"),
                        type=meta.get("type")
                    ),
                    score=item.get("score", 0.0),
                    distance=item.get("distance", 1.0)
                )
            )
            
        elapsed = int((time.time() - start_time) * 1000)
        return RetrievalResponse(
            query=request.query,
            results=results,
            elapsed_ms=elapsed
        )
    except Exception as e:
        logger.error(f"Vector search failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"檢索失敗: {str(e)}"
        )

@router.post("/semantic-hybrid-search", response_model=RetrievalResponse)
async def semantic_hybrid_search(request: RetrievalRequest):
    """
    執行語義混合搜尋：密集向量使用專門的語義化 AI 模組生成，結合稀疏向量做 RRF 混合檢索。
    """
    start_time = time.time()
    try:
        kb_id = PydanticObjectId(request.knowledge_base_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="無效的知識庫 ID 格式"
        )
        
    kb = await KnowledgeBase.get(kb_id)
    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="指定的知識庫不存在"
        )
        
    try:
        # 1. 取得查詢字串的語義密集向量與進行 Instruct 語義分析
        query_vector = None
        semantic_json = None
        embeddings_input = None
        sparse_keywords = None
        query_vector_preview = None
        vector_size = None
        
        has_query = bool(request.query and request.query.strip())
        search_query_text = request.query
        
        if has_query:
            # 呼叫 Instruct AI 轉 JSON
            semantic_json = await EmbeddingService.query_to_semantic_json(request.query)
            embeddings_input = semantic_json.get("embeddings_input", request.query)
            sparse_keywords = semantic_json.get("sparse_keywords", [])
            
            # 轉換 embeddings_input 為密集向量
            query_vector = await EmbeddingService.get_semantic_embedding(embeddings_input)
            if query_vector:
                query_vector_preview = str(query_vector[:10]) + "..."
                vector_size = len(query_vector)
            
            # 設定用來做稀疏查詢的文本
            search_query_text = " ".join(sparse_keywords) if sparse_keywords else request.query
        
        # 2. 向 Qdrant 進行語義混合檢索 (search_type 強制為 "semantic_hybrid")
        raw_results = await QdrantService.search_similar(
            collection_name=kb.qdrant_collection_name,
            query_vector=query_vector,
            query_text=search_query_text,
            search_type="semantic_hybrid",
            top_k=request.params.top_k,
            score_threshold=request.params.score_threshold if has_query else 0.0,
            filter_tags=request.params.filter_tags,
            filter_filename=request.params.filter_filename,
            disable_parent_merge=request.params.disable_parent_merge
        )
        
        # 3. 包裝為回應格式
        results = []
        for item in raw_results:
            meta = item.get("metadata", {})
            results.append(
                RetrievalResultItem(
                    chunk_id=item.get("chunk_id"),
                    content=item.get("content", ""),
                    metadata=RetrievalMetadata(
                        filename=meta.get("filename"),
                        page=meta.get("page"),
                        section=meta.get("section"),
                        chunk_index=meta.get("chunk_index"),
                        tags=meta.get("tags", []),
                        class_list=meta.get("class", []),
                        parent_id=meta.get("parent_id"),
                        function_name=meta.get("function_name"),
                        type=meta.get("type")
                    ),
                    score=item.get("score", 0.0),
                    distance=item.get("distance", 1.0)
                )
            )
            
        elapsed = int((time.time() - start_time) * 1000)
        return RetrievalResponse(
            query=request.query,
            results=results,
            elapsed_ms=elapsed,
            semantic_json=semantic_json,
            embeddings_input=embeddings_input,
            sparse_keywords=sparse_keywords,
            query_vector_preview=query_vector_preview,
            vector_size=vector_size
        )
    except Exception as e:
        logger.error(f"Semantic hybrid search failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"語義混合檢索失敗: {str(e)}"
        )

@router.post("/query-transform", response_model=QueryTransformResponse)
async def query_transform(request: QueryTransformRequest):
    """
    透過 LLM 將查詢進行重寫 (Query Rewriting) 或生成假想文檔 (HyDE)，再執行檢索。
    """
    try:
        kb_id = PydanticObjectId(request.knowledge_base_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="無效的知識庫 ID 格式"
        )
        
    kb = await KnowledgeBase.get(kb_id)
    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="指定的知識庫不存在"
        )
        
    try:
        # 1. 執行查詢轉換策略
        transformed_query = request.query
        if request.strategy == "rewrite":
            transformed_query = await LLMService.query_rewrite(request.query)
        elif request.strategy == "hyde":
            transformed_query = await LLMService.hyde_generation(request.query)
            
        # 2. 取得轉換後查詢字串的向量
        query_vector = await EmbeddingService.get_embedding(transformed_query)
        
        # 3. 向 Qdrant 進行向量檢索
        raw_results = await QdrantService.search_similar(
            collection_name=kb.qdrant_collection_name,
            query_vector=query_vector,
            top_k=8,
            score_threshold=0.3
        )
        
        # 4. 包裝為回應格式
        results = []
        for item in raw_results:
            meta = item.get("metadata", {})
            results.append(
                RetrievalResultItem(
                    chunk_id=item.get("chunk_id"),
                    content=item.get("content", ""),
                    metadata=RetrievalMetadata(
                        filename=meta.get("filename"),
                        page=meta.get("page"),
                        section=meta.get("section"),
                        chunk_index=meta.get("chunk_index"),
                        tags=meta.get("tags", []),
                        class_list=meta.get("class", []),
                        parent_id=meta.get("parent_id"),
                        function_name=meta.get("function_name"),
                        type=meta.get("type")
                    ),
                    score=item.get("score", 0.0),
                    distance=item.get("distance", 1.0)
                )
            )
            
        return QueryTransformResponse(
            original_query=request.query,
            transformed_query=transformed_query,
            strategy=request.strategy,
            results=results
        )
    except Exception as e:
        logger.error(f"Query transformation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"查詢轉換失敗: {str(e)}"
        )


@router.post("/knowledge-bases/{knowledge_base_id}/points/batch-delete")
async def batch_delete_points(knowledge_base_id: str, request: BatchDeleteRequest):
    """
    批次刪除指定知識庫中的多個 Points (向量節點)
    """
    try:
        kb_id = PydanticObjectId(knowledge_base_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="無效的知識庫 ID 格式"
        )
        
    kb = await KnowledgeBase.get(kb_id)
    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="指定的知識庫不存在"
        )
        
    if not request.point_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="請提供至少一個 Point ID 進行刪除"
        )
        
    success = await QdrantService.delete_points(kb.qdrant_collection_name, request.point_ids)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="無法從向量資料庫中刪除指定的 Points"
        )
        
    # 更新 MongoDB 中的 chunk_count
    kb.chunk_count = max(0, kb.chunk_count - len(request.point_ids))
    kb.updated_at = datetime.utcnow()
    await kb.save()
    
    return {
        "message": "批次刪除成功",
        "deleted_count": len(request.point_ids)
    }


@router.post("/knowledge-bases/{knowledge_base_id}/files/delete-by-filename")
async def delete_file_by_filename(knowledge_base_id: str, request: DeleteByFilenameRequest):
    """
    刪除指定知識庫中特定檔案名稱的所有向量段落 (Points)
    """
    try:
        kb_id = PydanticObjectId(knowledge_base_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="無效的知識庫 ID 格式"
        )
        
    kb = await KnowledgeBase.get(kb_id)
    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="指定的知識庫不存在"
        )
        
    if not request.filename.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="請提供檔案名稱"
        )
        
    try:
        deleted_count = await QdrantService.delete_by_filename(kb.qdrant_collection_name, request.filename)
        
        # 更新 MongoDB 中的 chunk_count
        kb.chunk_count = max(0, kb.chunk_count - deleted_count)
        kb.updated_at = datetime.utcnow()
        await kb.save()
        
        return {
            "message": f"成功刪除檔案 '{request.filename}'",
            "deleted_count": deleted_count
        }
    except Exception as e:
        logger.error(f"Delete file by filename failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"無法從向量資料庫中刪除檔案: {str(e)}"
        )

