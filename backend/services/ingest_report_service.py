import os
import asyncio
import logging
from datetime import datetime
from typing import Any, List, Optional

import httpx

from models.app_registration import AppRegistration

logger = logging.getLogger("airag.services.ingest_report_service")


class IngestReportService:
    """
    多應用 RAG 同步的混合回報機制（見 MULTI_APP_RAG_SYNC_PLAN.md 2.1、2.3 節）：
    依 AppRegistration.report_mode 決定要走 Webhook 回呼，還是直連目標 App 的 DB 寫入進度。
    """

    @classmethod
    async def report(
        cls,
        app_reg: AppRegistration,
        *,
        source_type: str,
        source_id: Any,
        target_version: int,
        status: str,
        title: Optional[str] = None,
        callback_url: Optional[str] = None,
        progress: Optional[int] = None,
        error_message: Optional[str] = None,
        synced_version: Optional[int] = None
    ) -> None:
        if app_reg.report_mode == "direct_db":
            await cls._report_direct_db(
                app_reg, source_type=source_type, source_id=source_id, target_version=target_version,
                status=status, progress=progress, error_message=error_message, synced_version=synced_version
            )
        else:
            await cls._report_webhook(
                app_reg, callback_url=callback_url, source_type=source_type, source_id=source_id,
                target_version=target_version, title=title, status=status, progress=progress,
                error_message=error_message, synced_version=synced_version
            )

    @classmethod
    async def _report_webhook(
        cls, app_reg: AppRegistration, *, callback_url: Optional[str], source_type: str, source_id: Any,
        target_version: int, title: Optional[str], status: str, progress: Optional[int],
        error_message: Optional[str], synced_version: Optional[int]
    ) -> None:
        """
        HTTP Webhook 回調（見 2.3 節），POST 至 trigger 請求帶入的 callback_url。
        """
        if not callback_url:
            logger.error(
                f"[IngestReportService] app_id='{app_reg.app_id}' 為 webhook 模式但缺少 callback_url，無法回報進度"
            )
            return

        sync_key = os.getenv(f"{app_reg.app_id.upper()}_RAG_SYNC_KEY")
        body = {
            "appId": app_reg.app_id,
            "docType": source_type,
            "sourceId": source_id,
            "title": title,
            "targetVersion": target_version,
            "status": status,
            "progress": progress,
            "errorMessage": error_message,
            "syncedVersion": synced_version,
            "syncedAt": datetime.utcnow().isoformat()
        }
        headers = {"X-RAG-Sync-Key": sync_key} if sync_key else {}
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(callback_url, json=body, headers=headers)
                resp.raise_for_status()
        except Exception as e:
            logger.error(f"[IngestReportService] Webhook 回報失敗 (app_id='{app_reg.app_id}', url='{callback_url}'): {e}")

    @classmethod
    async def _report_direct_db(
        cls, app_reg: AppRegistration, *, source_type: str, source_id: Any, target_version: int,
        status: str, progress: Optional[int], error_message: Optional[str], synced_version: Optional[int]
    ) -> None:
        """
        直連目標 App 的 SQL Server 寫入進度（僅 report_mode="direct_db" 使用，目前僅 "kb" 適用），
        SQL 語句對應 RAG_SYNC_PLAN.md 6 節第 5 點，含 target_version 防競態條件。
        """
        conn_str = os.getenv(f"{app_reg.app_id.upper()}_DB_CONNECTION_STRING")
        if not conn_str:
            logger.error(
                f"[IngestReportService] app_id='{app_reg.app_id}' 為 direct_db 模式但缺少 "
                f"{app_reg.app_id.upper()}_DB_CONNECTION_STRING 環境變數，無法回報進度"
            )
            return

        def _write():
            import pyodbc
            conn = pyodbc.connect(conn_str, timeout=10)
            try:
                cur = conn.cursor()
                if status == "completed":
                    cur.execute(
                        "UPDATE rag_sync_status SET status=?, progress=?, last_synced_at=GETDATE(), "
                        "last_synced_version=? WHERE source_type=? AND source_id=? AND target_version=?",
                        status, progress if progress is not None else 100, synced_version,
                        source_type, source_id, target_version
                    )
                elif status == "processing":
                    cur.execute(
                        "UPDATE rag_sync_status SET status=? WHERE source_type=? AND source_id=? AND target_version=?",
                        status, source_type, source_id, target_version
                    )
                else:
                    cur.execute(
                        "UPDATE rag_sync_status SET status=?, error_message=? "
                        "WHERE source_type=? AND source_id=? AND target_version=?",
                        status, error_message, source_type, source_id, target_version
                    )
                    cur.execute(
                        "INSERT INTO rag_sync_logs (source_type, source_id, stage, level, message) "
                        "VALUES (?, ?, ?, ?, ?)",
                        source_type, source_id, "qdrant_upsert", "error", error_message or "unknown error"
                    )
                conn.commit()
            finally:
                conn.close()

        try:
            await asyncio.to_thread(_write)
        except Exception as e:
            logger.error(f"[IngestReportService] direct_db 回報失敗 (app_id='{app_reg.app_id}'): {e}")
