from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from beanie import Document, PydanticObjectId

class DatasetItem(BaseModel):
    question: str
    ground_truth: str
    relevant_contexts: List[str] = Field(default_factory=list)
    source_feedback_id: Optional[PydanticObjectId] = None

class TestDataset(Document):
    name: str
    description: Optional[str] = None
    items: List[DatasetItem] = Field(default_factory=list)
    item_count: int = 0
    created_by: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "test_datasets"
        indexes = [
            "name",
            "-created_at"
        ]
