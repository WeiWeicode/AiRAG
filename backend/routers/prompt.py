from fastapi import APIRouter, Depends
from utils.security import get_current_user

router = APIRouter(prefix="/prompt", tags=["Prompt"], dependencies=[Depends(get_current_user)])

@router.post("/generate")
async def generate_stub():
    return {"message": "Prompt generation stub."}

@router.post("/preview")
async def preview_stub():
    return {"rendered_system_prompt": "", "rendered_user_prompt": "", "total_estimated_tokens": 0}

@router.post("/ab-test")
async def ab_test_stub():
    return {"results": []}
