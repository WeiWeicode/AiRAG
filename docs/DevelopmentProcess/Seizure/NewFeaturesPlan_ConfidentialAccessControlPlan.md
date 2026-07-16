# 文件機密權限控管（Confidential Document Access Control）規劃文件

> 狀態：規劃中，待使用者確認後執行
> 影響範圍：新增 MongoDB `departments`／`users` 兩個 Collection 與對應 Router；Qdrant Point payload 新增 `is_confidential`／`confidential_level`／`confidential_departments` 三個欄位；`backend/services/qdrant_service.py`（`get_unique_metadata`、新增 `update_permissions_by_filename`）；`backend/routers/rag.py`（`vector_search` step 後插入權限過濾與排除訊息、Early Exit 新增「權限不足」分支）；`backend/routers/retrieval.py`（`/search`、`/semantic-hybrid-search`、新增 `/files/update-permissions`）；前端新增「角色設定」頁面與側邊選單、`VectorManagementTab.vue` 新增機密設定區塊、`paramsStore.js` 與檢索參數 UI 新增「模擬使用者」。
> **不觸碰**：現有單一共用登入機制（`AUTH_USERNAME`/`AUTH_PASSWORD_HASH`、`utils/security.py`）、既有 `links_to`/`linked_attachments`/`tags`/`class` 欄位邏輯、未勾選「模擬使用者」時所有既有查詢法的行為（維持零改變）。

---

## 1. 目標與範圍

### 目標
讓知識庫中的文件可以標記為「機密文件」，設定機密等級（1~10）與可讀取部門；並讓工程師在測試頁面（RAG 對話測試、向量搜尋測試）用「模擬使用者」身分驗證檢索與回答結果是否正確地依權限排除了不該看到的內容。

### 明確的範圍邊界
- 這是**內部測試平台的權限模擬機制**，不是取代現有登入系統的正式多帳號權限系統（見第 3 節決策 1）。「使用者」是一份姓名/部門/職級名冊，用於在測試頁面套用權限身分做驗證，不具備登入密碼。
- 權限判定為**檔案層級**（file-level），不做逐段落（per-chunk）不同機密等級的精細化設定——與現有 `links_to`/`linked_attachments` 一致，透過「已向量化資料管理與刪除」頁面選定檔案後批次套用到該檔案全部段落（Points）。
- `semantic_db_query`（語義資料庫查詢法）查詢的是 `source == "db_query_profile"` 的獨立 Profile 向量，本來就與一般文件 Chunk 隔離（見 [04_DB_SCHEMA.md 第 4.2 節](../04_DB_SCHEMA.md)），不在本次權限過濾範圍內。

---

## 2. 名詞定義

| 名詞 | 說明 |
|---|---|
| 機密文件 (Confidential Document) | 知識庫中被標記 `is_confidential = true` 的檔案，其所有 Points 皆帶有相同的機密設定。 |
| 機密等級 (Confidential Level) | 1~10 的整數，**數字越低代表越機密**。未標記機密的文件視為對所有人開放，無此欄位限制。 |
| 職級 (Job Title / Level) | 使用者名冊中每個人的職等，對應一個 1~10 的數字：一般人員=10、組長=8、課長=7、經理=6、總經理=4，或「自訂」由使用者輸入任意 1~10 數字。 |
| 使用者名冊 (User Roster) | MongoDB `users` Collection，儲存姓名/部門/職級，供「模擬使用者」下拉選單使用，**不是登入帳號**。 |
| 模擬使用者 (Simulate User) | 測試頁面上的一個開關；勾選並選定使用者後，該次檢索/對話請求會依該使用者的職級與部門執行權限過濾；不勾選時行為與現在完全相同（無過濾）。 |
| 排除清單 (Excluded Items) | 檢索完成、權限過濾後，因權限不足被剔除的段落清單，僅顯示中繼資料（檔名、段落範圍、排除原因），不顯示實際內容。 |

---

## 3. 已與使用者確認之關鍵決策

在動工前透過 `AskUserQuestion` 確認以下 4 個高影響決策，後續設計皆以此為準：

1. **使用者的本質**：純角色名冊（不具帳號密碼，不影響現有單一共用登入），僅供「模擬使用者」做權限測試。
2. **存取規則**：`使用者職級數字 <= 文件機密等級數字` 才可存取。例：總經理(4) 可讀取等級 4~10 的文件，讀不到等級 1~3（留給更高階自訂角色，例如董事長自訂=1）；一般人員(10) 只能讀取等級剛好 10 的文件。
3. **部門邏輯**：文件部門為**多選**（可歸屬多個部門，未設定=不限部門），使用者部門為單選；只要使用者部門存在於文件的部門清單中即視為部門符合。機密等級與部門兩個條件是 **AND** 關係，需同時滿足才能存取。
4. **排除清單內容**：只顯示 metadata（檔名、段落範圍、機密等級、排除原因），**絕不顯示被排除段落的實際內容**。

---

## 4. 資料模型設計

### 4.1 MongoDB `departments` — 部門主檔（新增）
比照既有 `tags`/`class_options` 的最簡單 pattern（[tag.py](../../backend/models/tag.py)）：
```python
class Department(Document):
    name: Indexed(str, unique=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "departments"
```

### 4.2 MongoDB `users` — 使用者名冊（新增）
```python
JOB_TITLE_LEVELS = {
    "一般人員": 10,
    "組長": 8,
    "課長": 7,
    "經理": 6,
    "總經理": 4,
    # "自訂"：level 由前端輸入，範圍 1~10，後端驗證
}

class UserProfile(Document):
    name: str
    department: str        # 單選，儲存 Department.name
    job_title: str          # "一般人員" | "組長" | "課長" | "經理" | "總經理" | "自訂"
    level: int               # 1~10；非自訂時由後端依 JOB_TITLE_LEVELS 帶入，自訂時採用使用者輸入值
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "users"
        indexes = ["department", "-created_at"]
```
> Collection 命名為 `users`、Model 命名為 `UserProfile`（避開與認證概念的 `User` 混淆），需在 [mongodb.py](../../backend/models/mongodb.py) 的 `init_beanie(document_models=[...])` 清單新增 `Department`、`UserProfile`（比照現有 15 個 Collection 的註冊方式，[mongodb.py:16-31](../../backend/models/mongodb.py)）。

### 4.3 Qdrant Point Payload 新增欄位
延續 [embedding.py:427-444](../../backend/routers/embedding.py) 的 payload 結構與 [04_DB_SCHEMA.md 4.2 節](../04_DB_SCHEMA.md)「條件性透傳欄位」慣例，新增：
```json
{
  "is_confidential": false,
  "confidential_level": null,
  "confidential_departments": []
}
```
- **不在初次向量化流程寫入**：與 `links_to`/`linked_attachments` 一致，這三個欄位只透過「已向量化資料管理與刪除」頁面事後批次設定（見 5.4／6.3），初次上傳/向量化不出現這三個 key。
- 所有讀取都用防禦性 `payload.get(key, 預設值)`，缺欄位（既有舊資料）一律視為「非機密、無部門限制」，符合「未勾選代表可以被全部人讀取」的需求。

---

## 5. 後端設計

### 5.1 新增 Router：`backend/routers/users.py`
比照 [embedding.py:546-619](../../backend/routers/embedding.py) 的 tags/classes CRUD 風格，路徑 `/api/users/*`：

| Method | Path | 說明 |
|---|---|---|
| GET | `/api/users/departments` | 回傳 `List[str]`（部門名稱） |
| POST | `/api/users/departments` | Body `{name}`，新增部門 |
| DELETE | `/api/users/departments/{id}` | 刪除部門（僅刪主檔，不級聯清除已設定該部門的機密文件或使用者，比照 `attachments` 刪除不級聯的既有慣例） |
| GET | `/api/users` | 回傳使用者名冊清單（含 `id`/`name`/`department`/`job_title`/`level`） |
| POST | `/api/users` | 新增使用者。Body `{name, department, job_title, level}`；`job_title != "自訂"` 時後端以 `JOB_TITLE_LEVELS` 覆寫 `level`（忽略前端傳入值，避免不一致）；`job_title == "自訂"` 時驗證 `1 <= level <= 10`，否則回 400。 |
| DELETE | `/api/users/{id}` | 刪除使用者 |

全部掛在既有的 `Depends(get_current_user)` 保護下（與其他 router 一致，單一共用登入即可操作名冊，不需要额外權限分級）。

**錯誤處理需比照既有慣例明確補上**（審查意見 2，已依專案既有寫法調整）：
- **部門重複新增**：`Department.name` 為 `Indexed(str, unique=True)`。**比照 [`create_tag`](../../backend/routers/embedding.py) 既有寫法**（[embedding.py:566-573](../../backend/routers/embedding.py)：先 `find_one` 預查、命中則 400，而非捕捉 `DuplicateKeyError`），`POST /api/users/departments` 也應先 `Department.find_one(Department.name == request.name)`，存在則回 `HTTPException(400, "部門 '{name}' 已存在")`，維持與 `create_tag` 一致的錯誤處理模式。
- **職級分類驗證**：`POST /api/users` 時，若 `job_title` 不在 `{"一般人員", "組長", "課長", "經理", "總經理", "自訂"}` 集合中，回 400「不合法的職級分類」；若 `job_title == "自訂"` 但 `level` 不在 `1~10` 範圍，回 400「自訂職級數字須介於 1~10」。兩者皆屬「Fail loudly」（見 [AGENT.md](../../AGENT.md) 第 6 節）而非靜默 clamp 或忽略。

### 5.2 新增 Service：`backend/services/permission_service.py`
核心權限判定邏輯，供 `rag.py` 與 `retrieval.py` 共用：
```python
class PermissionService:
    @classmethod
    async def get_user(cls, user_id: Optional[str]) -> Optional[UserProfile]:
        """user_id 為 None／查無此人 一律回傳 None，呼叫端視為『未模擬使用者』"""
        ...

    @classmethod
    def filter_results(cls, raw_results: List[dict], user: Optional[UserProfile]) -> Tuple[List[dict], List[dict]]:
        """
        user is None（未勾選模擬使用者）：直接回傳 (raw_results, [])，不做任何過濾，
        維持現有行為零改變。
        user 有值：逐一檢查每個候選片段的 metadata，
        - is_confidential 非 True → 放行
        - confidential_level 存在且 user.level > confidential_level → 排除
        - confidential_departments 非空且 user.department 不在其中 → 排除
        回傳 (放行清單, 排除清單)，排除清單每筆帶 `_exclusion_reason` 文字。
        """

    @classmethod
    def build_exclusion_summary(cls, excluded: List[dict]) -> str:
        """
        依 (filename, reason) 分組，組成人類可讀文字，例如：
        排除 [年度財報.pdf] 段落 #12~#15，原因：檔案權限等級: 3，王小明（一般人員，等級10）權限不足
        排除 [人事規章.docx] 段落 #4，原因：部門限制: 僅限「人資部、法務部」，王小明所屬部門「業務部」不符
        （段落範圍以該分組內最小～最大 chunk_index 顯示，為簡化呈現，非嚴格逐一列舉；
        僅顯示檔名與段落範圍等 metadata，不含實際內容，符合決策 4）
        """
```

### 5.3 `QdrantService` 擴充
**a) `get_unique_metadata()` 擴充**（[qdrant_service.py:923-1010](../../backend/services/qdrant_service.py)）：`with_payload` 清單新增 `is_confidential`/`confidential_level`/`confidential_departments`，`structured_map[fn]` 比照 `links_to` 寫法帶出這三個欄位（**取該檔案任一 Point 的值即可，因為批次設定保證同檔案所有 Points 一致**），供前端 `VectorManagementTab.vue` 選定檔案時預填目前設定。
> 注意：此結構化 map 目前也會被步驟 2（Instruct LLM 語義解析）的 Prompt 引用（見 [02_ARCHITECTURE.md](../02_ARCHITECTURE.md) 簽章流程說明）。**新欄位不應注入進該 Prompt**——與查詢解析無關，且不必要地暴露機密設定字串給语義解析用的 LLM。
> **已查證無虞**（審查意見 3）：[`embedding_service.py:199-224`](../../backend/services/embedding_service.py) 組裝 Prompt 時是針對 `structured_metadata` 每筆項目**顯式枚舉** `item.get("class")`／`item.get("tags")`／`item.get("links_to")` 三個 key，其餘 key（包含本次新增的 `is_confidential`/`confidential_level`/`confidential_departments`）不會被讀取進 Prompt。因此即使 `structured_metadata` 回傳給前端的 dict 裡帶有機密欄位，也不會外洩進語義解析 Prompt，**此項不需要額外程式碼變更去「排除」新欄位**，維持現狀寫法即可安全。

**b) 新增 `update_permissions_by_filename()`**，完全比照 [`update_links_to_by_filename`](../../backend/services/qdrant_service.py) / [`update_attachments_by_filename`](../../backend/services/qdrant_service.py)（[qdrant_service.py:1169-1242](../../backend/services/qdrant_service.py)）的 scroll → `set_payload` 模式：
```python
@classmethod
async def update_permissions_by_filename(
    cls, collection_name: str, filename: str,
    is_confidential: bool, confidential_level: Optional[int], confidential_departments: List[str]
) -> int:
    # 1. scroll 取得該 filename 所有 Point ID（比照既有寫法，limit=10000）
    # 2. client.set_payload(payload={
    #      "is_confidential": is_confidential,
    #      "confidential_level": confidential_level,
    #      "confidential_departments": confidential_departments
    #    }, points=point_ids)
    # 3. 回傳更新筆數
```

### 5.4 `backend/schemas/retrieval.py` 擴充
```python
class UpdatePermissionsRequest(BaseModel):
    filename: str
    is_confidential: bool
    confidential_level: Optional[int] = None
    confidential_departments: List[str] = Field(default_factory=list)

class ExcludedResultItem(BaseModel):
    filename: str
    chunk_indices: List[Any] = Field(default_factory=list)
    reason: str

# SearchParams 新增一個欄位（緊接既有欄位之後，預設 None 代表不模擬，行為零改變）：
    simulated_user_id: Optional[str] = Field(default=None)

# RetrievalMetadata 新增（供前端徽章顯示已設定的機密狀態）：
    is_confidential: Optional[bool] = None
    confidential_level: Optional[int] = None
    confidential_departments: Optional[List[str]] = Field(default_factory=list)

# RetrievalResponse 新增：
    excluded_items: List[ExcludedResultItem] = Field(default_factory=list)
```

### 5.5 `backend/routers/retrieval.py` 整合
**`/search`**（[retrieval.py:23-122](../../backend/routers/retrieval.py)）與 **`/semantic-hybrid-search`**（[retrieval.py:124-256](../../backend/routers/retrieval.py)）：在取得 `raw_results` 之後、組裝 `RetrievalResultItem` 清單之前，插入：
```python
simulated_user = await PermissionService.get_user(request.params.simulated_user_id)
raw_results, excluded = PermissionService.filter_results(raw_results, simulated_user)
```
後續組裝 `results` 只用過濾後的 `raw_results`（未被過濾掉的維持現有邏輯完全不動）；`excluded` 依 filename 分組轉成 `List[ExcludedResultItem]` 塞進 response 的 `excluded_items`。**這個過濾套用在兩個端點、涵蓋 `vector`/`hybrid`/`semantic_hybrid`/`semantic_hybrid_feedback`/`semantic_hybrid_attachment` 全部既有查詢法**，對應前端需求「檢索模式勾選後套用到每個檢索模式」。`simulated_user_id` 為 `None` 時 `filter_results` 直接原樣放行，不影響現有任何行為。

**新增 `POST /knowledge-bases/{knowledge_base_id}/files/update-permissions`**，完全比照 [`update_file_links`](../../backend/routers/retrieval.py)（[retrieval.py:430-476](../../backend/routers/retrieval.py)）的結構：驗證 kb_id、驗證 kb 存在、驗證 filename 非空、呼叫 `QdrantService.update_permissions_by_filename(...)`、`invalidate_metadata_cache`、更新 `kb.updated_at`、回傳 `{message, updated_count}`。

### 5.6 `backend/routers/rag.py` 整合
**`ChatParams`**（[rag.py:28-42](../../backend/routers/rag.py)）新增：
```python
simulated_user_id: Optional[str] = None
```

**插入點需修正為兩處，不能只在迴圈前插一次**（審查意見 1，重點修正）：

原規劃打算在 [rag.py:463-472](../../backend/routers/rag.py) 兩分支收斂之後、[rag.py:474](../../backend/routers/rag.py) 迴圈前统一插入一次過濾，但 `search_type in ("semantic_hybrid", "semantic_hybrid_feedback", "semantic_hybrid_attachment")` 分支（[rag.py:417-462](../../backend/routers/rag.py)）裡，**第 439-462 行「語義混合附件查詢法：收集並查詢關聯附件」這段邏輯，發生在 rerank／feedback boost 之後、但仍在 if 分支內部**——若過濾動作放在 if/else 收斂後的第 473 行才做，會導致：使用者權限不足以讀取的機密文件，其 `linked_attachments` 仍會在第 442-447 行被收集，對應的 `Attachment` 紀錄仍會在第 450-460 行被查出並塞進 `attachments_to_send`（[rag.py:455-460](../../backend/routers/rag.py)），這份清單最終會透過 `event: sources` 送給前端（[rag.py:803](../../backend/routers/rag.py)），即使該機密文件本身的 chunk 之後在 474 行迴圈被過濾掉、不出現在 `sources` 裡，**附件的檔名/說明/下載連結仍已經外洩**。

正確插入點：
- **if 分支（two-step 家族）**：在 [rag.py:437](../../backend/routers/rag.py)（`feedback_boost_applied = True` 之後）與 [rag.py:439](../../backend/routers/rag.py)（`if search_type == "semantic_hybrid_attachment"` 之前）之間插入：
  ```python
  simulated_user = await PermissionService.get_user(params.simulated_user_id if params else None)
  raw_results, excluded_items = PermissionService.filter_results(raw_results, simulated_user)
  ```
  使第 440-462 行的附件收集邏輯讀到的 `raw_results` 已經是過濾後的清單，機密文件的 `linked_attachments` 根本不會被枚舉到。
- **else 分支（`search_similar`，[rag.py:463-472](../../backend/routers/rag.py)）**：該分支沒有附件收集邏輯，維持原規劃——在第 472 行取得 `raw_results` 之後立即呼叫同樣的過濾（`simulated_user` 只需解析一次，可在 if/else 之前統一算好傳入兩處）。

兩分支都過濾完成後才進入 [rag.py:474](../../backend/routers/rag.py) 開始的 `for idx, item in enumerate(raw_results):` 迴圈，之後既有迴圈（組 `sources`/`context_parts`）完全不動，**因為 `raw_results` 已經是過濾後的清單，被排除的內容不會進入 `sources`，也就永遠不會被送進 LLM Context 或回傳給前端**——落實「不顯示實際內容」的決策，同時堵住上述附件外洩的路徑。

**排除訊息顯示**：[rag.py:560-581](../../backend/routers/rag.py) 現有的 `vector_search` step 成功/警告訊息（`search_details`）後方，若 `excluded_items` 非空，附加 `PermissionService.build_exclusion_summary(excluded_items)`，與既有 `feedback_boost_applied` 的附加訊息寫法（[rag.py:568-569](../../backend/routers/rag.py)）相同模式。

**Early Exit「權限不足」分支**：[rag.py:628-633](../../backend/routers/rag.py) 現有邏輯是「`context_str` 為空 → 檢查 `raw_results` 是否非空 → 非空代表『找到但相似度不足門檻』」。需要在此之前新增一個更早的判斷分支，區分「相似度不足」與「權限不足」兩種情境：
```python
permission_blocked_all = bool(excluded_items) and not raw_results and not has_attachments
if permission_blocked_all and search_type != "semantic_db_query" and request.knowledge_base_id:
    denial_msg = (
        "⚠️ **權限不足，無法提供回答**\n\n"
        f"檢索到相關內容，但依目前模擬使用者「{simulated_user.name}」的權限不足，已排除以下段落：\n\n"
        f"{PermissionService.build_exclusion_summary(excluded_items)}"
    )
    # 比照既有 skipped_msg 分支（rag.py:628 之後）的事件序列與 return 方式產生 conclusion/chunk/sources/done 事件
    ...
    return
```
> 實作時需完整讀取 [rag.py:628-680 一帶](../../backend/routers/rag.py) 既有 Early Exit 分支實際送出的事件序列（`step: conclusion`、`chunk` 系列、`sources`、`done` 的確切格式），比照其寫法補完此分支，此處僅為示意。**判斷式刻意寫成 `not raw_results`（過濾後為空）而非 `not context_str`**，是為了不影響既有「找到候選但相似度低於 AI 總結門檻」的分支（那個情境 `raw_results` 非空，只是 `context_parts` 空，屬於既有邏輯，不應被本次改動誤判為權限問題）。

---

## 6. 前端設計

### 6.1 新增路由與側邊選單
- [router/index.js](../../frontend/src/router/index.js)：新增 `{ path: '/role-settings', name: 'RoleSettings', component: RoleSettingsView, meta: { requiresAuth: true } }`。
- [AppSidebar.vue:12-43](../../frontend/src/components/common/AppSidebar.vue) 的 `menuItems` 陣列新增一筆「角色設定」項目（含 icon），比照現有寫法插入清單中。

### 6.2 新增 `frontend/src/views/RoleSettingsView.vue`
沿用專案既有的深色卡片風格（`bg-[#111827]/70 border border-white/8 rounded-2xl` 等 class，比照 [VectorManagementTab.vue:270](../../frontend/src/components/embedding/VectorManagementTab.vue)），分兩個區塊：

**a) 部門管理**：文字輸入框 + 「新增」按鈕 + 已有部門清單（每筆帶刪除按鈕），呼叫新增的 `userService.js` 對應方法。

**b) 使用者名冊管理**：
- 表單：姓名（文字輸入）、部門（下拉單選，選項來自部門管理清單）、職級（下拉：一般人員/組長/課長/經理/總經理/自訂）；選「自訂」時額外顯示一個 1~10 數字輸入框。
- 「新增使用者」按鈕送出。
- 下方表格列出既有使用者（姓名/部門/職級/等級/建立時間/刪除按鈕）。

### 6.3 `VectorManagementTab.vue` 新增「機密權限設定」區塊
緊接在既有「設定關聯附件」區塊之後（[VectorManagementTab.vue:362-402](../../frontend/src/components/embedding/VectorManagementTab.vue)），完全比照該區塊「勾選/多選 + 儲存按鈕」的 UI 與資料流模式：
- `isConfidential`（checkbox）、`confidentialLevel`（1~10 slider 或 select，僅 `isConfidential` 為 true 時顯示）、`confidentialDepartments`（部門多選 checkbox list，來源為 6.2 部門管理清單，`allDepartments` 比照現有 `allAttachments` 的 `fetchAllAttachments` 模式抓取）。
- 選定檔案時（`fetchManagementMetadata`/`loadManagementPoints`）比照 [VectorManagementTab.vue:82-83、98-100](../../frontend/src/components/embedding/VectorManagementTab.vue) 從 `managementStructuredMetadata` 預填三個欄位目前值。
- 「儲存機密權限設定」按鈕呼叫 `retrievalService.updatePermissions(...)`（見 6.5），完成後 `fetchManagementMetadata()` + `loadManagementPoints()` 重新整理。
- 段落列表每筆（[VectorManagementTab.vue:454-511](../../frontend/src/components/embedding/VectorManagementTab.vue) 徽章區）新增一個徽章：`point.metadata?.is_confidential` 為 true 時顯示「🔒 機密等級 {{ confidential_level }}」，比照既有 🔗/📎 徽章樣式。

### 6.4 `paramsStore.js` 新增狀態
```js
simulatedUserEnabled: false,
simulatedUserId: null,
```

### 6.5 「模擬使用者」UI（套用到每個檢索模式）
- [RagParamsPanel.vue](../../frontend/src/components/params/RagParamsPanel.vue) 的「檢索模式 (Search Mode)」selector（[RagParamsPanel.vue:116-130](../../frontend/src/components/params/RagParamsPanel.vue)）下方新增一個區塊：勾選「是否模擬使用者」+ 勾選後顯示的使用者下拉選單（選項來自 `userService.listUsers()`，顯示 `姓名（職級/等級/部門）`）。
- [RetrievalTestView.vue](../../frontend/src/views/RetrievalTestView.vue) 的「檢索模式 (Search Type)」選單（[RetrievalTestView.vue:572](../../frontend/src/views/RetrievalTestView.vue)）附近新增相同的勾選+下拉 UI（該頁未使用 `RagParamsPanel.vue`，是獨立內聯 UI，需個別加）。
- 兩處皆綁定同一個 `paramsStore.simulatedUserEnabled`/`simulatedUserId`，因為是共用 Pinia store，狀態天然同步。
- 兩個頁面各自組裝請求 payload 的地方（`RagTestView.vue` 呼叫 `ragService.chat` 前、`RetrievalTestView.vue` 呼叫 `retrievalService.search`/`semanticHybridSearch` 前）需新增：
  ```js
  simulated_user_id: paramsStore.simulatedUserEnabled ? paramsStore.simulatedUserId : null
  ```
  塞進 `params`。**未勾選時固定傳 `null`，後端 `filter_results` 收到 `None` 直接不過濾**，維持零改變的安全預設。

### 6.6 排除清單顯示
- **RAG 對話測試（RagTestView）**：`vector_search` step 的排除文字已經內嵌在既有 step content 字串中（見 5.6）。**已查證無虞（審查意見 4）**：[`MessageBubble.vue:120`](../../frontend/src/components/chat/MessageBubble.vue) 的 step content 顯示區塊已套用 `whitespace-pre-wrap font-mono` class，多行排除摘要文字可直接正確換行呈現，**不需要新建元件或修改樣式**。
- **向量搜尋測試（RetrievalTestView）**：目前結果為一次性 JSON response，非串流，需新增一個獨立區塊顯示 `response.excluded_items`（檔名 + 段落範圍 + 排除原因），比照結果卡片樣式但用警示色（如 `red-500`/`amber-500`）標示，且**不顯示任何內容文字**。

---

## 7. 需同步更新的文件（依 CLAUDE.md 要求）

- [`docs/04_DB_SCHEMA.md`](../04_DB_SCHEMA.md)：新增 `departments`／`users` 兩個 Collection 章節；4.2 節 Qdrant Payload 定義新增三個欄位說明。
- [`docs/03_API_CONTRACT.md`](../03_API_CONTRACT.md)：新增 `/api/users/*` 端點章節；`/api/retrieval/search`、`/semantic-hybrid-search`、`/rag/chat` 的 request/response 補上新欄位；新增 `/api/retrieval/knowledge-bases/{id}/files/update-permissions`。
- 完成實作後依 [AGENT.md](../../AGENT.md) 第 9 節，在 [`docs/DevelopmentProcess/NewFeatures.md`](NewFeatures.md)、[`BackendCorrection.md`](BackendCorrection.md)、[`FrontendCorrection.md`](FrontendCorrection.md) 留下對應紀錄。

---

## 8. 明確不做的事（Out of Scope）

- 不重構現有單一共用登入機制，不新增登入密碼欄位，不做真正的多帳號驗證/授權（決策 1）。
- 不做逐段落（chunk 級）不同機密等級的精細化設定，機密設定為檔案層級，批次套用到整份文件的所有 Points。
- 不對 `semantic_db_query` 查詢法（`db_query_profile` 向量）套用權限過濾，該查詢法本就與一般文件 Chunk 隔離。
- 不做部門/使用者刪除時的級聯清理（例如刪除部門不會自動清掉已設定該部門的機密文件設定），比照現有 `attachments` 刪除不級聯的慣例。
- 不新增稽核紀錄（誰在何時查詢了什麼被排除的內容），如日後需要可另外提案。

---

## 9. 執行步驟 Checklist

**後端**
- [x] `backend/models/department.py`、`backend/models/user_profile.py` 新增，`mongodb.py` 註冊
- [x] `backend/routers/users.py` 新增（部門 + 使用者 CRUD）並掛進 `main.py`
- [x] `backend/services/permission_service.py` 新增
- [x] `backend/services/qdrant_service.py`：`get_unique_metadata` 擴充、新增 `update_permissions_by_filename`
- [x] `backend/schemas/retrieval.py` 擴充（`UpdatePermissionsRequest`/`ExcludedResultItem`/`SearchParams.simulated_user_id`/`RetrievalMetadata` 新欄位/`RetrievalResponse.excluded_items`）
- [x] `backend/routers/retrieval.py`：`/search`、`/semantic-hybrid-search` 整合權限過濾；新增 `/files/update-permissions`
- [x] `backend/routers/rag.py`：`ChatParams.simulated_user_id`、過濾插入點、排除訊息、Early Exit 權限不足分支

**前端**
- [x] `frontend/src/services/userService.js` 新增
- [x] `frontend/src/services/retrievalService.js` 新增 `updatePermissions`
- [x] `frontend/src/stores/paramsStore.js` 新增狀態
- [x] `frontend/src/router/index.js` + `AppSidebar.vue` 新增「角色設定」路由與選單
- [x] `frontend/src/views/RoleSettingsView.vue` 新增（部門管理 + 使用者名冊管理）
- [x] `VectorManagementTab.vue` 新增機密權限設定區塊 + 段落徽章
- [x] `RagParamsPanel.vue`、`RetrievalTestView.vue` 新增「模擬使用者」勾選 + 下拉，並在送出請求處帶入 `simulated_user_id`
- [x] `RetrievalTestView.vue` 新增排除清單顯示區塊

**文件**
- [x] 更新 `docs/04_DB_SCHEMA.md`、`docs/03_API_CONTRACT.md`
- [x] 完成後於 `docs/DevelopmentProcess/NewFeatures.md`／`BackendCorrection.md`／`FrontendCorrection.md` 留紀錄

---

## 10. 實作完成後 Code Review：待修正事項

對照 `git diff` 實際檢查所有新增/修改檔案後發現以下問題，依嚴重程度排序。**第 1 項會導致整個功能在執行期完全無法使用，需優先修正。**

### 10.1 【Critical／功能全面失效】`users.py` 路由被重複掛上 `/api` 前綴，所有 `/api/users/*` 端點實際上都是 404

- **問題**：[`backend/routers/users.py:13`](../../backend/routers/users.py) 自己宣告 `router = APIRouter(prefix="/api/users", tags=[...])`（前綴已經包含 `/api`），但 [`backend/main.py:75`](../../backend/main.py) 掛載時又寫了 `app.include_router(users.router, prefix="/api")`。FastAPI 的 `include_router(prefix=...)` 會把這個前綴**疊加**在 router 自身的 `prefix` 前面，等於實際掛載路徑變成 `/api` + `/api/users/...` = **`/api/api/users`**、**`/api/api/users/departments`** 等，而不是文件（[03_API_CONTRACT.md §17](../03_API_CONTRACT.md)）與前端 `userService.js` 期望的 `/api/users/...`。
- **佐證**：本專案其餘所有 router（`rag.py`、`retrieval.py`、`embedding.py`、`attachment.py` 等）都是遵循「router 自身只宣告模組名稱前綴（如 `prefix="/rag"`），`/api` 前綴統一由 `main.py` 的 `include_router(..., prefix="/api")` 加上去」的既有慣例，只有 `users.py` 這次多打了一份 `/api`。
- **影響範圍（全部會 404）**：
  - `RoleSettingsView.vue` 的部門管理、使用者名冊管理（`userService.getDepartments/createDepartment/deleteDepartment/listUsers/createUser/deleteUser` 全部呼叫失敗）
  - `RagParamsPanel.vue`、`RetrievalTestView.vue` 的「模擬使用者」下拉選單（`loadUsers()` 呼叫失敗，選單永遠是空的「尚無使用者，請先新增」）
  - 連帶導致整個機密權限過濾功能形同虛設——沒有部門、沒有使用者可選，`simulated_user_id` 永遠不會有值送到後端。
- **修正建議**：把 `backend/routers/users.py:13` 改成 `router = APIRouter(prefix="/users", tags=["Users & Departments"])`（拿掉自帶的 `/api`），與其他 router 的慣例一致；`main.py` 的掛載方式不需要改。

### 10.2 【High／功能性 Bug】「刪除部門」按鈕完全無效，且模板上根本沒有刪除入口

- **問題**：[`RoleSettingsView.vue:73-84`](../../frontend/src/views/RoleSettingsView.vue) 的 `handleDeleteDepartment(deptName)` 函式本體只是重新呼叫一次 `userService.getDepartments()`（結果存進未使用的 `allDepts` 後就丟棄）再 `loadDepartments()`，**從頭到尾沒有呼叫 `userService.deleteDepartment(id)`**。函式自己的註解也承認了這件事：「我們可以從清單取得名單重構，但因為 GET /departments 回傳 str[]，我們呼叫 API 的 deleteDepartment 需要找到 object；在這裡先實做直接重新整理」。
- **根因**：`GET /api/users/departments` 依照既有 `tags`/`classes` 慣例只回傳 `List[str]`（純名稱），前端沒有部門的 Mongo `_id` 可用來呼叫 `DELETE /api/users/departments/{id}`，於是這個刪除功能被寫成了空殼。
- **另一個問題**：[`RoleSettingsView.vue:190-201`](../../frontend/src/views/RoleSettingsView.vue) 「Department Chips」的 template 裡，每個部門 chip 只有 `<span>🏢 {{ dept }}</span>`，**沒有任何刪除按鈕綁定 `handleDeleteDepartment`**，所以這個函式目前是連 UI 入口都沒有的死碼；後端已經正確實作好的 `DELETE /api/users/departments/{dept_id}`（[`users.py:71-89`](../../backend/routers/users.py)）永遠不會被呼叫到。
- **修正建議**：`GET /api/users/departments` 改回傳 `List[DepartmentResponse]`（含 `id`/`name`，`users.py` 已經定義好 `DepartmentResponse` 這個 schema，只是 `get_departments` 的 `response_model` 目前寫的是 `List[str]`），或另外新增一支回傳完整物件的端點；`RoleSettingsView.vue` 儲存部門清單為 `{id, name}` 物件陣列，並在部門 chip 上補一個刪除按鈕呼叫 `userService.deleteDepartment(dept.id)`。

### 10.3 【Low／Fail-Open 風險】機密等級比對遇到非預期型別會靜默略過檢查而非報錯

- **問題**：[`permission_service.py:58`](../../backend/services/permission_service.py) `if c_level is not None and isinstance(c_level, int):` — 只有當 `confidential_level` 剛好是 Python `int` 型別時才會執行「使用者職級 <= 文件機密等級」的比對；萬一 Qdrant 回傳的值因為某些非本次功能寫入路徑（例如手動用 Qdrant 工具改過 payload、或未來其他程式碼誤寫入字串/浮點數）而不是 `int`，這個條件會直接跳過、**該筆機密段落就完全不會被等級規則排除**，等同悄悄開放。目前透過本功能唯一的寫入路徑（`UpdatePermissionsRequest.confidential_level: Optional[int]`）不會觸發，機率低，但屬於「靜默跳過安全檢查」的模式，與 [AGENT.md](../../AGENT.md) 第 6 節「失敗要明確說」的精神相牴觸——條件不滿足時應該記 log warning 或用 `int(c_level)` 容錯轉型後仍套用比對，而不是無聲放行。
- **修正建議（低優先，可視情況決定是否處理）**：把型別檢查改成盡量寬容地轉型（例如 `try: c_level_int = int(c_level) except (TypeError, ValueError): c_level_int = None; logger.warning(...)`），或至少在 `isinstance` 判斷失敗時加一行 `logger.warning`，避免未來排查「機密文件為什麼沒被擋下」時毫無線索。

---

## 11. 第二輪 Code Review：功能符合度與文件同步檢查

已重新讀取修正後的程式碼確認：**第 10.1（`users.py` 雙重 `/api` 前綴）、10.2（部門刪除空殼）、10.3（機密等級型別 fail-open）三個問題目前都已正確修正**——`users.py:13` 前綴改為 `/users`；`permission_service.py:58-70` 改為 `try: int(c_level) except (TypeError, ValueError): logger.warning(...)`；`RoleSettingsView.vue` 的部門刪除已串上真正的 `userService.deleteDepartment(dept.id)` 且 UI 補上了 ✕ 按鈕。也確認了修 10.2 造成 `GET /api/users/departments` 回應格式從 `List[str]` 改成 `List[DepartmentResponse]` 這個變動，`VectorManagementTab.vue:69` 的 `fetchDepartments()` 已經用 `.map(d => typeof d === 'string' ? d : d.name)` 做了向下相容處理，沒有連帶壞掉。

對照最初需求逐條重新檢查（前端 1~5、後端 1~4），**功能行為本身九條都已對應實作完成**，沒有發現遺漏的需求項目。這一輪發現的問題集中在**文件（`docs/03_API_CONTRACT.md`、`docs/04_DB_SCHEMA.md`）與實際程式碼之間的落差**——這些文件的同步更新本來就是規劃文件第 7 節與第 9 節 Checklist 明列的項目（且已被勾選為完成），但實際內容有多處對不上，依嚴重程度列出：

### 11.1 【High／文件把存取規則方向寫反，且與同一次改動的另一份文件自相矛盾】

- **問題**：[`docs/04_DB_SCHEMA.md:389`](../04_DB_SCHEMA.md) 寫「檢索與 RAG 流水線在開啟『模擬使用者』身分時，會自動讀取此三欄位進行權限比對（**等級高於文件等級且部門符合才放行**）」。但實際規則（[`permission_service.py:61`](../../backend/services/permission_service.py)）是 `if user.level > c_level_int:` 才會被排除，也就是**使用者等級數字必須「小於等於」文件等級數字才會放行**，數字「高於」文件等級是被排除的條件，剛好寫反。
- **佐證矛盾**：同一天新增的 [`docs/DevelopmentProcess/NewFeatures.md`](NewFeatures.md) 裡對同一段邏輯的描述是正確的：「比對 `user.level <= file.confidential_level` 與 `user.department in file.confidential_departments`」。也就是本次功能自己產出的兩份文件，對同一條存取規則的方向描述互相矛盾，其中 `04_DB_SCHEMA.md` 那句是錯的。這是整個功能裡最核心的安全規則，文件寫反特別容易誤導之後維護這段程式碼的人（尤其是搭配 3.16 節「數字越小機密等級越高」一起讀時更容易看錯方向）。
- **修正建議**：把 `04_DB_SCHEMA.md:389` 改成「使用者等級數字小於等於文件等級數字，且（未設定部門限制，或使用者部門存在於文件部門清單中）才放行」，或直接引用 `NewFeatures.md` 裡已經寫對的版本。

### 11.2 【Medium／`docs/03_API_CONTRACT.md` 多處跟修正後的實際程式碼對不上】

- **§17.1 `GET /api/users/departments`**（[03_API_CONTRACT.md:699-703](../03_API_CONTRACT.md)）：回應範例仍是舊格式 `["研發部", "人資部", "財務部"]`（純字串陣列）。但為了修好 10.2 的部門刪除問題，這支端點的 `response_model` 已經改成 `List[DepartmentResponse]`，實際回應是 `[{"id": "...", "name": "研發部"}, ...]`，文件沒有跟著更新。
- **§17.2 `POST /api/users/departments`**（[03_API_CONTRACT.md:705-714](../03_API_CONTRACT.md)）：回應範例多寫了一個 `"created_at": "2026-07-16T10:00:00Z"` 欄位，但 `DepartmentResponse`（[`users.py:20-22`](../../backend/routers/users.py)）只有 `id`/`name` 兩個欄位，沒有 `created_at`，屬於文件憑空多寫的欄位（非本輪修正造成，初版就這樣）。
- **§17.5 `DELETE /api/users/{user_id}`**（[03_API_CONTRACT.md:754-759](../03_API_CONTRACT.md)）：文件寫回應是 `{"message": "成功刪除使用者"}`，實際程式碼（[`users.py:175`](../../backend/routers/users.py)）回傳的是 `{"message": f"已成功刪除使用者 '{user.name}'"}"`，文字對不起來。
- **完全沒有記錄 `DELETE /api/users/departments/{dept_id}`**：這支端點在 `users.py:71-89` 本來就有實作，這次修 10.2 之後前端終於會真的呼叫到它了，但 `03_API_CONTRACT.md` 第 17 節從頭到尾沒有這一小節（只有 17.1/17.2/17.3/17.4/17.5，缺一支部門刪除）。
- **§4.1 `POST /api/retrieval/search`**（[03_API_CONTRACT.md:136-182](../03_API_CONTRACT.md)）：Response 200 範例（154-180 行）沒有補上新的 `excluded_items` 欄位，`metadata` 物件範例（162-169 行）也沒有補上新的 `is_confidential`/`confidential_level`/`confidential_departments` 三個欄位，跟 `schemas/retrieval.py` 實際的 `RetrievalMetadata`/`RetrievalResponse` 定義對不齊。
- **文件宣稱更新了「§4.8」但實際不存在**：[`docs/DevelopmentProcess/NewFeatures.md`](NewFeatures.md) 寫「更新 `docs/03_API_CONTRACT.md`（§3.1, §4.1, §4.8, §17）」，但 `03_API_CONTRACT.md` 第 4 節的端點編號到 **§4.7（`update-attachments`）就直接接到「## 5. 準確度評估 API」**，根本沒有 §4.8。也就是 `POST /api/retrieval/knowledge-bases/{id}/files/update-permissions` 這支新端點——本次功能新增的兩支寫入端點之一——完全沒有被寫進 API 文件。
- **修正建議**：補上一節「§4.8 POST `/api/retrieval/knowledge-bases/{knowledge_base_id}/files/update-permissions`」（可完全比照 §4.6/§4.7 的格式），並修正上述幾處範例內容使其與目前 `schemas/retrieval.py`、`users.py` 的實際欄位一致。

### 11.3 【Low／邊界情境：刪除模擬使用者後，前端殘留的舊選取狀態會讓過濾「靜默失效」而非「安全預設拒絕」】

- **問題**：`paramsStore.simulatedUserId` 是存在瀏覽器端 Pinia store 裡的 ID 字串，一旦使用者在「角色與權限設定」頁刪除了某個模擬使用者，其他分頁／同一分頁稍後送出的請求若仍帶著這個已刪除的 `simulated_user_id`，後端 `PermissionService.get_user()`（[`permission_service.py:11-23`](../../backend/services/permission_service.py)）在 `UserProfile.get(obj_id)` 查無此人時會回傳 `None`，而 `filter_results()` 對 `None` 的處理是「視為未啟用模擬使用者、全數放行」（[`permission_service.py:38-39`](../../backend/services/permission_service.py)）。也就是說，刪除一個使用者不會讓引用他的請求被拒絕或報錯，而是讓那次請求的權限過濾**整個悄悄關閉**，回到「顯示全部內容」。
- **影響**：屬於邊界情境（需要「模擬使用者被刪除的同時、另一個分頁還留著舊選取」才會觸發），且原始需求沒有明確定義這種情況該怎麼處理，所以不算違反需求，但方向上是 fail-open（悄悄放寬）而不是 fail-closed（悄悄收緊），跟 10.3 屬於同一類風險模式，一併記錄供之後決定是否要處理（例如查無使用者時應該擋下請求並回錯誤，而不是靜默視為不過濾）。

---

## 12. 第三輪確認：11.1～11.3 修正驗證 + 完整需求追溯

重新讀取修正後的程式碼與文件，逐項確認：

- **11.1（存取規則方向寫反）已修正**：[`04_DB_SCHEMA.md:389`](../04_DB_SCHEMA.md) 現在寫「使用者等級數字小於等於文件等級數字，且部門符合時才放行」，方向正確，與 `permission_service.py:86` 的 `if user.level > c_level_int:`（超過才排除）以及 `NewFeatures.md` 的描述三方一致，不再自相矛盾。
- **11.2（`03_API_CONTRACT.md` 多處對不上）已修正**：§17.1／§17.2 的回應範例已改成 `{"id": ..., "name": ...}` 物件格式（不再是舊的 `List[str]`，也不再多寫不存在的 `created_at`）；新增了原本完全缺漏的 **§17.3 `DELETE /api/users/departments/{dept_id}`**（訊息文字 `已成功刪除部門 '研發部'` 與 [`users.py:89`](../../backend/routers/users.py) 一致）；§17.6（原 §17.5）`DELETE /api/users/{user_id}` 的回應範例已改成 `已成功刪除使用者 '王小明'`，與程式碼一致；**§4.8 `update-permissions`** 端點現在也確實存在（[03_API_CONTRACT.md:256-271](../03_API_CONTRACT.md)），§4.1 的 Response 範例也補上了 `excluded_items` 與 `is_confidential`/`confidential_level`/`confidential_departments`。
- **11.3（刪除使用者後過濾靜默失效）已修正，且採用了比原建議更完整的方案**：[`permission_service.py:11-48`](../../backend/services/permission_service.py) 的 `get_user()` 在查無此人（含已刪除、ID 格式錯誤）時，不再回傳 `None`，而是回傳一個合成的 Fail-Closed 佔位身分（`level=10`／`department="無部門"`／`name="已無效之模擬使用者"`），並記錄 `logger.warning`。由於 `level=10` 是本系統定義中最低的存取層級（一般人員），加上 `department="無部門"` 不會比對到任何真實部門，這個合成身分實際上只能看到「未設任何部門限制、且機密等級剛好為 10」的最低敏感度機密文件，其餘一律排除——是目前系統可表達範圍內最保守的預設值，優於原本「完全不過濾」的行為。

### 完整需求追溯（對照使用者最初提出的 9 條需求）

| # | 需求 | 狀態 | 對應實作 |
|---|---|---|---|
| 前端1 | 已向量化資料管理與刪除：勾選機密＋等級 1~10＋部門，未勾選=全部人可讀，全部段落都要加上 | ✅ | `VectorManagementTab.vue` 機密權限控管設定區塊 + `update_permissions_by_filename` 批次套用全檔 Points |
| 前端2 | 角色設定選單：姓名/部門/職級（一般人員10、組長8、課長7、經理6、總經理4、自訂） | ✅ | `RoleSettingsView.vue` + 側邊欄「角色與權限設定」 |
| 前端3 | RAG測試/向量搜尋測試：勾選模擬使用者＋下拉選使用者 | ✅ | `RagParamsPanel.vue`／`RetrievalTestView.vue` 模擬使用者區塊 |
| 前端4 | 檢索模式勾選後套用到每個檢索模式 | ✅ | `filter_results` 套用於 `/rag/chat`、`/retrieval/search`、`/retrieval/semantic-hybrid-search`，涵蓋 vector/hybrid/semantic_hybrid/semantic_hybrid_feedback/semantic_hybrid_attachment |
| 前端5 | 過程顯示排除文字，總結顯示「權限不足無法提供回答」 | ✅ | `vector_search` step 附加 `build_exclusion_summary`；`permission_blocked_all` 時的 Early Exit 回覆固定以「⚠️ 權限不足，無法提供回答」開頭 |
| 後端1 | 使用者資料存 MongoDB | ✅ | `UserProfile`／`users` collection |
| 後端2 | 部門資料存 MongoDB | ✅ | `Department`／`departments` collection |
| 後端3 | Qdrant Point 新增權限 key，無 key 預設全部人可讀 | ✅ | `is_confidential`/`confidential_level`/`confidential_departments`，防禦性 `payload.get(...)` 預設開放 |
| 後端4 | 向量查詢後執行權限檢查並顯示排除清單（檔名/段落範圍/原因） | ✅ | `PermissionService.filter_results` + `build_exclusion_summary` |

九條需求逐一對照程式碼後皆已對應實作完成，這一輪沒有找到新的功能性缺陷或需求缺口。連同已驗證修正的 11.1～11.3，本規劃文件記錄的所有已知問題目前皆為已解決狀態。

---

## 13. 使用者實測發現的 BUG（2026-07-16）：機密設定未能覆蓋檔案的「全部段落」，導致部分片段仍可被無權限使用者查到

### 13.1 測試情境與觀察到的現象

測試對象：`GP51建立備份營運中心.docx`，透過「已向量化資料管理與刪除」設定為機密文件、**機密等級 7**、可讀取部門 **資訊部**（未勾選研發部）。

| 使用者 | 部門 | 職級 | 等級 | 預期 | 實測結果 |
|---|---|---|---|---|---|
| eric | 資訊部 | 經理 | 6 | 應可看到（6 ≤ 7 且部門符合） | ✅ 正常 |
| harry | 資訊部 | 一般人員 | 10 | 應排除（10 > 7） | ❌ 仍可查到並被 AI 引用回答 |
| jerry | 研發部 | 課長 | 7 | 應排除（部門不符：研發部不在「資訊部」清單中） | ❌ 仍可查到 |

實測截圖佐證：
1. 「已向量化資料管理與刪除」畫面顯示目前設定為 `is_confidential` 已勾選、**機密等級下拉選單顯示「等級 7」**、部門僅勾選「資訊部」。
2. 同一份檔案裡的一個 Point（`chunk_type: image`、`chunk_index: 16`、帶 `parent_id`）直接用 Qdrant 內建 Dashboard 查看，payload 卻顯示 **`"confidential_level": 10`**（不是 7），`"confidential_departments": ["資訊部"]`（部門這項與 UI 一致）。
3. 模擬 harry（資訊部／一般人員／等級 10）跑 RAG 對話測試，`search_type: hybrid`，成功召回並在 AI 總結中引用了 `GP51建立備份營運中心.docx` 段落 #1、#3~5、#6~10、#16~20、#21~24...等多段內容，沒有出現任何「權限過濾摘要」排除訊息。

### 13.2 根因分析

**這不是權限比對邏輯（`PermissionService.filter_results`）本身的 Bug**——比對規則（等級 `user.level > c_level` 才排除、部門 `user.department not in c_depts` 才排除）在前兩輪 Review 已反覆驗證方向正確。問題出在**批次寫入端**：[`QdrantService.update_permissions_by_filename()`](../../backend/services/qdrant_service.py:1262-1306) 是用 `Filter(must=[FieldCondition(key="filename", match=MatchValue(value=filename))])` 這種**精確字串比對**去 `scroll` 找出「這個檔名底下所有 Points」，再對這批 `point_ids` 一次性 `set_payload`。這支函式本身邏輯沒錯——只要一次執行成功，比對到的所有 Points 一定會被寫入**同一個**機密等級/部門值，不可能同一次寫入卻讓不同 Points 出現不同的 `confidential_level`。

**但截圖 2 的證據，直接證明「至少有一個 Point 沒有被最近一次的儲存動作覆蓋到」**：UI 目前顯示等級 7，代表最後一次儲存送出的是 `confidential_level: 7`；而這個 image 型別的 Point 卻停留在 `confidential_level: 10`。合理推論：管理者測試過程中可能先以「等級 10」存過一次（例如先拿寬鬆值驗證流程），之後才改成「等級 7」再存一次——**如果第二次儲存時，這個 Point 因為某種原因沒有被 `scroll` 的 filename filter 掃到，它就會停留在第一次寫入的等級 10，UI 卻因為讀到的是（來自其他有更新到的 Points 匯總出的）`structured_metadata` 而顯示「等級 7」**，兩者因此不同步。

Jerry 的情況（部門不符仍被放行）用同一個根因也能解釋：如果檔案裡還存在**從未被任何一次「儲存機密權限設定」動作覆蓋到**的 Points（例如 `is_confidential` 欄位根本不存在或仍是 `false`），這些 Points 在 `filter_results()` 裡第一步 `if not is_confidential: allowed.append(item); continue` 就會直接放行、完全不檢查部門——Jerry 的查詢很可能就是命中了這批「漏更新」的 Points。

**這代表「記得全部段落都要加上」（前端需求 1 明確提出的要求）目前並未被穩定保證**：只要檔案裡有任何 Points 因為某種原因沒被 `update_permissions_by_filename` 的 filename 過濾條件掃到，它們就會永久停留在舊值（或永遠不受機密設定保護），而且**沒有任何機制會提醒管理者發生了這種情況**。可能導致「漏掃」的具體情境包括：
- 同一個檔名被**重複向量化/重新上傳**過（例如先上傳一次、發現問題又重新上傳一次但沒有先用「刪除整個檔案」清掉舊 Points），導致向量庫中同時存在多個世代的 Points，較舊世代的某些 Points 若在最近一次「儲存機密權限設定」**之後**才被其他操作動到，或字串比對出現差異，就可能沒被涵蓋到。
- 中文檔名的 Unicode 正規化形式（NFC／NFD）在不同寫入路徑（例如原始上傳 vs. 图片子區塊另外產生的 Point）之間不一致，導致 `MatchValue(value=filename)` 精確比對失敗，即使畫面上看起來是同一個檔名字串。

### 13.3 目前最大的觀察缺口：儲存結果沒有讓管理者能夠自我核對

[`VectorManagementTab.vue:206-226`](../../frontend/src/components/embedding/VectorManagementTab.vue) 的 `handleSavePermissions()` 呼叫 `retrievalService.updatePermissions(...)` 後，**直接丟棄了回應內容**（`await retrievalService.updatePermissions(...)`，沒有接回傳值），只彈出固定文字「機密權限設定已成功更新！」。但後端 `update_permissions_by_filename()` 其實有回傳 `updated_count`（本次實際覆蓋到的 Points 數），而同一個畫面上方「Chunks List Card」已經有現成的「該檔案在向量庫中共有 `{{ managementPoints.length }}` 個段落」計數（[VectorManagementTab.vue:524](../../frontend/src/components/embedding/VectorManagementTab.vue)）。這兩個數字如果不一致，就是本次踩到的這種「漏掃 Points」情況的直接訊號，但目前完全沒有比對或提示，管理者無從察覺剛剛的儲存動作其實沒有覆蓋到全部段落。

### 13.4 建議的診斷步驟與修正方向

**診斷（不需要改程式碼，可以直接驗證是哪一種情況）**：對 `GP51建立備份營運中心.docx` 什麼都不改，直接再按一次「儲存機密權限設定」，然後重新用 Qdrant Dashboard 檢查同一個 Point（`chunk_index: 16` 的 image 型別 Point）：
- 若這次變成 `confidential_level: 7` 了 → 代表該 Point 其實會被 filename filter 掃到，只是先前剛好卡在兩次儲存動作中間的舊值，之後重存一次即可修復（但仍建議做下面的修正，避免下次又發生同樣的誤判空窗）。
- 若再存一次後仍然是 `confidential_level: 10` → 代表這個 Point **永遠不會**被目前的 `filename` 精確比對掃到，需要進一步排查是否有多世代重複 Points 或檔名字串編碼不一致的問題，並手動用 Qdrant 的 `scroll` 直接列出所有 `filename == "GP51建立備份營運中心.docx"` 的 Points 總數，和「該檔案在向量庫中共有 X 個段落」顯示的數字比對是否相符。

**修正方向（待使用者確認是否要排入下一輪修正）**：
1. `handleSavePermissions()` 應該接住 `retrievalService.updatePermissions(...)` 的回應，把 `updated_count` 顯示在成功訊息裡（例如「機密權限設定已成功更新（共 12 筆段落）」），並在 `updated_count !== managementPoints.value.length` 時額外跳出警示，提醒管理者「畫面顯示 N 個段落，但這次只更新了 M 筆，可能有段落未被涵蓋」——這是成本最低、最直接能攔住這整類問題的修正。
2. 比照這個發現重新檢視「刪除整個檔案」（`delete-by-filename`）、「設定關聯檔案」（`update-links`）、「設定關聯附件」（`update-attachments`）是不是也共用同一種精確字串 `MatchValue(filename)` 比對模式、因此potentially有同樣的「漏掃」風險——這幾個既有功能目前後果較輕（漏刪/漏關聯不是資安問題），但機密權限這個功能一旦漏掃，後果是機密外洩，风险等级不同，優先度應該最高。
3. 確認管理者操作流程：同一檔名如果需要「重新上傳」，應該先用「刪除整個檔案」清掉舊 Points 再重新向量化，而不是直接對同檔名再次上傳疊加——但目前系統沒有在重複上傳同檔名時提出任何警告，這點也建議之後評估是否要加提示（非本次机密权限功能範圍，屬既有上傳流程的既存缺口，僅在此一併記錄以利追查根因）。

> 本節分析基於程式碼比對與使用者提供的截圖證據推論，因為專案慣例是使用者自行於瀏覽器測試、不由 AI 代為開啟瀏覽器驗證，所以無法在此直接重現並 100% 鎖定「漏掃」發生的確切原因（重複上傳 vs. 編碼差異 vs. 其他），已在 13.4 提供可由使用者直接執行、不需要改程式碼的診斷步驟來縮小範圍。

### 13.5【後續更新，2026-07-16】使用者已重新確認：chunk_index 16 這個 Point 目前確實是 `confidential_level: 7`

使用者依 13.4 的診斷步驟重新對「文件機密等級」欄位再次確認並儲存後，回報 Qdrant Dashboard 顯示同一個 Point（`chunk_index: 16`，image 類型）的 `is_confidential: true`、`confidential_level: 7`、`confidential_departments: ["資訊部"]`，跟目前 UI 設定完全一致——**13.2 假設的「Points 漏掃/停留在舊值」這個根因，至少對這個 Point 而言已經排除**。但同一次 RAG 對話測試（模擬 harry：資訊部／一般人員／等級 10），檢索模式 `hybrid`，向量資料查詢步驟明確寫出「成功召回 **2** 筆相關段落」，AI 結論卻引用了「段落 #1、#3~5、#6~10、#11、#12~14、#15、#16~20、#21~24、#25~29、#30~34、#35~38、#39、#43、#44」——幾乎橫跨整份文件的段落範圍，遠超過這次檢索到的 2 筆，而且整段回覆完全沒有出現「權限過濾摘要」排除訊息。這代表**還有另一個獨立的根因**，見下一節。

### 13.6【使用者要求確認，2026-07-16】後端向量查詢後是否確實有排除權限不足內容的語法

逐字確認 [`backend/routers/rag.py`](../../backend/routers/rag.py) 目前的程式碼，**答案是肯定的：語法確實存在，位置也正確**。這次實測用的檢索模式是 `hybrid`，對應的是 `search_type` 不屬於 `semantic_hybrid` 家族的 `else` 分支：

```python
else:
    raw_results = await QdrantService.search_similar(
        collection_name=kb.qdrant_collection_name,
        query_vector=query_vector,
        query_text=search_query_text,
        search_type=search_type,
        top_k=top_k,
        score_threshold=score_threshold,
        filter_tags=filter_tags
    )
    # 執行機密權限過濾 (標準/混合檢索分支)
    raw_results, excluded_items = PermissionService.filter_results(raw_results, simulated_user)
```
（[rag.py:472-483](../../backend/routers/rag.py)），緊接在後面第 491 行才開始 `for idx, item in enumerate(raw_results):` 把結果組進 `sources`／`context_parts`——**過濾語法確實在「拿到向量查詢結果之後、組進總結內容之前」執行，順序沒有問題**，`simulated_user` 也已經在第 310-311 行正確解析過。

**但這帶出一個新的關鍵線索，能重新解讀 13.5 的現象**：如果這一輪實際檢索到的「2 筆相關段落」真的來自機密等級 7 的 Points，`filter_results` 應該會把它們判定為排除，而且第 482-483 行過濾完之後，[rag.py:578-579](../../backend/routers/rag.py) 一定會把 `PermissionService.build_exclusion_summary(excluded_items)` 的內容附加進「向量資料查詢」步驟的文字裡（`if excluded_items: search_details += "\n\n【權限過濾摘要】..."`）。但截圖裡的步驟內容完全沒有這段文字，且這 2 筆片段被明確標記「已放入總結脈絡」（代表 `filter_results` 判定為放行，`excluded_items` 是空的）。

對照這 2 筆片段的內容預覽——「[1] ...這是一張電腦螢幕介面的截圖的敘述...」與「[2] ...[段落編號] 第 **1** 段 [分類標籤] 圖片，操作說明...」——**這兩筆看起來對應的是段落 #0／#1 附近，並不是使用者已經驗證過、確實帶有 `confidential_level: 7` 的 chunk_index 16**。也就是說，**13.2 提出的「Points 漏掃」假設很可能沒有錯，只是使用者剛好驗證到了「有被涵蓋到」的那個 Point（chunk 16），而這次 hybrid 檢索實際命中、且真正外洩的是另一批「還沒被涵蓋到」的 Points（很可能是段落 #1 附近這幾筆）**。強烈建議下一步直接去 Qdrant Dashboard 用同樣的 `filename:GP51建立備份營運中心.docx` 篩選，逐一檢查段落編號 #1（截圖裡 `[2]` 內容預覽提到的「第 1 段」）與其對應的圖片 Point 是否也帶有 `is_confidential: true`／`confidential_level: 7`——如果這幾筆仍然是 `false` 或 `confidential_level: 10`（甚至完全沒有這三個欄位），就直接證實是 13.2 講的「同檔名下有些 Points 沒被最新一次的『儲存機密權限設定』覆蓋到」，而不是過濾語法本身有問題。

至於結論引用到 #3~#44 這些完全沒出現在「2 筆相關段落」清單裡的段落，跟本節（過濾語法是否存在）是兩個獨立的問題，該部分的根因分析請見第 14 節（`chat_history` 未受過濾）。

---

## 14. 使用者實測發現的第二個 BUG（2026-07-16）：多輪對話歷史 (`chat_history`) 完全不受權限過濾，會讓已經回答過的機密內容持續外洩

### 14.1 根因（已由程式碼直接證實，非推論）

`backend/routers/rag.py` 組出最終回答 Prompt 給 vLLM 時的程式碼：

```python
messages = [{"role": "system", "content": system_prompt}]

# 加入歷史對話
if request.chat_history:
    for msg in request.chat_history:
        messages.append({"role": msg.role, "content": msg.content})

# 加入目前的提問
messages.append({"role": "user", "content": question})
```
（[rag.py:781-789](../../backend/routers/rag.py)）

`request.chat_history` 裡的每一則訊息（包含**先前 AI 助理自己給過的完整回答內容**）會被原封不動、逐筆塞進送給 vLLM 的 `messages` 陣列，**完全不經過 `PermissionService.filter_results` 或任何其他過濾**——`filter_results` 只作用於「這一輪」新檢索到的 `raw_results`／`context_str`，從來不會去檢查、也沒有機制能去清洗 `chat_history` 裡已經包含的舊內容。程式碼裡另一處（[rag.py:70-75](../../backend/routers/rag.py) 的 `_build_history_window`）甚至用註解自己講明了這個差異：「與既有塞入最終回答 Prompt 時『整份 chat_history 全帶』的作法不同，此處刻意限縮視窗」——換句話說，**這個「整份歷史不經篩選直接餵給 LLM」的行為是既有既定設計**，只是在沒有機密權限控管之前不構成問題，現在有了機密權限控管，就變成一個會直接繞過過濾的漏洞。

前端組出 `chat_history` 的地方（[chatStore.js:120](../../frontend/src/stores/chatStore.js)）：
```js
chat_history: this.messages.slice(0, -2).map(m => ({ role: m.role, content: m.content })),
```
`this.messages` 是**整個對話視窗（Pinia store）持續累積的訊息陣列**，只有使用者按下「+ 新對話」（`clearMessages()`，[chatStore.js:39-50](../../frontend/src/stores/chatStore.js)）才會重置。**切換「模擬使用者」下拉選單（`paramsStore.simulatedUserId`）完全不會清空或影響 `this.messages`**。

### 14.2 這如何解釋 13.5 觀察到的現象

只要在**同一個對話視窗**（未按「+ 新對話」）裡，較早的某一輪對話曾經在「未模擬使用者」或「模擬了權限足夠的使用者（如 eric）」的狀態下，針對 `GP51建立備份營運中心.docx` 問過類似問題並得到過完整回答（例如管理者在設定機密權限、驗證流程時自己測試問過），那則完整回答就會被永久保留在 `this.messages`。之後即使切換成模擬 harry（等級 10，權限不足）重新問同一個檔案，**這一輪的檢索與過濾確實正確地只召回、只放行 2 筆片段**（如向量資料查詢步驟所寫），但 AI 產生最終回答時，`chat_history` 裡還帶著先前那則完整的舊回答內容，AI 自然可以直接依據歷史訊息「重述」整份文件的內容，而不需要依賴這一輪（已被正確過濾）的檢索結果——**這也解釋了為什麼結論引用的段落範圍（#1~#44）遠超過這一輪實際召回的 2 筆，且完全沒有跳出排除訊息**：因為排除訊息只描述「這一輪被排除的片段」，它没有、也無法知道 AI 其實是從歷史訊息裡把答案講出來的。

### 14.3 建議的驗證方式（不需改程式碼）

在同一個瀏覽器畫面：點擊「+ 新對話」清空對話視窗、確認左側訊息只剩下歡迎詞，**在勾選模擬使用者＝harry 的狀態下**、直接問「跟我說明 GP51建立備份營運中心」。
- 若這次「向量資料查詢」步驟顯示排除訊息、且最終結論變成「⚠️ 權限不足，無法提供回答」→ 直接證實 14.1 的推論成立，先前的洩漏是因為同一對話視窗殘留了機密內容尚未過濾的舊回答。
- 若在全新對話、harry 身分下仍然能看到完整內容 → 代表除了 14.1 之外還有其他根因（例如檢索/過濾本身在 `hybrid` 模式下有別的問題），需要另外排查。

### 14.4 待決策的修正方向（影響範圍較大，建議先確認要採用哪種再動工）

這個問題**不是 Bug 修一修就好，而是牽涉到「機密權限控管」與既有「多輪對話歷史」兩個既有設計之間的根本衝突**，需要決定修正方向：

1. **最簡單、最保守**：只要 `simulated_user_id` 有值（處於模擬使用者狀態），這一輪請求就**不要把 `chat_history` 帶進最終回答 Prompt**（等同每次模擬檢測都視為單輪問答），避免任何歷史殘留內容繞過過濾。缺點：模擬使用者狀態下無法測試「多輪對話＋指代消解」的組合情境。
2. **精確但複雜**：只清洗/移除 `chat_history` 中「來源包含目前已被判定為機密且使用者無權限的檔案」的歷史訊息，其餘保留。需要在每則歷史訊息額外記錄它當初依賴了哪些來源檔案／機密等級才能做篩選，目前的訊息結構（`ChatMessage`／前端 `messages`）沒有保留這個關聯，改動範圍較大。
3. **維持現狀，僅在文件/UI 加註警語**：既然這是內部測試平台（見第 1 節範圍邊界：模擬使用者是測試工具，不是正式存取控制），可以選擇不修，只在「模擬使用者」勾選框旁加一行提示，例如「權限模擬僅套用於本輪新檢索的內容，不會回溯清除同一對話視窗中先前已出現過的內容，如需乾淨測試請先按『+ 新對話』」，把這個限制講清楚讓使用者自己避開，而不是動程式邏輯。

三個方向的取捨（功能完整性 vs. 實作複雜度 vs. 使用者教育成本）需要使用者決定，這裡先如實記錄問題與選項，不預先選定實作。

---

## 15.【Critical／找到真正根本原因，2026-07-16】`QdrantService` 組裝檢索結果的 `metadata` dict 用的是寫死的欄位白名單，`is_confidential`/`confidential_level`/`confidential_departments` 從未被列入，導致 `filter_results()` 永遠讀不到這三個欄位

### 15.1 決定性證據

使用者接續用 Qdrant Dashboard 直接查了 `chunk_index: 0` 與 `chunk_index: 1`（也就是這次 hybrid 檢索實際命中、且被截圖 [1][2] 引用的那兩筆「第 1 段」「第 2 段」），確認兩者的 payload 都**確實**是 `"is_confidential": true`、`"confidential_level": 7`、`"confidential_departments": ["資訊部"]`，跟目前 UI 設定完全一致。這代表 **13.6 的假設（那 2 筆是還沒被涵蓋到的 Points）也被推翻了**——寫入端（`update_permissions_by_filename`）與 Qdrant 裡的實際資料，這三筆全部都正確無誤。

資料正確、過濾語法（[rag.py:472-483](../../backend/routers/rag.py)）位置也正確，卻仍然完全沒有排除——代表問題出在**兩者之間**：`filter_results()` 實際讀到的 `metadata` dict，並不是 Qdrant payload 本身，而是 `QdrantService.search_similar()` 另外重新組裝出來的一份 dict。查證 [`qdrant_service.py:499-522`](../../backend/services/qdrant_service.py) 的核心轉換邏輯：

```python
payload = res.payload or {}
temp_results.append({
    "chunk_id": str(res.id),
    "content": payload.get("content", ""),
    "metadata": {
        "filename": payload.get("filename"),
        "page": payload.get("page"),
        "section": payload.get("section"),
        "chunk_index": payload.get("chunk_index"),
        "tags": payload.get("tags", []),
        "class": payload.get("class", []),
        "parent_id": payload.get("parent_id"),
        "parent_content": payload.get("parent_content"),
        "parent_chunk_index_range": payload.get("parent_chunk_index_range"),
        "function_name": payload.get("function_name"),
        "type": payload.get("type"),
        "links_to": payload.get("links_to", []),
        "linked_attachments": payload.get("linked_attachments", []),
        "chunk_type": payload.get("chunk_type"),
        "image_filename": payload.get("image_filename")
        # ← 沒有 is_confidential / confidential_level / confidential_departments
    },
    ...
})
```

這是一份**逐欄位手動列舉**的白名單（不是把整個 `payload` dict 直接展開），本次機密權限控管功能新增的三個 payload 欄位**從頭到尾沒有被加進這份白名單**。`search_similar_two_step()` 的「2nd-hop 鄰居結果」有自己另一份幾乎一模一樣、同樣缺這三個欄位的白名單（[`qdrant_service.py:778-797`](../../backend/services/qdrant_service.py)），而 `search_similar_two_step()` 的「1st-hop 核心結果」其實是直接呼叫 `search_similar()`（[`qdrant_service.py:632-643`](../../backend/services/qdrant_service.py)），所以也一併中招。也就是說 **`vector`／`hybrid`／`semantic_hybrid`／`semantic_hybrid_feedback`／`semantic_hybrid_attachment` 這五種既有查詢法，全部都是透過這兩份白名單其中之一取得 `metadata`**。

`PermissionService.filter_results()`（[`permission_service.py:70-71`](../../backend/services/permission_service.py)）讀的正是 `item.get("metadata", {}).get("is_confidential")`——這個 key 在白名單裡從缺，`.get()` 永遠拿到 `None`，`bool(None)` 永遠是 `False`，於是 `filter_results()` 對**任何 Point**都會直接判定「非機密，放行」，完全不會進入等級／部門比對的分支。

**這代表：不管 Qdrant 裡的機密設定寫得多正確、`PermissionService` 的比對規則寫得多正確，「機密權限控管」這個功能的實際過濾效果，從第一次實作完成到現在，對 `vector`／`hybrid`／`semantic_hybrid`／`semantic_hybrid_feedback`／`semantic_hybrid_attachment` 檢索法從未真正生效過**——之前 eric（等級 6）「正常」通過，並不是過濾邏輯正確排除了 harry／jerry 卻放行了 eric，而是這個功能對**所有人**都形同放行，eric 只是剛好是應該被放行的那個人，湊巧看起來像是「對的」。

（同一份 [`RetrievalMetadata`](../../backend/schemas/retrieval.py) 回應裡的 `is_confidential`/`confidential_level`/`confidential_departments` 欄位，之所以在 `VectorManagementTab.vue` 的「已向量化資料管理與刪除」頁面能正確顯示機密徽章與預填表單，是因為那個畫面呼叫的是 `retrievalService.search(...)`（`/api/retrieval/search`），而該端點的 `RetrievalMetadata` 建構同樣讀自 `search_similar()` 回傳的 `metadata`——這裡其實**也一樣讀不到**這三個欄位，但巧合的是頁面預填邏輯讀的是 `managementStructuredMetadata`（來自 `get_unique_metadata()`，走的是完全不同的一條 scroll 路徑，[qdrant_service.py:952-955](../../backend/services/qdrant_service.py) 那份 `with_payload` 清單有正確包含這三個欄位），才沒有一併穿幫，讓管理頁面看起來一切正常，掩蓋了檢索路徑其實讀不到這三個欄位的事實。）

### 15.2 修正方式（明確、範圍小、無架構爭議，建議直接排入下一輪修正）

在 [`qdrant_service.py:502-518`](../../backend/services/qdrant_service.py)（`search_similar()`）與 [`qdrant_service.py:781-797`](../../backend/services/qdrant_service.py)（`search_similar_two_step()` 鄰居結果）這兩處 `"metadata": {...}` 字典裡，各自補上三行：
```python
"is_confidential": payload.get("is_confidential", False),
"confidential_level": payload.get("confidential_level"),
"confidential_departments": payload.get("confidential_departments", []),
```
比照既有 `links_to`/`linked_attachments` 的預設值寫法（`is_confidential` 缺欄位預設 `False`、`confidential_departments` 缺欄位預設空陣列，維持「未設定＝全部人可讀」的既有語意）。

建議一併處理 [`qdrant_service.py:1482-1495`](../../backend/services/qdrant_service.py)（`get_by_parent_id()`，供 `get_siblings_and_merge`/`get_image_siblings` 使用）——雖然目前 `filter_results()` 只檢查最外層 `raw_results` 的 `metadata`、不會去檢查巢狀 `image_chunks` 裡每一筆的機密欄位，這批鄰居／兄弟節點理論上都跟父節點同檔案、共用同一份機密設定，практически風險較低，但為了資料結構一致與未來防禦性考量，同一次順手補上三行即可，成本很低。

這是本次規劃文件記錄下來所有問題裡**唯一一個「不修就等於整個機密權限控管功能沒有實際作用」的問題**，優先度應高於第 13、14 節已記錄的其他項目——建議先修這個，修完後再重新用同一組 eric／harry／jerry 測試情境驗證一次，屆時才能真正確認排除邏輯是否運作，也才能進一步判斷第 14 節的 `chat_history` 洩漏問題是否仍會在乾淨的單輪對話中重現。

### 15.3【已修正，2026-07-16】

已依 15.2 的方案在 [`qdrant_service.py`](../../backend/services/qdrant_service.py) 三處補上 `is_confidential`/`confidential_level`/`confidential_departments`：
- `search_similar()` 的 `metadata` dict（[qdrant_service.py:518-520](../../backend/services/qdrant_service.py)）。
- `search_similar_two_step()` 2nd-hop 鄰居結果的 `metadata` dict（[qdrant_service.py:800-802](../../backend/services/qdrant_service.py)）。
- `get_by_parent_id()` 的 `metadata` dict（[qdrant_service.py:1501-1503](../../backend/services/qdrant_service.py)，供圖片兄弟節點合併使用，一併補上）。

三處皆沿用既有 `links_to`/`linked_attachments` 的預設值寫法（`is_confidential` 缺欄位預設 `False`、`confidential_departments` 缺欄位預設空陣列），語法已通過 `python -m ast` 解析驗證。**尚未實際跑過 eric／harry／jerry 的重新測試**——修正是否讓過濾如預期生效、以及修好之後第 14 節的 `chat_history` 洩漏問題是否仍會重現，需要使用者依 13.4／14.3 的方式手動於瀏覽器重新測試一次才能確認，AI 不代為開啟瀏覽器驗證。已記錄於 [`BackendCorrection.md`](BackendCorrection.md) 2026-07-16 條目。
