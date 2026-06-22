from fastapi import APIRouter, Depends
from utils.security import get_current_user

router = APIRouter(prefix="/evaluation", tags=["Evaluation"], dependencies=[Depends(get_current_user)])

@router.post("/datasets")
async def create_dataset_stub():
    return {"dataset_id": "stub", "name": "stub", "item_count": 0}

@router.get("/datasets")
async def list_datasets_stub():
    return {"items": []}

@router.post("/run")
async def run_eval_stub():
    return {"report_id": "stub", "summary": {}, "details": []}

@router.get("/reports/{report_id}")
async def get_report_stub(report_id: str):
    return {"report_id": report_id, "summary": {}, "details": []}
