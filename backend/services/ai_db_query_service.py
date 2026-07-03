import json
import time
import logging
import asyncio
from datetime import datetime, date
from typing import List, Dict, Any, Optional

import httpx
from beanie import PydanticObjectId

from config import settings
from models.database_config import DatabaseConfig
from models.db_query_profile import DBQueryProfile
from models.knowledge_base import KnowledgeBase
# 重用既有「資料庫匯入向量化」功能的唯讀連線與 SQL 安全驗證邏輯，不重寫、不修改原檔案。
from routers.database_indexing import get_db_connection, validate_sql_query

logger = logging.getLogger("airag.ai_db_query")


class AIDBQueryError(Exception):
    """語義資料庫查詢法流程中的可預期錯誤（設定檔不足、SQL 產生/執行失敗等），需直接回報給使用者，不做靜默降級。"""
    pass


class AIDBQueryService:

    @classmethod
    async def _call_instruct_llm(cls, system_prompt: str, user_content: str, max_tokens: int = 512, temperature: float = 0.1) -> str:
        """
        呼叫地端 Instruct 語義化 AI（與 EmbeddingService.query_to_semantic_json 共用同一組端點設定）。
        """
        url = f"{settings.DENSE_VECTOR_LLAMACPP_BASE_URL.rstrip('/')}/v1/chat/completions"
        payload = {
            "model": settings.DENSE_VECTOR_INSTRUCT_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "max_tokens": max_tokens,
            "temperature": temperature
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"]

    @classmethod
    async def _select_relevant_profiles_from_catalog(cls, question: str, catalog: List[DBQueryProfile]) -> Dict[str, Any]:
        """
        第 1-2 步：語義理解 + Profile 選擇。在呼叫任何向量檢索之前，先把「目前所有查詢設定檔」的完整清單
        提供給語義 AI，讓它直接依問題語意判斷需要用到哪幾個設定檔（可複選），而不是單純依向量相似度門檻篩選。
        這樣可避免問題同時橫跨多張表格（例如同時問到附件與文章）時，因單一門檻/單一最高分而漏掉其中一個。
        """
        catalog_lines = "\n".join(
            f'- id: "{p.id}" | 名稱: {p.name} | 表格: {p.table_name} | 用途: {p.table_purpose or p.platform_description or "（無說明）"}'
            for p in catalog
        )
        system_prompt = (
            "你是一個資料庫查詢設定檔選擇器。以下【目前所有查詢設定檔清單】列出了系統中所有可用的設定檔，"
            "每個設定檔對應一張資料表的用途。\n"
            "請根據使用者問題，判斷需要用到清單中的哪些設定檔才能完整回答問題：\n"
            "- 可以是 0 個（若問題與任何設定檔都無關）、1 個，或多個（例如問題同時問到性質不同的兩種資料時，"
            "應同時選擇對應的多個設定檔，不要只挑一個看起來最像的）。\n"
            "- 只能選擇清單中確實列出的 id，絕對不可自行想像不存在的設定檔（防幻想）。\n"
            "- 請依相關性由高到低排序輸出。\n"
            "只輸出以下 JSON 格式，不要包含任何 Markdown 標記或額外說明文字：\n"
            "{\n"
            "  \"selected_profile_ids\": [\"<id>\", \"...\"],\n"
            "  \"reason\": \"<簡短說明為何選擇/不選擇這些設定檔>\"\n"
            "}\n\n"
            f"【目前所有查詢設定檔清單】\n{catalog_lines}"
        )
        try:
            content = await cls._call_instruct_llm(system_prompt, f"使用者問題：{question}", max_tokens=512, temperature=0.1)
            text = content.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                text = "\n".join(lines).strip()
            parsed = json.loads(text)
            return {
                "selected_profile_ids": [str(pid) for pid in parsed.get("selected_profile_ids", [])],
                "reason": parsed.get("reason", "")
            }
        except Exception as e:
            logger.warning(f"Profile selection via catalog failed, falling back to empty selection: {e}")
            return {"selected_profile_ids": [], "reason": f"設定檔選擇解析失敗：{e}"}

    @classmethod
    async def match_profiles(
        cls,
        question: str,
        knowledge_base_id: Optional[str] = None,
        score_threshold: Optional[float] = None,
        limit: int = 5
    ) -> Dict[str, Any]:
        """
        第 1-2 步：語義理解 + Profile 選擇，回傳候選設定檔清單（依 AI 判斷的相關性排序，而非向量相似度分數）。
        - 指定 knowledge_base_id：僅在該知識庫範圍內的設定檔清單中選擇（既有行為，呼叫端通常會列出候選讓使用者選取）。
        - 不指定 knowledge_base_id：掃描所有知識庫的查詢設定檔清單，讓 AI 直接判斷需要哪幾個
          （呼叫端可自行決定要列出候選或直接執行，見 rag.py 的「不限定知識庫」模式）。
        若完全沒有候選，回傳空清單，呼叫端須明確告知使用者查無對應設定檔，不可猜測硬湊。
        """
        if knowledge_base_id:
            try:
                kb = await KnowledgeBase.get(PydanticObjectId(knowledge_base_id))
            except Exception:
                kb = None
            if not kb:
                raise AIDBQueryError("指定的知識庫不存在")
            catalog = await DBQueryProfile.find(DBQueryProfile.knowledge_base_id == str(kb.id)).to_list()
        else:
            catalog = await DBQueryProfile.find_all().to_list()

        if not catalog:
            raise AIDBQueryError("尚無任何查詢設定檔，請先於「資料庫匯入向量化」頁面建立查詢設定檔。")

        selection = await cls._select_relevant_profiles_from_catalog(question, catalog)
        selected_ids = selection["selected_profile_ids"]
        reason = selection["reason"]

        profile_map = {str(p.id): p for p in catalog}

        # 「必定查詢」設定檔：不論 AI 判斷結果為何，一律強制加入候選清單最前面
        # （例如問題語意不明確落在特定表格時，仍會確保這類廣泛用途/兜底設定檔被查詢到）。
        default_ids = [str(p.id) for p in catalog if p.is_default]
        forced_ids = [pid for pid in default_ids if pid not in selected_ids]
        final_ids = (forced_ids + selected_ids)[:limit]

        if forced_ids:
            forced_names = "、".join(profile_map[pid].name for pid in forced_ids)
            reason = f"{reason}（另有標記為必定查詢的設定檔已強制加入：{forced_names}）" if reason else f"已強制加入必定查詢的設定檔：{forced_names}"

        candidates = []
        for i, pid in enumerate(final_ids):
            profile = profile_map.get(pid)
            if not profile:
                continue
            candidates.append({
                "profile_id": str(profile.id),
                "name": profile.name,
                "table_name": profile.table_name,
                "table_purpose": profile.table_purpose,
                "score": round(max(1.0 - i * 0.05, 0.0), 4)
            })

        return {"candidates": candidates, "selection_reason": reason}

    @classmethod
    async def _generate_sql(
        cls,
        question: str,
        profile: DBQueryProfile,
        db_config: DatabaseConfig,
        max_rows: int,
        retry_error: Optional[str] = None,
        previous_sql: Optional[str] = None
    ) -> str:
        """
        第 3 步：依查詢設定檔的表格/欄位定義，讓 Instruct AI 產生唯讀 SQL。
        規則：只能輸出 SELECT、只能用設定檔中列出的欄位（防幻想）、依 db_type 語法自動加上限制筆數子句、
        文字篩選一律用 LIKE 模糊比對（而非 = 完全比對，避免使用者用詞與資料庫實際內容不完全一致時查無資料）、
        SELECT 應包含足夠的識別欄位供後續摘要判斷相關性，而非只挑使用者問到的單一欄位。
        若帶入 retry_error/previous_sql，代表上一次產生的 SQL 執行失敗（多半是欄位名稱幻覺），
        會把失敗原因回饋給模型要求修正，只重試一次，不做無限重試。
        """
        enabled_columns = [c for c in profile.columns if c.enabled]
        columns_desc = "\n".join(
            f"- {c.column_name}：{c.meaning or c.column_name}" for c in enabled_columns
        ) or "（無指定欄位，需使用 SELECT *）"
        all_column_names = ", ".join(c.column_name for c in enabled_columns) or "*"

        limit_clause_hint = (
            f"SQL Server 語法請使用 SELECT TOP {max_rows} ...；"
            if db_config.db_type == "sqlserver"
            else f"Oracle 語法請使用 ... FETCH FIRST {max_rows} ROWS ONLY；"
        )

        system_prompt = (
            "你是一個嚴謹的唯讀 SQL 產生器。請根據下方提供的「資料表定義」，將使用者問題轉換成一段可執行的 SQL 查詢。\n"
            "【嚴格規則】\n"
            "1. 只能輸出 SELECT 或 WITH 開頭的唯讀查詢，絕對不可輸出 INSERT/UPDATE/DELETE/DROP/ALTER/CREATE 等任何寫入或結構變更語句。\n"
            f"2. 【防幻想，最重要】只能使用下方【資料表定義】列出的表格「{profile.table_name}」與其欄位（{all_column_names}），"
            "絕對不可自行想像不存在的欄位或表格。下方 Few-Shot 範例中出現的表格名稱與欄位名稱（如 attachments、articles、title、"
            "description、content）僅為示範 SQL 句型結構之用，與本次實際要查詢的表格/欄位完全無關，"
            "絕對不可以把範例中的欄位名稱直接套用到本次查詢，只能使用本次【資料表定義】明確列出的欄位名稱。\n"
            f"3. 必須限制回傳筆數，最多 {max_rows} 筆。{limit_clause_hint}\n"
            "4. 只輸出純 SQL 字串，不要包含任何 Markdown 標記（如 ```sql）、說明文字或分號後的多餘內容。\n"
            "5. 【模糊查詢規則，非常重要】使用者的用詞與資料庫實際內容經常不完全一致（例如使用者只打檔名的一部分、或用口語描述而非完整標題），"
            "若用 = 做完全相等比對很容易查無資料。因此：\n"
            "   a. 先從使用者問題中拆解出 2-5 個核心關鍵字（實體名稱、檔名、模組名稱、業務名詞等，去除「請幫我」「查詢」「跟我說」等虛詞）。\n"
            "   b. 針對文字型欄位（標題、名稱、描述、內容等，依欄位意義判斷），一律使用 LIKE '%關鍵字%' 做模糊比對，不要用 = 完全比對。\n"
            "   c. 多個關鍵字、多個文字型欄位之間一律用 OR 串接（放在同一組括號內），盡量提高命中機會，而不是用 AND 疊加多重限制條件把範圍越縮越小。\n"
            "   d. 只有明確是數值、日期、布林、ID 等非文字型欄位時才使用 = 或範圍比對，不要對這類欄位使用 LIKE。\n"
            "   e. 【排除資料類型詞，非常重要】使用者問題中若有詞只是在描述「資料的類型/表格本身」（例如「附件」「文章」「文件」「資料」「紀錄」「清單」，"
            "尤其是與本表格的名稱或用途相同/相近的詞），這些詞的作用是指出要查哪張表，已經在前一階段的設定檔選擇中處理完畢，"
            "【絕對不可】再把它們當成 LIKE 關鍵字，否則會撈到大量內文只是剛好含有該詞、實際上與問題無關的雜訊資料。"
            "只保留真正的內容實體關鍵字（如系統名稱、檔名、程式名、單號、人名等）。\n"
            "6. 【SELECT 欄位規則】除非欄位數量過多（超過 10 個），否則 SELECT 應包含【資料表定義】中列出的所有啟用欄位"
            f"（{all_column_names}），而不是只選使用者字面上問到的單一欄位，讓後續摘要步驟有足夠上下文可以判斷資料是否真的相關。\n\n"
            "【Few-Shot 範例，僅供參考句型結構，範例中的表格/欄位名稱與本次查詢無關】\n"
            "■ 範例 1 - 好的寫法（模糊查詢 + OR + 完整欄位）：\n"
            "  假設表格定義為 attachments(title, description, created_by_name)，使用者問題：查詢 zz_file 程式資料建立作業，跟我說誰建立的\n"
            "  SELECT TOP 50 title, description, created_by_name FROM attachments "
            "WHERE title LIKE '%zz_file%' OR description LIKE '%zz_file%' OR title LIKE '%程式資料建立作業%' OR description LIKE '%程式資料建立作業%'\n"
            "■ 範例 1 - 錯誤寫法（完全比對 + AND + 只選單一欄位，容易查無資料）：\n"
            "  SELECT TOP 50 created_by_name FROM attachments WHERE title = 'zz_file' AND description LIKE '%程式資料建立作業%'\n"
            "■ 範例 2 - 好的寫法（排除資料類型詞）：\n"
            "  假設表格定義為 articles(title, content, created_by_name)，使用者問題：EFGP有附件跟文章嗎?（本表格用途：放置文章）\n"
            "  SELECT TOP 50 title, content, created_by_name FROM articles WHERE title LIKE '%EFGP%' OR content LIKE '%EFGP%'\n"
            "■ 範例 2 - 錯誤寫法（把資料類型詞當關鍵字，撈到大量無關雜訊）：\n"
            "  SELECT TOP 50 title, content, created_by_name FROM articles "
            "WHERE title LIKE '%EFGP%' OR content LIKE '%EFGP%' OR title LIKE '%附件%' OR content LIKE '%文章%'\n"
            "  （錯誤原因：「附件」「文章」是資料類型詞，選表階段已處理，任何內文提到這兩個字的無關資料都會被撈出來）\n\n"
            f"【資料表定義（本次實際查詢，只能用這裡列出的欄位）】\n"
            f"資料庫類型：{db_config.db_type}\n"
            f"表格名稱：{profile.table_name}\n"
            f"表格用途：{profile.table_purpose or profile.platform_description}\n"
            f"欄位定義：\n{columns_desc}"
        )

        if retry_error and previous_sql:
            system_prompt += (
                f"\n\n【上一次產生的 SQL 執行失敗，請修正】\n"
                f"上一次的 SQL：{previous_sql}\n"
                f"資料庫回傳的錯誤：{retry_error}\n"
                f"這通常代表你使用了不存在的欄位名稱。請重新檢查【資料表定義】中的欄位定義，"
                f"只使用實際列出的欄位名稱（{all_column_names}）重新產生 SQL。"
            )

        content = await cls._call_instruct_llm(system_prompt, f"使用者問題：{question}", max_tokens=512, temperature=0.1)
        sql = content.strip()
        if sql.startswith("```"):
            lines = sql.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            sql = "\n".join(lines).strip()
        return sql

    @classmethod
    def _truncate(cls, value: Any, max_len: int) -> str:
        s = "" if value is None else str(value)
        if len(s) > max_len:
            return s[:max_len] + "（已截斷）"
        return s

    @classmethod
    def _rows_to_text(cls, profile_name: str, table_name: str, table_purpose: str, columns: List, rows: List[Dict[str, Any]], global_max_chars: int) -> str:
        """
        第 5 步：結果整理。逐欄位套用設定檔中的自訂截斷長度（若有），否則用全域上限，避免灌爆主模型 context。
        標頭帶上設定檔名稱，讓主模型在多設定檔合併查詢時能分別陳述各表格的結果；
        查無資料時明確寫出，避免主模型誤把「這個表格沒資料」與其他表格的結果混為一談。
        """
        col_max_len = {c.column_name: (c.max_length or global_max_chars) for c in columns}
        lines = [f"以下是設定檔「{profile_name}」對資料表「{table_name}」（{table_purpose or '未提供表格用途說明'}）的查詢結果："]
        if not rows:
            lines.append("（此表格查無符合資料）")
        for idx, row in enumerate(rows, start=1):
            parts = []
            for col_name, val in row.items():
                max_len = col_max_len.get(col_name, global_max_chars)
                parts.append(f"{col_name}={cls._truncate(val, max_len)}")
            lines.append(f"第 {idx} 筆：" + "、".join(parts))
        return "\n".join(lines)

    @classmethod
    async def execute(
        cls,
        question: str,
        profile_id: str,
        max_rows: Optional[int] = None,
        max_chars: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        第 3-5 步：使用者（或評估流程）選定候選設定檔之後，產生 SQL、驗證、執行、整理成文字結果。
        任一階段失敗都直接拋出 AIDBQueryError 附明確原因，不重試硬猜、不靜默降級。
        """
        start_time = time.time()

        try:
            profile = await DBQueryProfile.get(PydanticObjectId(profile_id))
        except Exception:
            profile = None
        if not profile:
            raise AIDBQueryError("找不到指定的查詢設定檔")

        try:
            db_config = await DatabaseConfig.get(PydanticObjectId(profile.database_config_id))
        except Exception:
            db_config = None
        if not db_config:
            raise AIDBQueryError("查詢設定檔關聯的資料庫連線設定已不存在")

        effective_max_rows = max_rows or settings.AI_DB_QUERY_MAX_ROWS
        effective_max_chars = max_chars or settings.AI_DB_QUERY_MAX_CHARS

        # 最多嘗試 2 次：若第一次產生的 SQL 因欄位名稱幻覺等原因執行失敗，
        # 把實際的資料庫錯誤訊息回饋給 AI 要求修正後只重試一次，避免無限重試。
        max_attempts = 2
        retry_error = None
        previous_sql = None
        generated_sql = None
        records = None

        for attempt in range(1, max_attempts + 1):
            try:
                generated_sql = await cls._generate_sql(
                    question, profile, db_config, effective_max_rows,
                    retry_error=retry_error, previous_sql=previous_sql
                )
            except Exception as e:
                raise AIDBQueryError(f"SQL 產生失敗：{e}")

            try:
                validate_sql_query(generated_sql)
            except ValueError as ve:
                raise AIDBQueryError(f"AI 產生的 SQL 未通過安全驗證：{ve}\nSQL: {generated_sql}")

            try:
                def _fetch(sql=generated_sql):
                    conn = get_db_connection(
                        db_type=db_config.db_type,
                        host=db_config.host,
                        port=db_config.port,
                        database=db_config.database,
                        username=db_config.username,
                        password=db_config.password
                    )
                    cursor = conn.cursor()
                    cursor.execute(sql)
                    columns = [col[0] for col in cursor.description] if cursor.description else []
                    rows = cursor.fetchall()

                    records = []
                    for r in rows[:effective_max_rows]:
                        rec = {}
                        for col, val in zip(columns, r):
                            if isinstance(val, (datetime, date)):
                                rec[col] = val.isoformat()
                            elif isinstance(val, bytes):
                                rec[col] = val.decode('utf-8', errors='ignore')
                            else:
                                rec[col] = val
                        records.append(rec)
                    conn.close()
                    return records

                records = await asyncio.to_thread(_fetch)
                break
            except Exception as e:
                if attempt < max_attempts:
                    logger.warning(f"SQL 執行失敗，回饋錯誤給 AI 重試一次：{e}\nSQL: {generated_sql}")
                    retry_error = str(e)
                    previous_sql = generated_sql
                    continue
                raise AIDBQueryError(f"SQL 執行失敗（已重試 {max_attempts} 次）：{e}\nSQL: {generated_sql}")

        context_text = cls._rows_to_text(profile.name, profile.table_name, profile.table_purpose, profile.columns, records, effective_max_chars)
        if len(context_text) > effective_max_chars:
            context_text = context_text[:effective_max_chars] + "\n（內容過長，已截斷）"

        elapsed_ms = int((time.time() - start_time) * 1000)
        return {
            "profile_id": str(profile.id),
            "profile_name": profile.name,
            "generated_sql": generated_sql,
            "row_count": len(records),
            "context_text": context_text,
            "elapsed_ms": elapsed_ms
        }
