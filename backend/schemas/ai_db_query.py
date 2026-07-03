from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any


class ProfileColumnInput(BaseModel):
    column_name: str
    enabled: bool = True
    meaning: str = ""
    max_length: Optional[int] = None


class DBQueryProfileCreate(BaseModel):
    name: str
    database_config_id: str
    knowledge_base_id: str
    platform_description: str = ""
    table_name: str
    table_purpose: str = ""
    columns: List[ProfileColumnInput] = Field(default_factory=list)
    is_default: bool = False  # 必定查詢：問題與任何設定檔都無明顯關聯時，仍會強制加入查詢


class DBQueryProfileResponse(BaseModel):
    id: str
    name: str
    database_config_id: str
    knowledge_base_id: str
    platform_description: str
    table_name: str
    table_purpose: str
    columns: List[ProfileColumnInput]
    is_default: bool
    composed_description: str


class ListTablesRequest(BaseModel):
    config_id: str


class ListColumnsRequest(BaseModel):
    config_id: str
    table_name: str


class MatchProfilesRequest(BaseModel):
    question: str
    knowledge_base_id: Optional[str] = None  # 留空代表不限定知識庫，掃描所有知識庫的查詢設定檔
    score_threshold: Optional[float] = None
    limit: int = 5


class ProfileCandidate(BaseModel):
    profile_id: str
    name: str
    table_name: str
    table_purpose: str
    score: float


class MatchProfilesResponse(BaseModel):
    candidates: List[ProfileCandidate]
    selection_reason: str


class ExecuteQueryRequest(BaseModel):
    question: str
    profile_id: str
    max_rows: Optional[int] = None
    max_chars: Optional[int] = None


class ExecuteQueryResponse(BaseModel):
    profile_id: str
    profile_name: str
    generated_sql: str
    row_count: int
    context_text: str
    elapsed_ms: int
