from datetime import datetime
from typing import Optional, List, Dict, Any
from beanie import Document

class PromptTestRecord(Document):
    name: str                           # 紀錄標題，例如 "請假福利 A/B 測試 - 2026-06-23"
    system_prompt: str                  # 當時的系統設定
    user_prompt_template: str           # 當時的使用者範本
    context: str                        # 當時的 Context
    question: str                       # 當時的問題
    results: List[Dict[str, Any]]       # A/B 測試的生成結果清單，每項包含 label, answer, params, elapsed_ms
    created_by: Optional[str] = None
    created_at: datetime = datetime.utcnow()

    class Settings:
        name = "prompt_test_records"
        indexes = [
            "created_at"
        ]
