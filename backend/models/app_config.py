from datetime import datetime
from typing import Any, Optional
from beanie import Document, Indexed

class AppConfig(Document):
    key: Indexed(str, unique=True)
    value: Any
    description: Optional[str] = None
    updated_at: datetime = datetime.utcnow()

    class Settings:
        name = "app_configs"
