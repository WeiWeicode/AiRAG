import json
import logging
from datetime import datetime
from typing import Any, Dict

from beanie import PydanticObjectId

from config import settings
from models.app_registration import AppRegistration
from models.knowledge_base import KnowledgeBase
from services.app_content_client import AppContentClient
from services.chunking_service import ChunkingService
from services.document_parser import DocumentParser
from services.embedding_service import EmbeddingService
from services.qdrant_service import QdrantService
from services.ingest_report_service import IngestReportService

logger = logging.getLogger("airag.services.ingest_service")


class IngestService:
    """
    多應用 RAG 同步的核心處理邏輯（見 MULTI_APP_RAG_SYNC_PLAN.md），由 arq worker
    (worker.py 的 process_ingest_task) 呼叫：拉取內容、切分、embedding、寫入 Qdrant、回報進度。
    """

    @classmethod
    async def process(cls, payload: Dict[str, Any]) -> None:
        app_id = payload["app_id"]
        doc_type = payload["doc_type"]
        source_id = payload["source_id"]
        target_version = payload["target_version"]
        action = payload.get("action", "upsert")
        knowledge_base_id = payload["knowledge_base_id"]
        title = payload.get("title")
        callback_url = payload.get("callback_url")

        app_reg = await AppRegistration.find_one(AppRegistration.app_id == app_id)
        if not app_reg or not app_reg.is_active:
            logger.error(f"[IngestService] app_id='{app_id}' 未登錄或已停用，任務中止")
            return

        kb = await KnowledgeBase.get(PydanticObjectId(knowledge_base_id))
        if not kb:
            logger.error(f"[IngestService] knowledgeBaseId='{knowledge_base_id}' 不存在，任務中止")
            await IngestReportService.report(
                app_reg, callback_url=callback_url, source_type=doc_type, source_id=source_id,
                target_version=target_version, title=title, status="failed",
                error_message="knowledgeBaseId 對應的知識庫不存在"
            )
            return

        await IngestReportService.report(
            app_reg, callback_url=callback_url, source_type=doc_type, source_id=source_id,
            target_version=target_version, title=title, status="processing"
        )

        try:
            if action == "delete":
                await cls._process_delete(app_reg, kb, doc_type, source_id)
                await IngestReportService.report(
                    app_reg, callback_url=callback_url, source_type=doc_type, source_id=source_id,
                    target_version=target_version, title=title, status="completed", progress=100,
                    synced_version=target_version
                )
                return

            filename, synced_version = await cls._process_upsert(
                app_reg, kb, app_id=app_id, doc_type=doc_type, source_id=source_id,
                title=title, target_version=target_version
            )
            await IngestReportService.report(
                app_reg, callback_url=callback_url, source_type=doc_type, source_id=source_id,
                target_version=target_version, title=filename, status="completed", progress=100,
                synced_version=synced_version
            )
        except Exception as e:
            logger.error(f"[IngestService] 處理 app_id='{app_id}' doc_type='{doc_type}' source_id='{source_id}' 失敗: {e}")
            await IngestReportService.report(
                app_reg, callback_url=callback_url, source_type=doc_type, source_id=source_id,
                target_version=target_version, title=title, status="failed", error_message=str(e)
            )

    @classmethod
    async def _process_delete(cls, app_reg: AppRegistration, kb: KnowledgeBase, doc_type: str, source_id: Any) -> None:
        deleted = await QdrantService.delete_by_app_source(kb.qdrant_collection_name, app_reg.app_id, doc_type, source_id)
        if deleted:
            kb.chunk_count = max(0, kb.chunk_count - deleted)
            await kb.save()
            QdrantService.invalidate_metadata_cache(kb.qdrant_collection_name)

    @classmethod
    async def _process_upsert(
        cls, app_reg: AppRegistration, kb: KnowledgeBase, *, app_id: str, doc_type: str,
        source_id: Any, title: str, target_version: int
    ):
        """
        拉取內容、切分、embedding 後寫入 Qdrant，回傳 (filename, version) 供回報使用。
        內容端點路由規則：doc_type == "attachment_file" 走附件二進位端點，其餘走文字/文章端點
        （兩份範例文件皆以此值區分，見 MULTI_APP_RAG_SYNC_PLAN.md 2.1、2.2 節）。
        """
        if doc_type == "attachment_file":
            content_bytes, headers = await AppContentClient.fetch_attachment(app_reg, source_id)
            filename = title or f"{app_id}_{source_id}"
            text, _pages, _chars = DocumentParser.parse_file(filename, content_bytes)
            version = int(headers.get("x-doc-version") or target_version)
            updated_date = headers.get("x-doc-updated-at") or datetime.utcnow().isoformat()
            is_public = (headers.get("x-doc-is-public") or "false").lower() == "true"
            access_dept = headers.get("x-doc-access-dept") or None
            access_level_raw = headers.get("x-doc-access-level")
            access_level = int(access_level_raw) if access_level_raw not in (None, "") else None
            try:
                access_members = json.loads(headers.get("x-doc-access-members") or "[]")
            except (json.JSONDecodeError, TypeError):
                access_members = []
        else:
            doc = await AppContentClient.fetch_doc(app_reg, source_id)
            text = doc.get("content") or ""
            filename = doc.get("title") or title or f"{app_id}_{source_id}"
            version = doc.get("version", target_version)
            updated_date = doc.get("updatedAt") or datetime.utcnow().isoformat()
            perms = doc.get("permissions") or {}
            is_public = bool(perms.get("isPublic", False))
            access_dept = perms.get("accessDept")
            access_level = perms.get("accessLevel")
            access_members = perms.get("accessMembers") or []

        if not text or not text.strip():
            raise ValueError("拉取到的內容為空，無法切分")

        pieces = ChunkingService.split_text(text, settings.DEFAULT_CHUNK_SIZE, settings.DEFAULT_CHUNK_OVERLAP)
        if not pieces:
            raise ValueError("內容切分後沒有任何 chunk")

        texts = [p["content"] for p in pieces]
        vectors = await EmbeddingService.get_embeddings_batch(texts)

        parent_id = f"{app_id}:{doc_type}:{source_id}"
        total_chunks = len(pieces)
        now_iso = datetime.utcnow().isoformat()

        chunks_payload = []
        for idx, piece in enumerate(pieces):
            chunks_payload.append({
                "content": piece["content"],
                "filename": filename,
                "page": 1,
                "section": "",
                "chunk_index": idx,
                "token_count": piece["token_count"],
                "char_count": piece["char_count"],
                "source": f"external_ingest_{app_id}",
                "tags": [],
                "class": [],
                "links_to": [],
                "app_id": app_id,
                "doc_type": doc_type,
                "source_id": source_id,
                "parent_id": parent_id,
                "version": version,
                "updated_date": updated_date,
                "is_public": is_public,
                "access_dept": access_dept,
                "access_level": access_level,
                "access_members": access_members,
                "total_chunks": total_chunks,
                "created_at": now_iso
            })

        deleted = await QdrantService.delete_by_app_source(kb.qdrant_collection_name, app_id, doc_type, source_id)
        inserted = await QdrantService.upsert_chunks(kb.qdrant_collection_name, chunks_payload, vectors)

        kb.chunk_count = max(0, kb.chunk_count - deleted + inserted)
        await kb.save()
        QdrantService.invalidate_metadata_cache(kb.qdrant_collection_name)

        return filename, version
