import os
import logging
from typing import Any, Dict, Tuple

import httpx

from models.app_registration import AppRegistration

logger = logging.getLogger("airag.services.app_content_client")


def _get_sync_key(app_id: str) -> str:
    """
    依 MULTI_APP_RAG_SYNC_PLAN.md 2.4 節命名慣例，讀取 {APP_ID}_RAG_SYNC_KEY 環境變數。
    機敏資料不進 MongoDB，僅由維運人員在部署環境的 .env 設定。
    """
    key = os.getenv(f"{app_id.upper()}_RAG_SYNC_KEY")
    if not key:
        raise RuntimeError(f"缺少環境變數 {app_id.upper()}_RAG_SYNC_KEY，無法呼叫 '{app_id}' 的內容拉取端點")
    return key


def _build_url(base_url: str, path_template: str, source_id: Any) -> str:
    return base_url.rstrip("/") + path_template.format(id=source_id)


class AppContentClient:
    """
    封裝呼叫各接入 App 登錄的內容/附件拉取端點（見 MULTI_APP_RAG_SYNC_PLAN.md 2.2 節）。
    路徑一律依 AppRegistration 的樣板組成，不對各 App 的實際路徑命名做任何假設。
    """

    @staticmethod
    async def fetch_doc(app_reg: AppRegistration, source_id: Any) -> Dict[str, Any]:
        """
        呼叫文字/文章內容 API，回傳 JSON 內容（appId/docType/sourceId/title/content/version/updatedAt/permissions）。
        """
        url = _build_url(app_reg.base_url, app_reg.content_docs_path_template, source_id)
        headers = {"X-RAG-Sync-Key": _get_sync_key(app_reg.app_id)}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    async def fetch_attachment(app_reg: AppRegistration, source_id: Any) -> Tuple[bytes, Dict[str, str]]:
        """
        呼叫附件二進位檔 API，回傳 (檔案二進位內容, Response Headers)。
        """
        url = _build_url(app_reg.base_url, app_reg.content_attachment_path_template, source_id)
        headers = {"X-RAG-Sync-Key": _get_sync_key(app_reg.app_id)}
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.content, dict(resp.headers)
