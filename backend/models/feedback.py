from datetime import datetime
from typing import Optional
from beanie import Document, Indexed, PydanticObjectId
from pydantic import Field

class Feedback(Document):
    chat_message_id: Indexed(str)
    session_id: Optional[str] = None
    question: str
    ai_answer: str
    is_correct: bool
    correct_answer: Optional[str] = None
    error_type: Optional[str] = None  # "hallucination" | "incomplete" | "wrong_source" | "format_issue" | "other"
    note: Optional[str] = None
    exported_to_dataset_id: Optional[PydanticObjectId] = None
    created_by: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "feedbacks"
        indexes = [
            "is_correct",
            "error_type",
            "-created_at"
        ]
