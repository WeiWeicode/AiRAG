import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from beanie import PydanticObjectId

from models.external_api_key import ExternalApiKey
from utils.security import generate_external_api_key, get_current_user

logger = logging.getLogger("airag.routers.external_api_keys")

# 這是給內部管理者用的後台管理功能，沿用 get_current_user JWT 保護；
# 不是外部呼叫端使用的端點，不要與 verify_external_api_key 混淆
router = APIRouter(prefix="/external-api-keys", tags=["External API Keys"], dependencies=[Depends(get_current_user)])


class ExternalApiKeyCreateRequest(BaseModel):
    name: str = Field(..., description="用途/系統名稱標示，例如「HR 入口網站」")


class ExternalApiKeyResponse(BaseModel):
    id: str
    name: str
    key_prefix: str
    is_active: bool
    created_at: str
    last_used_at: Optional[str] = None


class ExternalApiKeyCreatedResponse(ExternalApiKeyResponse):
    api_key: str = Field(..., description="完整金鑰明碼，僅在建立當下回傳一次，之後無法再次取得")


def _to_response(key: ExternalApiKey) -> ExternalApiKeyResponse:
    return ExternalApiKeyResponse(
        id=str(key.id),
        name=key.name,
        key_prefix=key.key_prefix,
        is_active=key.is_active,
        created_at=key.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        last_used_at=key.last_used_at.strftime("%Y-%m-%d %H:%M:%S") if key.last_used_at else None
    )


@router.get("", response_model=List[ExternalApiKeyResponse])
async def get_external_api_keys(current_user: str = Depends(get_current_user)):
    """
    取得所有外部 API 金鑰清單（不含明碼與 hash）
    """
    keys = await ExternalApiKey.find_all().sort("-created_at").to_list()
    return [_to_response(k) for k in keys]


@router.post("", response_model=ExternalApiKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_external_api_key(
    request: ExternalApiKeyCreateRequest,
    current_user: str = Depends(get_current_user)
):
    """
    建立新的外部 API 金鑰，回傳的 api_key 為完整明碼，僅此一次，請妥善保存
    """
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="名稱不能為空")

    plaintext, prefix, key_hash = generate_external_api_key()

    key = ExternalApiKey(name=name, key_prefix=prefix, key_hash=key_hash)
    await key.insert()

    return ExternalApiKeyCreatedResponse(
        **_to_response(key).model_dump(),
        api_key=plaintext
    )


@router.delete("/{key_id}")
async def delete_external_api_key(
    key_id: str,
    current_user: str = Depends(get_current_user)
):
    """
    刪除指定的外部 API 金鑰（刪除後該金鑰立即失效）
    """
    try:
        obj_id = PydanticObjectId(key_id)
    except Exception:
        raise HTTPException(status_code=400, detail="無效的金鑰 ID 格式")

    key = await ExternalApiKey.get(obj_id)
    if not key:
        raise HTTPException(status_code=404, detail="找不到指定的金鑰")

    await key.delete()
    return {"message": f"已成功刪除金鑰 '{key.name}'"}
