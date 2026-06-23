from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class SearchParams(BaseModel):
    top_k: int = Field(default=8)
    score_threshold: float = Field(default=0.4)
    search_type: str = Field(default="vector")  # "vector" or "hybrid"
    hnsw_ef_search: int = Field(default=128)
    filter_tags: Optional[List[str]] = Field(default=None)
    filter_filename: Optional[str] = Field(default=None)

class RetrievalRequest(BaseModel):
    query: str
    knowledge_base_id: str
    params: SearchParams = Field(default_factory=SearchParams)

class RetrievalMetadata(BaseModel):
    filename: Optional[str] = None
    page: Optional[int] = 1
    section: Optional[str] = ""
    chunk_index: Optional[int] = None
    tags: Optional[List[str]] = Field(default_factory=list)

class RetrievalResultItem(BaseModel):
    chunk_id: str
    content: str
    metadata: RetrievalMetadata
    score: float
    distance: float

class RetrievalResponse(BaseModel):
    query: str
    results: List[RetrievalResultItem]
    elapsed_ms: int

class QueryTransformRequest(BaseModel):
    query: str
    strategy: str  # "rewrite" or "hyde"
    knowledge_base_id: str

class QueryTransformResponse(BaseModel):
    original_query: str
    transformed_query: str
    strategy: str
    results: List[RetrievalResultItem] = Field(default_factory=list)
