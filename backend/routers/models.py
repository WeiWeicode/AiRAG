import logging

from fastapi import APIRouter, Depends, HTTPException, status

from config import settings
from services.model_discovery_service import ModelDiscoveryService
from utils.security import get_current_user

logger = logging.getLogger("airag.models")

router = APIRouter(prefix="/models", tags=["Models"], dependencies=[Depends(get_current_user)])


@router.get("/list")
async def list_models():
    """
    列出本機 Ollama 已下載的模型與目前各角色採用的模型，供前端模型下拉選單動態載入。
    """
    try:
        models = await ModelDiscoveryService.list_models()
    except Exception as e:
        logger.error(f"偵測 Ollama 模型失敗：{type(e).__name__}: {e!r}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"無法連線 Ollama（{ModelDiscoveryService.ollama_root_url()}）：{type(e).__name__}",
        )

    # 啟動時 Ollama 尚未就緒會留下空值，這裡順手補選一次，不必重啟服務
    if not settings.VLLM_MODEL or not settings.DENSE_VECTOR_INSTRUCT_MODEL:
        await ModelDiscoveryService.resolve_default_models()

    return {
        "provider": "ollama",
        "base_url": ModelDiscoveryService.ollama_root_url(),
        "default_chat_model": settings.VLLM_MODEL,
        "instruct_model": settings.DENSE_VECTOR_INSTRUCT_MODEL,
        "embedding_model": settings.EMBEDDING_MODEL,
        "models": models,
    }
