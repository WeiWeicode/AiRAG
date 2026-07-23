from typing import List, Optional, Literal
from pydantic import BaseModel, Field, ConfigDict

class IngestPermissions(BaseModel):
    """
    對應 MULTI_APP_RAG_SYNC_PLAN.md 2.1 節 permissions 物件，HTTP 傳輸層採 camelCase。
    """
    model_config = ConfigDict(populate_by_name=True)

    is_public: bool = Field(False, alias="isPublic")
    access_dept: Optional[str] = Field(None, alias="accessDept")
    access_level: Optional[int] = Field(None, alias="accessLevel")
    access_members: List[str] = Field(default_factory=list, alias="accessMembers")

class IngestTriggerRequest(BaseModel):
    """
    對應 MULTI_APP_RAG_SYNC_PLAN.md 2.1 節 POST /api/external/ingest/trigger 的 Request Body。
    HTTP 傳輸層採 camelCase，AiRAG 內部處理沿用 Python snake_case 慣例（見該文件第 4 節命名風格說明）。
    """
    model_config = ConfigDict(populate_by_name=True)

    app_id: str = Field(..., alias="appId")
    doc_type: str = Field(..., alias="docType")
    source_id: int = Field(..., alias="sourceId")
    title: Optional[str] = None
    target_version: int = Field(..., alias="targetVersion")
    action: Literal["upsert", "delete"] = "upsert"
    knowledge_base_id: str = Field(..., alias="knowledgeBaseId")
    callback_url: Optional[str] = Field(None, alias="callbackUrl")
    permissions: Optional[IngestPermissions] = None
