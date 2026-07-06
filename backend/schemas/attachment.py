from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class AttachmentResponse(BaseModel):
    id: str
    knowledge_base_id: str
    original_filename: str
    description: str
    has_extracted_content: bool = False
    extraction_error: Optional[str] = None
    tags: List[str]
    classes: List[str]
    content_type: Optional[str] = None
    size: int
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        json_encoders = {
            datetime: lambda dt: dt.isoformat()
        }

class AttachmentListResponse(BaseModel):
    items: List[AttachmentResponse]
    total: int
