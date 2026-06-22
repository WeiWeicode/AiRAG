from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class UploadResponse(BaseModel):
    file_id: str
    filename: str
    content: str
    page_count: int
    char_count: int

class ChunkParams(BaseModel):
    chunk_size: int = 512
    chunk_overlap: int = 50
    separator: str = "\n\n"

class ChunkRequest(BaseModel):
    file_id: Optional[str] = None
    content: str
    params: ChunkParams = Field(default_factory=ChunkParams)

class ChunkItem(BaseModel):
    index: int
    content: str
    token_count: int
    char_count: int
    start_char: int
    end_char: int

class ChunkResponse(BaseModel):
    chunks: List[ChunkItem]
    total_chunks: int
    avg_token_count: int

class VectorizeChunkItem(BaseModel):
    index: int
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

class VectorizeRequest(BaseModel):
    chunks: List[VectorizeChunkItem]
    knowledge_base_id: str
    embedding_model: str = "Qwen3-Embedding-8B-Q8_0.gguf"

class VectorizeResponse(BaseModel):
    knowledge_base_id: str
    inserted_count: int
    embedding_model: str
    elapsed_ms: int
