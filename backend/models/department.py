from datetime import datetime
from typing import Optional
from beanie import Document, Indexed
from pydantic import Field

class Department(Document):
    name: Indexed(str, unique=True)
    # sparse=True：既有部署在此欄位新增前已存在的部門文件沒有 code，
    # 若用一般 unique index，多筆文件同時缺少 code 會被視為重複的 null 值導致索引建置失敗（E11000）；
    # sparse index 只對「有此欄位」的文件強制唯一，缺少 code 的舊資料不受影響，新建立的部門（API 端已要求必填）則正常受唯一性保護
    code: Optional[Indexed(str, unique=True, sparse=True)] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "departments"
