import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from models.retrieval_stats import RetrievalStats
from models.knowledge_base import KnowledgeBase
from utils.security import get_current_user
from config import settings

logger = logging.getLogger("airag.dashboard_router")
router = APIRouter(prefix="/dashboard", tags=["Dashboard"], dependencies=[Depends(get_current_user)])


class KnowledgeBaseScoreItem(BaseModel):
    knowledge_base_id: Optional[str] = None
    knowledge_base_name: Optional[str] = None
    avg_score: Optional[float] = None
    total_queries: int = 0


class RetrievalStatsSummaryResponse(BaseModel):
    period_days: int
    total_queries: int
    zero_hit_count: int
    zero_hit_rate: float
    avg_score: Optional[float] = None
    by_knowledge_base: List[KnowledgeBaseScoreItem] = []


class ZeroHitQuestionItem(BaseModel):
    id: str
    question: str
    knowledge_base_id: Optional[str] = None
    knowledge_base_name: Optional[str] = None
    search_type: str
    created_at: datetime


class ZeroHitQuestionsResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[ZeroHitQuestionItem]


async def _build_kb_name_map() -> Dict[str, str]:
    """
    記憶體 ID→Name 對照表，避免對 retrieval_stats 這種獨立小型 collection 使用 $lookup 聯表。
    """
    kbs = await KnowledgeBase.find_all().to_list()
    return {str(kb.id): kb.name for kb in kbs}


def _resolve_kb_name(kb_id: Optional[str], kb_map: Dict[str, str]) -> Optional[str]:
    if not kb_id:
        return None
    return kb_map.get(kb_id, "(已刪除)")


@router.get("/retrieval-stats/summary", response_model=RetrievalStatsSummaryResponse)
async def get_retrieval_stats_summary(days: Optional[int] = Query(None, ge=1)):
    """
    回傳近 N 天的檢索命中統計聚合摘要（總檢索次數、無命中比例、平均分數、依知識庫分組）。
    """
    period_days = days if days is not None else settings.DASHBOARD_STATS_DEFAULT_PERIOD_DAYS
    cutoff = datetime.utcnow() - timedelta(days=period_days)
    try:
        pipeline = [
            {"$match": {"created_at": {"$gte": cutoff}}},
            {"$facet": {
                "overall": [
                    {"$group": {
                        "_id": None,
                        "total_queries": {"$sum": 1},
                        "zero_hit_count": {"$sum": {"$cond": [{"$eq": ["$hit_count", 0]}, 1, 0]}},
                        "avg_score": {"$avg": "$avg_score"}
                    }}
                ],
                "by_kb": [
                    {"$group": {
                        "_id": "$knowledge_base_id",
                        "avg_score": {"$avg": "$avg_score"},
                        "total_queries": {"$sum": 1}
                    }}
                ]
            }}
        ]
        # 不用 RetrievalStats.aggregate()：本專案固定的 beanie/motor/pymongo 版本組合下，
        # 該 wrapper 內部對 aggregate cursor 多 await 了一次會拋 TypeError（與 models/mongodb.py
        # 頂部 append_metadata 補丁屬同一類版本相容性問題），改直接操作底層 collection 繞開。
        cursor = RetrievalStats.get_pymongo_collection().aggregate(pipeline)
        result = await cursor.to_list(length=None)
        facet_result = result[0] if result else {"overall": [], "by_kb": []}
        overall = facet_result["overall"][0] if facet_result.get("overall") else {}

        total_queries = overall.get("total_queries", 0)
        zero_hit_count = overall.get("zero_hit_count", 0)
        zero_hit_rate = (zero_hit_count / total_queries) if total_queries else 0.0

        kb_map = await _build_kb_name_map()
        by_knowledge_base = [
            KnowledgeBaseScoreItem(
                knowledge_base_id=row.get("_id"),
                knowledge_base_name=_resolve_kb_name(row.get("_id"), kb_map),
                avg_score=row.get("avg_score"),
                total_queries=row.get("total_queries", 0)
            )
            for row in facet_result.get("by_kb", [])
        ]

        return RetrievalStatsSummaryResponse(
            period_days=period_days,
            total_queries=total_queries,
            zero_hit_count=zero_hit_count,
            zero_hit_rate=zero_hit_rate,
            avg_score=overall.get("avg_score"),
            by_knowledge_base=by_knowledge_base
        )
    except Exception as e:
        logger.error(f"Failed to aggregate retrieval stats summary: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"取得檢索命中統計摘要失敗: {str(e)}"
        )


@router.get("/retrieval-stats/zero-hit-questions", response_model=ZeroHitQuestionsResponse)
async def get_zero_hit_questions(
    days: Optional[int] = Query(None, ge=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100)
):
    """
    回傳近 N 天內零命中（hit_count == 0）的問題清單（分頁），供使用者具體檢視是哪些問題查無結果。
    """
    period_days = days if days is not None else settings.DASHBOARD_STATS_DEFAULT_PERIOD_DAYS
    cutoff = datetime.utcnow() - timedelta(days=period_days)
    try:
        query = {"created_at": {"$gte": cutoff}, "hit_count": 0}
        total = await RetrievalStats.find(query).count()

        skip = (page - 1) * page_size
        docs = await RetrievalStats.find(query).sort("-created_at").skip(skip).limit(page_size).to_list()

        kb_map = await _build_kb_name_map()
        items = [
            ZeroHitQuestionItem(
                id=str(doc.id),
                question=doc.question,
                knowledge_base_id=doc.knowledge_base_id,
                knowledge_base_name=_resolve_kb_name(doc.knowledge_base_id, kb_map),
                search_type=doc.search_type,
                created_at=doc.created_at
            )
            for doc in docs
        ]

        return ZeroHitQuestionsResponse(total=total, page=page, page_size=page_size, items=items)
    except Exception as e:
        logger.error(f"Failed to fetch zero-hit questions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"取得零命中問題清單失敗: {str(e)}"
        )
