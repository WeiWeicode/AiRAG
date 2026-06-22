import time
import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Query
from beanie import PydanticObjectId
from typing import Optional

from schemas.sqlserver import (
    SQLServerArticlesResponse, SQLServerArticleItem,
    SQLServerImportRequest, SQLServerImportResponse
)
from models.sqlserver import execute_query_async
from models.knowledge_base import KnowledgeBase
from services.chunking_service import ChunkingService
from services.embedding_service import EmbeddingService
from services.qdrant_service import QdrantService
from utils.security import get_current_user

logger = logging.getLogger("airag.sqlserver_router")
router = APIRouter(prefix="/sqlserver", tags=["SQL Server Articles"], dependencies=[Depends(get_current_user)])

@router.get("/articles", response_model=SQLServerArticlesResponse)
async def list_articles(
    page: int = Query(1, ge=1, description="頁碼"),
    page_size: int = Query(10, ge=1, le=100, description="每頁筆數"),
    search: Optional[str] = Query(None, description="標題搜尋關鍵字")
):
    """
    從唯讀 SQL Server 資料庫查詢文章清單 (分頁與關鍵字搜尋)。
    """
    offset = (page - 1) * page_size
    
    # 建立條件子句
    where_clauses = []
    params = []
    
    if search:
        where_clauses.append("title LIKE ?")
        params.append(f"%{search}%")
        
    where_str = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""
    
    try:
        # 查詢總筆數
        count_query = f"SELECT COUNT(*) as total FROM articles{where_str}"
        count_rows = await execute_query_async(count_query, tuple(params))
        total = count_rows[0]["total"] if count_rows else 0
        
        if total == 0:
            return SQLServerArticlesResponse(items=[], total=0)
            
        # 分頁查詢所有文章欄位
        page_query = (
            f"SELECT id, title, is_published, is_public, access_dept, access_members, "
            f"access_level, version_number, created_by, created_by_name, created_at, updated_at "
            f"FROM articles{where_str} "
            f"ORDER BY id OFFSET ? ROWS FETCH NEXT ? ROWS ONLY"
        )
        
        # 加上分頁參數
        page_params = tuple(params + [offset, page_size])
        rows = await execute_query_async(page_query, page_params)
        
        items = []
        for row in rows:
            # 轉換 id 為字串以適配 schema
            items.append(
                SQLServerArticleItem(
                    id=str(row["id"]),
                    title=row["title"],
                    is_published=bool(row["is_published"]),
                    is_public=bool(row["is_public"]),
                    access_dept=row.get("access_dept"),
                    access_members=row.get("access_members"),
                    access_level=row.get("access_level"),
                    version_number=row.get("version_number"),
                    created_by=row.get("created_by"),
                    created_by_name=row.get("created_by_name"),
                    created_at=row.get("created_at"),
                    updated_at=row.get("updated_at")
                )
            )
            
        return SQLServerArticlesResponse(items=items, total=total)
    except Exception as e:
        logger.error(f"Failed to query SQL Server articles: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"讀取 SQL Server 既有知識庫失敗: {str(e)}"
        )

@router.post("/import", response_model=SQLServerImportResponse)
async def import_article(request: SQLServerImportRequest):
    """
    從 SQL Server 讀取特定 Markdown 文章，切分並寫入指定的 Qdrant 知識庫。
    """
    start_time = time.time()
    
    # 1. 驗證知識庫是否存在
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
        
    # 2. 從 SQL Server 讀取文章標題與 markdown 內容
    try:
        # 嘗試轉換 ID 為整數，若失敗則使用字串查詢
        try:
            int_id = int(request.article_id)
            rows = await execute_query_async("SELECT title, content FROM articles WHERE id = ?", (int_id,))
        except ValueError:
            rows = await execute_query_async("SELECT title, content FROM articles WHERE id = ?", (request.article_id,))
            
        if not rows:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"在 SQL Server 中找不到 ID 為 {request.article_id} 的文章"
            )
            
        title = rows[0]["title"]
        content = rows[0]["content"] or ""
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"SQL Server query failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"從 SQL Server 查詢文章失敗: {str(e)}"
        )
        
    if not content.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="該文章的 content 內容為空，無法進行向量化"
        )
        
    # 3. 進行 Chunking 切分
    try:
        chunks_data = ChunkingService.split_text(
            text=content,
            chunk_size=request.chunk_size,
            chunk_overlap=request.chunk_overlap,
            separator=request.separator
        )
        
        if not chunks_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="文章內容無法切分成任何有效 Chunk"
            )
    except Exception as e:
        logger.error(f"Chunking failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"文本切分失敗: {str(e)}"
        )
        
    # 4. 向量化與寫入向量資料庫
    try:
        # 向量化
        texts = [c["content"] for c in chunks_data]
        vectors = await EmbeddingService.get_embeddings_batch(texts)
        
        # 封裝 Payload 並上傳 Qdrant
        qdrant_chunks = []
        for c in chunks_data:
            qdrant_chunks.append({
                "content": c["content"],
                "filename": f"SQLServer_Article_{request.article_id}",
                "page": 1,
                "section": title,
                "chunk_index": c["index"],
                "token_count": c["token_count"],
                "char_count": len(c["content"]),
                "source": "sqlserver",
                "created_at": datetime.utcnow().isoformat()
            })
            
        inserted = await QdrantService.upsert_chunks(
            collection_name=kb.qdrant_collection_name,
            chunks=qdrant_chunks,
            vectors=vectors
        )
        
        # 5. 更新 MongoDB 知識庫的 Chunk 計數
        kb.chunk_count += inserted
        kb.updated_at = datetime.utcnow()
        await kb.save()
        
        elapsed = int((time.time() - start_time) * 1000)
        return SQLServerImportResponse(
            knowledge_base_id=str(kb.id),
            inserted_count=inserted,
            elapsed_ms=elapsed
        )
    except Exception as e:
        logger.error(f"Ingest failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"向量化與匯入 Qdrant 失敗: {str(e)}"
        )
