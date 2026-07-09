from datetime import datetime
from typing import Optional, List
from beanie import Document
from pydantic import Field

class RetrievalStats(Document):
    knowledge_base_id: Optional[str] = None
    search_type: str
    question: str
    top_k: int
    score_threshold: float
    retrieved_scores: List[float] = Field(default_factory=list)  # 本次所有候選片段的 semantic_score（與 score_threshold 同尺度，非原始 RRF score）
    hit_count: int = 0            # semantic_score >= score_threshold 的筆數
    total_candidates: int = 0     # 本次檢索到的候選總數（去重合併後）
    avg_score: Optional[float] = None
    min_score: Optional[float] = None
    max_score: Optional[float] = None
    elapsed_ms: Optional[int] = None   # 檢索耗時（不含最終 LLM 生成時間）
    session_id: Optional[str] = None   # 選填，供未來需要時關聯回具體對話
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "retrieval_stats"
        indexes = [
            "knowledge_base_id",
            "search_type",
            "-created_at",
            [("knowledge_base_id", 1), ("created_at", -1)]
        ]
