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

async def seed_default_records():
    """
    如果資料庫中沒有此預設 RAG 智慧對話範本之測試紀錄，則自動寫入，以便在自訂 Context 生成頁面選取。
    """
    try:
        exists = await PromptTestRecord.find_one(PromptTestRecord.name == "預設 RAG 智慧對話範本")
        if not exists:
            record = PromptTestRecord(
                name="預設 RAG 智慧對話範本",
                system_prompt=(
                    "你是一個專業的 RAG 智慧對話助理。請根據以下提供的「參考資料」回答使用者的問題。\n"
                    "規則：\n"
                    "1. 儘量使用參考資料中的資訊來回答。\n"
                    "2. 如果參考資料不足以回答問題，請直接回答『知識庫沒有相關資訊。』，絕對不要使用你的既有知識回答，也不要編造任何內容。\n"
                    "3. 保持回答清晰、專業且符合邏輯。\n"
                    "4. 回答時，必須明確在回答的開頭或結尾指出你是參考了哪些文檔引用段落，格式範例：\n"
                    "   「依據 [文件名] 段落: #段落編號 做出以下結論：」或是「（參考來源：[文件名] 段落: #段落編號）」\n"
                    "   若是引用多個段落，請使用頓號（、）或逗號分隔，例如：「依據[知識庫操作說明.md] 段落: #43、[知識庫操作說明.md] 段落: #45、[知識庫操作說明.md] 段落: #10 做出以下結論：」"
                ),
                user_prompt_template="根據以下提供的參考資料回答問題：\n{context}\n\n使用者問題：{question}\n\n請以繁體中文回答：",
                context="【來源文件：說明文檔.md | 段落編號：#1】\n這是測試用的上下文範例內容。",
                question="測試問題？",
                results=[],
                created_by="system",
                created_at=datetime.utcnow()
            )
            await record.insert()
            import logging
            logging.getLogger("airag.mongodb").info("Default PromptTestRecord seeded successfully.")
    except Exception as e:
        import logging
        logging.getLogger("airag.mongodb").error(f"Failed to seed default PromptTestRecord: {e}")
