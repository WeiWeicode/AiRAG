from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from beanie import Document, Indexed

class ChatParams(BaseModel):
    model: str = "Qwen3.6-35B-A3B-FP8"
    temperature: float = 0.7
    top_p: float = 0.9
    max_tokens: int = 2048
    top_k: int = 5
    score_threshold: float = 0.7

class ChatSession(Document):
    title: Optional[str] = None
    knowledge_base_id: Optional[str] = None  # 對應的知識庫 ID (可用 string)
    params: ChatParams = Field(default_factory=ChatParams)
    created_by: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "chat_sessions"
        indexes = [
            "-created_at",
            "created_by"
        ]
