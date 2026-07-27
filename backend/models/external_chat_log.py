from datetime import datetime
from typing import Any, List, Optional
from beanie import Document, PydanticObjectId
from pydantic import BaseModel, Field

class SourceSummaryItem(BaseModel):
    filename: Optional[str] = None
    chunk_id: Optional[str] = None
    # 啟用 Parent-Child 合併時，QdrantService 會刻意把 metadata.chunk_index 覆寫為父區塊範圍字串
    # （例如 "0~2"），因此不能限定為 int，否則稽核紀錄會驗證失敗。
    # 型別與 schemas/retrieval.py 的 RetrievalMetadata.chunk_index 一致。
    chunk_index: Optional[Any] = None
    score: Optional[float] = None
    semantic_score: Optional[float] = None

class ExternalChatLog(Document):
    api_key_id: Optional[PydanticObjectId] = None
    employee_id: str
    employee_name: str
    department_code: str
    department_name: str
    job_title_name: str
    job_title_level: int
    knowledge_base_id: Optional[str] = None
    search_type: Optional[str] = None
    question: str
    answer: str
    sources_summary: List[SourceSummaryItem] = Field(default_factory=list)
    custom_system_prompt: Optional[str] = None
    elapsed_ms: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "external_chat_logs"
        indexes = ["-created_at", "employee_id", "api_key_id"]
