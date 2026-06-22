from pydantic import BaseModel
from typing import List, Optional, Union
from datetime import datetime

class SQLServerArticleItem(BaseModel):
    id: str
    title: str
    is_published: bool
    is_public: bool
    access_dept: Optional[str] = None
    access_members: Optional[str] = None
    access_level: Optional[int] = None
    version_number: Optional[Union[int, str]] = None
    created_by: Optional[str] = None
    created_by_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class SQLServerArticlesResponse(BaseModel):
    items: List[SQLServerArticleItem]
    total: int

class SQLServerImportRequest(BaseModel):
    article_id: str
    knowledge_base_id: str
    chunk_size: Optional[int] = 512
    chunk_overlap: Optional[int] = 50
    separator: Optional[str] = "\n\n"

class SQLServerImportResponse(BaseModel):
    knowledge_base_id: str
    inserted_count: int
    elapsed_ms: int
