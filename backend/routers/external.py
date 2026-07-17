import logging
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from routers.rag import ChatRequest, rag_chat_stream

logger = logging.getLogger("airag.external_router")
# 供公司內網外部應用串接使用，暫不掛認證（依 NewFeaturesPlan_ExternalApiTestPlan.md 決策）
router = APIRouter(prefix="/external", tags=["External API"])

@router.post("/chat")
async def external_chat(request: ChatRequest):
    return StreamingResponse(rag_chat_stream(request), media_type="text/event-stream")
