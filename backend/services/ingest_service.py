import json
import logging
from datetime import datetime
from typing import Any, Dict
from urllib.parse import unquote

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
        if not app_reg:
            logger.error(f"[IngestService] app_id='{app_id}' 未登錄（app_registrations 查無此筆），任務中止")
            return
        if not app_reg.is_active:
            logger.error(f"[IngestService] app_id='{app_id}' 已登錄但為停用狀態（is_active=false），任務中止")
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

            filename, synced_version, caption_failed_count = await cls._process_upsert(
                app_reg, kb, app_id=app_id, doc_type=doc_type, source_id=source_id,
                title=title, target_version=target_version
            )
            if caption_failed_count:
                logger.warning(
                    f"[IngestService] doc_type='{doc_type}' source_id='{source_id}' 切分完成，"
                    f"但有 {caption_failed_count} 張圖片的描述產生失敗，已回報給來源應用"
                )
            await IngestReportService.report(
                app_reg, callback_url=callback_url, source_type=doc_type, source_id=source_id,
                target_version=target_version, title=filename, status="completed", progress=100,
                synced_version=synced_version, caption_failed_count=caption_failed_count
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
        拉取內容、切分、embedding 後寫入 Qdrant，回傳 (filename, version, caption_failed_count) 供回報使用。
        caption_failed_count 讓來源應用（如 KB 的 rag_sync_status）能看出「切分完成但部分圖片描述失敗」，
        否則此情況與完全成功一樣都回報 completed，來源端無從得知。
        內容端點路由規則：doc_type == "attachment_file" 走附件二進位端點，其餘走文字/文章端點
        （兩份範例文件皆以此值區分，見 MULTI_APP_RAG_SYNC_PLAN.md 2.1、2.2 節）。
        預設套用 Parent-Child 大小雙層切分與 PDF/Word 內嵌圖片自動擷取與描述生成。
        """
        content_bytes = None
        extracted_images = []

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
            # 標籤 / 所屬目錄 / 關聯附件（KB 端經 encodeURIComponent 編碼中文字元，需先 unquote 再解析 JSON）
            try:
                doc_tags = json.loads(unquote(headers.get("x-doc-tags") or "[]"))
            except (json.JSONDecodeError, TypeError):
                doc_tags = []
            try:
                doc_class = json.loads(unquote(headers.get("x-doc-class") or "[]"))
            except (json.JSONDecodeError, TypeError):
                doc_class = []
            try:
                doc_links_to = json.loads(unquote(headers.get("x-doc-links-to") or "[]"))
            except (json.JSONDecodeError, TypeError):
                doc_links_to = []
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
            doc_tags = doc.get("tags") or []
            doc_class = doc.get("class") or []
            doc_links_to = doc.get("linksTo") or []

        if not text or not text.strip():
            raise ValueError("拉取到的內容為空，無法切分")

        ext = filename.split(".")[-1].lower()

        # 1. 抽取 PDF/Word 中的圖片並透過 LLM 生成描述
        if content_bytes and ext in ["pdf", "docx", "dotx"]:
            raw_images = []
            if ext == "pdf":
                raw_images = DocumentParser.extract_images_from_pdf(content_bytes)
            elif ext in ["docx", "dotx"]:
                raw_images = DocumentParser.extract_images_from_docx(content_bytes)

            if raw_images:
                import os
                import uuid
                import asyncio
                from schemas.embedding import ExtractedImageItem
                from services.llm_service import LLMService
                from services.markdown_parent_child_chunker import generate_parent_id

                image_dir = os.path.join(settings.FILE_ATTACHMENTS_DIR, settings.FILE_ATTACHMENTS_IMAGE_SUBDIR)
                os.makedirs(image_dir, exist_ok=True)
                caption_semaphore = asyncio.Semaphore(settings.IMAGE_CAPTION_CONCURRENCY)

                async def process_one_image(raw_img: dict) -> ExtractedImageItem:
                    img_bytes = raw_img["image_bytes"]
                    img_ext = raw_img["ext"]
                    stored_filename = f"{uuid.uuid4().hex}.{img_ext}"
                    target_path = os.path.join(image_dir, stored_filename)
                    mime_type = f"image/{img_ext}" if img_ext != "jpg" else "image/jpeg"

                    context_hint = ""
                    page_val = None
                    parent_id_val = None

                    if ext == "pdf":
                        page_val = raw_img["page_number"]
                        context_hint = f"第 {page_val} 頁"
                    elif ext in ["docx", "dotx"]:
                        header_path = raw_img.get("header_path")
                        if header_path:
                            header_vals = [header_path[k] for k in sorted(header_path.keys())]
                            context_hint = " > ".join(header_vals)
                            parent_id_val = generate_parent_id(filename, header_path)

                    caption_failed = False
                    caption_truncated = False
                    description = ""
                    try:
                        async with caption_semaphore:
                            # 內含單張圖片的牆鐘時間上限與自動重試，避免偶發逾時就留下佔位描述
                            description, caption_truncated = await LLMService.describe_image_with_retry(
                                image_bytes=img_bytes,
                                mime_type=mime_type,
                                context_hint=context_hint
                            )
                    except Exception as ex:
                        logger.error(
                            f"[IngestService] Image captioning failed for {stored_filename}: {type(ex).__name__}: {ex!r}"
                        )
                        caption_failed = True
                        description = f"[圖片描述產生失敗：{filename}_img{raw_img.get('image_index', 1)}]"

                    with open(target_path, "wb") as f_out:
                        f_out.write(img_bytes)

                    return ExtractedImageItem(
                        image_filename=stored_filename,
                        description=description,
                        page=page_val,
                        parent_id=parent_id_val,
                        caption_failed=caption_failed,
                        caption_truncated=caption_truncated
                    )

                extracted_images = list(await asyncio.gather(*[process_one_image(img) for img in raw_images]))

        # 2. 進行 Parent-Child 大小雙層切分
        all_chunks_info = []
        idx = 0

        is_4fd = ext == '4fd'
        is_4gl = ext == '4gl'

        if is_4fd:
            from services.parent_child_chunker import parse_4fd_to_parents, slice_4fd_to_children
            parents = parse_4fd_to_parents(text, filename)
            for parent in parents:
                children = slice_4fd_to_children(parent_chunk=parent, source_file=filename)
                start_idx = idx
                end_idx = idx + len(children) - 1
                parent_range = f"{start_idx}~{end_idx}" if len(children) > 1 else str(start_idx)
                for child in children:
                    child_meta = dict(child.get("metadata", {}))
                    child_meta["parent_chunk_index_range"] = parent_range
                    all_chunks_info.append({
                        "content": child["child_content"],
                        "metadata": child_meta,
                        "chunk_type": "text"
                    })
                    idx += 1
        elif is_4gl:
            from services.parent_child_chunker import parse_4gl_to_parents, slice_to_children
            parents = parse_4gl_to_parents(text, filename)
            for parent in parents:
                children = slice_to_children(
                    content=parent["content"],
                    parent_chunk=parent,
                    source_file=filename,
                    child_size=settings.DEFAULT_CHUNK_SIZE,
                    child_overlap=settings.DEFAULT_CHUNK_OVERLAP
                )
                start_idx = idx
                end_idx = idx + len(children) - 1
                parent_range = f"{start_idx}~{end_idx}" if len(children) > 1 else str(start_idx)
                for child in children:
                    child_meta = dict(child.get("metadata", {}))
                    child_meta["parent_chunk_index_range"] = parent_range
                    all_chunks_info.append({
                        "content": child["child_content"],
                        "metadata": child_meta,
                        "chunk_type": "text"
                    })
                    idx += 1
        else:
            from services.markdown_parent_child_chunker import chunk_markdown_content
            children = chunk_markdown_content(
                markdown_content=text,
                filename=filename,
                child_size=settings.DEFAULT_CHUNK_SIZE,
                child_overlap=settings.DEFAULT_CHUNK_OVERLAP,
                use_langchain=True
            )
            parent_to_indices = {}
            for child_idx, child in enumerate(children):
                pid = child["metadata"]["parent_id"]
                if pid not in parent_to_indices:
                    parent_to_indices[pid] = []
                parent_to_indices[pid].append(child_idx)

            for child_idx, child in enumerate(children):
                pid = child["metadata"]["parent_id"]
                indices = parent_to_indices[pid]
                start_idx = indices[0]
                end_idx = indices[-1]
                parent_range = f"{start_idx}~{end_idx}" if len(indices) > 1 else str(start_idx)

                child_meta = dict(child["metadata"])
                child_meta["parent_chunk_index_range"] = parent_range
                child_meta["file_type"] = ext

                all_chunks_info.append({
                    "content": child["child_content"],
                    "metadata": child_meta,
                    "chunk_type": "text"
                })
                idx += 1

        # 3. 處理圖片描述 Chunks
        if extracted_images:
            for img_idx, img_item in enumerate(extracted_images):
                p_id = img_item.parent_id or f"{filename}_img_fallback_{img_idx}"
                img_pieces = ChunkingService.split_text(
                    text=img_item.description,
                    chunk_size=settings.DEFAULT_CHUNK_SIZE,
                    chunk_overlap=settings.DEFAULT_CHUNK_OVERLAP,
                    separator="\n\n"
                )
                if not img_pieces:
                    img_pieces = [{
                        "content": img_item.description,
                        "token_count": ChunkingService.estimate_tokens(img_item.description),
                        "char_count": len(img_item.description)
                    }]

                piece_start = idx
                for piece in img_pieces:
                    all_chunks_info.append({
                        "content": piece["content"],
                        "metadata": {
                            "chunk_type": "image",
                            "image_filename": img_item.image_filename,
                            "page": img_item.page or 1,
                            "filename": filename,
                            "parent_id": p_id,
                            "parent_chunk_index_range": "",
                            "caption_failed": img_item.caption_failed
                        },
                        "chunk_type": "image"
                    })
                    idx += 1
                piece_end = idx - 1
                img_range = f"{piece_start}~{piece_end}" if piece_end > piece_start else str(piece_start)
                for chunk_obj in all_chunks_info[-(piece_end - piece_start + 1):]:
                    chunk_obj["metadata"]["parent_chunk_index_range"] = img_range

        if not all_chunks_info:
            raise ValueError("內容切分後沒有任何 chunk")

        # 自動檢查並在 MongoDB 建立 "圖片" 標籤 (若包含圖片 chunks)
        has_image = any(c.get("chunk_type") == "image" for c in all_chunks_info)
        if has_image:
            try:
                from models.tag import Tag
                existing_tag = await Tag.find_one(Tag.name == "圖片")
                if not existing_tag:
                    await Tag(name="圖片").insert()
                    logger.info("[IngestService] 自動於 MongoDB 建立 '圖片' 標籤")
            except Exception as tag_err:
                logger.error(f"[IngestService] 自動建立 '圖片' 標籤失敗: {tag_err}")

        total_chunks = len(all_chunks_info)
        now_iso = datetime.utcnow().isoformat()
        fallback_parent_id = f"{app_id}:{doc_type}:{source_id}"

        chunks_payload = []
        texts = []

        for chunk_idx, chunk_obj in enumerate(all_chunks_info):
            meta = chunk_obj.get("metadata", {})
            c_type = chunk_obj.get("chunk_type", "text")
            c_tags = []
            if c_type == "image":
                c_tags.append("圖片")
            chunk_tags = list(dict.fromkeys([*doc_tags, *c_tags]))

            p_id = meta.get("parent_id") or fallback_parent_id
            page_val = meta.get("page", 1)

            # 組裝 Prompt 結構化前綴文字
            tags_str = ", ".join(c_tags) if c_tags else "一般"
            structured_content = (
                f"[檔案名稱] {filename}\n"
                f"[段落編號] 第 {chunk_idx + 1} 段\n"
                f"[分類標籤] {tags_str}\n"
                f"[主要內容]\n"
                f"{chunk_obj['content']}"
            )
            texts.append(structured_content)

            payload_item = {
                "content": structured_content,
                "filename": filename,
                "page": page_val,
                "section": meta.get("section", ""),
                "chunk_index": chunk_idx,
                "token_count": ChunkingService.estimate_tokens(structured_content),
                "char_count": len(structured_content),
                "source": f"external_ingest_{app_id}",
                "tags": chunk_tags,
                "class": doc_class,
                "links_to": doc_links_to,
                "app_id": app_id,
                "doc_type": doc_type,
                "source_id": source_id,
                "parent_id": p_id,
                "parent_chunk_index_range": meta.get("parent_chunk_index_range", ""),
                "version": version,
                "updated_date": updated_date,
                "is_public": is_public,
                "access_dept": access_dept,
                "access_level": access_level,
                "access_members": access_members,
                "total_chunks": total_chunks,
                "created_at": now_iso
            }
            if c_type == "image":
                payload_item["chunk_type"] = "image"
                payload_item["image_filename"] = meta.get("image_filename", "")
                # 供「重新產生圖片描述」修復功能篩選出描述失敗的段落
                payload_item["caption_failed"] = bool(meta.get("caption_failed", False))

            chunks_payload.append(payload_item)

        vectors = await EmbeddingService.get_embeddings_batch(texts)

        deleted = await QdrantService.delete_by_app_source(kb.qdrant_collection_name, app_id, doc_type, source_id)
        inserted = await QdrantService.upsert_chunks(kb.qdrant_collection_name, chunks_payload, vectors)

        kb.chunk_count = max(0, kb.chunk_count - deleted + inserted)
        await kb.save()
        QdrantService.invalidate_metadata_cache(kb.qdrant_collection_name)

        caption_failed_count = sum(1 for img in extracted_images if img.caption_failed)
        return filename, version, caption_failed_count
