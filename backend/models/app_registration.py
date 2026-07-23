from datetime import datetime
from beanie import Document, Indexed
from pydantic import Field

class AppRegistration(Document):
    """
    多應用 RAG 同步的 App Registry（見 MULTI_APP_RAG_SYNC_PLAN.md 2.4 節）。
    記錄各接入應用的內容/附件拉取路徑樣板與回報模式，AiRAG 依 trigger 的 appId 查此表決定
    要呼叫哪個 URL、用哪種方式回報進度，不在程式碼中對各 App 的路徑命名做任何假設。
    """
    app_id: Indexed(str, unique=True)
    display_name: str
    base_url: str
    content_docs_path_template: str
    content_attachment_path_template: str
    report_mode: str = "webhook"  # "direct_db"（僅 app_id == "kb" 適用） | "webhook"
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "app_registrations"
        indexes = ["-created_at"]
