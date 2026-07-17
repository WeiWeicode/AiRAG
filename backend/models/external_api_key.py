from datetime import datetime
from typing import Optional
from beanie import Document, Indexed
from pydantic import Field

class ExternalApiKey(Document):
    name: str
    key_prefix: Indexed(str, unique=True)
    key_hash: str
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_used_at: Optional[datetime] = None

    class Settings:
        name = "external_api_keys"
        indexes = ["-created_at"]
