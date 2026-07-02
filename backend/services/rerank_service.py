import httpx
import json
import logging
from typing import List, Dict, Any
from config import settings

logger = logging.getLogger("airag.rerank")

class RerankService:
    """
    借用既有地端 Instruct LLM（Qwen3VL-8B-Instruct）對 RRF 融合後的候選片段做相關性重排序，
    彌補 RRF 只看排名、不看實際語意相關程度的限制。任何失敗皆優雅降級為保留原始順序，不中斷檢索流程。
    """
    MAX_CANDIDATES = 20
    CONTENT_PREVIEW_LEN = 500

    @classmethod
    async def rerank(cls, query: str, candidates: List[Dict[str, Any]], top_k: int) -> List[Dict[str, Any]]:
        if not candidates or len(candidates) <= top_k:
            return candidates

        pool = candidates[:cls.MAX_CANDIDATES]

        items_desc = []
        for idx, item in enumerate(pool):
            content = (item.get("content") or "")[:cls.CONTENT_PREVIEW_LEN]
            filename = item.get("metadata", {}).get("filename", "unknown")
            items_desc.append(f"[{idx}] 檔案：{filename}\n內容：{content}")

        system_prompt = (
            "你是專業的檢索結果重排序助手。以下提供使用者問題與多筆候選檢索片段，"
            "請依據每筆片段與問題的實際相關性進行排序（最相關排最前）。\n"
            "只能輸出符合以下 Schema 的單一 JSON，不要包含任何額外文字或 Markdown：\n"
            "{\"ranking\": [<候選編號，按相關性由高到低排序>]}\n"
            "ranking 必須包含所有候選編號各一次，不可遺漏或新增編號。"
        )
        user_prompt = f"問題：{query}\n\n候選片段：\n" + "\n\n".join(items_desc)

        url = f"{settings.DENSE_VECTOR_LLAMACPP_BASE_URL.rstrip('/')}/v1/chat/completions"
        payload = {
            "model": settings.DENSE_VECTOR_INSTRUCT_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.1,
            "max_tokens": 256,
            "response_format": {"type": "json_object"}
        }

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                result = response.json()
                content = result["choices"][0]["message"]["content"].strip()

                if content.startswith("```"):
                    lines = content.split("\n")
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].startswith("```"):
                        lines = lines[:-1]
                    content = "\n".join(lines).strip()

                parsed = json.loads(content)
                ranking = parsed.get("ranking", [])

                valid_indices = [i for i in ranking if isinstance(i, int) and 0 <= i < len(pool)]
                # 補上任何遺漏的候選編號（保底，確保候選不會憑空消失）
                seen = set(valid_indices)
                for i in range(len(pool)):
                    if i not in seen:
                        valid_indices.append(i)

                reranked = [pool[i] for i in valid_indices]
                logger.info(f"LLM rerank 完成：候選 {len(pool)} 筆重排序後取前 {top_k} 筆。")
                return reranked[:top_k]
        except Exception as e:
            logger.warning(f"LLM rerank 失敗，降級為保留原始順序: {e}")
            return candidates[:top_k]
