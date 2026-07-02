import logging
from typing import Any, Dict, List, Optional

from models.feedback import Feedback
from config import settings

logger = logging.getLogger("airag.feedback_boost")

class FeedbackBoostService:
    """
    依據歷史人工回饋標註（正確/不正確），對檢索結果進行分數加權調整。
    比對鍵為 filename + chunk_index（而非 Qdrant chunk_id），因為文件重新上傳/切分後
    point id 會變動，filename+chunk_index 較能延續回饋歷史的有效性。任何查詢/計算失敗
    皆優雅降級為保留原始排序，不中斷檢索流程。
    """

    @classmethod
    async def apply_feedback_boost(
        cls,
        results: List[Dict[str, Any]],
        knowledge_base_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        if not results:
            return results

        try:
            keys = set()
            for item in results:
                meta = item.get("metadata", {})
                filename = meta.get("filename")
                chunk_index = meta.get("chunk_index")
                if filename is not None and chunk_index is not None:
                    keys.add((filename, str(chunk_index)))

            if not keys:
                return results

            filenames = list({key[0] for key in keys})
            query: Dict[str, Any] = {"source_chunks.filename": {"$in": filenames}}
            if knowledge_base_id:
                query["knowledge_base_id"] = knowledge_base_id

            feedbacks = await Feedback.find(query).to_list()

            stats: Dict[tuple, Dict[str, int]] = {}
            for fb in feedbacks:
                if not fb.source_chunks:
                    continue
                for sc in fb.source_chunks:
                    key = (sc.filename, str(sc.chunk_index))
                    if key not in keys:
                        continue
                    entry = stats.setdefault(key, {"pos": 0, "neg": 0})
                    if fb.is_correct:
                        entry["pos"] += 1
                    else:
                        entry["neg"] += 1

            if not stats:
                return results

            weight = settings.FEEDBACK_BOOST_WEIGHT
            for item in results:
                meta = item.get("metadata", {})
                key = (meta.get("filename"), str(meta.get("chunk_index")))
                entry = stats.get(key)
                if entry:
                    total = entry["pos"] + entry["neg"]
                    boost = (entry["pos"] - entry["neg"]) / total if total else 0.0
                    item["score"] = item.get("score", 0.0) * (1 + weight * boost)
                    item["feedback_boost"] = boost

            results.sort(key=lambda x: x.get("score", 0.0), reverse=True)
            return results
        except Exception as e:
            logger.warning(f"Feedback boost failed, returning original results: {e}")
            return results
