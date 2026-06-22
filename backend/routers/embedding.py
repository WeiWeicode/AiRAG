import time
import uuid
import logging
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, status
from beanie import PydanticObjectId

from schemas.embedding import (
    UploadResponse, ChunkRequest, ChunkResponse, ChunkItem,
    VectorizeRequest, VectorizeResponse
)
from services.document_parser import DocumentParser
from services.chunking_service import ChunkingService
from services.embedding_service import EmbeddingService
from services.qdrant_service import QdrantService
from models.knowledge_base import KnowledgeBase
from utils.security import get_current_user

logger = logging.getLogger("airag.embedding_router")
router = APIRouter(prefix="/embedding", tags=["Embedding"], dependencies=[Depends(get_current_user)])

@router.post("/upload", response_model=UploadResponse)
async def upload_document(file: UploadFile = File(...)):
    """
    上傳檔案，呼叫解析引擎，並傳回純文字與頁數資訊。
    """
    try:
        content_bytes = await file.read()
        text, pages, chars = DocumentParser.parse_file(file.filename, content_bytes)
        
        file_id = str(uuid.uuid4())
        return UploadResponse(
            file_id=file_id,
            filename=file.filename,
            content=text,
            page_count=pages,
            char_count=chars
        )
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        logger.error(f"Upload and parse failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"檔案處理失敗: {str(e)}"
        )

@router.post("/chunk", response_model=ChunkResponse)
async def chunk_text(request: ChunkRequest):
    """
    依據設定切分純文字。
    """
    try:
        chunks_data = ChunkingService.split_text(
            text=request.content,
            chunk_size=request.params.chunk_size,
            chunk_overlap=request.params.chunk_overlap,
            separator=request.params.separator
        )
        
        items = []
        total_tokens = 0
        for item in chunks_data:
            items.append(ChunkItem(**item))
            total_tokens += item["token_count"]
            
        avg_tokens = int(total_tokens / len(items)) if items else 0
        
        return ChunkResponse(
            chunks=items,
            total_chunks=len(items),
            avg_token_count=avg_tokens
        )
    except Exception as e:
        logger.error(f"Text chunking failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail=f"文本切分失敗: {str(e)}"
        )

@router.post("/vectorize", response_model=VectorizeResponse)
async def vectorize_chunks(request: VectorizeRequest):
    """
    呼叫地端 Embedding 模型進行向量化，並將結果寫入對應的 Qdrant 集合，更新 MongoDB 知識庫狀態。
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
        
    if not request.chunks:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="請提供至少一個 Chunk 進行向量化"
        )
        
    try:
        # 準備需要向量化的文本清單
        texts = [chunk.content for chunk in request.chunks]
        
        # 批次向 llama.cpp 取得向量
        vectors = await EmbeddingService.get_embeddings_batch(texts)
        
        # 準備寫入 Qdrant 的 Payload
        qdrant_chunks = []
        for chunk in request.chunks:
            qdrant_chunks.append({
                "content": chunk.content,
                "filename": chunk.metadata.get("filename", "unknown"),
                "page": chunk.metadata.get("page", 1),
                "section": chunk.metadata.get("section", ""),
                "chunk_index": chunk.index,
                "token_count": ChunkingService.estimate_tokens(chunk.content),
                "char_count": len(chunk.content),
                "source": chunk.metadata.get("source", "upload"),
                "tags": chunk.metadata.get("tags", []),
                "created_at": datetime.utcnow().isoformat()
            })
            
        # 寫入 Qdrant
        inserted = await QdrantService.upsert_chunks(
            collection_name=kb.qdrant_collection_name,
            chunks=qdrant_chunks,
            vectors=vectors
        )
        
        # 更新 MongoDB 知識庫的 Chunk 總量
        kb.chunk_count += inserted
        kb.updated_at = datetime.utcnow()
        await kb.save()
        
        elapsed = int((time.time() - start_time) * 1000)
        return VectorizeResponse(
            knowledge_base_id=str(kb.id),
            inserted_count=inserted,
            embedding_model=request.embedding_model,
            elapsed_ms=elapsed
        )
    except Exception as e:
        logger.error(f"Vectorization or Qdrant ingestion failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"向量化寫入失敗: {str(e)}"
        )
