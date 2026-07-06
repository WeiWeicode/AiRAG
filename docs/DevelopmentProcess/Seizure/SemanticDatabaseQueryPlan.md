# 語義資料庫查詢法（Semantic DB Query）規劃文件

> 狀態：**已實作，且已依實測回饋調整**。本文件為原始規劃，實作過程中的異動請對照 `docs/DevelopmentProcess/NewFeatures.md`／`BugFix.md` 的 2026-07-03 條目。
> 目標範例：「請幫我在 10.10.130.220 知識資料庫查詢知識庫有幾篇文章」、「請幫我在 10.10.130.220 知識資料庫查詢 ERP 開帳文章」。
>
> **重要架構異動（2026-07-03，實測後調整）**：第 3.2、6 節原規劃的「Profile 向量比對」機制（Qdrant hybrid RRF + 分數門檻）在實測中發現，
> 當問題橫跨多張表格（例如同時問「附件」與「文章」）時，單一分數門檻/取最高分容易漏掉其中一個真正相關的設定檔。
> 因此**選擇設定檔的機制改為**：直接把「目前所有查詢設定檔」的完整清單（名稱/表格/用途）提供給語義 AI，讓它依問題語意直接判斷需要用到哪幾個
> 設定檔（可複選、可 0 個），取代原本的向量相似度門檻篩選。詳見 `backend/services/ai_db_query_service.py` 的
> `_select_relevant_profiles_from_catalog()`。既有的 Profile 向量寫入機制（`QdrantService.upsert_db_query_profile()`，
> 存進 KnowledgeBase collection 供向量管理頁面/未來擴充使用）維持不變，只是**選擇邏輯不再讀取這些向量**。

## 1. 目標與範圍

新增一種**新的檢索模式**，讓 AI 能夠在使用者提問時，自動判斷該用哪個資料庫設定檔、自動產生對應 SQL、查詢既有的（唯讀）關聯式資料庫，並把查到的資料交給主模型統整成答案。

**明確不動的部分**（對應需求 1）：
- 既有 `vector` / `hybrid` / `semantic_hybrid` / `semantic_hybrid_feedback` 四種查詢法的程式路徑、Prompt **完全不修改**。
- 既有「資料庫匯入向量化」（`database_indexing.py` 的 ingest 流程，把資料庫內容轉成向量長期存放）**功能與行為不變**，新功能是在同一個 Tab 內「新增選項」，不是取代。
- 新查詢法將以新增 `search_type` 值（暫定 `semantic_db_query`）的方式掛進 `rag.py` / `retrieval.py` / `evaluation.py`，比照 2026-07-02 `semantic_hybrid_feedback` 的加法式作法（見 `NewFeatures.md`），不改動既有分支邏輯，只新增分支。
- 依使用者確認，Profile 向量將存進**同一個既有 KnowledgeBase collection**（見 3.2 節），因此 `qdrant_service.search_similar()` 需要新增一個**加法式、對既有資料零影響**的過濾條件（見 3.2 節說明），這是唯一一處會碰到既有共用方法的地方，其餘完全不動。

**只能查詢，不能寫入**（對應需求 3）：完全重用 `database_indexing.py` 既有的 `validate_sql_query()`（只允許 `SELECT`/`WITH`，擋掉 `INSERT/UPDATE/DELETE/DROP/ALTER/...`），AI 產生的 SQL 一樣要過這關才能執行。

## 2. 名詞定義

| 名詞 | 說明 |
|---|---|
| 資料庫連線設定檔（DB Config） | 既有 `DatabaseConfig`（`backend/models/database_config.py`），存放 host/port/database/username/password，`database_indexing.py` 已在用。**直接重用，不重造**（對應需求 2）。 |
| 查詢設定檔（Query Profile） | **新概念**：描述「某個連線設定檔下的某張表格，欄位分別代表什麼意思」，並自動組成一段自然語言描述文字後存成向量，供語義比對用。 |

## 3. 資料模型設計

### 3.1 新 MongoDB Document：`DBQueryProfile`

新檔案 `backend/models/db_query_profile.py`：

```python
class DBQueryProfileColumn(BaseModel):
    column_name: str
    enabled: bool = True
    meaning: str = ""          # 欄位中文意義描述
    max_length: int | None = None   # 大型欄位（如 nvarchar(max)）的自訂截斷長度；
                                     # 不填則沿用全域 AI_DB_QUERY_MAX_CHARS

class DBQueryProfile(Document):
    name: str                          # 設定檔顯示名稱
    database_config_id: str            # 關聯 DatabaseConfig._id（既有，重用）
    knowledge_base_id: str             # 關聯 KnowledgeBase._id；決定 Profile 向量實際存放的 collection
    platform_description: str          # 「功能是...」平台/資料庫用途自由描述
    table_name: str                    # 選取的表格
    table_purpose: str                 # 表格用途描述
    columns: List[DBQueryProfileColumn]
    composed_description: str          # 自動組合出的完整自然語言描述（拿去 embedding）
    qdrant_point_id: str               # 對應 Qdrant point，供更新/刪除
    created_by: str | None
    created_at, updated_at: datetime

    class Settings:
        name = "db_query_profiles"
```

自然語言組合邏輯**重用**現有 `database_indexing.py` 第 443–494 行「natural_language 模式」的敘述產生器（同一套「表單意義 + 逐欄位意義」的組句方式），對應到使用者範例：

> 這是資料庫查詢的設定檔：{DB Config 名稱} 平台，資料庫是 {database 名稱}，功能是 {platform_description}，表單是 {table_name}，功能是 {table_purpose}，以下為欄位說明：{每欄位 meaning}...

若某欄位設有 `max_length`（例如 `nvarchar(max)` 大型文字欄位），組合描述時會額外加註一句「（此欄位內容較長，查詢時超過 N 字將自動截斷）」，讓語義 AI 與使用者都能提前知道這個欄位的呈現限制。

### 3.2 Qdrant：Profile 向量存進既有 KnowledgeBase collection（依使用者確認）

**決策**：Profile 向量存進**使用者選定的既有 KnowledgeBase collection**（不是獨立 collection），方便直接用既有的向量管理頁面、準確度評估、回饋機制一起測試。

寫入時在 payload 新增 `source: "db_query_profile"`（延續既有 `source` 欄位慣例，目前既有值為 `"upload" | "database" | "json_semantic"`，新增第四種值），並保留 `profile_id`、`table_name` 等欄位供比對與管理頁面顯示。

**為了不讓 Profile 描述文字混進一般文件檢索結果**，需要對 `qdrant_service.py` 做一處**加法式**修改：
- `search_similar()` / `search_similar_two_step()` 內部組 Qdrant Filter 時，固定加上一條 `must_not: [{key: "source", match: {value: "db_query_profile"}}]`。
- 因為既有資料的 `source` 欄位從未出現過這個值，這條件對所有既有資料而言**永遠不成立、不影響任何既有查詢結果**，等同零行為變化；只有新寫入的 Profile point 會被這條規則排除在一般文件檢索之外。
- 這是本次規劃中**唯一一處**觸碰既有共用檢索方法的地方，其餘 `vector`/`hybrid`/`semantic_hybrid`/`semantic_hybrid_feedback` 的邏輯、Prompt、排序、rerank 都不變。

新增 `QdrantService.upsert_db_query_profile()` / `search_db_query_profiles()` 兩個**獨立新方法**（可以內部呼叫既有 dense/sparse embedding 與 upsert/query 的底層工具函式以避免重複造輪子，但方法本身是新增，不覆寫既有方法簽章）：
- `upsert_db_query_profile(collection_name, profile)`：寫入/更新一個 Profile point。
- `search_db_query_profiles(collection_name, query_text, knowledge_base_id, score_threshold, limit)`：hybrid RRF 搜尋，強制加上 `source == "db_query_profile"` 的過濾條件，回傳候選清單（含分數）。

## 4. 後端 API 設計

新檔案 `backend/routers/ai_db_query.py`（掛在 `/api/ai-db-query`，比照其他 router 需要 `Depends(get_current_user)`）：

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/ai-db-query/profiles?knowledge_base_id=` | 列出查詢設定檔 |
| POST | `/api/ai-db-query/profiles` | 建立設定檔：組自然語言描述 → 產生 embedding → 寫入 Qdrant + Mongo |
| PUT | `/api/ai-db-query/profiles/{id}` | 更新設定檔（重新組字串、重新 embedding、更新 Qdrant point） |
| DELETE | `/api/ai-db-query/profiles/{id}` | 刪除（Mongo + Qdrant point 一併刪除） |
| POST | `/api/ai-db-query/list-tables` | 輸入 `config_id`，回傳該連線底下的表格清單（唯讀 schema 查詢，SQL Server 用 `INFORMATION_SCHEMA.TABLES`，Oracle 用 `USER_TABLES`） |
| POST | `/api/ai-db-query/list-columns` | 輸入 `config_id` + `table_name`，回傳欄位清單（`INFORMATION_SCHEMA.COLUMNS` / `ALL_TAB_COLUMNS`），純 schema 查詢不撈資料，供欄位對照表 UI 使用 |
| POST | `/api/ai-db-query/match-profiles` | **查詢用（第一階段）**：輸入 `question` + `knowledge_base_id`，執行第 6 節步驟 1–2（語義理解 + Profile 向量比對），回傳候選設定檔清單（`profile_id`/`name`/`table_name`/`table_purpose`/`score`，依分數排序），**不執行 SQL**。供前端列出候選讓使用者選取。 |
| POST | `/api/ai-db-query/execute` | **查詢用（第二階段）**：輸入 `question` + `profile_id`（使用者選定的候選）+ 可選 `max_rows`/`max_chars` 覆寫值，執行第 6 節步驟 3–5（SQL 產生、驗證、執行、結果文字化），回傳 `generated_sql`/`row_count`/`context_text`。給 `rag.py`/`retrieval.py`/`evaluation.py` 內部呼叫，或前端測試頁直接呼叫來檢視中繼結果。 |

`list-tables` / `list-columns` 走的是純 metadata catalog 查詢，複用 `database_indexing.py` 既有的 `get_db_connection()` 連線邏輯（不重寫 pyodbc/oracledb 分支）。

### 4.1 核心查詢邏輯：新 Service `backend/services/ai_db_query_service.py`

抽成獨立 service（比照 `FeedbackBoostService`、`RerankService` 的模式），讓 `rag.py` / `retrieval.py` / `evaluation.py` 三處共用同一套邏輯，不各自重複實作：

```python
class AIDBQueryService:
    @classmethod
    async def match_profiles(cls, question: str, knowledge_base_id: str) -> list[ProfileCandidate]:
        # 對應第 6 節步驟 1–2，回傳候選清單供使用者選取
        ...

    @classmethod
    async def execute(cls, question: str, profile_id: str,
                       max_rows: int | None = None, max_chars: int | None = None) -> AIDBQueryResult:
        # 對應第 6 節步驟 3–5，使用者選定 profile 後才真正下 SQL
        ...
```

`execute()` 回傳內容包含：`matched_profile`、`generated_sql`、`row_count`、`context_text`（要交給主模型的文字）、`elapsed_ms`；`match_profiles()`/`execute()` 任一階段失敗都要帶明確錯誤原因（找不到設定檔 / SQL 產生失敗 / 執行失敗），**不做靜默降級或亂猜答案**（對應 AGENT.md「錯誤要大聲說出來」）。

## 5. 前端設計

### 5.1 EmbeddingTest → 「資料庫匯入向量化」Tab 內新增子模式（對應需求 4）

`frontend/src/components/embedding/DatabaseIndexingTab.vue` 頂部新增一組模式切換（不新增外層 Tab，維持在同一個 Tab 內）：

- ① 將資料庫內容轉向量（**既有功能，完全不動**）
- ② AI 查詢設定檔（**新增**）

選 ②時，切換顯示新的子元件 `frontend/src/components/embedding/DBQueryProfileManager.vue`（獨立新檔，避免既有 632 行的 `DatabaseIndexingTab.vue` 再繼續膨脹），欄位對應使用者給的範例格式：

1. 選取 DatabaseConfig（下拉，重用既有 `loadDbConfigs()` / `databaseIndexingService.getConfigs()`）
2. 選取 KnowledgeBase（重用既有 `KnowledgeBaseSelector.vue` / `knowledgeBaseService`）
3. 自由輸入「平台/資料庫功能描述」
4. 選取表格（呼叫新 `list-tables` API 撈選項）
5. 自由輸入「表單功能描述」
6. 欄位對照表（呼叫新 `list-columns` API 帶出欄位，UI 樣式比照既有 `dbColumnsConfig` 表格：checkbox 啟用 + 中文意義輸入框 + **選填的「截斷長度」欄位**，供大型欄位如 `nvarchar(max)` 自訂截斷長度，不填則用全域預設值）
7. 即時預覽自動組合出的自然語言描述（比照既有 `dbPreviewText` computed 的做法，若有欄位設定截斷長度會一併顯示提示句）
8. 儲存 → 呼叫 `POST /api/ai-db-query/profiles`
9. 下方列出已建立的設定檔，可編輯/刪除

查詢時的筆數/字數上限（`AI_DB_QUERY_MAX_ROWS`/`AI_DB_QUERY_MAX_CHARS`）在**測試頁面**（`RetrievalTestView.vue` 的參數面板）提供可調整輸入框，預設帶入 `config.py` 的全域值，使用者送出查詢時可覆寫，對應到 `POST /api/ai-db-query/execute` 的 `max_rows`/`max_chars` 參數。

新增 `frontend/src/services/aiDbQueryService.js`，比照 `databaseIndexingService.js` 的簡單 axios wrapper 風格。

### 5.2 三處測試頁面新增查詢法選項（對應需求 5）

比照 2026-07-02「語義混合回饋查詢法」上線時的加法模式：

- `frontend/src/components/params/RagParamsPanel.vue`：檢索模式下拉新增「語義資料庫查詢法 (Semantic DB Query)」
- `frontend/src/views/RetrievalTestView.vue`：`handleSearch()` 新增分支，先打 `match-profiles` 顯示候選設定檔清單（卡片式列表，顯示 `name`/`table_name`/`table_purpose`/`score`），使用者點選其中一個候選後再打 `execute` 取得 SQL + 資料列 + 摘要；因為回傳格式跟一般 chunk 列表不同，需要新的結果顯示區塊，不能硬塞進既有的 chunk 卡片 UI
- `frontend/src/components/eval/TestSetManager.vue`：評估用的 search_type 選項新增此項，讓 LLM-as-Judge 也能對「資料庫問答」的準確度評分（評估流程無真人可選候選，見第 6 節「自動化例外」說明）
- RAG 對話測試（`ChatWindow.vue`/`rag.py` SSE）：選到此查詢法時，第一次串流會在收到候選清單後**暫停**並新增一個 SSE 事件（例如 `step="profile_candidates"`，`content` 帶候選清單 JSON），前端跳出候選選取 UI；使用者選定後，前端帶著 `selected_profile_id` 重新呼叫對話端點，才繼續 SQL 產生與最終摘要，沿用既有 `step/status/content` SSE 契約，只是新增了一種會讓串流「先停一次」的 step 值，不改變既有四種查詢法的串流行為。

## 6. AI 執行流程設計（對應需求 6，含優化建議）

使用者提出的流程：
語義 AI 整理 → 向量資料庫找設定檔 → 語義 AI 產生 SQL → 撈資料庫（限筆數/大小）→ 主模型總結

規劃後的完整流程（在使用者流程基礎上，補上安全驗證與失敗處理，其餘不變）：

```
1. 語義理解（Instruct LLM）
   使用者問題 → 結構化 JSON { embeddings_input, sparse_keywords }
   （新 Prompt，比照既有 query_to_semantic_json 的反幻想規則，
    但鎖定在「資料庫/表格/欄位」語意而非一般文件語意）

2. Profile 檢索（Qdrant hybrid RRF，同一 KnowledgeBase collection，見 3.2 節）
   依 knowledge_base_id + source=="db_query_profile" 過濾 + score_threshold
   → 回傳所有分數 ≥ 門檻值的候選設定檔（依分數排序），交給使用者選取
     （對應需求確認：不自動取 Top-1，交由人工判斷避免誤用錯的表/欄位定義）
   → 若完全沒有候選（最高分 < 門檻值），直接判定「查無對應資料庫設定檔」，
     中止並明確告知使用者，不猜測、不用其他設定檔硬湊（AGENT.md 第 6 條）
   → 【自動化例外】評估流程（evaluation.py 批次跑測試集）沒有真人可以選候選，
     此情境下自動取分數最高者（Top-1）繼續往下執行，並在評估結果中記錄
     「本題為自動選取設定檔，非人工確認」，讓評估報告可以分辨兩種情境
     （見第 8 節「決策紀錄」第 5 點，此為新浮現的必要設計，非使用者原題）

3. SQL 產生（Instruct LLM）—— 使用者（或評估流程）選定候選設定檔之後才執行
   輸入：設定檔的 table_name / columns（僅 enabled 欄位）/ table_purpose / db_type
   規則：只能輸出 SELECT、只能用設定檔中列出的表格與欄位（防幻想）、
        依 db_type 語法自動加上限制筆數子句
        （SQL Server: TOP N；Oracle: FETCH FIRST N ROWS ONLY / ROWNUM）

4. 安全驗證 + 執行
   - 重用既有 validate_sql_query()（擋 DML/DDL，只准 SELECT/WITH）
   - 重用既有 get_db_connection()（pyodbc/oracledb 連線邏輯不重寫）
   - 筆數上限：AI_DB_QUERY_MAX_ROWS（預設 50，前端可調整覆寫；
     若 LLM 產生的 SQL 未自帶限制則後端強制截斷)
   - 內容大小上限：AI_DB_QUERY_MAX_CHARS（預設 4000 字，前端可調整覆寫；
     逐欄位序列化時，若該欄位有自訂 max_length 則優先套用該值，
     超過就截斷並註記「（已截斷）」)
   - SQL 執行失敗（語法錯誤等）→ 直接回報錯誤，不重試硬猜、不靜默吞掉

5. 結果整理
   把撈到的資料列 → 文字化（重用/抽出 database_indexing.py 既有 row→text 的組句邏輯，
   讓 ingestion 與這裡共用同一份，不重複實作兩套）

6. 主模型總結（vLLM，既有 llm_service）
   將結果文字 + 使用者原問題 一起送給主模型產生最終答案，
   SSE 事件沿用既有 step/status/content 格式，只新增中間步驟的文字說明
   （例如新增 step="profile_candidates" 讓前端列出候選讓使用者選，
    選定後才繼續 step="vector_search" 標註「已選定設定檔：XXX，正在查詢...」）
```

## 7. 新增設定值（`backend/config.py`）

| 變數 | 預設值 | 用途 |
|---|---|---|
| `AI_DB_QUERY_MAX_ROWS` | 50 | 單次查詢回傳最大列數（全域預設，前端測試頁可覆寫） |
| `AI_DB_QUERY_MAX_CHARS` | 4000 | 交給主模型前的內容字數上限（全域預設；欄位有自訂 `max_length` 時優先套用欄位值） |
| `AI_DB_QUERY_PROFILE_SCORE_THRESHOLD` | 0.5 | Profile 比對最低相似度，低於則判定查無設定檔候選 |

> 因 Profile 改存進既有 KnowledgeBase collection（非獨立 collection），不再需要 `DB_QUERY_PROFILE_COLLECTION_NAME` 這個設定值。

## 8. 決策紀錄

以下 4 點使用者已確認，記錄決策與影響，後續不再視為待確認事項：

1. **Profile 向量存放位置**：存進使用者選定的既有 KnowledgeBase collection（非獨立 collection），方便共用向量管理頁面、準確度評估、回饋機制。影響：`qdrant_service.search_similar()`/`search_similar_two_step()` 需新增一條加法式 `must_not: source=="db_query_profile"` 過濾（見 3.2 節，對既有資料零影響）。
2. **候選設定檔呈現方式**：不自動取 Top-1，比對結果一律列出候選讓使用者選取（見第 6 節步驟 2）。影響：RAG 對話測試的 SSE 流程需要新增一個「暫停等待使用者選擇」的中繼步驟（見 5.2 節），检索測試頁與評估流程也都變成「先列候選、再執行」的兩段式 API（`match-profiles` → `execute`，見第 4 節）。
3. **筆數/字數上限**：前端測試頁可調整（預設 50 列 / 4000 字），逐欄位可另外於設定檔中自訂截斷長度（例如 `nvarchar(max)` 欄位），寫入設定檔向量時會註明該欄位有截斷限制（見 3.1 節）。
4. **密碼明碼儲存**：暫不處理，本次沿用 `DatabaseConfig` 既有明碼儲存做法，不在此功能範圍內一併加密。

5. **評估流程的候選處理**（因決策 2 而衍生，已確認）：`evaluation.py` 批次跑測試集時沒有真人可以中途選候選設定檔，採用「自動取分數最高的候選（Top-1）並在評估結果中標記為『自動選取，非人工確認』」，讓評估報告可以分辨兩種情境。

## 9. 分階段實作 Checklist

- [ ] `backend/models/db_query_profile.py`（新模型，含欄位 `max_length`）+ 註冊進 `mongodb.py` 的 `document_models`
- [ ] `backend/schemas/ai_db_query.py`（新 schema，含 `match-profiles`/`execute` 的 request/response）
- [ ] `backend/services/ai_db_query_service.py`（`match_profiles()` + `execute()` 兩段式核心流程）
- [ ] `backend/services/qdrant_service.py`：
  - [ ] `search_similar()` / `search_similar_two_step()` 加上 `must_not: source=="db_query_profile"`（加法式，不影響既有行為）
  - [ ] 新增 `upsert_db_query_profile()` / `search_db_query_profiles()`（獨立新方法）
- [ ] `backend/routers/ai_db_query.py`（CRUD + list-tables/list-columns + match-profiles + execute）
- [ ] `backend/routers/rag.py` 新增 `semantic_db_query` 分支（含 SSE `profile_candidates` 暫停步驟）
- [ ] `backend/routers/retrieval.py` / `evaluation.py` 新增 `semantic_db_query` 分支（含評估流程自動選 Top-1 的標記邏輯）
- [ ] `backend/config.py` 新增設定值（`AI_DB_QUERY_MAX_ROWS`/`AI_DB_QUERY_MAX_CHARS`/`AI_DB_QUERY_PROFILE_SCORE_THRESHOLD`）
- [ ] `frontend/src/services/aiDbQueryService.js`
- [ ] `frontend/src/components/embedding/DBQueryProfileManager.vue`（新元件，含欄位截斷長度輸入）+ `DatabaseIndexingTab.vue` 模式切換
- [ ] `frontend/src/components/params/RagParamsPanel.vue` / `views/RetrievalTestView.vue`（含候選選取 UI + 筆數/字數上限輸入框）/ `components/eval/TestSetManager.vue` 新增選項
- [ ] `frontend/src/components/chat/ChatWindow.vue`：處理 SSE `profile_candidates` 步驟並跳出候選選取 UI，選定後重新呼叫對話端點
- [ ] `docs/03_API_CONTRACT.md`、`docs/04_DB_SCHEMA.md` 補上新 API/欄位說明
- [ ] `docs/DevelopmentProcess/NewFeatures.md` 記錄本次新增（實作完成後）
