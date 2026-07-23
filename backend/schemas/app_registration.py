from datetime import datetime
from pydantic import BaseModel
from typing import List, Optional, Literal

class AppRegistrationCreate(BaseModel):
    app_id: str
    display_name: str
    base_url: str
    content_docs_path_template: str
    content_attachment_path_template: str
    report_mode: Literal["direct_db", "webhook"] = "webhook"
    is_active: bool = True

class AppRegistrationUpdate(BaseModel):
    display_name: Optional[str] = None
    base_url: Optional[str] = None
    content_docs_path_template: Optional[str] = None
    content_attachment_path_template: Optional[str] = None
    report_mode: Optional[Literal["direct_db", "webhook"]] = None
    is_active: Optional[bool] = None

class AppRegistrationItem(BaseModel):
    id: str
    app_id: str
    display_name: str
    base_url: str
    content_docs_path_template: str
    content_attachment_path_template: str
    report_mode: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

class AppRegistrationListResponse(BaseModel):
    items: List[AppRegistrationItem]
