import logging
import asyncio
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from beanie import PydanticObjectId
from typing import List

from models.database_config import DatabaseConfig
from models.db_query_profile import DBQueryProfile, DBQueryProfileColumn
from models.knowledge_base import KnowledgeBase
from schemas.ai_db_query import (
    DBQueryProfileCreate, DBQueryProfileResponse, ProfileColumnInput,
    ListTablesRequest, ListColumnsRequest,
    MatchProfilesRequest, MatchProfilesResponse, ProfileCandidate,
    ExecuteQueryRequest, ExecuteQueryResponse
)
from services.embedding_service import EmbeddingService
from services.qdrant_service import QdrantService
from services.ai_db_query_service import AIDBQueryService, AIDBQueryError
# 重用既有「資料庫匯入向量化」功能的唯讀連線邏輯，不重寫、不修改原檔案。
from routers.database_indexing import get_db_connection
from utils.security import get_current_user

logger = logging.getLogger("airag.ai_db_query_router")

router = APIRouter(prefix="/ai-db-query", tags=["Semantic DB Query"], dependencies=[Depends(get_current_user)])


def _compose_description(db_config: DatabaseConfig, kb: KnowledgeBase, request: DBQueryProfileCreate) -> str:
    """
    依使用者選取/輸入的欄位，自動組合出一段自然語言描述文字，供 embedding 使用。
    """
    parts = [
        f"這是資料庫查詢的設定檔：{db_config.name} 平台，資料庫是 {kb.name}，"
        f"功能是{request.platform_description or '（未提供描述）'}，"
        f"表單是 {request.table_name}，功能是{request.table_purpose or '（未提供描述）'}，"
        f"以下為欄位說明："
    ]
    enabled_cols = [c for c in request.columns if c.enabled]
    if not enabled_cols:
        parts.append("（未指定任何欄位）")
    else:
        col_descs = []
        for c in enabled_cols:
            desc = f"{c.column_name}（{c.meaning or c.column_name}）"
            if c.max_length:
                desc += f"（此欄位內容較長，查詢時超過 {c.max_length} 字將自動截斷）"
            col_descs.append(desc)
        parts.append("、".join(col_descs))
    return "".join(parts)


async def _get_config_or_404(config_id: str) -> DatabaseConfig:
    try:
        oid = PydanticObjectId(config_id)
    except Exception:
        raise HTTPException(status_code=400, detail="無效的設定檔 ID 格式")
    config = await DatabaseConfig.get(oid)
    if not config:
        raise HTTPException(status_code=404, detail="找不到指定的資料庫連線設定檔")
    return config


def _to_response(profile: DBQueryProfile) -> DBQueryProfileResponse:
    return DBQueryProfileResponse(
        id=str(profile.id),
        name=profile.name,
        database_config_id=profile.database_config_id,
        knowledge_base_id=profile.knowledge_base_id,
        platform_description=profile.platform_description,
        table_name=profile.table_name,
        table_purpose=profile.table_purpose,
        columns=[
            ProfileColumnInput(column_name=c.column_name, enabled=c.enabled, meaning=c.meaning, max_length=c.max_length)
            for c in profile.columns
        ],
        is_default=profile.is_default,
        composed_description=profile.composed_description
    )


# ----------------- 查詢設定檔 CRUD -----------------

@router.get("/profiles", response_model=List[DBQueryProfileResponse])
async def list_profiles(knowledge_base_id: str = None):
    query = DBQueryProfile.find_all()
    if knowledge_base_id:
        query = DBQueryProfile.find(DBQueryProfile.knowledge_base_id == knowledge_base_id)
    profiles = await query.to_list()
    return [_to_response(p) for p in profiles]


@router.post("/profiles", response_model=DBQueryProfileResponse)
async def create_profile(request: DBQueryProfileCreate):
    db_config = await _get_config_or_404(request.database_config_id)

    try:
        kb_oid = PydanticObjectId(request.knowledge_base_id)
    except Exception:
        raise HTTPException(status_code=400, detail="無效的知識庫 ID 格式")
    kb = await KnowledgeBase.get(kb_oid)
    if not kb:
        raise HTTPException(status_code=404, detail="指定的知識庫不存在")

    composed_description = _compose_description(db_config, kb, request)

    profile = DBQueryProfile(
        name=request.name,
        database_config_id=request.database_config_id,
        knowledge_base_id=request.knowledge_base_id,
        platform_description=request.platform_description,
        table_name=request.table_name,
        table_purpose=request.table_purpose,
        columns=[
            DBQueryProfileColumn(column_name=c.column_name, enabled=c.enabled, meaning=c.meaning, max_length=c.max_length)
            for c in request.columns
        ],
        is_default=request.is_default,
        composed_description=composed_description,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    await profile.insert()

    try:
        vector = await EmbeddingService.get_semantic_embedding(composed_description)
        point_id = await QdrantService.upsert_db_query_profile(
            collection_name=kb.qdrant_collection_name,
            profile_id=str(profile.id),
            composed_description=composed_description,
            dense_vector=vector,
            knowledge_base_id=request.knowledge_base_id,
            table_name=request.table_name,
            is_default=request.is_default
        )
        profile.qdrant_point_id = point_id
        await profile.save()
    except Exception as e:
        logger.error(f"Failed to embed/upsert db query profile: {e}")
        raise HTTPException(status_code=500, detail=f"查詢設定檔向量化寫入失敗: {str(e)}")

    return _to_response(profile)


@router.put("/profiles/{profile_id}", response_model=DBQueryProfileResponse)
async def update_profile(profile_id: str, request: DBQueryProfileCreate):
    try:
        oid = PydanticObjectId(profile_id)
    except Exception:
        raise HTTPException(status_code=400, detail="無效的查詢設定檔 ID 格式")
    profile = await DBQueryProfile.get(oid)
    if not profile:
        raise HTTPException(status_code=404, detail="找不到指定的查詢設定檔")

    db_config = await _get_config_or_404(request.database_config_id)
    try:
        kb_oid = PydanticObjectId(request.knowledge_base_id)
    except Exception:
        raise HTTPException(status_code=400, detail="無效的知識庫 ID 格式")
    kb = await KnowledgeBase.get(kb_oid)
    if not kb:
        raise HTTPException(status_code=404, detail="指定的知識庫不存在")

    composed_description = _compose_description(db_config, kb, request)

    profile.name = request.name
    profile.database_config_id = request.database_config_id
    profile.knowledge_base_id = request.knowledge_base_id
    profile.platform_description = request.platform_description
    profile.table_name = request.table_name
    profile.table_purpose = request.table_purpose
    profile.columns = [
        DBQueryProfileColumn(column_name=c.column_name, enabled=c.enabled, meaning=c.meaning, max_length=c.max_length)
        for c in request.columns
    ]
    profile.is_default = request.is_default
    profile.composed_description = composed_description
    profile.updated_at = datetime.utcnow()

    try:
        vector = await EmbeddingService.get_semantic_embedding(composed_description)
        point_id = await QdrantService.upsert_db_query_profile(
            collection_name=kb.qdrant_collection_name,
            profile_id=str(profile.id),
            composed_description=composed_description,
            dense_vector=vector,
            knowledge_base_id=request.knowledge_base_id,
            table_name=request.table_name,
            existing_point_id=profile.qdrant_point_id,
            is_default=request.is_default
        )
        profile.qdrant_point_id = point_id
    except Exception as e:
        logger.error(f"Failed to re-embed/upsert db query profile: {e}")
        raise HTTPException(status_code=500, detail=f"查詢設定檔向量更新失敗: {str(e)}")

    await profile.save()
    return _to_response(profile)


@router.delete("/profiles/{profile_id}")
async def delete_profile(profile_id: str):
    try:
        oid = PydanticObjectId(profile_id)
    except Exception:
        raise HTTPException(status_code=400, detail="無效的查詢設定檔 ID 格式")
    profile = await DBQueryProfile.get(oid)
    if not profile:
        raise HTTPException(status_code=404, detail="找不到指定的查詢設定檔")

    if profile.qdrant_point_id:
        try:
            kb = await KnowledgeBase.get(PydanticObjectId(profile.knowledge_base_id))
            if kb:
                await QdrantService.delete_db_query_profile_point(kb.qdrant_collection_name, profile.qdrant_point_id)
        except Exception as e:
            logger.warning(f"Failed to delete db query profile vector point (continuing with Mongo delete): {e}")

    await profile.delete()
    return {"message": "查詢設定檔已刪除"}


# ----------------- 資料庫 Schema 探索 (供前端選取用) -----------------

@router.post("/list-tables")
async def list_tables(request: ListTablesRequest):
    config = await _get_config_or_404(request.config_id)

    if config.db_type == "sqlserver":
        sql = "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME"
    elif config.db_type == "oracle":
        sql = "SELECT TABLE_NAME FROM USER_TABLES ORDER BY TABLE_NAME"
    else:
        raise HTTPException(status_code=400, detail=f"不支援的資料庫類型: {config.db_type}")

    try:
        def _fetch():
            conn = get_db_connection(
                db_type=config.db_type, host=config.host, port=config.port,
                database=config.database, username=config.username, password=config.password
            )
            cursor = conn.cursor()
            cursor.execute(sql)
            rows = cursor.fetchall()
            conn.close()
            return [r[0] for r in rows]

        tables = await asyncio.to_thread(_fetch)
        return {"tables": tables}
    except Exception as e:
        logger.error(f"Failed to list tables: {e}")
        raise HTTPException(status_code=400, detail=f"取得表格清單失敗: {str(e)}")


@router.post("/list-columns")
async def list_columns(request: ListColumnsRequest):
    config = await _get_config_or_404(request.config_id)

    if config.db_type == "sqlserver":
        sql = "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION"
        params = (request.table_name,)
    elif config.db_type == "oracle":
        sql = "SELECT COLUMN_NAME FROM USER_TAB_COLUMNS WHERE TABLE_NAME = :table_name ORDER BY COLUMN_ID"
        params = {"table_name": request.table_name.upper()}
    else:
        raise HTTPException(status_code=400, detail=f"不支援的資料庫類型: {config.db_type}")

    try:
        def _fetch():
            conn = get_db_connection(
                db_type=config.db_type, host=config.host, port=config.port,
                database=config.database, username=config.username, password=config.password
            )
            cursor = conn.cursor()
            if config.db_type == "sqlserver":
                cursor.execute(sql, params)
            else:
                cursor.execute(sql, params)
            rows = cursor.fetchall()
            conn.close()
            return [r[0] for r in rows]

        columns = await asyncio.to_thread(_fetch)
        return {"columns": columns}
    except Exception as e:
        logger.error(f"Failed to list columns: {e}")
        raise HTTPException(status_code=400, detail=f"取得欄位清單失敗: {str(e)}")


# ----------------- 語義資料庫查詢法：兩段式查詢執行 -----------------

@router.post("/match-profiles", response_model=MatchProfilesResponse)
async def match_profiles(request: MatchProfilesRequest):
    try:
        result = await AIDBQueryService.match_profiles(
            question=request.question,
            knowledge_base_id=request.knowledge_base_id,
            score_threshold=request.score_threshold,
            limit=request.limit
        )
    except AIDBQueryError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return MatchProfilesResponse(
        candidates=[ProfileCandidate(**c) for c in result["candidates"]],
        selection_reason=result["selection_reason"]
    )


@router.post("/execute", response_model=ExecuteQueryResponse)
async def execute_query(request: ExecuteQueryRequest):
    try:
        result = await AIDBQueryService.execute(
            question=request.question,
            profile_id=request.profile_id,
            max_rows=request.max_rows,
            max_chars=request.max_chars
        )
    except AIDBQueryError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return ExecuteQueryResponse(**result)
