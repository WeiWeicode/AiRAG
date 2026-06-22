from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from beanie import Document, Indexed, PydanticObjectId

class SourceChunkMetadata(BaseModel):
    filename: Optional[str] = None
    page: Optional[int] = None
    section: Optional[str] = None
    chunk_index: Optional[int] = None

class SourceChunk(BaseModel):
    chunk_id: str
    content: str
    metadata: SourceChunkMetadata = Field(default_factory=SourceChunkMetadata)
    score: float
    distance: Optional[float] = None

class ChatMessage(Document):
    session_id: PydanticObjectId
    role: str  # "user" | "assistant"
    content: str
    source_chunks: Optional[List[SourceChunk]] = None
    thinking_content: Optional[str] = None
    token_count: Optional[int] = None
    elapsed_ms: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "chat_messages"
        indexes = [
            [("session_id", 1), ("created_at", 1)]
        ]
