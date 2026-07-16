import logging
from typing import List, Optional, Tuple, Dict, Any
from beanie import PydanticObjectId
from models.user_profile import UserProfile

logger = logging.getLogger("airag.services.permission")


class PermissionService:
    @classmethod
    async def get_user(cls, user_id: Optional[str]) -> Optional[UserProfile]:
        """
        傳入 user_id (str)：
        - 若為 None 或空字串：回傳 None (未啟用模擬使用者，不執行過濾)。
        - 若傳入 user_id 且查有此人：回傳該 UserProfile。
        - 若傳入 user_id 但資料庫無此紀錄 (例如已刪除)：回傳 Fail-Closed 預設客用身分 (Level 10)，
          避免無效 ID 靜默降級為未過濾模式 (Fail-Open)。
        """
        if not user_id:
            return None
        try:
            obj_id = PydanticObjectId(user_id)
            user = await UserProfile.get(obj_id)
            if user:
                return user

            logger.warning(
                "[PermissionService] 模擬使用者 ID '%s' 不存在或已被刪除，套用 Fail-Closed 安全預設防護 (Level 10 / 無部門)",
                user_id
            )
            return UserProfile(
                name="已無效之模擬使用者",
                department="無部門",
                job_title="無效身分",
                level=10
            )
        except Exception as e:
            logger.warning(
                "[PermissionService] 解析模擬使用者 ID '%s' 失敗: %s，套用 Fail-Closed 安全預設防護 (Level 10 / 無部門)",
                user_id,
                e
            )
            return UserProfile(
                name="已無效之模擬使用者",
                department="無部門",
                job_title="無效身分",
                level=10
            )

    @classmethod
    def filter_results(
        cls,
        raw_results: List[dict],
        user: Optional[UserProfile]
    ) -> Tuple[List[dict], List[dict]]:
        """
        針對檢索結果 (raw_results) 執行機密權限過濾。

        :param raw_results: 檢索到的候選片段清單
        :param user: 模擬使用者 (None 代表不模擬，全數放行)
        :return: (allowed_results, excluded_results)
        """
        if user is None or not raw_results:
            return raw_results, []

        allowed: List[dict] = []
        excluded: List[dict] = []

        for item in raw_results:
            meta = item.get("metadata", {}) or {}
            is_confidential = bool(meta.get("is_confidential"))

            # 未標記為機密的文件 -> 直接放行
            if not is_confidential:
                allowed.append(item)
                continue

            reasons: List[str] = []
            c_level = meta.get("confidential_level")
            c_depts = meta.get("confidential_departments") or []

            # 機密等級驗證：使用者數字 > 文件等級數字 -> 權限不足（使用寬容轉型與 Warning 日誌）
            if c_level is not None:
                try:
                    c_level_int = int(c_level)
                    if user.level > c_level_int:
                        reasons.append(
                            f"檔案權限等級: {c_level_int}，{user.name}（{user.job_title}，等級 {user.level}）權限不足"
                        )
                except (TypeError, ValueError):
                    logger.warning(
                        "無法將 confidential_level '%s' 轉型為整數 (filename: %s)",
                        c_level,
                        meta.get("filename", "未知檔名")
                    )

            # 部門過濾驗證：文件有指定部門且使用者部門不在列表中 -> 部門不符
            if c_depts:
                dept_str_list = [str(d) for d in c_depts if d]
                if dept_str_list and user.department not in dept_str_list:
                    dept_join = "、".join(dept_str_list)
                    reasons.append(
                        f"部門限制: 僅限「{dept_join}」，{user.name} 所屬部門「{user.department}」不符"
                    )

            if reasons:
                item_copy = dict(item)
                item_copy["_exclusion_reason"] = " 且 ".join(reasons)
                excluded.append(item_copy)
            else:
                allowed.append(item)

        return allowed, excluded

    @classmethod
    def build_exclusion_summary(cls, excluded: List[dict]) -> str:
        """
        將被排除的片段依 (filename, exclusion_reason) 分組，組合成人類可讀的多行摘要說明。
        """
        if not excluded:
            return ""

        grouped: Dict[Tuple[str, str], List[Any]] = {}
        for item in excluded:
            meta = item.get("metadata", {}) or {}
            fn = meta.get("filename") or "未知檔案"
            reason = item.get("_exclusion_reason", "權限不足")
            chunk_idx = meta.get("chunk_index")

            key = (fn, reason)
            if key not in grouped:
                grouped[key] = []
            if chunk_idx is not None:
                grouped[key].append(chunk_idx)

        summary_lines: List[str] = []
        for (fn, reason), indices in grouped.items():
            if indices:
                # 簡寫顯示段落範圍 (例如 #1~#5 或 #4)
                valid_ints = [i for i in indices if isinstance(i, int)]
                if valid_ints:
                    min_idx, max_idx = min(valid_ints), max(valid_ints)
                    range_str = f"#{min_idx}" if min_idx == max_idx else f"#{min_idx}~#{max_idx}"
                else:
                    range_str = f"#{indices[0]}"
            else:
                range_str = "全檔案"

            summary_lines.append(f"排除 [{fn}] 段落 {range_str}，原因：{reason}")

        return "\n".join(summary_lines)
