from datetime import datetime
from typing import Optional
from beanie import Document, Indexed
from pydantic import Field

class Tag(Document):
    name: Indexed(str, unique=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "tags"
