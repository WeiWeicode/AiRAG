import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from beanie import PydanticObjectId

from schemas.knowledge_base import (
    KnowledgeBaseCreate, KnowledgeBaseItem, KnowledgeBaseListResponse
)
from models.knowledge_base import KnowledgeBase
from services.qdrant_service import QdrantService
from utils.security import get_current_user

logger = logging.getLogger("airag.kb_router")
router = APIRouter(prefix="/knowledge-bases", tags=["Knowledge Base"], dependencies=[Depends(get_current_user)])

@router.get("", response_model=KnowledgeBaseListResponse)
async def list_knowledge_bases():
    """
    列出所有系統內的知識庫。
    """
    try:
        kbs = await KnowledgeBase.find_all().to_list()
        items = []
        for kb in kbs:
            items.append(
                KnowledgeBaseItem(
                    id=str(kb.id),
                    name=kb.name,
                    description=kb.description,
                    chunk_count=kb.chunk_count,
                    created_at=kb.created_at
                )
            )
        return KnowledgeBaseListResponse(items=items)
    except Exception as e:
        logger.error(f"Failed to list knowledge bases: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"查詢知識庫列表失敗: {str(e)}"
        )

@router.post("", response_model=KnowledgeBaseItem, status_code=status.HTTP_201_CREATED)
async def create_knowledge_base(request: KnowledgeBaseCreate, current_user: str = Depends(get_current_user)):
    """
    建立新的知識庫（並在 Qdrant 中建立對應的 Collection）。
    """
    # 產生一組新的 PydanticObjectId
    kb_id = PydanticObjectId()
    qdrant_collection_name = f"kb_{str(kb_id)}"
    
    # 在 Qdrant 建立 Collection
    qdrant_success = await QdrantService.create_collection(qdrant_collection_name)
    if not qdrant_success:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="無法在向量資料庫中建立對應的知識集合"
        )
        
    try:
        kb = KnowledgeBase(
            id=kb_id,
            name=request.name,
            description=request.description,
            qdrant_collection_name=qdrant_collection_name,
            embedding_model="Qwen3-Embedding-8B-Q8_0.gguf",
            chunk_count=0,
            created_by=current_user,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        await kb.insert()
        
        return KnowledgeBaseItem(
            id=str(kb.id),
            name=kb.name,
            description=kb.description,
            chunk_count=kb.chunk_count,
            created_at=kb.created_at
        )
    except Exception as e:
        logger.error(f"Failed to insert knowledge base: {e}")
        # 嘗試復原 Qdrant 的 collection
        await QdrantService.delete_collection(qdrant_collection_name)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"建立知識庫紀錄失敗: {str(e)}"
        )

@router.delete("/{id}")
async def delete_knowledge_base(id: str):
    """
    刪除知識庫並連帶清除 Qdrant 對應的集合。
    """
    try:
        kb_id = PydanticObjectId(id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="無效的知識庫 ID 格式"
        )
        
    kb = await KnowledgeBase.get(kb_id)
    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="知識庫不存在"
        )
        
    # 刪除 Qdrant 集合
    qdrant_success = await QdrantService.delete_collection(kb.qdrant_collection_name)
    if not qdrant_success:
        logger.warning(f"Failed to delete Qdrant collection {kb.qdrant_collection_name} during deletion of KB {id}")
    QdrantService.invalidate_metadata_cache(kb.qdrant_collection_name)

    try:
        await kb.delete()
        return {"message": "刪除成功"}
    except Exception as e:
        logger.error(f"Failed to delete knowledge base record: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"刪除知識庫紀錄失敗: {str(e)}"
        )

@router.get("/{id}/metadata")
async def get_kb_metadata(id: str):
    """
    獲取知識庫內的所有唯一檔案名稱與標籤。
    """
    try:
        kb_id = PydanticObjectId(id)
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
        
    metadata = await QdrantService.get_unique_metadata(kb.qdrant_collection_name)
    return metadata
