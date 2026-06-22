from datetime import datetime
from typing import Optional
from beanie import Document

class PromptTemplate(Document):
    name: str
    system_prompt: Optional[str] = None
    user_prompt_template: str
    is_default: bool = False
    created_by: Optional[str] = None
    created_at: datetime = datetime.utcnow()
    updated_at: datetime = datetime.utcnow()

    class Settings:
        name = "prompt_templates"
        indexes = [
            "is_default"
        ]
