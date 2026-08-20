import logging

from fastapi import APIRouter, Depends, HTTPException, status

from schemas.image_audit import ImageAuditScanResponse, ImageAuditCleanupRequest, ImageAuditCleanupResponse
from services.image_audit_service import ImageAuditService, ImageAuditVerifyError
from utils.security import get_current_user

logger = logging.getLogger("airag.image_audit_router")
router = APIRouter(prefix="/image-audit", tags=["Image Audit"], dependencies=[Depends(get_current_user)])

@router.get("/scan", response_model=ImageAuditScanResponse)
async def scan_images(refresh: bool = False):
    """
    比對 Qdrant 全部 Collection 的圖片段落與地端 FileAttachments/image 資料夾，
    回傳孤兒檔（磁碟有、無向量引用）、遺失檔（有向量引用、磁碟無檔）與正常檔案清單。
    結果快取 60 秒，傳入 refresh=true 可強制重新掃描。
    """
    try:
        return await ImageAuditService.scan(refresh=refresh)
    except Exception as e:
        logger.error(f"Image audit scan failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"圖片稽核掃描失敗: {str(e)}"
        )

@router.post("/cleanup", response_model=ImageAuditCleanupResponse)
async def cleanup_orphan_images(request: ImageAuditCleanupRequest):
    """
    刪除孤兒圖檔。刪除前會重新掃過所有 Collection 複驗仍無引用，
    仍被引用、或 mtime 落在保護期內（未指定 include_recent）者一律跳過不刪。
    delete_all_orphans=true 時忽略 filenames，改為清除當下複驗仍無引用的全部孤兒檔。
    """
    if not request.delete_all_orphans and not request.filenames:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="請提供要刪除的圖片檔名，或指定 delete_all_orphans=true"
        )

    try:
        return await ImageAuditService.cleanup_orphans(
            filenames=request.filenames,
            delete_all_orphans=request.delete_all_orphans,
            include_recent=request.include_recent
        )
    except ImageAuditVerifyError as e:
        # 有 Collection 掃不動就無法判定孤兒，回 409 讓前端明確顯示原因而非誤以為刪除成功
        logger.warning(f"Image audit cleanup aborted: {e}")
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        logger.error(f"Image audit cleanup failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"清理孤兒圖檔失敗: {str(e)}"
        )
