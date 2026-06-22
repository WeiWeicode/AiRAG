from datetime import datetime
from typing import Optional
from beanie import Document, Indexed

class KnowledgeBase(Document):
    name: str
    description: Optional[str] = None
    qdrant_collection_name: Indexed(str, unique=True)
    embedding_model: str = "Qwen3-Embedding-8B-Q8_0.gguf"
    chunk_count: int = 0
    created_by: Optional[str] = None
    created_at: datetime = datetime.utcnow()
    updated_at: datetime = datetime.utcnow()

    class Settings:
        name = "knowledge_bases"
        indexes = [
            "name",
            "-created_at"
        ]
