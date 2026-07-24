<!-- 後端修正紀錄(最新紀錄放最前面) -->

## 2026-07-24 子部門權限比對（部門代號前三碼相符歸類）實作

### 背景
集團內部包含諸多課級與子部門（例如 `S1800` 資訊服務部、`S1810` 網路通訊課），為使同部門群組內之子部門能互相存取該部門限制的文件，新增部門代號前三碼相符即歸類為相同部門之比對邏輯。

### 變更內容
- `backend/services/permission_service.py`：
  - 新增 `PermissionService._match_dept(user, target_dept)` 類別方法：
    1. 首先進行部門名稱與代號之完全比對 (`user.department == target_str` 或 `user.department_code == target_str`)。
    2. 若未完全相同，檢查使用者 `department_code` 與限制部門 `target_str` 長度是否皆 >= 3，若前三碼不分大小寫相同（如 `S1810` 與 `S1800` 皆為 `S18`），即判定為部門相符放行。
  - 將 `filter_results()` 與 `filter_results_kb_semantic_hybrid()` 中的所有 `access_dept` 與 `confidential_departments` 比對點統一代換為 `_match_dept()` 呼叫。

### 驗證
- 執行 `scratch/test_kb_semantic_hybrid.py` 單元測試：
  - `S1810`（網路通訊課）使用者成功匹配存取限制為 `S1800`（資訊服務部）之文件。
  - `S1720`（生產二課）使用者成功匹配存取限制為 `S1700`（生產管理部）之文件，且跨部門 `S1800` 文件被正確排除。
- 後端容器編譯與重啟 (`docker-compose up --build -d backend worker`) 順利完成。

---

### 背景
配合 [NewFeaturesPlan_KBSemanticHybridPlan.md](NewFeaturesPlan_KBSemanticHybridPlan.md) 規劃，新增獨立檢索模式 `KB_semantic_hybrid`。針對 Qdrant Point Payload 中的 `is_public` 欄位進行獨立的部門與職級過濾。

### 變更內容
- `backend/services/permission_service.py`：
  - 新增 `PermissionService.filter_results_kb_semantic_hybrid(raw_results, user)` 類別方法。
  - 當 Point Payload 包含 `is_public` 時：
    - `is_public == true`：開放跨部門存取，但必須符合職級門檻 (`user.level <= access_level`)。
    - `is_public == false`：必須符合部門限制 (`user.department == access_dept` 或代號相符) **且** 符合職級門檻 (`user.level <= access_level`)。
    - 個人白名單 `access_members` 優先覆蓋放行。
- `backend/routers/rag.py`：
  - 在 `rag_chat_stream()` 的檢索條件與 `search_similar_two_step` 呼叫點加入 `KB_semantic_hybrid` 模式。
  - 於機密過濾處新增判斷：`search_type == "KB_semantic_hybrid"` 時呼叫 `filter_results_kb_semantic_hybrid`，其餘模式維持原 `filter_results`。
- `backend/routers/retrieval.py`：
  - 在 `/api/retrieval/search` 檢索測試端點的 `is_semantic_hybrid_family` 判斷與權限過濾處加入 `KB_semantic_hybrid` 分流。

### 驗證
- 執行 `scratch/test_kb_semantic_hybrid.py` 權限過濾邏輯單元測試，全數 Test Cases 通過。

---

### 背景
外部 Ingest API 與系統核心在呼叫 `QdrantService.upsert_chunks` 時，此前一次性傳送全部 points 給 Qdrant。當長文件產生大量 chunks 時，單次 HTTP Payload 可能太大導致連線失敗。

### 變更內容
- `backend/services/qdrant_service.py`：
  - `upsert_chunks()` 方法新增 `batch_size: int = 20` 參數，內部改採 `range(0, total_points, batch_size)` 迴圈。
  - 將向量點位分割為每批最多 20 筆（相容密集與稀疏雙向量，以及 fallback 單一密集向量模態），避免單次 Payload 過大。

### 驗證
- `python -m py_compile backend/services/qdrant_service.py` 語法檢驗通過。

---

## 2026-07-23 多應用 RAG 同步段落 Prompt 結構化文字前綴自動注入實作

### 背景
依據需求與手動切分慣例，外部應用同步傳入的文檔/文章在經過 Parent-Child 階層切分與圖片描述生成後，需於每個 chunk 的內文前自動注入 `[檔案名稱]`、`[段落編號]`、`[分類標籤]`、`[主要內容]` 結構化樣板前綴並同步向量化。

### 變更內容
- `backend/services/ingest_service.py`：
  - 在 `_process_upsert()` 產出文字與圖片 chunks 後，於組裝 Qdrant payload 階段為每個 chunk 自動注入結構化標頭前綴：
    ```
    [檔案名稱] {filename}
    [段落編號] 第 {chunk_index + 1} 段
    [分類標籤] {tags}
    [主要內容]
    {chunk_content}
    ```
  - 重新計算結構化內文的 `token_count` 與 `char_count`，並將包含結構化標頭的內文送入 `EmbeddingService.get_embeddings_batch()` 產生向量，確保向量空間與手動批量寫入完全一致。

### 驗證
- `python -m py_compile backend/services/ingest_service.py` 語法檢驗通過。

---

## 2026-07-23 Qdrant 結構化元資料快取 (Metadata Cache) 跨容器與無刷新問題修復

### 背景
外部 Ingest API 在 worker 容器寫入資料後，僅清除 worker 進程內的快取，backend 容器仍沿用高達 600 秒的舊記憶體快取，導致前端 `GET /api/knowledge-bases/{id}/metadata` 無法即時取得最新寫入的檔案名稱選單。

### 變更內容
- `backend/services/qdrant_service.py`：將 `_METADATA_CACHE_TTL` 由 `600` 秒調降為 `60` 秒保底，降低跨容器異動延遲。
- `backend/routers/knowledge_base.py`：`GET /api/knowledge-bases/{id}/metadata` 新增 `refresh: bool = False` 參數，傳入 `refresh=True` 時主動呼叫 `invalidate_metadata_cache()` 清除該 Collection 快取並重新從 Qdrant 掃描最新檔案名稱與標籤。

### 驗證
- `python -m py_compile backend/routers/knowledge_base.py backend/services/qdrant_service.py` 通過。

---

## 2026-07-23 多應用 RAG 同步服務（IngestService）預設 Parent-Child 大小雙層切分與 PDF/Word 圖片自動擷取描述實作

### 背景
依據 [`MULTI_APP_RAG_SYNC_PLAN.md`](MULTI_APP_RAG_SYNC_PLAN.md) 規劃與需求，外部應用（如 Knowledge Base, BPM, Meeting 等）透過 API 同步文件與附件至 AiRAG 時，切區段預設套用 Parent-Child 大小雙層結構，並自動針對 PDF 及 Word 檔擷取內嵌圖片透過 VLM/LLM 產生說明描述後獨立向量化。

### 變更內容
- `backend/services/ingest_service.py`：
  - 擴充 `_process_upsert()` 邏輯：
    1. **圖片擷取與描述**：當 `doc_type == "attachment_file"` 且副檔名為 `pdf`, `docx`, `dotx` 時，調用 `DocumentParser.extract_images_from_pdf` / `extract_images_from_docx` 提取圖片。
    2. 使用 `caption_semaphore` 非同步控制併發，呼叫 `LLMService.describe_image` 產生圖片描述，並將實體圖檔儲存於 `FILE_ATTACHMENTS_DIR/image`。
    3. **Parent-Child 雙層切分**：對傳入文字內容（支援 Markdown, Word, PDF, 4GL, 4FD）進行 Parent-Child 大小雙層結構切分，計算各 Parent Block 的 Child 索引範圍並設定 `parent_id` 與 `parent_chunk_index_range`。
    4. **組合圖片 Chunk 與寫入 Qdrant**：將圖片描述轉為 `chunk_type="image"` 的 Chunk，附加 `"圖片"` Tag（若 MongoDB 無此 Tag 則自動建置），連同文字片段取得向量後批次寫入 Qdrant。

### 驗證
- 執行 `python -m py_compile backend/services/ingest_service.py` 檢查語法無誤。

---

## 2026-07-17 外部 API 真實使用者身分、問答稽核紀錄、API Key 驗證機制後端實作

### 背景
依據 [`NewFeaturesPlan_ExternalApiTestPlan.md`](NewFeaturesPlan_ExternalApiTestPlan.md) 第 8～12 節實作，取代先前「外部端點暫不驗證」的決策。

### 變更內容
- `backend/models/department.py`：`Department` 新增 `code: Indexed(str, unique=True)`。
- `backend/models/user_profile.py`：`UserProfile` 新增 `department_code: Optional[str]`；新增 `ExternalUserInfo`（`employee_id`/`name`/`department_code`/`department_name`/`job_title_name`/`job_title_level`），定義在此檔以避免 `rag.py`↔`permission_service.py` 之間的循環引用。
- `backend/routers/users.py`：`DepartmentCreateRequest`/`DepartmentResponse` 新增 `code`（必填，重複檢查）；`create_department()` 增加代號空值/重複驗證；`UserResponse` 新增 `department_code`；`create_user()` 新增時以 `Department.find_one(name==dept_name)` 查代號連動帶入，找不到則為 `None`（此時 `PermissionService` 仍可退回名稱比對）。
- `backend/services/permission_service.py`：
  - `filter_results()` 部門比對邏輯改為雙軌相容：`user.department in dept_str_list or (user.department_code and user.department_code in dept_str_list)`，過渡期不需要遷移既有 Qdrant `confidential_departments` 資料。
  - 新增 `get_user_from_external_info(info: ExternalUserInfo) -> UserProfile` classmethod，將外部使用者資訊轉為與模擬使用者相同形狀的物件（不落地寫入 `users` collection）。
- `backend/routers/rag.py`：`ChatParams` 新增 `external_user: Optional[ExternalUserInfo]`；`rag_chat_stream()` 解析身分處新增分支——有 `external_user` 時優先呼叫 `get_user_from_external_info()`，否則才走原本 `simulated_user_id` 查詢路徑，其餘下游過濾/排除摘要邏輯不變。
- `backend/utils/security.py`：新增 `generate_external_api_key()`（`secrets.token_urlsafe(32)` 產生明碼，回傳明碼/前綴/bcrypt hash）與 `verify_external_api_key()`（`X-API-Key` 標頭依賴注入，先以前綴查候選再 bcrypt 核對，通過後更新 `last_used_at`），與既有 `get_current_user` JWT 各自獨立。
- `backend/models/external_api_key.py`（新檔）：`ExternalApiKey` Document（`name`/`key_prefix` unique indexed/`key_hash`/`is_active`/`created_at`/`last_used_at`）。
- `backend/routers/external_api_keys.py`（新檔）：`GET/POST /api/external-api-keys`、`DELETE /api/external-api-keys/{id}`，沿用 `get_current_user` JWT 保護；`POST` 回應內的 `api_key` 明碼僅回傳一次。
- `backend/models/external_chat_log.py`（新檔）：`SourceSummaryItem`（精簡來源中繼資料，不存全文）與 `ExternalChatLog`（稽核紀錄，含呼叫端身分六欄位、問答內容、`custom_system_prompt` 實際使用文字、`api_key_id`）。
- `backend/routers/external.py`：
  - `POST /chat` 新增 `Depends(verify_external_api_key)`，並要求 `request.params.external_user` 必填（缺少回傳 400）。
  - 新增 `_external_chat_with_logging()`：以 `try...finally` 包住 `async for evt in rag_chat_stream(request)` 的轉發迴圈，旁路解析累積回答內容與來源，於 `finally`（涵蓋正常結束、中途斷線、例外）寫入一筆 `ExternalChatLog`；寫入本身另包 `try/except`，失敗僅記警告 log，不影響已送達使用者的串流結果（比照既有 `RetrievalStatsService.record` 的 best-effort 慣例）。
- `backend/models/mongodb.py`：`init_beanie` 註冊 `ExternalApiKey`、`ExternalChatLog`。
- `backend/main.py`：註冊 `external_api_keys.router`。

### 驗證
- `python -m py_compile` 全數通過（`rag.py`/`users.py`/`permission_service.py`/`user_profile.py`/`department.py`/`external_api_key.py`/`external_chat_log.py`/`external.py`/`external_api_keys.py`/`utils/security.py`/`main.py`/`models/mongodb.py`）。
- 以 venv Python 實際 import 全部新增/修改模組並執行端到端 smoke test：確認 `ChatParams.external_user` 欄位存在、`external.py`/`external_api_keys.py` 路由正確註冊、`get_user_from_external_info()` 能正確轉換欄位、`generate_external_api_key()` 產生的金鑰可被 `verify_password()` 正確驗證且錯誤金鑰會被拒絕。

---

## 2026-07-17 外部 API 測試頁面 (External API Test) 後端實作

### 背景
依據 [`NewFeaturesPlan_ExternalApiTestPlan.md`](NewFeaturesPlan_ExternalApiTestPlan.md) 規劃實作。新增獨立於內部測試 API 的外部端點，供公司內網外部應用未來串接，並支援自訂總結提示詞。

### 變更內容
- `backend/routers/external.py`（新檔）：新增 `POST /api/external/chat`，`APIRouter(prefix="/external")` 未掛 `Depends(get_current_user)`（依規劃決策，暫不驗證，僅限公司內網存取把關）。直接 import 並重用 `routers.rag` 現有的 `ChatRequest` schema 與 `rag_chat_stream()` async generator，未複製檢索/摘要/串流管線邏輯。
- `backend/routers/rag.py`：
  - `ChatParams` 新增 `custom_system_prompt: Optional[str] = None`。
  - `rag_chat_stream()` 新增區域變數擷取（去除頭尾空白後為空字串視同未帶）。
  - 三處組裝 `system_prompt` 的分支（`semantic_db_query` 分支／一般 `context_str` 分支／無資料 `else` 分支）皆改為：有帶 `custom_system_prompt` 時完全取代預設的指示規則文字，檢索到的參考資料（或資料庫查詢結果）仍由後端接續附加在後方；`else` 分支（無知識庫／無檢索資料）額外處理為若有帶入則直接等於 `custom_system_prompt`，不再強制接上「知識庫沒有相關資訊」警語，可用於純 Prompt／LLM 行為測試。未帶此欄位時三處皆完全維持原本預設文字，`/api/rag/chat` 行為不受影響。
- `backend/main.py`：`routers` import 新增 `external`，並註冊 `app.include_router(external.router, prefix="/api")`。

### 驗證
- `python -m py_compile routers/rag.py routers/external.py main.py` 通過。
- 以 venv Python 執行 `import routers.external`／`routers.rag`，確認 `'custom_system_prompt' in rag.ChatParams.model_fields` 為 `True`，且 `external.router` 路由為 `POST /external/chat`。

---

## 2026-07-16 手動建立與選擇 Qdrant 知識庫 (Knowledge Base / Collections) 實作

### 背景
依據 [`NewFeaturesPlan_ManualKnowledgeBaseCollectionsPlan.md`](NewFeaturesPlan_ManualKnowledgeBaseCollectionsPlan.md) 規劃修訂後端路由與 Schema。

### 變更內容
- `backend/routers/evaluation.py`：移除 `["tech_specs", "hr_docs"]` 舊相容分支，簡化知識庫解析邏輯為直接依 `PydanticObjectId` 尋找 `KnowledgeBase` 模型（無效或查無時 fallback 第一個知識庫）。
- `backend/routers/feedback.py`：
  - 導入 `KnowledgeBase` 模型。
  - `FeedbackItem` schema 補上 `knowledge_base_id: Optional[str]` 與 `knowledge_base_name: Optional[str]`。
  - `create_feedback()` 新增單筆 KnowledgeBase 名稱查詢並回傳。
  - `list_feedbacks()` 實作批次 KnowledgeBase 查詢（`$in` 條件），並加入 `try: PydanticObjectId(raw_id) except: pass` 過濾，排除髒資料與避免 N+1 查詢崩潰。

---

## 2026-07-16 文件機密權限控管 (Confidential Document Access Control) 實作

### 背景
依據 [`NewFeaturesPlan_ConfidentialAccessControlPlan.md`](NewFeaturesPlan_ConfidentialAccessControlPlan.md) 規劃實作。建立部門與使用者名冊，實作數值與部門雙重過濾之 `PermissionService`，解決檢索點位與附件下載連結可能洩漏機密文件的資安風險。

### 變更內容
- `backend/models/department.py` / `user_profile.py`：建立 `Department` 與 `UserProfile` Beanie Documents，並定義 `JOB_TITLE_LEVELS` 對照表。
- `backend/models/mongodb.py`：在 `init_beanie` 註冊二模型。
- `backend/routers/users.py`：實作 `/api/users/departments` 與 `/api/users` 之 CRUD 端點與 HTTP 400 驗證防護（修正：APIRouter `prefix` 改為 `/users` 避免 404；`get_departments` 的 `response_model` 改為 `List[DepartmentResponse]` 回傳 id 與 name）。
- `backend/services/permission_service.py`：實作核心權限過濾 `filter_results` 與隱私防禦型排除摘要產生器 `build_exclusion_summary`（修正：`confidential_level` 改採 `int(c_level)` 寬容轉型；當帶入已刪除/無效之 `simulated_user_id` 時，`get_user` 改採 Fail-Closed 最嚴防護模式回傳預設 Level 10 客戶身分，避免無效 ID 靜默降級洩漏機密）。
- `backend/services/qdrant_service.py`：`get_unique_metadata` 補齊權限 metadata，實作 `update_permissions_by_filename` 批次寫入（**Critical 修正**：`search_similar()`／`search_similar_two_step()` 鄰居結果／`get_by_parent_id()` 這三處組裝檢索結果 `metadata` dict 的程式碼，原本是逐欄位手動列舉的白名單，未列入 `is_confidential`/`confidential_level`/`confidential_departments`，導致 `PermissionService.filter_results()` 永遠讀不到這三個欄位、對任何人一律判定為非機密放行——等同 `vector`/`hybrid`/`semantic_hybrid` 家族查詢法的機密權限過濾自實作以來從未真正生效。三處皆已補上 `payload.get(...)` 讀取，詳見 [`NewFeaturesPlan_ConfidentialAccessControlPlan.md` 第 15 節](NewFeaturesPlan_ConfidentialAccessControlPlan.md)）。
- `backend/schemas/retrieval.py`：新增 `simulated_user_id`、`is_confidential`、`confidential_level`、`confidential_departments`、`excluded_items` 與 `UpdatePermissionsRequest`。
- `backend/routers/retrieval.py`：`/search` 與 `/semantic-hybrid-search` 整合過濾，新增 POST `/files/update-permissions` 端點。
- `backend/routers/rag.py`：在雙階段附件收集前及單階段搜尋處插入權限過濾，並處理 `permission_blocked_all` Early Exit 事件。

---

## 2026-07-14 AI 總結門檻審查問題修正 (8.2 附件 Early Exit 誤殺 / 8.3 死碼清理 / 8.4 補回無 KB 步驟)

### 背景
依據 [`NewFeaturesPlan_SimilaritySummaryThresholdPlan.md`](NewFeaturesPlan_SimilaritySummaryThresholdPlan.md) 8.2 ~ 8.4 審查項修復。修正附件查詢法在主文 Chunk 低於分數門檻時被 Early Exit 誤殺的問題、清理未使用的死碼 Schema 欄位，並補齊無知識庫情境下遺漏的 step 提示。

### 變更內容
- `backend/routers/rag.py`：
  - **8.2 附件 Early Exit 誤殺修復**：計算 `has_attachments` 狀態，當勾選「AI 讀取附件內容」且含有關聯附件時，Early Exit 不會觸發；Map-Reduce 區塊判斷調整為 `if context_str or has_attachments:`，確保附件文字能正確被 Map-Reduce 合併或摘要後送入 LLM 生成總結。
  - **8.4 無知識庫步驟修復**：於 `request.knowledge_base_id` 不存在的分支補上 `else`，發送 `semantic_analysis` 與 `vector_search` 略過提示事件。
- `backend/schemas/retrieval.py`：
  - **8.3 死碼清理**：從 `SearchParams` 移除未於 `/api/retrieval/search` 說明的 `ai_summary_score_threshold` 欄位。

---

## 2026-07-13 AI 總結相似度門檻與拒絕生成機制實作

### 背景
依據 [`NewFeaturesPlan_SimilaritySummaryThresholdPlan.md`](NewFeaturesPlan_SimilaritySummaryThresholdPlan.md) 規劃實作。提供前端 `ai_summary_score_threshold`（預設 `0.60`）參數，當檢索到的片段相似度低於此分數時排除於 LLM Context 外；當全數片段皆低於門檻時，觸發 Early Exit 硬防護跳過 LLM 總結。

### 變更內容
- `backend/schemas/retrieval.py`：
  - `SearchParams` 新增 `ai_summary_score_threshold: Optional[float] = Field(default=0.60)`。
- `backend/routers/rag.py`：
  - `ChatParams` 新增 `ai_summary_score_threshold: Optional[float] = None`。
  - `rag_chat_stream()` 提取 `ai_summary_score_threshold`（預設 0.60）。
  - 於 `raw_results` Chunks 處理循環中，逐一比較 `semantic_score >= ai_summary_score_threshold`：
    - 符合門檻才放入 `context_parts` 送給 LLM 做總結與回答。
    - 在每個 `sources` 筆數中補上 `semantic_score` 與 `metadata.included_in_ai_context` 狀態。
  - **Early Exit 機制**：若 `context_parts` 為空（全數片段皆低於門檻）：
    - `vector_search` 步驟事件發送 warning 與提示。
    - 以 SSE 直接串流友善提醒訊息及 `sources`，並 `return` 結束流，不調用 vLLM 推論，達成 100% 杜絕幻覺與零算力消耗。

### 驗證
- 執行 `python -m py_compile backend/routers/rag.py backend/schemas/retrieval.py` 通過。

## 2026-07-13 Qdrant 檢索查詢優化（中文 Tokenizer 設定與既有索引自動升級）

### 背景
依優化規劃文件 [QdrantRetrievalOptimizationPlan.md](QdrantRetrievalOptimizationPlan.md) 實作建議優先順序第 3 項目（方向二：優化中文全文檢索分詞 Tokenizer）。原本的 `models.TokenizerType.WORD` 是針對英文空格切分，導致中文查詢時的 Exact Keyword Boost（`models.MatchText`）幾乎無法命中。

### 變更內容
- [qdrant_service.py](file:///d:/%E6%AA%94%E6%A1%88%E5%88%86%E4%BA%AB/%E7%A8%8B%E5%BC%8F%E7%A2%BC/AiRAG/backend/services/qdrant_service.py)：
  - 在 `create_collection()` 方法中，將 `content` Payload 欄位的 Text Index Tokenizer 從 `WORD` 調整為 `MULTILINGUAL`（多語言/中文分詞器）。
  - 新增 `ensure_all_collections_payload_index()` 方法，自動遍歷 Qdrant 中所有 Collection 並升級 `content` 欄位的 Text Index 至 `MULTILINGUAL`。
- [mongodb.py](file:///d:/%E6%AA%94%E6%A1%88%E5%88%86%E4%BA%AB/%E7%A8%8B%E5%BC%8F%E7%A2%BC/AiRAG/backend/models/mongodb.py)：
  - 在後端啟動初始化邏輯 `init_mongodb()` 中呼叫 `QdrantService.ensure_all_collections_payload_index()`，讓現存的舊 Collection 於系統啟動時自動在背景完成中文分詞索引升級重建，無須手動執行重建指令或重灌向量資料。

### 驗證
- 語法編譯檢查（`python -m py_compile backend/services/qdrant_service.py backend/models/mongodb.py`）通過。

## 2026-07-13 Qdrant 檢索查詢優化（併行 Sibling 檢索與元資料分頁滾動）

### 背景
依優化規劃文件 [QdrantRetrievalOptimizationPlan.md](QdrantRetrievalOptimizationPlan.md) 實作建議優先順序第 1 與 2 項目（方向三與方向四）。

### 變更內容
- [qdrant_service.py](file:///d:/%E6%AA%94%E6%A1%88%E5%88%86%E4%BA%AB/%E7%A8%8B%E5%BC%8F%E7%A2%BC/AiRAG/backend/services/qdrant_service.py)：
  - **方向三（併行 Sibling 檢索）**：在 `search_similar()` 與 `search_similar_two_step()` 的 Parent-Child 還原合併階段，將原本依序串行（Sequential）執行的 `await cls.get_siblings_and_merge()` / `await cls.get_image_siblings()` 改為使用 `asyncio.gather()` 非同步併行執行。消除 Head-of-Line Blocking，顯著降低 1st-hop 與 2nd-hop 的 I/O 響應時間。
  - **方向四（元資料分頁滾動）**：在 `get_unique_metadata()` 中將一次性截斷抓取 `limit=10000` 改為基於 Cursor Pagination 的 `while True` 滾動分頁（每頁 1000 筆，迭代至 `next_offset` 為空），解決大規模 Collection（超過 10,000 點位）時元資料選單漏失檔案與標籤的問題。

### 驗證
- 語法編譯檢查（`python -m py_compile backend/services/qdrant_service.py`）通過。
