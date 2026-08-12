import asyncio
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from config import settings
from services.chunking_service import ChunkingService
from services.embedding_service import EmbeddingService
from services.llm_service import LLMService
from services.qdrant_service import QdrantService

logger = logging.getLogger("airag.services.image_caption_repair_service")

# ingest_service / routers.embedding 在圖片描述失敗時寫入的佔位文字前綴，
# 舊資料的 payload 沒有 caption_failed 欄位，只能靠這段文字辨識
CAPTION_FAILED_MARKER = "[圖片描述產生失敗"
MAIN_CONTENT_MARKER = "[主要內容]\n"


class ImageCaptionRepairService:
    """
    重新產生既有圖片段落的 AI 描述：以磁碟上留存的原圖重新呼叫多模態模型，
    成功後用相同 point id 覆蓋該段落（等同刪除舊段落再寫入新描述），失敗則保留原段落不動。
    """

    @staticmethod
    def is_caption_failed(payload: Dict[str, Any]) -> bool:
        if payload.get("caption_failed") is True:
            return True
        return CAPTION_FAILED_MARKER in (payload.get("content") or "")

    @staticmethod
    def _resolve_image_path(image_filename: str) -> str:
        """
        由 payload 的 image_filename 組出實際圖片路徑。只取 basename，
        避免 payload 內容被竄改時造成路徑穿越。
        """
        safe_name = os.path.basename(image_filename or "")
        if not safe_name:
            raise ValueError("此段落沒有 image_filename，無法取回原始圖片")
        path = os.path.join(
            settings.FILE_ATTACHMENTS_DIR, settings.FILE_ATTACHMENTS_IMAGE_SUBDIR, safe_name
        )
        if not os.path.isfile(path):
            raise FileNotFoundError(f"找不到原始圖片檔案 {safe_name}，無法重新產生描述")
        return path

    @staticmethod
    def _build_context_hint(payload: Dict[str, Any]) -> str:
        section = (payload.get("section") or "").strip()
        if section:
            return section
        page = payload.get("page")
        if page:
            return f"第 {page} 頁"
        return ""

    @staticmethod
    def _replace_main_content(original_content: str, new_description: str) -> str:
        """
        只替換結構化前綴 `[主要內容]` 之後的描述本文，保留原本的
        `[檔案名稱]` / `[段落編號]` / `[分類標籤]` 前綴，避免與 ingest 寫入格式不一致。
        """
        idx = original_content.find(MAIN_CONTENT_MARKER)
        if idx == -1:
            return new_description
        return original_content[:idx + len(MAIN_CONTENT_MARKER)] + new_description

    @classmethod
    async def repair(
        cls,
        collection_name: str,
        filename: Optional[str] = None,
        point_ids: Optional[List[str]] = None,
        only_failed: bool = True,
        app_id: Optional[str] = None,
        doc_type: Optional[str] = None,
        source_id: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        重新產生圖片描述。`point_ids` 指定要修復的段落；未指定時以 `filename` 或
        (`app_id`, `doc_type`, `source_id`) 掃出該文件的所有圖片段落（外部 ingest 進來的
        文件請用後者，理由見 QdrantService.get_image_points）。
        `only_failed` 為 True 時只處理描述失敗的段落。
        回傳處理統計與逐筆結果，呼叫端負責 invalidate metadata cache。
        """
        targets = await QdrantService.get_image_points(
            collection_name,
            filename=filename,
            point_ids=point_ids,
            app_id=app_id,
            doc_type=doc_type,
            source_id=source_id
        )

        details: List[Dict[str, Any]] = []
        pending: List[Dict[str, Any]] = []

        for target in targets:
            payload = target["payload"]
            point_id = target["point_id"]
            if payload.get("chunk_type") != "image":
                details.append({"point_id": point_id, "status": "skipped", "message": "非圖片段落"})
                continue
            if only_failed and not cls.is_caption_failed(payload):
                details.append({"point_id": point_id, "status": "skipped", "message": "描述未失敗，無須重新產生"})
                continue
            pending.append(target)

        if not pending:
            return {
                "total": len(targets),
                "repaired_count": 0,
                "failed_count": 0,
                "skipped_count": len(details),
                "details": details
            }

        semaphore = asyncio.Semaphore(settings.IMAGE_CAPTION_CONCURRENCY)

        async def regenerate_one(target: Dict[str, Any]) -> Dict[str, Any]:
            payload = target["payload"]
            point_id = target["point_id"]
            image_filename = payload.get("image_filename") or ""
            try:
                image_path = cls._resolve_image_path(image_filename)
                with open(image_path, "rb") as f:
                    image_bytes = f.read()

                ext = os.path.splitext(image_path)[1].lstrip(".").lower() or "png"
                mime_type = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"

                async with semaphore:
                    description, truncated = await LLMService.describe_image_with_retry(
                        image_bytes=image_bytes,
                        mime_type=mime_type,
                        context_hint=cls._build_context_hint(payload)
                    )
                if not description.strip():
                    raise ValueError("模型回傳空白描述")
                return {
                    "point_id": point_id,
                    "status": "repaired",
                    "image_filename": image_filename,
                    "description": description,
                    "caption_truncated": truncated
                }
            except Exception as e:
                logger.error(
                    f"[ImageCaptionRepair] 重新產生描述失敗 point_id={point_id} "
                    f"image={image_filename}: {type(e).__name__}: {e!r}"
                )
                return {
                    "point_id": point_id,
                    "status": "failed",
                    "image_filename": image_filename,
                    "message": f"{type(e).__name__}: {e}"
                }

        results = await asyncio.gather(*[regenerate_one(t) for t in pending])

        payload_by_point_id = {t["point_id"]: t["payload"] for t in pending}
        repaired_ids: List[str] = []
        repaired_payloads: List[Dict[str, Any]] = []
        repaired_texts: List[str] = []

        for result in results:
            if result["status"] != "repaired":
                details.append(result)
                continue

            point_id = result["point_id"]
            original_payload = payload_by_point_id[point_id]
            new_content = cls._replace_main_content(
                original_payload.get("content") or "", result["description"]
            )
            new_payload = {
                **original_payload,
                "content": new_content,
                "token_count": ChunkingService.estimate_tokens(new_content),
                "char_count": len(new_content),
                "caption_failed": False,
                "caption_truncated": result["caption_truncated"],
                "caption_repaired_at": datetime.utcnow().isoformat()
            }
            repaired_ids.append(point_id)
            repaired_payloads.append(new_payload)
            repaired_texts.append(new_content)
            details.append({
                "point_id": point_id,
                "status": "repaired",
                "image_filename": result["image_filename"],
                "caption_truncated": result["caption_truncated"],
                "description_preview": result["description"][:200]
            })

        if repaired_ids:
            vectors = await EmbeddingService.get_embeddings_batch(repaired_texts)
            # 沿用原 point id upsert，Qdrant 會整筆覆蓋 payload 與向量，
            # 等同刪除原本的失敗段落再寫入新描述，chunk_count 因此不需調整
            await QdrantService.upsert_chunks(
                collection_name, repaired_payloads, vectors, point_ids=repaired_ids
            )
            logger.info(
                f"[ImageCaptionRepair] collection='{collection_name}' 已重新產生 "
                f"{len(repaired_ids)} 個圖片段落的描述。"
            )

        failed_count = sum(1 for d in details if d["status"] == "failed")
        skipped_count = sum(1 for d in details if d["status"] == "skipped")
        return {
            "total": len(targets),
            "repaired_count": len(repaired_ids),
            "failed_count": failed_count,
            "skipped_count": skipped_count,
            "details": details
        }
