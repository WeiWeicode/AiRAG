from datetime import datetime
from typing import List, Optional
from beanie import Document
from pydantic import BaseModel, Field


class DBQueryProfileColumn(BaseModel):
    column_name: str
    enabled: bool = True
    meaning: str = ""          # 欄位中文意義描述
    max_length: Optional[int] = None  # 大型欄位（如 nvarchar(max)）的自訂截斷長度；不填則沿用全域 AI_DB_QUERY_MAX_CHARS


class DBQueryProfile(Document):
    name: str                          # 設定檔顯示名稱
    database_config_id: str            # 關聯 DatabaseConfig._id（既有，重用）
    knowledge_base_id: str              # 關聯 KnowledgeBase._id；決定 Profile 向量實際存放的 collection
    platform_description: str = ""     # 平台/資料庫用途自由描述
    table_name: str                    # 選取的表格
    table_purpose: str = ""            # 表格用途描述
    columns: List[DBQueryProfileColumn] = Field(default_factory=list)
    is_default: bool = False           # 必定查詢：使用者問題與任何設定檔都無明顯關聯時，仍會強制加入查詢
    composed_description: str = ""     # 自動組合出的完整自然語言描述（拿去 embedding）
    qdrant_point_id: Optional[str] = None  # 對應 Qdrant point，供更新/刪除
    created_by: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "db_query_profiles"
        indexes = [
            "knowledge_base_id",
            "database_config_id",
        ]
