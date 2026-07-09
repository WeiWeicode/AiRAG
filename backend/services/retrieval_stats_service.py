import logging
from typing import Any, Dict, List, Optional

from models.retrieval_stats import RetrievalStats
from config import settings

logger = logging.getLogger("airag.retrieval_stats")

class RetrievalStatsService:
    """
    以 best-effort 方式記錄每次檢索的命中統計，供檢索命中分析儀表板聚合使用。
    寫入失敗絕不拋出例外，呼叫端（rag.py）另有 try/except 包裹，這裡的例外處理是雙重保險。
    """

    @classmethod
    async def record(
        cls,
        knowledge_base_id: Optional[str],
        search_type: str,
        question: str,
        top_k: int,
        score_threshold: float,
        raw_results: List[Dict[str, Any]],
        elapsed_ms: Optional[int] = None,
        session_id: Optional[str] = None
    ) -> None:
        if not settings.RETRIEVAL_STATS_ENABLED:
            return

        try:
            # 讀 semantic_score（而非原始 score）：qdrant_service.py 已統一為所有查詢法/分支
            # 補上此欄位（RRF 分支重算 cosine、純向量分支直接沿用 score），故此處不需再依
            # search_type 分流計算方式，見 NewFeaturesPlan_RRFScoreThresholdMismatchPlan.md
            scores = [item.get("semantic_score", 0.0) for item in raw_results]
            hit_count = sum(1 for s in scores if s >= score_threshold)
            stats = RetrievalStats(
                knowledge_base_id=knowledge_base_id,
                search_type=search_type,
                question=question,
                top_k=top_k,
                score_threshold=score_threshold,
                retrieved_scores=scores,
                hit_count=hit_count,
                total_candidates=len(raw_results),
                avg_score=(sum(scores) / len(scores)) if scores else None,
                min_score=min(scores) if scores else None,
                max_score=max(scores) if scores else None,
                elapsed_ms=elapsed_ms,
                session_id=session_id
            )
            await stats.insert()
        except Exception as e:
            logger.warning(f"[RetrievalStats] 統計寫入失敗（不影響本次對話流程）: {e}")
