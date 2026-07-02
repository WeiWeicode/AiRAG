import time
import uuid
import logging
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, status
from beanie import PydanticObjectId

from typing import List
from schemas.embedding import (
    UploadResponse, ChunkRequest, ChunkResponse, ChunkItem,
    VectorizeRequest, VectorizeResponse, TagCreate, ClassOptionCreate,
    SemanticJSONIngestRequest, SemanticJSONIngestResponse
)
from services.document_parser import DocumentParser
from services.chunking_service import ChunkingService
from services.embedding_service import EmbeddingService
from services.qdrant_service import QdrantService
from models.knowledge_base import KnowledgeBase
from models.tag import Tag
from models.class_option import ClassOption
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
        # 檢查是否啟用大小雙層 (Parent-Child) 語法切分或是 4GL/4FD/MD/Word 檔案
        is_4fd = request.filename and request.filename.lower().endswith('.4fd')
        is_4gl = request.filename and request.filename.lower().endswith('.4gl')
        is_md = request.filename and (request.filename.lower().endswith('.md') or request.filename.lower().endswith('.markdown'))
        is_word = request.filename and (request.filename.lower().endswith('.docx') or request.filename.lower().endswith('.doc') or request.filename.lower().endswith('.dotx'))
        if request.params.chunk_mode == "parent_child" or is_4gl or is_4fd or is_md or is_word:
            all_children = []
            idx = 0
            
            if is_4fd:
                from services.parent_child_chunker import parse_4fd_to_parents, slice_4fd_to_children
                fname = request.filename or "unknown.4fd"
                parents = parse_4fd_to_parents(request.content, fname)
                for parent in parents:
                    children = slice_4fd_to_children(parent_chunk=parent, source_file=fname)
                    
                    # 計算該 Parent Block 切出來的 Child Chunks 索引範圍
                    start_idx = idx
                    end_idx = idx + len(children) - 1
                    parent_range = f"{start_idx}~{end_idx}" if len(children) > 1 else str(start_idx)
                    
                    for child in children:
                        # 注入 Parent Chunk 索引範圍到 metadata 中，以利後續檢索還原
                        child_metadata = dict(child["metadata"])
                        child_metadata["parent_chunk_index_range"] = parent_range
                        
                        all_children.append(ChunkItem(
                            index=idx,
                            content=child["child_content"],
                            token_count=ChunkingService.estimate_tokens(child["child_content"]),
                            char_count=len(child["child_content"]),
                            start_char=0,
                            end_char=len(child["child_content"]),
                            metadata=child_metadata
                        ))
                        idx += 1
            elif is_md or is_word:
                from services.markdown_parent_child_chunker import chunk_markdown_content
                fname = request.filename or ("unknown.md" if is_md else "unknown.docx")
                children = chunk_markdown_content(
                    markdown_content=request.content,
                    filename=fname,
                    child_size=request.params.chunk_size,
                    child_overlap=request.params.chunk_overlap,
                    use_langchain=True
                )
                
                # 計算每個 parent_id 對應的 Child Chunks 索引範圍
                parent_to_indices = {}
                for child_idx, child in enumerate(children):
                    pid = child["metadata"]["parent_id"]
                    if pid not in parent_to_indices:
                        parent_to_indices[pid] = []
                    parent_to_indices[pid].append(child_idx)
                
                for child_idx, child in enumerate(children):
                    pid = child["metadata"]["parent_id"]
                    indices = parent_to_indices[pid]
                    start_idx = indices[0]
                    end_idx = indices[-1]
                    parent_range = f"{start_idx}~{end_idx}" if len(indices) > 1 else str(start_idx)
                    
                    child_metadata = dict(child["metadata"])
                    child_metadata["parent_chunk_index_range"] = parent_range
                    child_metadata["file_type"] = fname.split('.')[-1].lower()
                    
                    all_children.append(ChunkItem(
                        index=idx,
                        content=child["child_content"],
                        token_count=ChunkingService.estimate_tokens(child["child_content"]),
                        char_count=len(child["child_content"]),
                        start_char=0,
                        end_char=len(child["child_content"]),
                        metadata=child_metadata
                    ))
                    idx += 1
            else:
                from services.parent_child_chunker import parse_4gl_to_parents, slice_to_children
                fname = request.filename or "unknown.4gl"
                parents = parse_4gl_to_parents(request.content, fname)
                for parent in parents:
                    children = slice_to_children(
                        content=parent["content"],
                        parent_chunk=parent,
                        source_file=fname,
                        child_size=request.params.chunk_size,
                        child_overlap=request.params.chunk_overlap
                    )
                    
                    # 計算該 Parent Block 切出來的 Child Chunks 索引範圍
                    start_idx = idx
                    end_idx = idx + len(children) - 1
                    parent_range = f"{start_idx}~{end_idx}" if len(children) > 1 else str(start_idx)
                    
                    for child in children:
                        # 注入 Parent Chunk 索引範圍到 metadata 中，以利後續檢索還原
                        child_metadata = dict(child["metadata"])
                        child_metadata["parent_chunk_index_range"] = parent_range
                        
                        all_children.append(ChunkItem(
                            index=idx,
                            content=child["child_content"],
                            token_count=ChunkingService.estimate_tokens(child["child_content"]),
                            char_count=len(child["child_content"]),
                            start_char=0,
                            end_char=len(child["child_content"]),
                            metadata=child_metadata
                        ))
                        idx += 1
            
            avg_tokens = int(sum(c.token_count for c in all_children) / len(all_children)) if all_children else 0
            return ChunkResponse(
                chunks=all_children,
                total_chunks=len(all_children),
                avg_token_count=avg_tokens
            )

        # 否則使用標準切分
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
            classes = chunk.metadata.get("classes", chunk.metadata.get("class", []))
            if isinstance(classes, str):
                classes = [classes] if classes else []
                
            links_to = chunk.metadata.get("links_to") or chunk.metadata.get("links") or []
            if isinstance(links_to, str):
                links_to = [links_to] if links_to else []
                
            payload = {
                "content": chunk.content,
                "filename": chunk.metadata.get("filename", "unknown"),
                "page": chunk.metadata.get("page", 1),
                "section": chunk.metadata.get("section", ""),
                "chunk_index": chunk.index,
                "token_count": ChunkingService.estimate_tokens(chunk.content),
                "char_count": len(chunk.content),
                "source": chunk.metadata.get("source", "upload"),
                "tags": chunk.metadata.get("tags", []),
                "class": classes,
                "links_to": links_to,
                "created_at": datetime.utcnow().isoformat()
            }
            # 額外合併 metadata 中的其他自訂屬性 (例如 parent_id, function_name, type)
            for k, v in chunk.metadata.items():
                if k not in payload and k not in ["class", "classes", "links_to", "links"]:
                    payload[k] = v
            qdrant_chunks.append(payload)
            
        # 寫入 Qdrant
        inserted = await QdrantService.upsert_chunks(
            collection_name=kb.qdrant_collection_name,
            chunks=qdrant_chunks,
            vectors=vectors
        )
        QdrantService.invalidate_metadata_cache(kb.qdrant_collection_name)

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

@router.post("/vectorize-json", response_model=SemanticJSONIngestResponse)
async def vectorize_json(request: SemanticJSONIngestRequest):
    """
    接收地端多模態 AI 產出的 JSON 資料，使用專門的語義化 AI 模組進行密集向量化，
    並生成稀疏向量後寫入向量資料庫 Qdrant。
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
        
    if not request.items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="請提供至少一筆 JSON 資料進行向量化"
        )
        
    try:
        # 1. 準備需要向量化的語義輸入文本清單 (embeddings_input)
        semantic_texts = [item.embeddings_input for item in request.items]
        
        # 2. 批次呼叫新的 get_semantic_embeddings_batch 取得密集向量
        dense_vectors = await EmbeddingService.get_semantic_embeddings_batch(semantic_texts)
        
        # 3. 取得向量維度大小
        vector_size = 4096  # 預設
        if dense_vectors and len(dense_vectors[0]) > 0:
            vector_size = len(dense_vectors[0])
            
        # 4. 準備轉換為字典陣列，便於 upsert 處理
        items_dict = [item.model_dump() for item in request.items]
        
        # 5. 寫入 Qdrant (包含自動建立 collection 與 sparse vector 產生)
        inserted = await QdrantService.upsert_semantic_json_chunks(
            collection_name=kb.qdrant_collection_name,
            items=items_dict,
            dense_vectors=dense_vectors,
            vector_size=vector_size
        )
        QdrantService.invalidate_metadata_cache(kb.qdrant_collection_name)

        # 6. 更新 MongoDB 知識庫的 Chunk 總量
        kb.chunk_count += inserted
        kb.updated_at = datetime.utcnow()
        await kb.save()
        
        elapsed = int((time.time() - start_time) * 1000)
        from config import settings
        return SemanticJSONIngestResponse(
            knowledge_base_id=str(kb.id),
            inserted_count=inserted,
            embedding_model=settings.EMBEDDING_MODEL,
            elapsed_ms=elapsed
        )
    except Exception as e:
        logger.error(f"Semantic JSON vectorization or Qdrant ingestion failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"語義 JSON 向量化寫入失敗: {str(e)}"
        )

@router.get("/tags", response_model=List[str])
async def get_tags():
    """
    取得所有分類標籤清單。
    """
    try:
        tags = await Tag.find_all().to_list()
        return [t.name for t in tags]
    except Exception as e:
        logger.error(f"Failed to get tags: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"取得標籤清單失敗: {str(e)}"
        )

@router.post("/tags", response_model=str)
async def create_tag(request: TagCreate):
    """
    建立新的分類標籤。
    """
    try:
        # Check if tag already exists
        existing = await Tag.find_one(Tag.name == request.name)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"標籤 '{request.name}' 已存在"
            )
        new_tag = Tag(name=request.name)
        await new_tag.insert()
        return new_tag.name
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create tag: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"建立標籤失敗: {str(e)}"
        )

@router.get("/classes", response_model=List[str])
async def get_classes():
    """
    取得所有類別選項清單。
    """
    try:
        classes = await ClassOption.find_all().to_list()
        return [c.name for c in classes]
    except Exception as e:
        logger.error(f"Failed to get class options: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"取得類別選項失敗: {str(e)}"
        )

@router.post("/classes", response_model=str)
async def create_class(request: ClassOptionCreate):
    """
    建立新的類別選項。
    """
    try:
        existing = await ClassOption.find_one(ClassOption.name == request.name)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"類別 '{request.name}' 已存在"
            )
        new_class = ClassOption(name=request.name)
        await new_class.insert()
        return new_class.name
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create class: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"建立類別失敗: {str(e)}"
        )

