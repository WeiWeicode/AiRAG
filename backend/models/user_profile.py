from datetime import datetime
from typing import Optional
from beanie import Document
from pydantic import BaseModel, Field

JOB_TITLE_LEVELS = {
    "一般人員": 10,
    "組長": 8,
    "課長": 7,
    "經理": 6,
    "總經理": 4,
}

class UserProfile(Document):
    name: str
    department: str
    department_code: Optional[str] = None
    job_title: str
    level: int
    employee_id: Optional[str] = None  # 供 access_members 個人白名單比對用（見 MULTI_APP_RAG_SYNC_PLAN.md 4 節）
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "users"
        indexes = ["department", "-created_at"]


class ExternalUserInfo(BaseModel):
    """
    外部應用呼叫 /api/external/chat 時傳入的真實使用者身分資訊，
    取代內部測試專用的 simulated_user_id（見 NewFeaturesPlan_ExternalApiTestPlan.md 第 8 節）。
    """
    employee_id: str
    name: str
    department_code: str
    department_name: str
    job_title_name: str
    job_title_level: int
