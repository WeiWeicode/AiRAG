from datetime import datetime
from beanie import Document
from pydantic import Field

class DatabaseConfig(Document):
    name: str
    db_type: str  # "sqlserver" or "oracle"
    host: str
    port: int
    database: str
    username: str
    password: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "database_configs"
