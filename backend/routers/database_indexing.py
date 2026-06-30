import time
import logging
import re
import json
import asyncio
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, status
from beanie import PydanticObjectId
from typing import List, Optional

import pyodbc
import oracledb
import os

from models.database_config import DatabaseConfig
from models.knowledge_base import KnowledgeBase
from schemas.database_indexing import (
    DBConfigCreate, DBConfigResponse, TestConnectionRequest,
    FetchMetadataRequest, IngestDatabaseRequest
)
from services.chunking_service import ChunkingService
from services.embedding_service import EmbeddingService
from services.qdrant_service import QdrantService
from utils.security import get_current_user

logger = logging.getLogger("airag.database_indexing")

oracle_init_error = None
# Initialize Oracle Instant Client to enable Thick Mode for compatibility with older DB versions (e.g. 11g)
try:
    lib_dir = os.environ.get("ORACLE_CLIENT_LIB_DIR")
    if lib_dir:
        oracledb.init_oracle_client(lib_dir=lib_dir)
    else:
        oracledb.init_oracle_client()
    logger.info("Oracle Instant Client initialized successfully (Thick Mode enabled).")
except Exception as e:
    oracle_init_error = e
    logger.warning(f"Failed to initialize Oracle Instant Client: {e}. Falling back to Thin Mode.")

router = APIRouter(prefix="/database-indexing", tags=["Database Indexing"], dependencies=[Depends(get_current_user)])

# Helper function to get dynamic DB connection
def get_db_connection(db_type: str, host: str, port: int, database: str, username: str, password: str):
    # Trim leading/trailing whitespaces to avoid connection failures (e.g. strict FreeTDS host parsing)
    if host:
        host = host.strip()
    if database:
        database = database.strip()
    if username:
        username = username.strip()
        
    if db_type == "sqlserver":
        try:
            installed_drivers = pyodbc.drivers()
        except Exception:
            installed_drivers = []
        
        selected_driver = None
        for d in installed_drivers:
            if "ODBC Driver 17" in d:
                selected_driver = d
                break
        if not selected_driver:
            for d in installed_drivers:
                if "ODBC Driver 18" in d:
                    selected_driver = d
                    break
        if not selected_driver:
            for d in installed_drivers:
                if "FreeTDS" in d:
                    selected_driver = d
                    break
        if not selected_driver:
            for d in installed_drivers:
                if "sql" in d.lower() or "tds" in d.lower():
                    selected_driver = d
                    break
        
        if selected_driver:
            conn_str = f"DRIVER={{{selected_driver}}};SERVER={host};DATABASE={database};UID={username};PWD={password}"
            if "FreeTDS" in selected_driver:
                if "PORT=" not in conn_str and "port=" not in conn_str:
                    conn_str += f";PORT={port}"
                if "TDS_Version" not in conn_str and "tds_version" not in conn_str:
                    conn_str += ";TDS_Version=7.4"
        else:
            conn_str = f"DRIVER={{SQL Server}};SERVER={host},{port};DATABASE={database};UID={username};PWD={password}"
            
        logger.info(f"Connecting to SQL Server with connection string: {conn_str.split('PWD=')[0]}PWD=*****")
        return pyodbc.connect(conn_str, timeout=10)
        
    elif db_type == "oracle":
        logger.info(f"Connecting to Oracle: {host}:{port}/{database} user={username}")
        try:
            try:
                return oracledb.connect(
                    user=username,
                    password=password,
                    host=host,
                    port=port,
                    service_name=database
                )
            except Exception as e:
                try:
                    return oracledb.connect(
                        user=username,
                        password=password,
                        host=host,
                        port=port,
                        sid=database
                    )
                except Exception:
                    raise e
        except Exception as e:
            if oracle_init_error:
                raise RuntimeError(f"{e} (Oracle Thick Mode failed to initialize: {oracle_init_error})")
            raise e
    else:
        raise ValueError(f"不支援的資料庫類型: {db_type}")

# SQL Injection and command validation
def validate_sql_query(query: str):
    q = query.strip().upper()
    # Remove comments to avoid detection bypass
    q_no_comments = re.sub(r'(--[^\n]*)|(/\*.*?\*/)', '', q, flags=re.DOTALL)
    clean_q = q_no_comments.strip()
    
    if not clean_q.startswith("SELECT") and not clean_q.startswith("WITH"):
        raise ValueError("安全限制：僅允許執行 SELECT 或 WITH 開頭的唯讀查詢語句。")
        
    forbidden_keywords = [
        r"\bINSERT\b", r"\bUPDATE\b", r"\bDELETE\b", r"\bDROP\b",
        r"\bALTER\b", r"\bCREATE\b", r"\bTRUNCATE\b", r"\bRENAME\b",
        r"\bMERGE\b", r"\bEXEC\b", r"\bEXECUTE\b", r"\bGRANT\b", r"\bREVOKE\b"
    ]
    for kw in forbidden_keywords:
        if re.search(kw, clean_q):
            kw_clean = kw.replace(r'\b', '')
            raise ValueError(f"安全限制：檢測到不允許使用的寫入或敏感關鍵字: {kw_clean}")

# Extract table name from SELECT query
def extract_table_name(query: str) -> str:
    match = re.search(r'\bFROM\s+([a-zA-Z0-9_\.]+)', query, re.IGNORECASE)
    if match:
        # Get just the table name if it's schema.table
        parts = match.group(1).split('.')
        return parts[-1]
    return "TABLE"

# ----------------- DB Config CRUD Endpoints -----------------

@router.get("/configs", response_model=List[DBConfigResponse])
async def list_configs():
    configs = await DatabaseConfig.find_all().to_list()
    return [
        DBConfigResponse(
            id=str(c.id),
            name=c.name,
            db_type=c.db_type,
            host=c.host,
            port=c.port,
            database=c.database,
            username=c.username,
            password=c.password
        ) for c in configs
    ]

@router.post("/configs", response_model=DBConfigResponse)
async def create_config(request: DBConfigCreate):
    config = DatabaseConfig(
        name=request.name.strip() if request.name else "",
        db_type=request.db_type.strip() if request.db_type else "",
        host=request.host.strip() if request.host else "",
        port=request.port,
        database=request.database.strip() if request.database else "",
        username=request.username.strip() if request.username else "",
        password=request.password,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    await config.insert()
    return DBConfigResponse(
        id=str(config.id),
        name=config.name,
        db_type=config.db_type,
        host=config.host,
        port=config.port,
        database=config.database,
        username=config.username,
        password=config.password
    )

@router.put("/configs/{config_id}", response_model=DBConfigResponse)
async def update_config(config_id: str, request: DBConfigCreate):
    try:
        oid = PydanticObjectId(config_id)
    except Exception:
        raise HTTPException(status_code=400, detail="無效的設定檔 ID 格式")
        
    config = await DatabaseConfig.get(oid)
    if not config:
        raise HTTPException(status_code=404, detail="找不到指定的資料庫設定檔")
        
    config.name = request.name.strip() if request.name else ""
    config.db_type = request.db_type.strip() if request.db_type else ""
    config.host = request.host.strip() if request.host else ""
    config.port = request.port
    config.database = request.database.strip() if request.database else ""
    config.username = request.username.strip() if request.username else ""
    config.password = request.password
    config.updated_at = datetime.utcnow()
    await config.save()
    
    return DBConfigResponse(
        id=str(config.id),
        name=config.name,
        db_type=config.db_type,
        host=config.host,
        port=config.port,
        database=config.database,
        username=config.username,
        password=config.password
    )

@router.delete("/configs/{config_id}")
async def delete_config(config_id: str):
    try:
        oid = PydanticObjectId(config_id)
    except Exception:
        raise HTTPException(status_code=400, detail="無效的設定檔 ID 格式")
        
    config = await DatabaseConfig.get(oid)
    if not config:
        raise HTTPException(status_code=404, detail="找不到指定的資料庫設定檔")
        
    await config.delete()
    return {"message": "資料庫設定檔已刪除"}

# ----------------- DB Indexing Actions -----------------

@router.post("/test-connection")
async def test_connection(request: TestConnectionRequest):
    try:
        def _test():
            conn = get_db_connection(
                db_type=request.db_type,
                host=request.host,
                port=request.port,
                database=request.database,
                username=request.username,
                password=request.password
            )
            # execute a simple test query
            cursor = conn.cursor()
            if request.db_type == "sqlserver":
                cursor.execute("SELECT 1")
            elif request.db_type == "oracle":
                cursor.execute("SELECT 1 FROM DUAL")
            cursor.fetchone()
            conn.close()
            
        await asyncio.to_thread(_test)
        return {"status": "success", "message": "資料庫連線測試成功"}
    except Exception as e:
        logger.error(f"Test connection failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"資料庫連線失敗: {str(e)}"
        )

@router.post("/fetch-metadata")
async def fetch_metadata(request: FetchMetadataRequest):
    # 1. 安全檢驗 SQL 語句
    try:
        validate_sql_query(request.sql_query)
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))

    # 2. 獲取資料庫連線參數
    conn_params = None
    if request.config_id:
        try:
            oid = PydanticObjectId(request.config_id)
        except Exception:
            raise HTTPException(status_code=400, detail="無效的設定檔 ID 格式")
        config = await DatabaseConfig.get(oid)
        if not config:
            raise HTTPException(status_code=404, detail="找不到指定的資料庫設定檔")
        conn_params = config
    elif request.connection:
        conn_params = request.connection
    else:
        raise HTTPException(status_code=400, detail="必須提供 config_id 或連線詳細資訊")

    # 3. 連線並執行查詢以取得欄位與第一筆資料
    try:
        def _fetch():
            conn = get_db_connection(
                db_type=conn_params.db_type,
                host=conn_params.host,
                port=conn_params.port,
                database=conn_params.database,
                username=conn_params.username,
                password=conn_params.password
            )
            cursor = conn.cursor()
            cursor.execute(request.sql_query)
            
            # 取得欄位名稱
            columns = []
            if cursor.description:
                columns = [col[0] for col in cursor.description]
                
            # 取得第一筆樣品
            row = cursor.fetchone()
            sample_data = {}
            if row and columns:
                # convert values to serializable types
                for col, val in zip(columns, row):
                    if isinstance(val, (datetime, date)):
                        sample_data[col] = val.isoformat()
                    elif isinstance(val, bytes):
                        sample_data[col] = val.decode('utf-8', errors='ignore')
                    else:
                        sample_data[col] = val
            
            conn.close()
            return columns, sample_data

        cols, sample = await asyncio.to_thread(_fetch)
        table_name = extract_table_name(request.sql_query)
        
        return {
            "columns": cols,
            "sample_row": sample,
            "table_name": table_name
        }
    except Exception as e:
        logger.error(f"Fetch metadata failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"執行查詢或提取結構失敗: {str(e)}"
        )

@router.post("/ingest")
async def ingest_database(request: IngestDatabaseRequest):
    start_time = time.time()
    
    # 1. 驗證知識庫
    try:
        kb_id = PydanticObjectId(request.knowledge_base_id)
    except Exception:
        raise HTTPException(status_code=400, detail="無效的知識庫 ID 格式")
    kb = await KnowledgeBase.get(kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="指定的知識庫不存在")

    # 2. 安全檢驗 SQL 語句
    try:
        validate_sql_query(request.sql_query)
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))

    # 3. 獲取資料庫連線參數
    conn_params = None
    if request.config_id:
        try:
            oid = PydanticObjectId(request.config_id)
        except Exception:
            raise HTTPException(status_code=400, detail="無效的設定檔 ID 格式")
        config = await DatabaseConfig.get(oid)
        if not config:
            raise HTTPException(status_code=404, detail="找不到指定的資料庫設定檔")
        conn_params = config
    elif request.connection:
        conn_params = request.connection
    else:
        raise HTTPException(status_code=400, detail="必須提供 config_id 或連線詳細資訊")

    # 4. 讀取所有資料
    try:
        def _fetch_all():
            conn = get_db_connection(
                db_type=conn_params.db_type,
                host=conn_params.host,
                port=conn_params.port,
                database=conn_params.database,
                username=conn_params.username,
                password=conn_params.password
            )
            cursor = conn.cursor()
            cursor.execute(request.sql_query)
            
            columns = [col[0] for col in cursor.description] if cursor.description else []
            rows = cursor.fetchall()
            
            records = []
            for r in rows:
                rec = {}
                for col, val in zip(columns, r):
                    if isinstance(val, (datetime, date)):
                        rec[col] = val.isoformat()
                    elif isinstance(val, bytes):
                        rec[col] = val.decode('utf-8', errors='ignore')
                    else:
                        rec[col] = val
                records.append(rec)
                
            conn.close()
            return records

        records = await asyncio.to_thread(_fetch_all)
    except Exception as e:
        logger.error(f"Failed to query database for ingestion: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"執行資料庫查詢失敗: {str(e)}"
        )

    if not records:
        return {
            "status": "success",
            "inserted_count": 0,
            "message": "查詢結果為空，未匯入任何資料",
            "elapsed_ms": int((time.time() - start_time) * 1000)
        }

    # 5. 依設定將資料轉換成對應的文字 (自然語言或 JSON)
    table_name = extract_table_name(request.sql_query)
    documents_to_embed = []
    
    for idx, row in enumerate(records):
        if request.ingestion_mode == "json":
            # 僅保留啟用欄位
            filtered_row = {"tableName": table_name}
            for col_name, val in row.items():
                col_cfg = request.columns_config.get(col_name)
                if col_cfg and col_cfg.enabled:
                    filtered_row[col_name] = val
            doc_text = json.dumps(filtered_row, ensure_ascii=False)
        else:
            # 自然語言模式
            table_meaning = request.table_meaning or "通用資料"
            t_name = table_name or "TABLE"
            
            def is_val_empty(v):
                if v is None:
                    return True
                s = str(v).strip()
                return s == "" or s.lower() == "null" or s.lower() == "none"

            non_empty_parts = []
            empty_cols = []

            for col_name, val in row.items():
                col_cfg = request.columns_config.get(col_name)
                if col_cfg and col_cfg.enabled:
                    meaning = (col_cfg.meaning or "").strip()
                    has_custom_meaning = meaning and meaning != col_name

                    if is_val_empty(val):
                        if has_custom_meaning:
                            if "為" in meaning or "是" in meaning:
                                non_empty_parts.append(f"{meaning}（{col_name}=空值）")
                            else:
                                non_empty_parts.append(f"{meaning}（{col_name}）為空值")
                        else:
                            empty_cols.append(col_name)
                    else:
                        if not has_custom_meaning:
                            non_empty_parts.append(f"{col_name}為「{val}」")
                        elif "為" in meaning or "是" in meaning:
                            non_empty_parts.append(f"{meaning}（{col_name}={val}）")
                        else:
                            non_empty_parts.append(f"{meaning}（{col_name}）為「{val}」")

            header = f"這是 ERP 的{table_meaning}表單（{t_name}）。"
            body = ""
            if non_empty_parts:
                body = f"此筆資料的{'；'.join(non_empty_parts)}"

            doc_text = header
            if body:
                doc_text += body
                if empty_cols:
                    empty_list = "、".join(f"({c})" for c in empty_cols)
                    doc_text += f"，{empty_list}皆為空值，未做描述。"
                else:
                    doc_text += "。"
            else:
                if empty_cols:
                    empty_list = "、".join(f"({c})" for c in empty_cols)
                    doc_text = doc_text[:-1] + f"，其中{empty_list}皆為空值，未做描述。"

        documents_to_embed.append({
            "text": doc_text,
            "row_index": idx
        })

    # 6. 切分 (若 non-one_chunk_per_row，但在 structured DB data，預設為一筆資料為一 Chunk)
    chunks_data = []
    if request.one_chunk_per_row:
        for doc in documents_to_embed:
            chunks_data.append({
                "content": doc["text"],
                "index": doc["row_index"],
                "token_count": len(doc["text"]) // 2 # 簡易估計，稍後由 FastEmbed / EmbeddingService 更新
            })
    else:
        # 使用 standard chunking
        current_chunk_idx = 0
        for doc in documents_to_embed:
            sub_chunks = ChunkingService.split_text(
                text=doc["text"],
                chunk_size=512,
                chunk_overlap=50,
                separator="\n"
            )
            for sc in sub_chunks:
                chunks_data.append({
                    "content": sc["content"],
                    "index": current_chunk_idx,
                    "token_count": sc["token_count"]
                })
                current_chunk_idx += 1

    if not chunks_data:
        raise HTTPException(status_code=400, detail="轉換後的段落內容為空，無法寫入")

    # 7. 向量化並寫入向量庫
    try:
        # 分批進行向量化寫入以防 Request Payload 過大 (批次大小 20)
        batch_size = 20
        total_batches = Math_ceil = (len(chunks_data) + batch_size - 1) // batch_size
        inserted_total = 0
        
        # 刪除之前匯入的同名資料庫備份以防重複 (Filename: DB_IMPORT_{table_name})
        import_filename = f"DB_IMPORT_{table_name}"
        deleted_count = await QdrantService.delete_by_filename(
            collection_name=kb.qdrant_collection_name,
            filename=import_filename
        )

        for b in range(total_batches):
            start_idx = b * batch_size
            end_idx = min(start_idx + batch_size, len(chunks_data))
            chunk_batch = chunks_data[start_idx:end_idx]
            
            texts = [c["content"] for c in chunk_batch]
            vectors = await EmbeddingService.get_embeddings_batch(texts)
            
            qdrant_chunks = []
            for c in chunk_batch:
                qdrant_chunks.append({
                    "content": c["content"],
                    "filename": import_filename,
                    "page": 1,
                    "section": f"Row_{c['index'] + 1}",
                    "chunk_index": c["index"],
                    "token_count": c["token_count"],
                    "char_count": len(c["content"]),
                    "source": "database",
                    "created_at": datetime.utcnow().isoformat()
                })
                
            inserted = await QdrantService.upsert_chunks(
                collection_name=kb.qdrant_collection_name,
                chunks=qdrant_chunks,
                vectors=vectors
            )
            inserted_total += inserted

        # 更新知識庫計數
        kb.chunk_count = max(0, kb.chunk_count - deleted_count + inserted_total)
        kb.updated_at = datetime.utcnow()
        await kb.save()
        
        elapsed = int((time.time() - start_time) * 1000)
        return {
            "status": "success",
            "inserted_count": inserted_total,
            "knowledge_base_id": str(kb.id),
            "elapsed_ms": elapsed,
            "filename": import_filename
        }
    except Exception as e:
        logger.error(f"Database Ingest embedding failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"向量化匯入 Qdrant 失敗: {str(e)}"
        )
