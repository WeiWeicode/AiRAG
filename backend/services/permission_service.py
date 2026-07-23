import logging
from typing import List, Optional, Tuple, Dict, Any
from beanie import PydanticObjectId
from models.user_profile import UserProfile, ExternalUserInfo

logger = logging.getLogger("airag.services.permission")


class PermissionService:
    @classmethod
    def get_user_from_external_info(cls, info: ExternalUserInfo) -> UserProfile:
        """
        將外部應用傳入的真實使用者資訊（ExternalUserInfo）轉換為 UserProfile 形狀的物件，
        供 filter_results()／build_exclusion_summary() 直接沿用同一套邏輯，不落地寫入 users collection
        （外部呼叫的身分快照改寫進 ExternalChatLog，見 NewFeaturesPlan_ExternalApiTestPlan.md 第 8.5、9 節）。
        job_title_level 由外部呼叫端直接信任帶入，不再對照 JOB_TITLE_LEVELS 重新換算。
        """
        return UserProfile(
            name=info.name,
            department=info.department_name,
            department_code=info.department_code,
            job_title=info.job_title_name,
            level=info.job_title_level,
            employee_id=info.employee_id
        )

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

            # 新式多應用權限欄位（is_public/access_dept/access_level/access_members，
            # 見 MULTI_APP_RAG_SYNC_PLAN.md 4 節）：與舊式 is_confidential 欄位互斥，
            # 只有透過多應用 RAG 同步寫入的 point 才會帶 is_public（非 None），
            # 既有 embedding 上傳流程的 point 一律落入下方舊邏輯。
            if meta.get("is_public") is not None:
                if meta.get("is_public"):
                    allowed.append(item)
                    continue

                reasons: List[str] = []
                dept_level_ok = True

                access_level = meta.get("access_level")
                if access_level is not None:
                    try:
                        access_level_int = int(access_level)
                        if user.level > access_level_int:
                            dept_level_ok = False
                            reasons.append(
                                f"檔案存取等級: {access_level_int}，{user.name}（{user.job_title}，等級 {user.level}）權限不足"
                            )
                    except (TypeError, ValueError):
                        logger.warning(
                            "無法將 access_level '%s' 轉型為整數 (filename: %s)",
                            access_level,
                            meta.get("filename", "未知檔名")
                        )

                access_dept = meta.get("access_dept")
                if access_dept:
                    dept_matched = (
                        user.department == access_dept or
                        (user.department_code and user.department_code == access_dept)
                    )
                    if not dept_matched:
                        dept_level_ok = False
                        reasons.append(
                            f"部門限制: 僅限「{access_dept}」，{user.name} 所屬部門「{user.department}」不符"
                        )

                # access_members 為個人層級白名單：即使不符部門/等級限制，
                # 只要使用者工號在名單內即視為有權存取（覆蓋一般政策，而非額外限制）
                access_members = meta.get("access_members") or []
                member_matched = bool(user.employee_id) and user.employee_id in access_members

                if dept_level_ok or member_matched:
                    allowed.append(item)
                else:
                    item_copy = dict(item)
                    item_copy["_exclusion_reason"] = " 且 ".join(reasons) if reasons else "權限不足"
                    excluded.append(item_copy)
                continue

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

            # 部門過濾驗證：文件有指定部門且使用者部門（代號或名稱皆可）不在列表中 -> 部門不符
            # 雙軌比對：confidential_departments 可能混雜舊資料（部門名稱）與新資料（部門代號），
            # 任一種格式命中即視為符合，過渡期不需要遷移既有資料（見 NewFeaturesPlan_ExternalApiTestPlan.md 第 8.4 節）
            if c_depts:
                dept_str_list = [str(d) for d in c_depts if d]
                matched = (
                    user.department in dept_str_list or
                    (user.department_code and user.department_code in dept_str_list)
                )
                if dept_str_list and not matched:
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
