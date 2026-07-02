from datetime import datetime
from typing import Any, List, Optional
from beanie import Document, Indexed, PydanticObjectId
from pydantic import BaseModel, Field

class FeedbackSourceChunk(BaseModel):
    filename: Optional[str] = None
    chunk_index: Optional[Any] = None

class Feedback(Document):
    chat_message_id: Indexed(str)
    session_id: Optional[str] = None
    question: str
    ai_answer: str
    is_correct: bool
    correct_answer: Optional[str] = None
    error_type: Optional[str] = None  # "hallucination" | "incomplete" | "wrong_source" | "format_issue" | "other"
    note: Optional[str] = None
    source_chunks: Optional[List[FeedbackSourceChunk]] = None  # 本次回答引用的來源片段 (filename+chunk_index)，供語義混合回饋查詢法比對
    knowledge_base_id: Optional[str] = None
    exported_to_dataset_id: Optional[PydanticObjectId] = None
    created_by: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "feedbacks"
        indexes = [
            "is_correct",
            "error_type",
            "-created_at",
            "source_chunks.filename"
        ]
