from fastapi import APIRouter, Depends
from utils.security import get_current_user

router = APIRouter(prefix="/feedback", tags=["Feedback"], dependencies=[Depends(get_current_user)])

@router.post("")
async def create_feedback_stub():
    return {"feedback_id": "stub", "chat_message_id": "stub", "is_correct": True}

@router.get("")
async def list_feedback_stub():
    return {"total": 0, "items": []}

@router.post("/export-to-dataset")
async def export_feedback_stub():
    return {"dataset_id": "stub", "imported_count": 0, "message": "stub"}
