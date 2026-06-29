from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class DBConfigCreate(BaseModel):
    name: str = Field(..., description="設定檔名稱")
    db_type: str = Field(..., description="資料庫類型 (sqlserver / oracle)")
    host: str = Field(..., description="主機 IP")
    port: int = Field(..., description="連接埠")
    database: str = Field(..., description="資料庫名稱/服務名稱")
    username: str = Field(..., description="使用者帳號")
    password: str = Field(..., description="密碼")

class DBConfigResponse(BaseModel):
    id: str = Field(..., description="設定檔 ID (hex string)")
    name: str
    db_type: str
    host: str
    port: int
    database: str
    username: str
    password: str

class TestConnectionRequest(BaseModel):
    db_type: str
    host: str
    port: int
    database: str
    username: str
    password: str

class FetchMetadataRequest(BaseModel):
    config_id: Optional[str] = None
    connection: Optional[TestConnectionRequest] = None
    sql_query: str

class ColumnConfig(BaseModel):
    enabled: bool
    meaning: str

class IngestDatabaseRequest(BaseModel):
    config_id: Optional[str] = None
    connection: Optional[TestConnectionRequest] = None
    sql_query: str
    ingestion_mode: str = Field("natural_language", description="natural_language or json")
    table_meaning: Optional[str] = None
    columns_config: Dict[str, ColumnConfig]
    knowledge_base_id: str
    one_chunk_per_row: bool = True
