from datetime import datetime
from typing import List, Optional
from beanie import Document
from pydantic import Field

class Attachment(Document):
    knowledge_base_id: str          # 關聯 KnowledgeBase._id
    original_filename: str          # 使用者上傳時的原始檔名（可能含中文/特殊字元）
    stored_filename: str            # 落地於 FileAttachments/ 的重新編碼檔名 (uuid4().hex + 副檔名)
    description: str = ""           # 使用者填寫的備註說明（僅供顯示參考，非 AI 讀取附件內容的主要來源）
    extracted_content: Optional[str] = None  # 上傳時自動從檔案解析出的純文字內容，AI 讀取附件內容時優先使用此欄位
    extraction_error: Optional[str] = None   # 自動解析失敗原因（例如不支援的檔案格式），失敗不影響附件上傳/下載
    tags: List[str] = Field(default_factory=list)
    classes: List[str] = Field(default_factory=list)
    content_type: Optional[str] = None
    size: int = 0
    created_by: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "attachments"
        indexes = [
            "knowledge_base_id",
            "-created_at"
        ]
