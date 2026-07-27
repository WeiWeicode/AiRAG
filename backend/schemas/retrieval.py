from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class SearchParams(BaseModel):
    top_k: int = Field(default=8)
    score_threshold: float = Field(default=0.4)
    search_type: str = Field(default="vector")  # "vector" or "hybrid"
    hnsw_ef_search: int = Field(default=128)
    filter_tags: Optional[List[str]] = Field(default=None)
    filter_filename: Optional[str] = Field(default=None)
    disable_parent_merge: bool = Field(default=False)
    simulated_user_id: Optional[str] = Field(default=None)

class RetrievalRequest(BaseModel):
    query: str
    knowledge_base_id: str
    params: SearchParams = Field(default_factory=SearchParams)

class RetrievalMetadata(BaseModel):
    filename: Optional[str] = None
    page: Optional[int] = 1
    section: Optional[str] = ""
    chunk_index: Optional[Any] = None
    tags: Optional[List[str]] = Field(default_factory=list)
    class_list: Optional[List[str]] = Field(default_factory=list, alias="class")
    parent_id: Optional[str] = None
    function_name: Optional[str] = None
    type: Optional[str] = None
    links_to: Optional[List[str]] = Field(default_factory=list)
    linked_attachments: Optional[List[str]] = Field(default_factory=list)
    chunk_type: Optional[str] = None
    image_filename: Optional[str] = None
    image_chunks: Optional[List[Dict[str, Any]]] = Field(default_factory=list)
    is_confidential: Optional[bool] = None
    confidential_level: Optional[int] = None
    confidential_departments: Optional[List[str]] = Field(default_factory=list)

    class Config:
        populate_by_name = True
        allow_population_by_field_name = True

class RetrievalResultItem(BaseModel):
    chunk_id: str
    content: str
    metadata: RetrievalMetadata
    score: float
    distance: float

class ExcludedResultItem(BaseModel):
    filename: str
    chunk_indices: List[Any] = Field(default_factory=list)
    reason: str

class RetrievalResponse(BaseModel):
    query: str
    results: List[RetrievalResultItem]
    elapsed_ms: int
    semantic_json: Optional[Dict[str, Any]] = None
    embeddings_input: Optional[str] = None
    sparse_keywords: Optional[List[str]] = None
    query_vector_preview: Optional[str] = None
    vector_size: Optional[int] = None
    is_fallback: Optional[bool] = None
    excluded_items: List[ExcludedResultItem] = Field(default_factory=list)

class QueryTransformRequest(BaseModel):
    query: str
    strategy: str  # "rewrite" or "hyde"
    knowledge_base_id: str

class QueryTransformResponse(BaseModel):
    original_query: str
    transformed_query: str
    strategy: str
    results: List[RetrievalResultItem] = Field(default_factory=list)

class BatchDeleteRequest(BaseModel):
    point_ids: List[str]

class DeleteByFilenameRequest(BaseModel):
    filename: str

class UpdateLinksRequest(BaseModel):
    filename: str
    links_to: List[str]

class UpdateAttachmentsRequest(BaseModel):
    filename: str
    attachment_ids: List[str]

class RegenerateImageCaptionsRequest(BaseModel):
    # 二者擇一：point_ids 指定要重新產生描述的圖片段落；filename 則掃出該檔案的所有圖片段落
    point_ids: Optional[List[str]] = None
    filename: Optional[str] = None
    # 預設只處理描述失敗的段落，避免誤覆蓋已成功的描述
    only_failed: bool = True

class UpdatePermissionsRequest(BaseModel):
    filename: str
    is_confidential: bool
    confidential_level: Optional[int] = None
    confidential_departments: List[str] = Field(default_factory=list)



