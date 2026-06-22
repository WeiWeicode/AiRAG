from fastapi import APIRouter, Depends
from utils.security import get_current_user

router = APIRouter(prefix="/rag", tags=["RAG"], dependencies=[Depends(get_current_user)])

@router.post("/chat")
async def chat_stub():
    return {"message": "RAG chat endpoint stub. Implemented in Phase 2."}

@router.get("/history")
async def history_stub():
    return {"total": 0, "items": []}
