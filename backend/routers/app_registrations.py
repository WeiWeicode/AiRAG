import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status

from schemas.app_registration import (
    AppRegistrationCreate, AppRegistrationUpdate, AppRegistrationItem, AppRegistrationListResponse
)
from models.app_registration import AppRegistration
from utils.security import get_current_user

logger = logging.getLogger("airag.app_registrations_router")
router = APIRouter(prefix="/app-registrations", tags=["App Registrations"], dependencies=[Depends(get_current_user)])

# report_mode="direct_db" 僅對 "kb" 開放（程式邏輯白名單，不對外露出可自由選擇的 UI 選項），
# 新接入的 App 一律只能選 "webhook"，避免 AiRAG 之後要維護愈來愈多異質 DB 連線
# （見 MULTI_APP_RAG_SYNC_PLAN.md 2.4 節）
DIRECT_DB_ALLOWED_APP_IDS = {"kb"}


def _to_item(app_reg: AppRegistration) -> AppRegistrationItem:
    return AppRegistrationItem(
        id=str(app_reg.id),
        app_id=app_reg.app_id,
        display_name=app_reg.display_name,
        base_url=app_reg.base_url,
        content_docs_path_template=app_reg.content_docs_path_template,
        content_attachment_path_template=app_reg.content_attachment_path_template,
        report_mode=app_reg.report_mode,
        is_active=app_reg.is_active,
        created_at=app_reg.created_at,
        updated_at=app_reg.updated_at
    )


def _validate_report_mode(app_id: str, report_mode: str):
    if report_mode == "direct_db" and app_id not in DIRECT_DB_ALLOWED_APP_IDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"report_mode='direct_db' 僅開放給 {sorted(DIRECT_DB_ALLOWED_APP_IDS)}，其餘 App 請使用 'webhook'"
        )


@router.get("", response_model=AppRegistrationListResponse)
async def list_app_registrations():
    """
    列出所有已登錄的 App Registry 項目。
    """
    apps = await AppRegistration.find_all().sort("-created_at").to_list()
    return AppRegistrationListResponse(items=[_to_item(a) for a in apps])


@router.post("", response_model=AppRegistrationItem, status_code=status.HTTP_201_CREATED)
async def create_app_registration(request: AppRegistrationCreate):
    """
    新增一個 App Registry 項目（見 MULTI_APP_RAG_SYNC_PLAN.md 2.4 節）。
    """
    _validate_report_mode(request.app_id, request.report_mode)

    existing = await AppRegistration.find_one(AppRegistration.app_id == request.app_id)
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"app_id '{request.app_id}' 已存在")

    app_reg = AppRegistration(
        app_id=request.app_id,
        display_name=request.display_name,
        base_url=request.base_url,
        content_docs_path_template=request.content_docs_path_template,
        content_attachment_path_template=request.content_attachment_path_template,
        report_mode=request.report_mode,
        is_active=request.is_active
    )
    await app_reg.insert()
    return _to_item(app_reg)


@router.put("/{app_id}", response_model=AppRegistrationItem)
async def update_app_registration(app_id: str, request: AppRegistrationUpdate):
    """
    更新指定 App Registry 項目。
    """
    app_reg = await AppRegistration.find_one(AppRegistration.app_id == app_id)
    if not app_reg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"找不到 app_id '{app_id}' 的登錄資料")

    update_data = request.model_dump(exclude_unset=True)
    new_report_mode = update_data.get("report_mode", app_reg.report_mode)
    _validate_report_mode(app_id, new_report_mode)

    for field, value in update_data.items():
        setattr(app_reg, field, value)
    app_reg.updated_at = datetime.utcnow()
    await app_reg.save()
    return _to_item(app_reg)


@router.delete("/{app_id}")
async def delete_app_registration(app_id: str):
    """
    刪除指定 App Registry 項目。
    """
    app_reg = await AppRegistration.find_one(AppRegistration.app_id == app_id)
    if not app_reg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"找不到 app_id '{app_id}' 的登錄資料")

    await app_reg.delete()
    return {"message": f"已成功刪除 App Registry '{app_id}'"}
