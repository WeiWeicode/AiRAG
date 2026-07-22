# 外部應用串接指南 — `POST /api/external/chat`

## 0. 文件資訊

* **對象**：公司內網其他應用的開發者（非 AiRAG 專案內部開發者）。本文件目標是「不需要讀 AiRAG 原始碼或其他內部架構文件，也能完成串接」。
* **對應功能規劃文件**：[NewFeaturesPlan_ExternalApiTestPlan.md](DevelopmentProcess/NewFeaturesPlan_ExternalApiTestPlan.md)（2026-07-17 完成實作，含後續 API Key 驗證與 `external_user` 身分欄位）。
* **實作對照程式碼**：[backend/routers/external.py](../backend/routers/external.py)、[backend/routers/rag.py](../backend/routers/rag.py)（底層共用管線）、[backend/utils/security.py](../backend/utils/security.py)（`verify_external_api_key`）。
* 若欄位或行為與本文件不符，請以程式碼為準並回報 AiRAG 專案維護者更新本文件。
* **建立日期**：2026-07-20。

---

## 1. 這是什麼

`POST /api/external/chat` 是 AiRAG 提供給**公司內網其他應用**串接的獨立問答端點，功能等同於 AiRAG 內部「RAG 功能測試」頁：送出一個問題與知識庫 ID，伺服器會執行向量檢索 → （視設定）機密權限過濾 → 交給 LLM 生成回答，並以 SSE（Server-Sent Events）串流方式即時回傳處理進度與最終答案。

與 AiRAG 內部人員登入使用的 `/api/rag/chat` 是**不同端點**，差異：

| 項目 | `/api/rag/chat`（內部） | `/api/external/chat`（本文件） |
|:---|:---|:---|
| 認證方式 | JWT（`Authorization: Bearer <token>`，AiRAG 帳號登入） | API Key（`X-API-Key: <key>`，見第 2 節） |
| 呼叫端身分 | `params.simulated_user_id`（挑選 AiRAG 內部預先建立的模擬身分，選填） | `params.external_user`（呼叫端直接帶入真實員工身分六大欄位，**必填**） |
| 自訂總結指示 | 無法自訂，固定寫死於後端 | `params.custom_system_prompt`（選填，可覆蓋預設指示規則文字） |
| 稽核紀錄 | 無 | 每次呼叫都會寫入 MongoDB 稽核紀錄（見第 8 節） |
| Response 格式 | SSE | 完全相同的 SSE 格式（底層共用同一套處理管線，見第 4 節） |

**如果你手上已經有一份實際的 Request JSON 範例**：AiRAG 前端「外部 API 測試」頁（`/external-api-test`，需 AiRAG 帳號登入）提供一個可視覺化組出 Request JSON 並直接送出測試的工具頁，畫面右側「API 預覽」區塊會即時顯示目前參數組出的完整 JSON，可以複製直接使用或比對本文件內容。

---

## 2. Base URL 與認證

### 2.1 Base URL

```
http://<AiRAG 後端主機>:53020/api
```

實際主機位址請向 AiRAG 維運人員索取；本端點僅供**公司內網**存取，未對外網開放。

### 2.2 取得 API Key

1. 請你的窗口（AiRAG 管理者，具備 AiRAG 登入帳號者）於 AiRAG 前端「角色與權限設定」頁（`/role-settings`）的「外部 API 金鑰管理」區塊建立一把新金鑰（呼叫 `POST /api/external-api-keys`，Body 只需 `{ "name": "你的系統名稱" }`）。
2. 金鑰**只會在建立當下顯示一次完整明碼**，資料庫僅保留雜湊值，之後無法再次查詢明碼，請務必當場妥善保存（例如存進你系統的密鑰管理服務）。遺失只能請管理者刪除舊金鑰並重新建立一把。
3. 每次呼叫 `/api/external/chat` 都要帶上這把金鑰。

### 2.3 Header 慣例

| Header | 值 | 說明 |
|:---|:---|:---|
| `Content-Type` | `application/json` | |
| `X-API-Key` | `<你的完整金鑰明碼>` | **必填**。刻意不使用 `Authorization: Bearer`，避免與 AiRAG 內部人員登入的 JWT 機制混淆——兩者語意不同：JWT 代表「已登入的人類使用者」，API Key 代表「已授權的外部系統」。 |

金鑰無效、已停用、或未帶此標頭：回傳 `401 Unauthorized`，Body 為 `{"detail": "無效的 API Key"}` 或 `{"detail": "無效或已停用的 API Key"}`。

> **跨來源資源共用 (CORS)**：AiRAG API 服務已啟用 CORS 設定，允許前端網頁應用程式（Web Client / SPA）跨網域發送帶有 `X-API-Key` 自訂標頭的 AJAX / Fetch 串流請求。

---

## 3. Request

### 3.1 端點

```
POST /api/external/chat
```

### 3.2 Request Body 完整欄位

```json
{
  "question": "上個月的請假規定是什麼？",
  "knowledge_base_id": "665f1a2b3c4d5e6f7a8b9c0d",
  "chat_history": [
    { "role": "user", "content": "之前問過的問題" },
    { "role": "assistant", "content": "AI 先前的回答" }
  ],
  "selected_db_profile_id": null,
  "params": {
    "search_type": "semantic_hybrid",
    "top_k": 13,
    "score_threshold": 0.65,
    "ai_summary_score_threshold": 0.60,
    "filter_tags": ["人資"],
    "temperature": 0.3,
    "max_tokens": 1024,
    "repetition_penalty": 1.1,
    "frequency_penalty": 0,
    "context_summarize_trigger_tokens": 50000,
    "read_attachment_content": false,
    "history_context_turns": 3,
    "pinned_filename": null,
    "custom_system_prompt": null,
    "external_user": {
      "employee_id": "E12345",
      "name": "王小明",
      "department_code": "HR01",
      "department_name": "人力資源部",
      "job_title_name": "專員",
      "job_title_level": 8
    }
  }
}
```

> 沒有列在上表的欄位（例如整份 `params`、`chat_history`）都可以直接省略，後端會套用預設值；`undefined`／不帶欄位 與明確帶 `null` 在多數欄位上效果相同（Pydantic `Optional[...] = None`）。

#### 3.2.1 頂層欄位

| 欄位 | 型別 | 必填 | 說明 |
|:---|:---|:---:|:---|
| `question` | string | ✅ | 使用者提問文字。 |
| `knowledge_base_id` | string \| null | 選填 | 要檢索的知識庫 ID（MongoDB ObjectId 字串）。如需指定特定知識庫（例如「人資規章知識庫」），請向 AiRAG 專案維護者或管理者索取該知識庫 ID。**留空 = 不執行任何檢索**，直接進入純 LLM 對話模式（此時若有帶 `custom_system_prompt` 會完全依該文字生成回答，見 3.4 節）。 |
| `chat_history` | array | 選填 | 多輪對話歷史，格式 `[{ "role": "user"｜"assistant", "content": "string" }, ...]`，供指代消解（例如「那它的價格呢」）與一般對話上下文使用。首次提問可省略或傳空陣列。 |
| `selected_db_profile_id` | string \| null | 選填 | 僅 `search_type = "semantic_db_query"` 且需要「二次選定候選查詢設定檔」時才帶入，見 3.5 節。一般查詢法不需要這個欄位。 |
| `params` | object | 選填 | 檢索與生成參數，見下表。整個 `params` 可省略，但**若要使用外部呼叫（見 `external_user`），實務上必帶**，否則會回傳 `400`（見 3.3 節）。 |

#### 3.2.2 `params.*`（檢索與生成參數）

| 欄位 | 型別 | 預設值 | 說明 |
|:---|:---|:---|:---|
| `search_type` | string | `"vector"` | 檢索模式，可選值與說明見 3.6 節。 |
| `top_k` | int | `13` | 檢索筆數上限。 |
| `score_threshold` | float | `0.65` | 檢索相似度最低門檻，低於此分數的片段不會被檢索回傳（不會出現在 `sources`）。 |
| `ai_summary_score_threshold` | float | `0.60` | AI 總結門檻。低於此分數但仍高於 `score_threshold` 的片段會出現在 `sources`，但不會被納入 AI 總結時參考的上下文；若本次檢索到的片段全數低於此門檻，會觸發防幻覺保護機制，提前回傳固定提示訊息、**不呼叫 LLM**（見 4.4 節「提前結束」情境）。 |
| `filter_tags` | string[] | 不過濾 | 依標籤過濾檢索範圍，未帶或空陣列代表不過濾。 |
| `temperature` | float | `0.3` | LLM 生成溫度。 |
| `max_tokens` | int | `1024` | LLM 最大生成 token 數。 |
| `repetition_penalty` | float | `1.1` | LLM 重複懲罰參數。 |
| `frequency_penalty` | float | `0` | LLM 頻率懲罰參數。 |
| `context_summarize_trigger_tokens` | int | `50000` | 檢索到的上下文總 token 數超過此門檻時，會先經過一輪 Map-Reduce 分批摘要才送進主模型，避免超出上下文長度限制；多數情況下不會觸發。 |
| `read_attachment_content` | bool | `false` | 僅 `search_type = "semantic_hybrid_attachment"` 有效：是否讀取命中片段關聯附件的實際內容一併納入回答依據。 |
| `history_context_turns` | int \| null | `3` | 語義理解階段（`semantic_hybrid` 家族）參考的歷史對話則數；設為 `0` 或 `null` 代表不帶歷史脈絡（純單輪理解）。 |
| `pinned_filename` | string \| null | 不鎖定 | 僅語義混合家族查詢法有效：手動鎖定只在指定檔名內檢索，`null` 代表由 AI 自動判斷要查哪份文件。 |
| `custom_system_prompt` | string \| null | 使用系統預設 | 自訂總結提示詞，見 3.4 節。 |
| `external_user` | object | 無預設，**外部呼叫必填** | 呼叫端真實使用者身分，見 3.3 節。 |

> `model` 欄位（若有帶）目前後端**不會**實際用來選擇模型，僅保留欄位相容性，不建議依賴。

### 3.3 `params.external_user`（必填）

外部應用呼叫本端點時，**必須**在 `params.external_user` 帶入實際發起這次提問的員工身分；若整個 `params` 或 `params.external_user` 缺漏，回傳：

```
400 Bad Request
{ "detail": "外部應用呼叫必須於 params.external_user 帶入使用者身分資訊" }
```

欄位：

| 欄位 | 型別 | 必填 | 說明 |
|:---|:---|:---:|:---|
| `employee_id` | string | ✅ | 工號。僅供稽核紀錄與畫面顯示，不影響檢索過濾判斷。 |
| `name` | string | ✅ | 姓名。僅供稽核紀錄與排除說明文字顯示（例如「已排除段落：王小明權限不足」）。 |
| `department_code` | string | ✅ | 部門代號。**實際用於機密文件的部門限制比對**（見下方說明）。 |
| `department_name` | string | ✅ | 部門名稱。僅供排除說明文字顯示用，不參與比對邏輯的主要判斷鍵。 |
| `job_title_name` | string | ✅ | 級職名稱（例如「經理」「專員」）。僅供排除說明文字顯示。 |
| `job_title_level` | int | ✅ | 級職等級，**數字越小代表權限越高**。實際用於機密文件的等級比對：文件標記等級為 N，使用者等級數字 > N 即視為權限不足。 |

**這組欄位如何影響回答內容**：AiRAG 的知識庫可以針對個別文件設定「機密等級」與「限定部門」。若某次檢索命中的片段被標記為機密，系統會比對 `job_title_level`（等級是否足夠）與 `department_code`（部門是否在允許清單內，判斷同時相容部門代號與部門名稱兩種格式），任一項不符即會將該片段從送進 LLM 的上下文中排除，並在最終回答前面加註排除說明。**這組欄位由呼叫端直接宣稱、後端不會再對照任何外部人事系統做二次驗證**，信任邊界建立在「已通過第 2 節 API Key 驗證的呼叫系統本身可信」——請確保你的系統只用真實登入使用者的身分資訊呼叫本端點，不要讓使用者自行填寫這幾個欄位。

### 3.4 `params.custom_system_prompt`（選填）— 自訂總結指示

* **留空（不帶或空白字串）**：使用 AiRAG 系統預設的總結指示規則（含引用格式規則等），行為與內部「RAG 功能測試」頁完全相同。
* **有帶內容**（去除頭尾空白後非空）：**完全取代**預設指示規則文字段落；本次檢索到的實際參考資料（若有指定 `knowledge_base_id`）仍會由後端自動接續在你提供的指示文字後面——呼叫當下你不可能預先知道會檢索到什麼內容，所以這裡只有「指示規則怎麼寫」是完全由你決定，資料本身仍由伺服器動態接續。
* **特殊情境**：若 `knowledge_base_id` 留空（不檢索任何資料）且有帶 `custom_system_prompt`，回答會直接依你提供的這段文字生成，**不會**被強制接上「知識庫沒有相關資訊」的預設警語——可用於「不掛知識庫、純測試 LLM 本身行為」的情境。
* 若 `knowledge_base_id` 有值但本次檢索結果為空或全數低於 `ai_summary_score_threshold`，仍會維持既有防幻幻覺機制提前回傳固定提示訊息、不呼叫 LLM，**不受** `custom_system_prompt` 影響（這是既有的保護機制，優先權高於自訂指示）。

### 3.5 `selected_db_profile_id`（僅 `search_type = "semantic_db_query"` 使用）

`semantic_db_query`（語義資料庫查詢法）是特殊的兩段式流程，用於讓 AI 依自然語言問題比對既有「查詢設定檔」、產生 SQL 查詢既有關聯式資料庫（非向量檢索）：

1. **第一次請求**：帶 `knowledge_base_id` 與 `question`，**不帶** `selected_db_profile_id`。若該知識庫命中多個候選查詢設定檔，伺服器會回傳 `event: step`（`step: "profile_candidates"`）列出候選清單並**暫停**（串流直接以 `chunk: done` 結束，不會呼叫 LLM）。
2. **第二次請求**：帶上完全相同的 `question`／`knowledge_base_id`，並在 `selected_db_profile_id` 帶入使用者從候選清單中選定的 `profile_id`，伺服器才會實際產生 SQL、查詢資料庫、將結果交給 LLM 總結。

> 若請求**未帶** `knowledge_base_id`（不限定知識庫），伺服器會自動掃描所有知識庫的查詢設定檔並自動選擇最相關的前幾個依序執行、合併結果，不會中斷等待選擇——此情境下不需要 `selected_db_profile_id`。

一般三種向量檢索法（`vector`／`hybrid`／`semantic_hybrid*`）**不需要**這個欄位，不使用 `semantic_db_query` 可以完全忽略本節。

### 3.6 `params.search_type` 可選值

| 值 | 說明 |
|:---|:---|
| `vector` | 純向量（Dense）相似度檢索，速度最快，適合語意單純明確的查詢。 |
| `hybrid` | 向量 + 關鍵字稀疏向量（Sparse）混合檢索並用 RRF 融合排序，兼顧語意與關鍵字命中。 |
| `semantic_hybrid` | 先由地端 Instruct LLM 把問題解析為結構化查詢 JSON，再執行雙階段關聯檢索（先查核心片段，再依文件間的關聯關係擴充查詢相關聯的片段），適合需要跨文件關聯脈絡的問題，是目前建議的預設查詢法。 |
| `semantic_hybrid_feedback` | 與 `semantic_hybrid` 相同，額外套用歷史使用者回饋（按讚/倒讚）調整排序權重。 |
| `semantic_hybrid_attachment` | 與 `semantic_hybrid` 相同，額外查詢命中片段關聯的附件檔案，並可選擇是否讀取附件實際內容納入回答依據（見 `read_attachment_content`）。 |
| `semantic_db_query` | 不查詢向量資料庫，改為比對既有「查詢設定檔」、產生唯讀 SQL 查詢既有關聯式資料庫，見 3.5 節。 |

不確定要用哪一種時，建議先用 `semantic_hybrid`。

---

## 4. Response：SSE 事件串流

### 4.1 基本格式

`Content-Type: text/event-stream`。每個事件為一段以空行結尾的文字區塊，格式固定為：

```
event: <事件名稱>
data: <一行 JSON>

```

用瀏覽器原生 `EventSource` **無法**送出 POST 請求與自訂 Header（`X-API-Key`），請改用 `fetch` + `ReadableStream` 手動解析（見第 6 節範例），或你熟悉的語言中支援自訂 Header 的 SSE / streaming HTTP client。

### 4.2 `event: step` — 處理進度

```json
{ "step": "semantic_analysis", "status": "running", "content": "..." }
```

| 欄位 | 說明 |
|:---|:---|
| `step` | 步驟識別碼，見下方列表。 |
| `status` | `running`／`success`／`failed`／`warning`／`pending`。同一個 `step` 通常會先送一次 `running` 再送一次 `success`（或 `failed`），前端對同一個 `step` 的顯示應以**最新一筆覆蓋前一筆**，而非逐筆疊加。 |
| `content` | 該步驟目前的說明文字（人類可讀），可直接顯示給使用者看處理進度。 |

固定會依序出現的核心步驟：`semantic_analysis` → `vector_search` → `llm_thinking` → `conclusion`（`conclusion` 固定只送一次 `status: pending`，代表接下來要開始輸出 `event: chunk`）。

視情況才會插入的動態步驟：

* `attachment_extraction`：僅 `search_type = "semantic_hybrid_attachment"` 且 `read_attachment_content = true` 且確實找到關聯附件時出現，列出讀取到的附件內容。
* `context_summarize_r{N}_batch_{i}` / `context_summarize_r{N}_reduce` / `context_summarize_error`：僅上下文 token 數超過 `context_summarize_trigger_tokens` 門檻時出現，代表正在執行分批摘要；未觸發時完全不會出現，不需特別處理。
* `profile_candidates`：僅 `search_type = "semantic_db_query"` 且需要使用者選擇候選設定檔時出現，`content` 之外額外帶 `candidates` 陣列，每筆候選為 `{ "profile_id": "string", "name": "string", "table_name": "string", "score": 0.95 }`，見 3.5 節。

### 4.3 `event: chunk` — LLM 逐字輸出

```json
{ "type": "content", "content": "回答文字片段" }
```

| `type` | 說明 |
|:---|:---|
| `reasoning` | 模型思考過程片段（若模型有輸出思考內容），可選擇性顯示或隱藏。 |
| `content` | 正式回答內容片段，依序拼接即為完整回答。 |
| `done` | 串流結束標記，此類型**沒有** `content` 欄位。**注意**：見 4.4 節，並非所有情境都會送出這個事件。 |

### 4.4 `event: message` — 提前結束的固定訊息（無 `chunk: done`）

某些情況伺服器會**不呼叫 LLM**、直接回傳一段固定提示訊息並提前結束整個串流：

```json
{ "delta": "⚠️ **權限不足，無法提供回答**\n\n..." }
```

會觸發的情境：
* 檢索到的內容因 `external_user` 權限比對全數被排除（機密文件權限不足）。
* 檢索到的內容全數低於 `ai_summary_score_threshold`（防幻覺保護）。

**這兩種情境的事件順序是 `event: message` → `event: sources` → 串流直接結束**，**不會**再送出 `event: chunk`（也就是不會有 `type: "done"`）。實作串流解析時請以「連線關閉」而非「收到 `chunk: done`」作為串流真正結束的判斷依據，避免卡在等待一個不會出現的事件。

### 4.5 `event: sources` — 引用來源與統計（`chunk: done` 之前送出一次，或提前結束時送出）

```json
{
  "sources": [
    {
      "chunk_id": "string",
      "content": "段落內容",
      "metadata": {
        "filename": "string",
        "page": 1,
        "section": "string",
        "chunk_index": 0,
        "tags": ["string"],
        "class": ["string"],
        "chunk_type": "image | text | null",
        "image_filename": "string | null"
      },
      "score": 0.85,
      "token_count": 512
    }
  ],
  "context_summary": {
    "total_tokens": 45000,
    "batch_count": 0,
    "rounds": 0,
    "was_summarized": false,
    "threshold_tokens": 50000
  },
  "attachments": [
    { "id": "string", "original_filename": "string", "description": "string", "download_url": "/api/attachments/{id}/download" }
  ]
}
```

* `sources`：本次回答實際引用的檢索片段清單，可用於前端顯示「參考資料來源」。
* `context_summary`：本次上下文 token 統計；`was_summarized = true` 代表有觸發第 4.2 節的分批摘要。
* `attachments`：僅 `search_type = "semantic_hybrid_attachment"` 且命中片段有關聯附件時才非空。其中 `download_url` 為相對路徑，但目前附件下載端點（`GET /api/attachments/{id}/download`）仍走內部 JWT 保護，外部應用使用者點擊時因無 JWT 會回傳 401。因此 **LLM 會在生成回答時直接讀取附件內容作答，但請勿直接將 `download_url` 暴露給未登入的外部使用者點擊**（如需開放下載請另行與 AiRAG 維護者確認存取方式）。

### 4.6 一次完整成功呼叫的事件順序範例

```
event: step   {"step":"semantic_analysis","status":"running", ...}
event: step   {"step":"semantic_analysis","status":"success", ...}
event: step   {"step":"vector_search","status":"running", ...}
event: step   {"step":"vector_search","status":"success", ...}
event: step   {"step":"llm_thinking","status":"running", ...}
event: step   {"step":"conclusion","status":"pending", ...}
event: chunk  {"type":"content","content":"根據"}
event: chunk  {"type":"content","content":"公司規定"}
event: chunk  {"type":"content","content":"..."}
event: sources {"sources":[...], "context_summary":{...}, "attachments":[]}
event: chunk  {"type":"done"}
```

---

## 5. 錯誤處理

| 情況 | HTTP 狀態碼 | Body |
|:---|:---|:---|
| 未帶 `X-API-Key` 或格式不符 | 401 | `{"detail": "無效的 API Key"}` |
| API Key 不存在、已停用、或雜湊比對失敗 | 401 | `{"detail": "無效或已停用的 API Key"}` |
| 缺少 `params.external_user` | 400 | `{"detail": "外部應用呼叫必須於 params.external_user 帶入使用者身分資訊"}` |
| Request Body 格式錯誤（例如缺少必填的 `question`、欄位型別錯誤） | 422 | FastAPI 標準驗證錯誤格式：`{"detail": [{"loc": ["body", "question"], "msg": "field required", "type": "value_error.missing"}]}` |
| 串流過程中檢索或 LLM 呼叫發生例外 | 200（串流已開始） | 以 `event: chunk` 的 `type: "content"` 送出一段「查詢失敗：...」文字後正常送出 `chunk: done` 結束，不會是 HTTP 層級的錯誤碼（因為 Header 早已送出） |

由於是串流回應，**只有連線建立當下**（尚未開始傳送任何事件）會是標準 HTTP 錯誤碼；一旦開始收到 `event: step` 或 `event: chunk`，代表請求本身已被接受，後續錯誤會包裝成串流內的文字訊息，不會是 HTTP 4xx/5xx。

---

## 6. 完整範例

### 6.1 curl

```bash
curl -N -X POST "http://<host>:53020/api/external/chat" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <你的金鑰明碼>" \
  -d '{
    "question": "特休假的計算方式是什麼？",
    "knowledge_base_id": "665f1a2b3c4d5e6f7a8b9c0d",
    "params": {
      "search_type": "semantic_hybrid",
      "external_user": {
        "employee_id": "E12345",
        "name": "王小明",
        "department_code": "HR01",
        "department_name": "人力資源部",
        "job_title_name": "專員",
        "job_title_level": 8
      }
    }
  }'
```

`-N` 停用 curl 的輸出緩衝，才能即時看到逐段送出的 SSE 事件。

### 6.2 JavaScript（`fetch` + `ReadableStream`，瀏覽器或 Node 18+）

```javascript
async function askAiRag(question, externalUser, apiKey, baseUrl) {
  const res = await fetch(`${baseUrl}/external/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-API-Key': apiKey
    },
    body: JSON.stringify({
      question,
      knowledge_base_id: '665f1a2b3c4d5e6f7a8b9c0d',
      params: {
        search_type: 'semantic_hybrid',
        external_user: externalUser
      }
    })
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(`呼叫失敗 (${res.status}): ${err.detail || res.statusText}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let answer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    // SSE 事件以空行分隔，逐一取出已收到的完整事件
    let sep
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const rawEvent = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)

      let eventName = null
      let data = null
      for (const line of rawEvent.split('\n')) {
        if (line.startsWith('event:')) eventName = line.slice(6).trim()
        else if (line.startsWith('data:')) data = JSON.parse(line.slice(5).trim())
      }

      if (eventName === 'chunk') {
        if (data.type === 'content') {
          answer += data.content
          // 可在此即時更新畫面
        } else if (data.type === 'reasoning') {
          // (選填) 模型思考過程片段，可自由選擇在 UI 上獨立顯示或隱藏
          console.log('[Reasoning]', data.content)
        }
      } else if (eventName === 'message') {
        answer = data.delta // 提前結束情境：整段覆蓋，非累加
      } else if (eventName === 'sources') {
        console.log('引用來源：', data.sources)
      } else if (eventName === 'step') {
        console.log(`[${data.step}] ${data.status}: ${data.content}`)
      }
      // event: chunk, type: "done" 出現時即代表本次已完整結束；
      // 但如第 4.4 節所述，部分情境不會送出此事件，串流連線關閉即代表結束
    }
  }

  return answer
}
```

---

## 7. `search_type` 快速選擇建議

* 一般問答、不確定選哪個：`semantic_hybrid`。
* 只是想要最快回應、問題語意單純：`vector`。
* 想要同時吃到附件內容：`semantic_hybrid_attachment` + `read_attachment_content: true`。
* 要問的是「查資料庫報表/統計數字」而非「查文件內容」：`semantic_db_query`（見 3.5 節兩段式流程）。

---

## 8. 稽核紀錄（僅供知悉，非本 API 的一部分）

每次呼叫本端點（不論正常結束、中途斷線、或例外）伺服器都會以 best-effort 方式在後端寫入一筆稽核紀錄（呼叫端身分、問題、回答、引用來源精簡中繼資料、耗時），供 AiRAG 管理者事後追查使用。**這是伺服器內部行為，本 API 不提供讀取或查詢這份稽核紀錄的端點**，呼叫端不需要也不應該依賴它做任何業務邏輯。

---

## 9. 已知限制

* 目前**未實作速率限制（Rate Limit）**。若你的系統呼叫頻率很高，請先與 AiRAG 維運人員討論，避免影響共用的 LLM／檢索服務資源給其他呼叫端。
* 本端點僅限公司內網存取，未對外網開放；若你的應用部署在外網，需另行與維運人員確認網路連線方式（例如經由內網閘道）。
* 附件下載端點（`event: sources` 內 `attachments[].download_url`）目前仍受內部 JWT 保護，外部應用尚無法直接下載，如有需求請與 AiRAG 維護者確認替代方案。
