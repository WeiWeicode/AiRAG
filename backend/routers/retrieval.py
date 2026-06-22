import time
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from beanie import PydanticObjectId

from schemas.retrieval import (
    RetrievalRequest, RetrievalResponse, RetrievalResultItem, RetrievalMetadata,
    QueryTransformRequest, QueryTransformResponse
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
        # 1. 取得查詢字串的向量
        query_vector = await EmbeddingService.get_embedding(request.query)
        
        # 2. 向 Qdrant 進行向量檢索
        raw_results = await QdrantService.search_similar(
            collection_name=kb.qdrant_collection_name,
            query_vector=query_vector,
            top_k=request.params.top_k,
            score_threshold=request.params.score_threshold
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
                        chunk_index=meta.get("chunk_index")
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
                        chunk_index=meta.get("chunk_index")
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
