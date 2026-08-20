import os
import time
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple

from config import settings
from models.knowledge_base import KnowledgeBase
from services.qdrant_service import QdrantService

logger = logging.getLogger("airag.image_audit")

class ImageAuditVerifyError(Exception):
    """複驗階段有 Collection 掃不動，無法證明檔案是孤兒，整批中止不刪。"""

class ImageAuditService:
    """
    比對「Qdrant 內所有 Collection 的圖片段落」與「地端 FileAttachments/image 資料夾」，
    找出孤兒檔（磁碟有、無 point 引用）與遺失檔（有 point 引用、磁碟無檔），並可清理孤兒檔。

    兩邊會不一致的已知成因：刪除知識庫時 delete_collection() 不清圖片、ingest 在 upsert 前失敗
    留下已落地的新圖、上傳後未向量化，以及 _cleanup_orphaned_image_files() 只查單一 Collection
    造成的跨知識庫誤刪。
    """

    _cache: Optional[Dict[str, Any]] = None
    _cache_expires_at: float = 0.0
    _CACHE_TTL = 60  # 秒，避免連點重新整理就對 Qdrant 打全庫 scroll

    @classmethod
    def get_image_dir(cls) -> str:
        return os.path.abspath(
            os.path.join(settings.FILE_ATTACHMENTS_DIR, settings.FILE_ATTACHMENTS_IMAGE_SUBDIR)
        )

    @classmethod
    def _is_safe_filename(cls, filename: str) -> bool:
        """
        僅允許單純檔名：不得為空、不得含路徑分隔字元或 '..'。
        """
        if not filename or not filename.strip():
            return False
        if filename != os.path.basename(filename):
            return False
        if filename in (".", "..") or "/" in filename or "\\" in filename:
            return False
        return True

    @classmethod
    def _resolve_safe_path(cls, image_dir: str, filename: str) -> Optional[str]:
        """
        組出實體路徑並確認落在 image_dir 底下，不合法回傳 None（比照 embedding.py 的路徑驗證）。
        """
        if not cls._is_safe_filename(filename):
            return None
        file_path = os.path.abspath(os.path.join(image_dir, filename))
        if not file_path.startswith(image_dir + os.sep):
            return None
        return file_path

    @classmethod
    def invalidate_cache(cls) -> None:
        cls._cache = None
        cls._cache_expires_at = 0.0

    @classmethod
    def _list_disk_filenames(cls, image_dir: str) -> List[str]:
        """列出 image 資料夾內的實體檔名（不含子目錄）。"""
        if not os.path.isdir(image_dir):
            return []
        return [
            entry for entry in os.listdir(image_dir)
            if os.path.isfile(os.path.join(image_dir, entry))
        ]

    @classmethod
    async def _collect_image_references(
        cls,
        collection_names: List[str],
        kb_map: Dict[str, Dict[str, str]]
    ) -> Tuple[Dict[str, List[Dict[str, Any]]], int, List[Dict[str, str]]]:
        """
        掃過所有 Collection 的圖片段落，回傳 (圖片檔名 -> 引用清單, 圖片段落總數, 掃描錯誤)。
        單一 Collection 失敗不中斷掃描，但會記錄在 errors：只要有 Collection 掃不動就無法判定孤兒。
        """
        refs: Dict[str, List[Dict[str, Any]]] = {}
        errors: List[Dict[str, str]] = []
        image_point_count = 0

        for collection_name in collection_names:
            kb_info = kb_map.get(collection_name, {})
            try:
                async for point_id, payload in QdrantService.iter_all_image_points(collection_name):
                    img_fn = payload.get("image_filename")
                    if not img_fn:
                        continue
                    image_point_count += 1
                    refs.setdefault(img_fn, []).append({
                        "collection": collection_name,
                        "kb_id": kb_info.get("kb_id"),
                        "kb_name": kb_info.get("kb_name"),
                        "point_id": point_id,
                        "filename": payload.get("filename", ""),
                        "page": payload.get("page"),
                        "caption_failed": bool(payload.get("caption_failed", False))
                    })
            except Exception as e:
                logger.warning(f"[ImageAudit] 掃描 Collection '{collection_name}' 失敗: {e}")
                errors.append({"collection": collection_name, "error": str(e)})

        return refs, image_point_count, errors

    @classmethod
    async def scan(cls, refresh: bool = False) -> Dict[str, Any]:
        """
        掃描全部 Collection 的圖片段落與磁碟檔案並比對，回傳分類結果。
        必須掃過所有 Collection 才能判定孤兒：只掃單一知識庫會把其他知識庫仍在使用的圖片誤判為可刪。
        """
        now = time.time()
        if not refresh and cls._cache is not None and now < cls._cache_expires_at:
            return cls._cache

        image_dir = cls.get_image_dir()
        errors: List[Dict[str, str]] = []

        # 1. 建立 collection -> 知識庫 對照表（Mongo 記錄已刪、Collection 還在的殘留也要顯示得出來）
        kb_map: Dict[str, Dict[str, str]] = {}
        try:
            kbs = await KnowledgeBase.find_all().to_list()
            for kb in kbs:
                kb_map[kb.qdrant_collection_name] = {"kb_id": str(kb.id), "kb_name": kb.name}
        except Exception as e:
            logger.error(f"[ImageAudit] 讀取知識庫清單失敗: {e}")
            errors.append({"collection": "-", "error": f"讀取知識庫清單失敗: {e}"})

        # 2. 逐 Collection 收集圖片段落的引用
        collection_names: List[str] = []
        try:
            collection_names = await QdrantService.list_collection_names()
        except Exception as e:
            logger.error(f"[ImageAudit] 取得 Collection 清單失敗: {e}")
            raise

        # 單一 Collection 掃描失敗會記在 errors，供前端停用清理功能
        refs, image_point_count, ref_errors = await cls._collect_image_references(collection_names, kb_map)
        errors.extend(ref_errors)

        # 3. 磁碟端檔案清單
        disk_files: Dict[str, os.stat_result] = {}
        if os.path.isdir(image_dir):
            for entry in os.listdir(image_dir):
                full_path = os.path.join(image_dir, entry)
                try:
                    if os.path.isfile(full_path):
                        disk_files[entry] = os.stat(full_path)
                except OSError as e:
                    logger.warning(f"[ImageAudit] 無法讀取檔案 '{entry}': {e}")
                    errors.append({"collection": "-", "error": f"無法讀取檔案 {entry}: {e}"})
        else:
            logger.warning(f"[ImageAudit] 圖片目錄不存在: {image_dir}")
            errors.append({"collection": "-", "error": f"圖片目錄不存在: {image_dir}"})

        # 4. 集合運算：孤兒檔 / 遺失檔 / 正常
        recent_threshold = now - settings.INGEST_JOB_TIMEOUT
        orphan_files: List[Dict[str, Any]] = []
        matched_files: List[Dict[str, Any]] = []
        orphan_recent_count = 0

        for filename, stat_result in disk_files.items():
            modified_at = datetime.fromtimestamp(stat_result.st_mtime, tz=timezone.utc)
            file_refs = refs.get(filename)
            if file_refs:
                matched_files.append({
                    "image_filename": filename,
                    "size": stat_result.st_size,
                    "modified_at": modified_at,
                    "reference_count": len(file_refs),
                    "references": file_refs
                })
            else:
                # mtime 在保護期內的檔案可能是「圖片已落地、point 尚未寫入」的進行中 ingest 任務產物
                is_recent = stat_result.st_mtime >= recent_threshold
                if is_recent:
                    orphan_recent_count += 1
                orphan_files.append({
                    "image_filename": filename,
                    "size": stat_result.st_size,
                    "modified_at": modified_at,
                    "is_recent": is_recent
                })

        missing_files = [
            {"image_filename": filename, "references": file_refs}
            for filename, file_refs in refs.items()
            if filename not in disk_files
        ]

        orphan_files.sort(key=lambda x: x["modified_at"], reverse=True)
        matched_files.sort(key=lambda x: x["modified_at"], reverse=True)
        missing_files.sort(key=lambda x: x["image_filename"])

        result = {
            "scanned_at": datetime.now(timezone.utc),
            "image_dir": image_dir,
            "recent_protect_seconds": settings.INGEST_JOB_TIMEOUT,
            "summary": {
                "disk_file_count": len(disk_files),
                "referenced_filename_count": len(refs),
                "image_point_count": image_point_count,
                "matched_count": len(matched_files),
                "orphan_file_count": len(orphan_files),
                "orphan_recent_count": orphan_recent_count,
                "missing_file_count": len(missing_files),
                "collection_count": len(collection_names)
            },
            "orphan_files": orphan_files,
            "missing_files": missing_files,
            "matched_files": matched_files,
            "errors": errors
        }

        cls._cache = result
        cls._cache_expires_at = now + cls._CACHE_TTL
        logger.info(
            f"[ImageAudit] 掃描完成：Collection {len(collection_names)} 個、磁碟 {len(disk_files)} 檔、"
            f"引用 {len(refs)} 檔名 / {image_point_count} 段落、孤兒 {len(orphan_files)} 檔"
            f"（近期 {orphan_recent_count} 檔）、遺失 {len(missing_files)} 檔、錯誤 {len(errors)} 筆"
        )
        return result

    @classmethod
    async def cleanup_orphans(
        cls,
        filenames: Optional[List[str]] = None,
        delete_all_orphans: bool = False,
        include_recent: bool = False
    ) -> Dict[str, Any]:
        """
        刪除孤兒圖檔。刪除前一律重新掃過所有 Collection 取得最新引用清單，
        因為掃描結果到使用者按下刪除之間可能已被重新引用（例如期間跑完一次重新向量）。
        只要有 Collection 掃不動就無法證明檔案是孤兒，整批中止不刪（拋 ImageAuditVerifyError）。

        delete_all_orphans=True 會忽略 filenames，改以「磁碟上有、複驗後無任何引用」的全部檔案為對象。
        include_recent=True 才會一併刪除 mtime 落在保護期內的近期檔案（可能是進行中的 ingest 產物）。
        """
        image_dir = cls.get_image_dir()
        collection_names = await QdrantService.list_collection_names()

        # 複驗改成「掃一次全庫建立引用集合」而非逐檔查詢：一鍵清除動輒數千檔，
        # 逐檔 × 逐 Collection 查詢會打出上萬次 Qdrant 請求。
        refs, _, ref_errors = await cls._collect_image_references(collection_names, {})
        if ref_errors:
            detail = "；".join(f"{item['collection']}: {item['error']}" for item in ref_errors)
            raise ImageAuditVerifyError(f"有 Collection 無法掃描，無法確認孤兒狀態，已中止清理：{detail}")

        referenced = set(refs.keys())
        recent_threshold = time.time() - settings.INGEST_JOB_TIMEOUT

        if delete_all_orphans:
            targets = sorted(fn for fn in cls._list_disk_filenames(image_dir) if fn not in referenced)
        else:
            targets = list(filenames or [])

        deleted: List[str] = []
        skipped: List[Dict[str, str]] = []
        failed: List[Dict[str, str]] = []

        for filename in targets:
            file_path = cls._resolve_safe_path(image_dir, filename)
            if file_path is None:
                logger.warning(f"[ImageAudit] 阻擋不合法的檔名: {filename}")
                skipped.append({"filename": filename, "reason": "invalid_filename"})
                continue

            if not os.path.isfile(file_path):
                skipped.append({"filename": filename, "reason": "file_not_found"})
                continue

            if filename in referenced:
                skipped.append({"filename": filename, "reason": "still_referenced"})
                continue

            try:
                if not include_recent and os.stat(file_path).st_mtime >= recent_threshold:
                    # 可能是進行中的 ingest 任務剛落地、point 還沒寫入的圖片
                    skipped.append({"filename": filename, "reason": "recent_file"})
                    continue
            except OSError as e:
                failed.append({"filename": filename, "error": str(e)})
                continue

            try:
                os.remove(file_path)
                deleted.append(filename)
            except Exception as e:
                logger.error(f"[ImageAudit] 刪除孤兒圖檔 '{filename}' 失敗: {e}")
                failed.append({"filename": filename, "error": str(e)})

        if deleted:
            cls.invalidate_cache()

        logger.info(
            f"[ImageAudit] 清理完成（delete_all_orphans={delete_all_orphans}, include_recent={include_recent}）："
            f"對象 {len(targets)} 檔、刪除 {len(deleted)} 檔、略過 {len(skipped)} 檔、失敗 {len(failed)} 檔"
        )

        return {
            "message": f"清理完成：刪除 {len(deleted)} 筆、略過 {len(skipped)} 筆、失敗 {len(failed)} 筆",
            "deleted": deleted,
            "skipped": skipped,
            "failed": failed
        }
