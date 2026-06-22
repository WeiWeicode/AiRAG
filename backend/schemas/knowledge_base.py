from datetime import datetime
from pydantic import BaseModel
from typing import List, Optional

class KnowledgeBaseCreate(BaseModel):
    name: str
    description: Optional[str] = None

class KnowledgeBaseItem(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    chunk_count: int
    created_at: datetime

class KnowledgeBaseListResponse(BaseModel):
    items: List[KnowledgeBaseItem]
