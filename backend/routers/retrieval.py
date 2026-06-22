from fastapi import APIRouter, Depends
from utils.security import get_current_user

router = APIRouter(prefix="/retrieval", tags=["Retrieval"], dependencies=[Depends(get_current_user)])

@router.post("/search")
async def search_stub():
    return {"query": "", "results": [], "elapsed_ms": 0}

@router.post("/query-transform")
async def query_transform_stub():
    return {"original_query": "", "transformed_query": "", "strategy": "none", "results": []}
