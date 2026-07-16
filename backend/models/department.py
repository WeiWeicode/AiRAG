from datetime import datetime
from beanie import Document, Indexed
from pydantic import Field

class Department(Document):
    name: Indexed(str, unique=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "departments"
