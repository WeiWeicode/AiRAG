from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from beanie import Document, PydanticObjectId

class EvalParams(BaseModel):
    temperature: float = 0.3
    top_k: int = 5
    score_threshold: float = 0.7
    max_tokens: Optional[int] = 1024
    search_type: Optional[str] = "vector"

class EvalMetrics(BaseModel):
    faithfulness: float = 0.0
    answer_relevancy: float = 0.0
    context_precision: float = 0.0
    context_recall: float = 0.0

class EvalDetail(BaseModel):
    question: str
    ground_truth: str
    generated_answer: str
    retrieved_contexts: List[str] = Field(default_factory=list)
    scores: EvalMetrics = Field(default_factory=EvalMetrics)
    db_query_note: Optional[str] = None  # 語義資料庫查詢法專用：記錄自動選取的設定檔/SQL 或失敗原因

class EvalReport(Document):
    dataset_id: PydanticObjectId
    dataset_name: str
    knowledge_base_id: Optional[str] = None
    model: str = "Qwen3.6-35B-A3B-FP8"
    params: EvalParams = Field(default_factory=EvalParams)
    summary: EvalMetrics = Field(default_factory=EvalMetrics)
    details: List[EvalDetail] = Field(default_factory=list)
    status: str = "pending"  # "pending" | "running" | "completed" | "failed"
    created_by: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None

    class Settings:
        name = "eval_reports"
        indexes = [
            "dataset_id",
            "status",
            "-created_at"
        ]
