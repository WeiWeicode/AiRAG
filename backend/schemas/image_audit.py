from datetime import datetime
from typing import List, Optional, Any
from pydantic import BaseModel

class ImageReference(BaseModel):
    """單一圖片段落（Qdrant point）對某張實體圖檔的引用資訊。"""
    collection: str
    kb_id: Optional[str] = None
    kb_name: Optional[str] = None
    point_id: str
    filename: str = ""          # 來源文件名稱（PDF/DOCX 檔名）
    page: Optional[Any] = None
    caption_failed: bool = False

class OrphanFileItem(BaseModel):
    """磁碟上存在、但沒有任何 Qdrant point 引用的圖片檔。"""
    image_filename: str
    size: int
    modified_at: datetime
    is_recent: bool = False     # mtime 落在保護期內，可能是進行中的 ingest 任務產物

class MissingFileItem(BaseModel):
    """Qdrant 仍有 point 引用、但磁碟上已不存在的圖片檔。"""
    image_filename: str
    references: List[ImageReference]

class MatchedFileItem(BaseModel):
    """兩邊都存在的正常圖片檔。"""
    image_filename: str
    size: int
    modified_at: datetime
    reference_count: int
    references: List[ImageReference]

class ScanErrorItem(BaseModel):
    collection: str
    error: str

class ImageAuditSummary(BaseModel):
    disk_file_count: int
    referenced_filename_count: int
    image_point_count: int
    matched_count: int
    orphan_file_count: int
    orphan_recent_count: int
    missing_file_count: int
    collection_count: int

class ImageAuditScanResponse(BaseModel):
    scanned_at: datetime
    image_dir: str
    recent_protect_seconds: int
    summary: ImageAuditSummary
    orphan_files: List[OrphanFileItem]
    missing_files: List[MissingFileItem]
    matched_files: List[MatchedFileItem]
    errors: List[ScanErrorItem]

class ImageAuditCleanupRequest(BaseModel):
    filenames: List[str] = []
    delete_all_orphans: bool = False   # True 時忽略 filenames，清掉當下複驗仍無引用的全部孤兒檔
    include_recent: bool = False       # True 才會一併刪除 mtime 落在保護期內的近期檔案

class CleanupSkippedItem(BaseModel):
    filename: str
    reason: str

class CleanupFailedItem(BaseModel):
    filename: str
    error: str

class ImageAuditCleanupResponse(BaseModel):
    message: str
    deleted: List[str]
    skipped: List[CleanupSkippedItem]
    failed: List[CleanupFailedItem]
