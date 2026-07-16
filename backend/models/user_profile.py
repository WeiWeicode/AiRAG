from datetime import datetime
from beanie import Document
from pydantic import Field

JOB_TITLE_LEVELS = {
    "一般人員": 10,
    "組長": 8,
    "課長": 7,
    "經理": 6,
    "總經理": 4,
}

class UserProfile(Document):
    name: str
    department: str
    job_title: str
    level: int
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "users"
        indexes = ["department", "-created_at"]
