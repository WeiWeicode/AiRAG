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

class RepairImageCaptionsTriggerRequest(BaseModel):
    """
    POST /api/external/ingest/repair-captions 的 Request Body（僅重試描述失敗的內嵌圖片，
    不做全量重新切分）。以 (app_id, doc_type, source_id) 定位要修復的圖片段落，與
    QdrantService.delete_by_app_source 的定位鍵一致；filename 僅供 log／訊息顯示，
    不參與 Qdrant 過濾。source_id 型別必須與寫入時一致（int），字串不會匹配到 payload 中的整數。
    """
    model_config = ConfigDict(populate_by_name=True)

    app_id: str = Field(..., alias="appId")
    doc_type: str = Field(..., alias="docType")
    source_id: int = Field(..., alias="sourceId")
    knowledge_base_id: str = Field(..., alias="knowledgeBaseId")
    callback_url: Optional[str] = Field(None, alias="callbackUrl")
    filename: Optional[str] = None
