import os
import uuid
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, status
from fastapi.responses import FileResponse
from beanie import PydanticObjectId

from config import settings
from utils.security import get_current_user
from models.attachment import Attachment
from models.knowledge_base import KnowledgeBase
from schemas.attachment import AttachmentResponse, AttachmentListResponse
from services.document_parser import DocumentParser

logger = logging.getLogger("airag.attachment_router")
router = APIRouter(prefix="/attachments", tags=["Attachment"])

@router.post("/upload", response_model=AttachmentResponse)
async def upload_attachment(
    knowledge_base_id: str = Form(...),
    description: str = Form(""),
    tags: Optional[str] = Form(""),
    classes: Optional[str] = Form(""),
    file: UploadFile = File(...),
    current_user: str = Depends(get_current_user)
):
    """
    上傳附件檔案（落地儲存，並於 MongoDB 記錄 metadata）。
    """
    # 驗證知識庫是否存在
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

    # 確保儲存目錄存在
    upload_dir = settings.FILE_ATTACHMENTS_DIR
    os.makedirs(upload_dir, exist_ok=True)

    # 生成安全隨機存檔名稱
    suffix = Path(file.filename).suffix
    stored_filename = f"{uuid.uuid4().hex}{suffix}"
    file_path = os.path.join(upload_dir, stored_filename)

    try:
        # 讀取並寫入檔案
        content = await file.read()
        file_size = len(content)
        with open(file_path, "wb") as f:
            f.write(content)
    except Exception as e:
        logger.error(f"Failed to write attachment file: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"寫入實體檔案失敗: {str(e)}"
        )

    # 解析標籤與類別
    tags_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    classes_list = [c.strip() for c in classes.split(",") if c.strip()] if classes else []

    # 自動解析檔案實際內容（AI 讀取附件內容時的主要來源，與使用者填寫的 description 備註分開）
    extracted_content = None
    extraction_error = None
    try:
        parsed_text, _, _ = DocumentParser.parse_file(file.filename, content)
        extracted_content = parsed_text.strip() or None
    except Exception as e:
        logger.warning(f"Attachment content extraction failed for '{file.filename}': {e}")
        extraction_error = str(e)

    # 建立 MongoDB 記錄
    username = current_user
    attachment = Attachment(
        knowledge_base_id=knowledge_base_id,
        original_filename=file.filename,
        stored_filename=stored_filename,
        description=description,
        extracted_content=extracted_content,
        extraction_error=extraction_error,
        tags=tags_list,
        classes=classes_list,
        content_type=file.content_type,
        size=file_size,
        created_by=username,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )

    try:
        await attachment.insert()
    except Exception as e:
        logger.error(f"Failed to save attachment metadata: {e}")
        # 若 DB 寫入失敗，試圖清理實體檔案
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"儲存附件資料失敗: {str(e)}"
        )

    return AttachmentResponse(
        id=str(attachment.id),
        knowledge_base_id=attachment.knowledge_base_id,
        original_filename=attachment.original_filename,
        description=attachment.description,
        has_extracted_content=bool(attachment.extracted_content),
        extraction_error=attachment.extraction_error,
        tags=attachment.tags,
        classes=attachment.classes,
        content_type=attachment.content_type,
        size=attachment.size,
        created_by=attachment.created_by,
        created_at=attachment.created_at,
        updated_at=attachment.updated_at
    )

@router.get("", response_model=AttachmentListResponse)
async def list_attachments(knowledge_base_id: str, current_user: str = Depends(get_current_user)):
    """
    列出指定知識庫的所有附件。
    """
    try:
        attachments = await Attachment.find(Attachment.knowledge_base_id == knowledge_base_id).sort(-Attachment.created_at).to_list()
        res_items = []
        for a in attachments:
            res_items.append(AttachmentResponse(
                id=str(a.id),
                knowledge_base_id=a.knowledge_base_id,
                original_filename=a.original_filename,
                description=a.description,
                has_extracted_content=bool(a.extracted_content),
                extraction_error=a.extraction_error,
                tags=a.tags,
                classes=a.classes,
                content_type=a.content_type,
                size=a.size,
                created_by=a.created_by,
                created_at=a.created_at,
                updated_at=a.updated_at
            ))
        return AttachmentListResponse(items=res_items, total=len(res_items))
    except Exception as e:
        logger.error(f"Failed to list attachments: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"取得附件清單失敗: {str(e)}"
        )

@router.delete("/{id}")
async def delete_attachment(id: str, current_user: str = Depends(get_current_user)):
    """
    刪除指定的附件（刪除 MongoDB 記錄與實體檔案）。
    """
    try:
        att_id = PydanticObjectId(id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="無效的附件 ID 格式"
        )

    attachment = await Attachment.get(att_id)
    if not attachment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="附件不存在"
        )

    # 刪除實體檔案
    file_path = os.path.join(settings.FILE_ATTACHMENTS_DIR, attachment.stored_filename)
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        logger.warning(f"Failed to remove physical file {file_path}: {e}")

    # 刪除 DB 記錄
    try:
        await attachment.delete()
    except Exception as e:
        logger.error(f"Failed to delete attachment metadata: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"刪除附件資料失敗: {str(e)}"
        )

    return {"status": "success", "message": f"Attachment {id} deleted successfully."}

@router.get("/{id}/download")
async def download_attachment(id: str, current_user: str = Depends(get_current_user)):
    """
    下載指定附件（回傳 FileResponse，Starlette 會自動編碼 Content-Disposition 使檔名正確還原）。
    """
    try:
        att_id = PydanticObjectId(id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="無效的附件 ID 格式"
        )

    attachment = await Attachment.get(att_id)
    if not attachment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="附件不存在"
        )

    file_path = os.path.join(settings.FILE_ATTACHMENTS_DIR, attachment.stored_filename)
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="實體檔案不存在於伺服器上"
        )

    # Starlette FileResponse 會自動以 UTF-8 方式處理中文檔名 (RFC 5987)
    return FileResponse(
        path=file_path,
        filename=attachment.original_filename,
        media_type=attachment.content_type or "application/octet-stream"
    )
