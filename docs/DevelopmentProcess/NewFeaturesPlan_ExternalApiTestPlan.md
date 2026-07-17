# 外部 API 測試頁面規劃文件

> 狀態：全部章節（第 1～12 節）**已實作完成**（2026-07-17，見 [NewFeatures.md](NewFeatures.md) / [BackendCorrection.md](BackendCorrection.md) / [FrontendCorrection.md](FrontendCorrection.md) 對應紀錄）。第 8.4 節「既有資料遷移風險」已採選項 2（過渡期雙軌比對）上線，不需額外遷移腳本；第 9.4 節的 `try...finally` 落地保護結構、第 10 節 API Key 驗證機制、`external_user` 取代 `simulated_user_id` 皆已落實於程式碼。
> 目的：讓「未來要接入 AiRAG 的公司內網外部應用」有一個獨立、不與內部測試共用的 API 端點；並在前端提供一個「組合參數 → 產生 JSON → 直接測試」的工具頁，讓開發者能照著畫面組出的 JSON 直接串接。

---

## 1. 背景與需求

現有 [RagTestView.vue](../../frontend/src/views/RagTestView.vue)（「RAG 功能測試」頁）呼叫的是 `POST /api/rag/chat`（[rag.py](../../backend/routers/rag.py)），此端點：
- 掛在 `Depends(get_current_user)` 底下，僅接受登入使用者的 JWT Bearer Token（見 [security.py](../../backend/utils/security.py)）。
- `system_prompt`（總結提示詞）完全寫死在後端（[rag.py:762-775](../../backend/routers/rag.py:762)，含引用格式規則等），無法由呼叫端客製化。

使用者需求：新增一個「外部 API 測試」頁面，讓使用者能：
1. 用與「RAG 功能測試」右側完全相同的「檢索設定」「生成模型設定」表單組出 POST JSON。
2. 額外可自訂「總結提示詞」，留空則用系統預設。
3. 組合完成後，畫面上要能看到這份 JSON 內容本身與逐欄位說明——這份內容日後會直接提供給外部應用的開發者作為串接參考。
4. 送出後能在同一頁面用「跟 RAG 功能測試一樣」的對話視窗看到 SSE 處理過程（語義分析／檢索／思考／結論等步驟）。
5. 後端要新增一個獨立的外部 API 端點，不與內部 `/api/rag/chat` 共用同一個 URL。

## 2. 已與使用者確認之決策

| 決策項目 | 結論 |
|:---|:---|
| 外部端點認證方式 | **暫不做認證**（僅限公司內網存取把關），之後有需要再補 API Key 機制 |
| 「檢索設定也需要外部 API」的範圍 | **取消**：不需要獨立的「僅檢索」外部端點；使用者組好 `/api/external/chat` 的 JSON 後直接提供給外部應用整合即可 |
| 自訂總結提示詞的客製化方式 | **完全覆蓋**：外部呼叫端若有帶 `custom_system_prompt`，就整段取代預設的指示規則文字（含引用格式規則等）；留空則沿用現有預設模板 |

> 關於「完全覆蓋」的技術補充：目前 `system_prompt` 是「指示規則文字」+「【參考資料】＋實際檢索到的內容」拼接而成（[rag.py:762-775](../../backend/routers/rag.py:762)）。呼叫端在送出請求當下不可能知道本次會檢索到什麼內容，因此 `custom_system_prompt` 只取代**指示規則文字**的部分，檢索到的參考資料仍由後端在其後方自動附加——這是讓「自訂提示詞」在 RAG 情境下仍然有意義的必要設計，並非部分覆蓋，而是「使用者可完全決定指示規則怎麼寫，資料本身仍由系統動態接續」。

## 3. 後端設計

### 3.1 新端點：`POST /api/external/chat`

新增檔案 [external.py](../../backend/routers/external.py)（比照現有 `routers/` 一檔一功能的慣例）：

```python
router = APIRouter(prefix="/external", tags=["External API"])
# 不掛 Depends(get_current_user) —— 依決策，外部端點暫不驗證

@router.post("/chat")
async def external_chat(request: ChatRequest):
    return StreamingResponse(rag_chat_stream(request), media_type="text/event-stream")
```

於 [main.py](../../backend/main.py) 註冊：`app.include_router(external.router, prefix="/api")` → 實際路徑 `POST /api/external/chat`。

**技術取捨**：直接 import 並重用 `routers.rag` 現有的 `ChatRequest` schema 與 `rag_chat_stream()` 這個 async generator（[rag.py:229-834](../../backend/routers/rag.py:229)），而不是複製一份約 800 行的檢索/摘要/串流管線邏輯。「不與內部測試 API 共用」理解為**不共用同一個 URL 路徑與認證需求**（外部呼叫者走獨立網址、無需登入），而非要求底層管線程式碼也要重寫一份——重寫會讓兩邊之後各自修 bug、行為容易長期不一致，違反「簡單優先」與「外科手術式修改」原則。若後續要讓外部端點在功能上與內部逐漸分岔（例如關閉某些 search_type），屆時再視需求拆分。

### 3.2 支援 `custom_system_prompt`

於 `ChatParams`（[rag.py:29-44](../../backend/routers/rag.py:29)）新增一個選填欄位：

```python
custom_system_prompt: Optional[str] = None
```

於 `rag_chat_stream()` 參數解析區（[rag.py:247-273](../../backend/routers/rag.py:247)）新增對應的區域變數擷取（模式與現有 `pinned_filename_param` 等一致），並在組裝 `system_prompt` 的三個分支（[rag.py:739-780](../../backend/routers/rag.py:739)：`semantic_db_query` 分支／一般 `context_str` 分支／無資料分支）分別改為：**若 `custom_system_prompt`（去除空白後）非空，就以它取代該分支原本寫死的規則文字段落，再接續原本就有的「【參考資料】／資料庫查詢結果」內容**；為空則完全維持現有預設文字，內部 `/api/rag/chat` 行為不受影響（因為內部前端從不會送這個欄位）。

> **補充：「無知識庫／無檢索資料」分支的明確行為**。已對照程式碼確認，`request.knowledge_base_id` 為 `null`（未選知識庫）時，[rag.py:641-643](../../backend/routers/rag.py:641) 只會略過檢索、`context_str` 維持空字串，並**不會**觸發 [rag.py:660](../../backend/routers/rag.py:660) 那段提早 `return`（該段 `if` 條件本身要求 `request.knowledge_base_id` 為真值才會生效），因此仍會往下走到組 `system_prompt` 的第三分支（[rag.py:776-779](../../backend/routers/rag.py:776)，目前寫死「請直接回答『知識庫沒有相關資訊。』」）並實際呼叫 LLM。因此明確規則是：**當 `knowledge_base_id` 為空且帶了 `custom_system_prompt` 時，`system_prompt` 直接等於 `custom_system_prompt`，不再強制接上「知識庫沒有相關資訊」這段警語**——這讓外部開發者能用這個端點做「不掛知識庫的純 Prompt／LLM 行為測試」。若 `knowledge_base_id` 為空但也沒帶 `custom_system_prompt`，則完全維持現有預設警語文字，行為不變。
>
> 另外，`request.knowledge_base_id` 有值、但本次檢索結果為空或全數低於門檻的情境（[rag.py:645-678](../../backend/routers/rag.py:645)）不在此次調整範圍內——那段邏輯會在組 `system_prompt` 之前就直接回傳固定提示訊息、完全不呼叫 LLM，這是既有的防幻覺保護機制，`custom_system_prompt` 不影響、也不應該影響這段提早 return 的判斷。

此欄位加在共用的 `ChatParams` 上，`/api/rag/chat` 與 `/api/external/chat` 共用同一份解析邏輯，兩邊都能用，但目前只有「外部 API 測試」頁面的表單會實際填寫並送出它。

### 3.3 已知限制（不在本次實作範圍，留待日後追加）

- 目前無認證機制，僅能依賴公司內網存取限制把關；若未來要對外開放或有資安疑慮，需再補 API Key／IP 白名單等機制。
- 未涵蓋速率限制（Rate Limit）；若外部應用行為異常可能影響共用的 vLLM/llama.cpp/Qdrant 資源，屆時再評估是否需要。

## 4. 前端設計

### 4.1 導覽選單與路由

- [AppSidebar.vue](../../frontend/src/components/common/AppSidebar.vue) 的 `menuItems` 新增一筆，路徑 `/external-api-test`，label 建議「外部 API 測試 (External API)」，圖示比照現有其他項目風格另尋一個 API/程式碼相關的 SVG icon。
- [router/index.js](../../frontend/src/router/index.js) 新增路由 `path: '/external-api-test'`, `name: 'ExternalApiTest'`, `component: ExternalApiTestView`, `meta: { requiresAuth: true }`。

> 這個測試工具頁本身仍在內部系統選單內，操作者需先登入才能使用（`requiresAuth: true`），這與「頁面呼叫的 `/api/external/chat` 端點本身不驗證」是兩件事——登入保護的是「誰能用這個組 API 的工具」，不是「外部端點本身」。

### 4.2 檢索／生成參數表單：直接重用既有元件與 `paramsStore`

「表單內容同 RAG 功能測試右側的設定參數」——不重寫一份新的表單，而是直接在新頁面內重用既有的
[RagParamsPanel.vue](../../frontend/src/components/params/RagParamsPanel.vue)、
[LlmParamsPanel.vue](../../frontend/src/components/params/LlmParamsPanel.vue)、
[KnowledgeBaseSelector.vue](../../frontend/src/components/common/KnowledgeBaseSelector.vue) 三個元件，這些元件目前都是直接綁定全域的 [paramsStore.js](../../frontend/src/stores/paramsStore.js)，不需要新建一份平行的 store 與元件（避免大量重複程式碼與日後兩邊各自漂移）。

**取捨說明**：這代表「RAG 功能測試」頁與「外部 API 測試」頁會共用同一份檢索/生成參數狀態（例如切到外部頁調整 Top-K，回到 RAG 測試頁也會是同一個值）。這是刻意的簡化，好處是零重複程式碼；如果實際使用上覺得兩頁參數會互相干擾造成困擾，之後可以再拆成獨立 store，但重複 5 個元件（含知識庫下拉、使用者列表載入邏輯）在目前階段不符合「簡單優先」。

新增 `customSystemPrompt: ''` 欄位到 `paramsStore.js` state（內部 RAG 測試頁的 `chatStore._streamChat` 組 payload 時本來就不會讀取這個新欄位，不影響現有行為）。

新增小元件 `components/params/CustomSystemPromptPanel.vue`：一個帶說明文字的 `<textarea>`，`v-model="paramsStore.customSystemPrompt"`，placeholder 提示「留空則使用系統預設總結提示詞」。**只放在外部 API 測試頁**，不加進 `LlmParamsPanel.vue`，避免這個新欄位也出現在內部「RAG 功能測試」頁面造成困惑。

### 4.3 API JSON 預覽區塊（2-2 需求）

新增元件 `components/params/ApiJsonPreviewPanel.vue`：
- 用一個 `computed` 屬性，依 `paramsStore` 目前的值即時組出與 [chatStore.js:117-137](../../frontend/src/stores/chatStore.js:117) 相同結構的 request body（`question` 欄位用聊天輸入框目前打的文字，若為空則顯示 `"<請輸入問題>"` 之類的佔位字樣；`custom_system_prompt` 只在非空白時才放進 `params`，維持「留空即不覆蓋」的語意），額外標明目標網址為 `POST {後端網址}/api/external/chat`。
- 畫面呈現：
  - 方法＋網址＋（無需 Authorization 標頭之說明）
  - 格式化後的 JSON（`<pre>`，附「複製」按鈕）
  - 逐欄位白話說明列表（例如 `search_type` 有哪些可選值、`custom_system_prompt` 的覆蓋規則等），比照本文件第 3 節的規則直接寫成給外部工程師看的白話文字
- 這個區塊是唯讀展示用途，不影響送出對話的實際行為（送出時仍是即時組出當下的 payload，邏輯與預覽共用同一個 computed，避免兩處各自組一次造成不一致）。
- **序列化細節**：預覽顯示一律用 `JSON.stringify(payload, null, 2)` 直接輸出這個共用 computed 的結果，不另外手動格式化。沿用 [chatStore.js:117-137](../../frontend/src/stores/chatStore.js:117) 目前已有的 `xxx || undefined` 模式（例如 `filter_tags` 為空陣列、`context_summarize_trigger_tokens` 未填時都組成 `undefined`），`JSON.stringify` 會自動略過值為 `undefined` 的欄位，因此空的選填欄位不會出現在預覽或實際送出的 JSON 中；至於 `pinned_filename`／`simulated_user_id` 這類欄位維持現況顯式傳 `null`（後端 `Optional[...] = None` 本就等效於未帶欄位，不會導致驗證失敗）。此規則沿用既有程式碼慣例，不需新增額外的欄位清理邏輯。**`simulated_user_id` 欄位的長期方向見第 8 節，屆時本節與欄位說明列表需要一併更新。**

### 4.4 對話視窗重用（3 需求）

「送出組合過的 API，可以看到處理過程，同 RAG 功能測試的對話視窗」——採用最小改動方式重用 [ChatWindow.vue](../../frontend/src/components/chat/ChatWindow.vue)，而不是整份複製：

1. 新增 `frontend/src/stores/externalChatStore.js`：與 [chatStore.js](../../frontend/src/stores/chatStore.js) 有相同的 `messages` / `isLoading` state，以及 `sendQuestion()` / `clearMessages()` / **`selectDbQueryProfile(assistantMessageId, profileId)`** 三個同名 action 介面（缺一不可——`selectDbQueryProfile` 是 `search_type = semantic_db_query` 兩段式候選設定檔選取流程必要的介面，[chatStore.js:89-95](../../frontend/src/stores/chatStore.js:89) 已有實作，外部頁面測試此查詢法時同樣需要）。`_streamChat()` 呼叫的目標是 `POST /api/external/chat`、**不帶 `Authorization` 標頭**（因為端點不驗證）、且不使用 `chatStore.js` 既有的 SSE 解析程式碼複製一份，而是抽出共用邏輯：
   - 將 [chatStore.js](../../frontend/src/stores/chatStore.js) 中「fetch + 讀取 SSE 串流 + 解析 `step`/`chunk`/`sources`/`message` 事件並更新訊息物件」這段（約 [chatStore.js:139-297](../../frontend/src/stores/chatStore.js:139)）抽成共用工具 `frontend/src/composables/useChatStream.js`，改吃 `{ endpoint, headers, payload, messages, assistantMessageId }` 參數，回傳/直接修改傳入的 message 物件。
   - `chatStore.js` 與新的 `externalChatStore.js` 都改呼叫這個共用工具，各自只保留自己的 `messages` 陣列狀態與 payload 組裝方式（`externalChatStore.js` 的 payload 直接讀 `paramsStore`，比照 4.3 節的 JSON 預覽邏輯）；`selectDbQueryProfile()` 的邏輯（找到訊息、重設 `awaitingProfileSelection`/`dbQueryCandidates`、帶著 `profileId` 重新呼叫 `_streamChat`）在兩個 store 中結構相同，直接比照 [chatStore.js:89-95](../../frontend/src/stores/chatStore.js:89) 複製一份即可（邏輯簡短，不需要另外抽共用工具）。
   - 這樣兩個頁面的對話紀錄各自獨立（不會互相污染訊息列表），但複雜且容易出錯的 SSE 解析邏輯只維護一份。
2. [ChatWindow.vue](../../frontend/src/components/chat/ChatWindow.vue) 目前內部直接 `useChatStore()`（[ChatWindow.vue:8](../../frontend/src/components/chat/ChatWindow.vue:8)），改為接受一個可選的 `store` prop，預設值才是 `useChatStore()`：外部頁面使用時傳入 `<ChatWindow :store="useExternalChatStore()" />`。已對照原始碼確認，`<script setup>` 內共有 6 處直接引用 `chatStore.*`（[ChatWindow.vue:8](../../frontend/src/components/chat/ChatWindow.vue:8) 取得 store、`isLoading`×3、`messages`、`clearMessages()`、`selectDbQueryProfile()`），改動時需**全部**改讀取注入的 `store` prop 而非只改 `sendQuestion` 那一處，否則外部頁面點「新對話」或選取資料庫查詢候選設定檔時仍會誤動到內部 `chatStore` 的狀態。模板與既有邏輯結構不變，`FeedbackPanel` 沿用（回饋功能走的 `/api/feedback` 本身仍需要登入 JWT，不受本次改動影響）。

### 4.5 頁面組裝

新增 [ExternalApiTestView.vue](../../frontend/src/views/ExternalApiTestView.vue)，版面比照 [RagTestView.vue](../../frontend/src/views/RagTestView.vue)（左側對話窗、右側可捲動參數側欄），右側側欄由上至下：`RagParamsPanel` → `LlmParamsPanel` → `CustomSystemPromptPanel` → `ApiJsonPreviewPanel`。因新增 JSON 預覽內容較長，實作時視畫面實際呈現效果調整側欄寬度（例如比內部頁的 320px 略寬），此為單純樣式細節，不影響前述資料流設計。

## 5. Proposed Changes（檔案清單，尚未動工）

### 後端
- **[NEW]** [backend/routers/external.py](../../backend/routers/external.py) — 新路由，`POST /api/external/chat`，無認證
- **[MODIFY]** [backend/routers/rag.py](../../backend/routers/rag.py) — `ChatParams` 新增 `custom_system_prompt`；`rag_chat_stream()` 三處 system_prompt 組裝分支支援覆蓋
- **[MODIFY]** [backend/main.py](../../backend/main.py) — 註冊 `external.router`

### 前端
- **[NEW]** `frontend/src/views/ExternalApiTestView.vue`
- **[NEW]** `frontend/src/stores/externalChatStore.js`
- **[NEW]** `frontend/src/composables/useChatStream.js`（從 chatStore.js 抽出的共用 SSE 處理邏輯）
- **[NEW]** `frontend/src/components/params/CustomSystemPromptPanel.vue`
- **[NEW]** `frontend/src/components/params/ApiJsonPreviewPanel.vue`
- **[MODIFY]** `frontend/src/stores/paramsStore.js` — 新增 `customSystemPrompt` 欄位
- **[MODIFY]** `frontend/src/stores/chatStore.js` — 改呼叫抽出後的 `useChatStream.js`（行為不變，純重構）
- **[MODIFY]** `frontend/src/components/chat/ChatWindow.vue` — 改為可注入 `store` prop（預設值不變）
- **[MODIFY]** `frontend/src/components/common/AppSidebar.vue` — 新增選單項目
- **[MODIFY]** `frontend/src/router/index.js` — 新增路由

### 文件
- **[MODIFY]** [docs/03_API_CONTRACT.md](../03_API_CONTRACT.md) — 待實作完成後，比照第 3.1 節 `/api/rag/chat` 的格式新增 `/api/external/chat` 條目（Request Body 額外多 `custom_system_prompt` 欄位；註明無需 `Authorization`；Response SSE 事件格式與 `/api/rag/chat` 完全相同，直接引用該節即可不必整段重複）
- 依 [AGENT.md](../../AGENT.md) 要求，實作完成後於 [BackendCorrection.md](BackendCorrection.md) 與 [FrontendCorrection.md](FrontendCorrection.md)（或 [NewFeatures.md](NewFeatures.md)）記錄本次變更

## 6. 驗證與測試計畫

1. **不帶 `custom_system_prompt`**：確認 `/api/external/chat` 與 `/api/rag/chat` 在相同參數下產生的 `system_prompt`／回答內容一致（驗證預設行為未被破壞）。
2. **帶 `custom_system_prompt`**：確認回答明顯依照自訂指示風格作答，且仍有把實際檢索到的參考資料接續在後面（驗證「規則覆蓋、資料仍動態接續」的設計）。
3. **無知識庫 / 無檢索結果情境**：確認與內部 API 行為一致（例如全數低於門檻時仍會提前 return 略過總結，不受 `custom_system_prompt` 影響——因為這個提前 return 發生在組 system_prompt 之前）。
4. **未帶 Authorization 標頭**呼叫 `/api/external/chat` 應可正常回應（驗證未掛 `get_current_user`）；同樣的請求打 `/api/rag/chat` 應維持回 401（驗證兩端點互不影響）。
5. **前端**：「外部 API 測試」頁與「RAG 功能測試」頁的對話紀錄互相獨立（在一頁對話不會出現在另一頁），JSON 預覽內容與實際送出的 request body 一致。
6. 使用者自行於瀏覽器手動測試（依專案慣例，不需要開瀏覽器自動化驗證）。

## 7. 待確認 / 後續事項

- `ApiJsonPreviewPanel.vue` 與 `CustomSystemPromptPanel.vue` 的實際版面配置（獨立分頁 tab 還是垂直排列在同一側欄）留待實作階段依畫面呈現效果決定，不影響本文件的資料流與後端設計。
- 是否要在 `docs/03_API_CONTRACT.md` 明確加註「此端點無認證，僅限內網」的資安警語字樣，或之後補上 API Key 機制時再一併更新文件，屆時再確認。

## 8. 後續規劃：外部應用真實使用者資訊欄位（尚未實作，僅記錄需求）

> 本節僅為規劃記錄，**尚未動工，也還沒有決定技術方案**，先把需求與現況落差記下來，待方向確認後再展開實際 Schema／程式碼修改規劃。

### 8.1 背景

目前 `params.simulated_user_id`（繼承自內部 `ChatParams`，見 [rag.py:44](../../backend/routers/rag.py:44)）只接受一個 MongoDB `UserProfile` 文件的 ObjectId 字串，且該文件必須先透過內部「角色與權限設定」頁面手動建立（欄位只有 `name`／`department`／`job_title`／`level`，見 [user_profile.py](../../backend/models/user_profile.py)）。這適合內部測試情境（從下拉選單挑選預先登記好的模擬身分），但未來真正接入的外部應用會直接帶入實際員工當下的身分資料，而不是一個「事先在 AiRAG 內部登記好」的模擬 ID。

### 8.2 未來需求：外部應用需要能直接傳入的真實使用者欄位

外部應用未來呼叫 `/api/external/chat` 時，需要能直接在請求中帶入以下 6 個欄位，取代或補充目前單一的 `simulated_user_id`：

| 欄位（中文） | 建議 JSON 欄位名稱 | 對應現有內部欄位／現況落差 |
|:---|:---|:---|
| 工號 | `employee_id` | 現有 `UserProfile` 無此欄位 |
| 姓名 | `name` | 對應 `UserProfile.name` |
| 部門代號 | `department_code` | 現有 `Department`／`UserProfile` 皆無「代號」欄位，現有只有部門「名稱」 |
| 部門名稱 | `department_name` | 對應 `UserProfile.department` |
| 級職名稱 | `job_title_name` | 對應 `UserProfile.job_title` |
| 級職等級 | `job_title_level` | 對應 `UserProfile.level` |

> 補充：欄位用途分工——`department_name`／`job_title_name` 屬於**顯示用**（沿用既有 `build_exclusion_summary()` 產生的人類可讀排除摘要文字，不需要修改該函式），實際**比對用**的鍵值分別是 `department_code`（見 8.4）與 `job_title_level`（見 8.3 決議 3）。

### 8.3 已決議事項（依使用者回覆整理，2026-07-17）

1. **取代**：`external_user` 物件（見 8.5）**取代** `simulated_user_id`，但僅限外部 `/api/external/chat` 這份 contract。內部「RAG 功能測試」頁沿用現況的 `simulated_user_id` 下拉選單（挑選 MongoDB 預先建立的模擬身分），不受影響——兩者最終都會在後端解析為同一種 `UserProfile` 形狀的物件，共用同一套 `PermissionService.filter_results()` 比對邏輯（見 8.5）。
2. **部門比對改用代號**：機密權限比對邏輯本身（不只是輸入格式）改為以「部門代號」判斷，取代現行的部門「名稱」字串比對。影響範圍與既有資料遷移風險見 8.4——這是本次規劃中風險最高的一項，因為會動到已經上線的機密權限控管功能。
3. **級職等級直接信任**：`job_title_level` 由外部呼叫端帶入的數字直接採用，不再比對 `JOB_TITLE_LEVELS`（[user_profile.py:5-11](../../backend/models/user_profile.py:5)）重新換算。此信任成立的前提是第 10 節新增的 API Key 驗證——呼叫端系統本身已通過身分驗證，才有理由直接信任其請求中宣稱的員工級職數字；沒有這道驗證前不應該貿然信任外部數字，兩個決議互為前提，需一併實作。
4. **問答紀錄留存 MongoDB**：獨立整理為新的第 9 節。

### 8.4 部門代號比對的實際影響範圍與遷移風險（Approach A：全面切換為代號比對）

已對照程式碼確認，`confidential_departments`（見 [schemas/retrieval.py:36](../../backend/schemas/retrieval.py:36)、[VectorManagementTab.vue:69,105,501](../../frontend/src/components/embedding/VectorManagementTab.vue:69)）目前存放的是部門**名稱**字串陣列，直接取自 `GET /api/users/departments` 回傳的 `name` 欄位，寫死存進 Qdrant point payload。切換為代號比對是一個**跨既有已上線功能**的變更，需要的連動修改（尚未實作，僅記錄範圍）：

- **[backend/models/department.py](../../backend/models/department.py)**：`Department` 新增 `code: Indexed(str, unique=True)` 欄位。
- **[backend/routers/users.py](../../backend/routers/users.py)**：`DepartmentCreateRequest`／`DepartmentResponse`（第 16-23 行）新增 `code` 欄位，`create_department()` 增加代號必填與重複檢查。
- **[backend/models/user_profile.py](../../backend/models/user_profile.py)** 與 `routers/users.py` 的 `UserCreateRequest`／`UserResponse`：`UserProfile` 新增 `department_code` 欄位，內部模擬使用者建立時改為從 `Department` 選單連動帶出代號，確保內部模擬使用者測試工具切換為代號比對後仍可正常運作。
- **[frontend/src/views/RoleSettingsView.vue](../../frontend/src/views/RoleSettingsView.vue)**：部門新增表單加上「部門代號」輸入欄位。
- **[frontend/src/components/embedding/VectorManagementTab.vue](../../frontend/src/components/embedding/VectorManagementTab.vue)**：「機密權限控管設定」卡片的部門複選改為儲存／比對代號（畫面仍可顯示名稱方便閱讀，但送出與比對的值改成代號）。
- **[backend/services/permission_service.py](../../backend/services/permission_service.py)**：`filter_results()`（第 97-104 行）部門比對邏輯依上方選項 2 決議，改為雙軌比對：`user.department_code not in dept_code_list and user.department_name not in dept_list`（`dept_list` 內可能同時混雜代號與名稱，任一種格式命中即視為符合）。

**既有資料遷移風險與決議**：若系統中已有文件透過「機密權限控管設定」設定過 `confidential_departments`（即已寫入 Qdrant point payload 的既有名稱字串），切換比對邏輯後這些既有設定會立即失效（代號比對不到舊存的名稱字串），等同短暫「權限保護失能」而不自知。曾列出兩個因應方向：

- 選項 1：撰寫一次性遷移腳本，逐一將 Qdrant 既有 `confidential_departments` 內的名稱字串透過 `Department.name → code` 對照表轉換為代號。
- **選項 2（已決議採用）**：過渡期間比對邏輯同時接受代號與名稱兩種格式（`user.department_code in dept_list or user.department_name in dept_list`）。

**採用選項 2 的理由**：不需要額外撰寫、測試、協調執行時機的一次性遷移腳本（腳本若對照表有缺漏或部門已被刪除，反而可能出錯遺漏轉換），且雙軌比對能保證切換上線的當下完全沒有「保護失效空窗期」——舊資料靠名稱比對繼續有效防護，同時新資料／往後任何一次重新編輯儲存都會透過改版後的 `VectorManagementTab.vue`（見上方）自然寫入代號格式，逐步自然收斂，不需要人工介入。這個雙軌比對分支之後若確認所有既有資料都已改用代號，可以再移除名稱比對分支收斂成單一邏輯，但**非本次規劃範圍，屬於可選的後續清理**，不阻塞先上線代號比對能力。

### 8.5 Schema 與比對邏輯整合方式（已決議：不分裂 Schema，直接擴充共用的 `ChatParams`）

新增 Pydantic 子物件（暫定位置 `backend/routers/rag.py`，與 `ChatParams` 放在一起）：
```python
class ExternalUserInfo(BaseModel):
    employee_id: str
    name: str
    department_code: str
    department_name: str
    job_title_name: str
    job_title_level: int
```

**已決議**：不新增 `ExternalChatParams` 分裂出獨立 Schema，而是直接在既有共用的 `ChatParams`（[rag.py:29-45](../../backend/routers/rag.py:29)）新增一個欄位 `external_user: Optional[ExternalUserInfo] = None`，與既有的 `simulated_user_id` 欄位並存於同一個 Schema 上。理由：
- 兩者都是 `Optional`，內部「RAG 功能測試」頁的請求永遠不會帶 `external_user`，外部呼叫端依「取代」的決議也不會再帶 `simulated_user_id`，兩者互斥使用但不需要用型別層級去強制分離。
- 沿用 §3.1 已決議的技術取捨（外部與內部共用底層 `rag_chat_stream()` 管線，不重寫一份），新增獨立 Schema 反而需要額外寫一層「`ExternalChatParams` → `ChatRequest`」的轉換/相容程式碼，比直接擴充同一個 Schema 複雜，不符合「簡單優先」。
- `external.py` 完全不需要新的 Request Schema，繼續直接沿用 `routers.rag.ChatRequest`（現況已是如此，零額外改動）。

`rag_chat_stream()` 內原本解析模擬使用者身分的段落（[rag.py:310-311](../../backend/routers/rag.py:310)：`simulated_user = await PermissionService.get_user(simulated_user_id)`）改為新增分支：**若 `request.params.external_user`有值，優先呼叫新增的 `PermissionService.get_user_from_external_info()`；否則才走原本的 `simulated_user_id` 查詢路徑**，其餘下游的 `filter_results()`／`build_exclusion_summary()` 邏輯完全不必修改（因為兩條路徑最終都會產生同一種 `UserProfile` 形狀的物件）。

`PermissionService` 新增 `classmethod get_user_from_external_info(info: ExternalUserInfo) -> UserProfile`，直接用四個欄位建構一個 `UserProfile` 形狀物件（`department`／`job_title` 沿用既有欄位名稱存放 `department_name`／`job_title_name`，讓既有的 `build_exclusion_summary()` 不必修改；另外多帶 `department_code` 供 8.4 節的新比對邏輯使用）。這個物件**不落地寫入 `users` collection**——`UserProfile`／`users` collection 仍只保留供內部模擬使用者測試名冊使用，與外部真實使用者身分是兩種不同用途，不應混用；外部呼叫的身分快照改寫進第 9 節新增的 `ExternalChatLog`。

---

## 9. 外部 API 問答紀錄留存 MongoDB（已決議）

### 9.1 背景

使用者決議「將問答紀錄存進 MongoDB」——每一次呼叫 `/api/external/chat` 的完整互動（呼叫端身分、問題、最終回答、來源等）都要留下稽核紀錄。

### 9.2 為何不直接沿用既有 `ChatSession`／`ChatMessage`

已對照程式碼確認 [chat_session.py](../../backend/models/chat_session.py)、[chat_message.py](../../backend/models/chat_message.py) 這兩個 Beanie Document **目前完全沒有被 `rag_chat_stream()` 或任何 router 實際寫入使用**——`/api/rag/history` 的 GET/DELETE 目前是寫死回傳空結果的 Stub（見 CLAUDE.md「Known doc/code drift」一節），這兩個 Model 是先前規劃但未串接完成的遺留設計。其設計目的是「Session + 多筆 Message」的多輪對話瀏覽介面（`ChatSession` 掛 `title`／`params`，`ChatMessage` 掛 `session_id` 外鍵關聯），且完全沒有「呼叫端身分」欄位（`created_by` 只是泛用的 `Optional[str]`）。外部 API 稽核紀錄要的是「每次請求」的扁平稽核紀錄（含呼叫端員工身分六大欄位），用途與資料形狀都不同，勉強共用只會讓兩個定位已經不清楚的既有 Model 更混亂。**因此建議新增一個專用的 `ExternalChatLog` Model，不重用 `ChatSession`／`ChatMessage`。**

### 9.3 新模型草案 `backend/models/external_chat_log.py`（欄位完整度已決議）

**已決議**：`sources_summary` 只存精簡的來源中繼資料（檔名／chunk_id／段落編號／分數），**不存片段全文**——原始內容已經完整存在 Qdrant，需要深入追查時可用 `chunk_id` 回查，沒必要在每筆稽核紀錄裡重複一份可能很大的原文，避免外部 API 呼叫量上來後這個 Collection 的儲存成本失控。`custom_system_prompt` 則相反，改為存**實際使用的完整文字**（而非只存一個 `bool` 有沒有用到）——這欄位本身通常不長，但對稽核「這筆回答是依照什麼指示產生的」很有價值，值得完整保留。

```python
class SourceSummaryItem(BaseModel):
    filename: Optional[str] = None
    chunk_id: Optional[str] = None
    chunk_index: Optional[int] = None
    score: Optional[float] = None
    semantic_score: Optional[float] = None

class ExternalChatLog(Document):
    api_key_id: Optional[PydanticObjectId] = None  # 對應第 10 節，記錄是哪把金鑰呼叫的
    employee_id: str
    employee_name: str
    department_code: str
    department_name: str
    job_title_name: str
    job_title_level: int
    knowledge_base_id: Optional[str] = None
    search_type: Optional[str] = None
    question: str
    answer: str
    sources_summary: List[SourceSummaryItem] = Field(default_factory=list)
    custom_system_prompt: Optional[str] = None  # 若有帶自訂總結提示詞，存實際使用的完整文字；未帶則為 None
    elapsed_ms: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "external_chat_logs"
        indexes = ["-created_at", "employee_id", "api_key_id"]
```

### 9.4 寫入時機（含中斷保護結構，已決議）

`external.py` 目前是把 `rag_chat_stream(request)` 直接交給 `StreamingResponse`（透明轉發）。要留存紀錄，需要改為包一層新的 async generator（例如 `_external_chat_with_logging()`）：逐一原樣轉發 `rag_chat_stream()` 產生的每個 SSE 事件（維持既有串流體驗不變），同時在旁路累積 `chunk: content` 拼出的完整回答文字與 `sources` 事件內容，於串流結束時寫入一筆 `ExternalChatLog`。

**已決議：正常結束與中途中斷都要落地寫入，靠 `try...finally` 結構保證，而非依賴「迴圈跑完後」再執行寫入的線性寫法**。外部呼叫端在 SSE 傳輸途中主動斷線，或 `rag_chat_stream()` 內部拋出例外，都會讓 `async for` 迴圈提前中止（斷線時是 `GeneratorExit`／`asyncio.CancelledError` 中斷迭代）；若寫入邏輯放在迴圈「後面」，這兩種情況都完全不會執行到，等於白白耗費了 LLM／檢索資源卻沒留下任何稽核紀錄。技術結構草案：

```python
async def _external_chat_with_logging(request: ChatRequest, api_key_id, resolved_user):
    accumulated_content = ""
    sources_data = []
    try:
        async for evt in rag_chat_stream(request):
            # 依 event 類型累積 accumulated_content / sources_data，並原樣 yield 出去
            yield evt
    finally:
        # 無論正常結束、中途斷線或例外，都會執行到這裡
        try:
            await ExternalChatLog(
                api_key_id=api_key_id,
                question=request.question,
                answer=accumulated_content,
                sources_summary=[...],  # 由 sources_data 轉換
                ...
            ).insert()
        except Exception as log_err:
            # 旁路稽核寫入採 best-effort，比照既有 RetrievalStatsService.record 的作法
            # （見 rag.py:622-634「檢索命中統計旁路寫入」），寫入失敗只記警告 log，
            # 不能讓稽核紀錄寫入失敗連帶影響（甚至掩蓋）原本已經送達使用者的串流結果
            logger.warning(f"[ExternalChatLog] 稽核紀錄寫入失敗（不影響本次對話流程）: {log_err}")
```

**待實作時驗證的細節（非阻塞性，先記錄提醒）**：`finally` 區塊內執行 `await`（MongoDB 寫入）在 ASGI 伺服器（Starlette/uvicorn）判定客戶端斷線後的實際行為，理論上 Python 的 `finally` 對 `GeneratorExit` 一樣會執行，但斷線情境下框架層是否會在 `finally` 的 `await` 完成前就強制回收整個請求任務，屬於需要實測確認的框架行為細節，實作完成後應手動測試「送出問題後立刻關閉連線／中斷網路」情境，確認 `ExternalChatLog` 是否確實落地。

**這一層包裝只包在 `external.py`**，不修改 `rag_chat_stream()` 本體，維持 §3.1 已決議「不與內部測試 API 共用」的技術取捨——內部 `/api/rag/chat` 呼叫路徑完全不受影響，不會意外開始寫入這個新 Collection。

---

## 10. 外部 API 安全機制：API Key 驗證（新決策，修正第 2 節先前的決議）

### 10.1 背景與決策修正

第 2 節先前已與使用者確認「外部端點認證方式：暫不做認證（僅限公司內網存取把關）」；本次使用者要求補上「傳入需要帶認證」，**正式修正為：`/api/external/chat` 需要驗證**，採用第一輪提問時列出但當時未選用的「新增 API Key 機制」方案。此驗證與使用者 JWT 登入機制（`get_current_user`）**各自獨立、不共用**，因為呼叫方是「外部系統」而非「登入的人類使用者」，語意不同。

### 10.2 設計：`ExternalApiKey` 模型

```python
class ExternalApiKey(Document):
    name: str  # 用途/系統名稱標示，例如「HR 入口網站」，方便管理介面辨識
    key_prefix: Indexed(str, unique=True)  # 金鑰前 12 碼明碼，作為查詢索引用，不足以單獨冒用
    key_hash: str  # bcrypt hash 完整金鑰，沿用 utils/security.py 既有的 bcrypt 慣例
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_used_at: Optional[datetime] = None

    class Settings:
        name = "external_api_keys"
```

金鑰只在建立當下用 `secrets.token_urlsafe(32)` 產生明碼，回傳一次給管理者複製保存；資料庫僅存 `key_prefix`（前 12 碼，供快速索引查找候選）與 `key_hash`（bcrypt hash 完整金鑰），之後無法再次於畫面顯示完整明碼，只能重新產生新金鑰——這是業界（GitHub PAT／Stripe API Key）常見作法，避免明碼常駐資料庫。

### 10.3 驗證流程與 Header 慣例

- Header 採 `X-API-Key: <key>`（刻意不用 `Authorization: Bearer`，避免與既有 JWT 機制混淆——兩套認證語意不同：JWT 代表「已登入的人類使用者」，API Key 代表「已授權的外部系統」）。
- 新增 FastAPI 依賴 `verify_external_api_key(x_api_key: str = Header(...))`：先用 `key_prefix`（明碼前 12 碼）查詢候選 `ExternalApiKey` 文件，再用 `bcrypt.checkpw` 核對完整金鑰雜湊，通過且 `is_active=True` 才放行，否則回傳 401（比照 `get_current_user`（[security.py:51-70](../../backend/utils/security.py:51)）現有的錯誤格式慣例）。
- [backend/routers/external.py](../../backend/routers/external.py)：`router = APIRouter(prefix="/external", tags=["External API"], dependencies=[Depends(verify_external_api_key)])`，比照現有 `Depends(get_current_user)` 掛載模式，維持風格一致。
- 驗證通過後，將解析出的 `ExternalApiKey` 文件 `id` 一併帶入第 9 節 `ExternalChatLog.api_key_id`，供稽核回溯是哪個外部系統送出了這筆請求。

### 10.4 金鑰管理介面（欄位豐富度已決議：維持最小可用版本）

- 建議新增管理端點 `GET/POST /api/external-api-keys`、`DELETE /api/external-api-keys/{id}`（沿用 `get_current_user` JWT 保護——這是給內部管理者用的後台管理功能，不是外部呼叫端使用的端點，兩者不要混淆）。
- 前端建議掛在既有 [RoleSettingsView.vue](../../frontend/src/views/RoleSettingsView.vue)（角色與權限設定）新增一個分頁／區塊，而非另開新頁面——該頁面已經是「誰能存取什麼」相關設定的集中管理處，新增外部 API 金鑰管理符合既有頁面定位，可避免側邊欄選單再增加一個窄用途項目。
- **已決議**：稽核欄位維持 10.2 節草案的最小可用版本（`name`／`key_prefix`／`is_active`／`created_at`／`last_used_at`），不額外新增「使用次數」「速率限制統計」等欄位——目前還沒有真正的外部應用接入，這些統計需求都是假設性的，符合 AGENT.md「不要寫未來可能用到的程式碼」原則。待實際接入後若真的需要，屆時再依真實使用情境擴充，`last_used_at` 已足夠應付「這把金鑰是否還在使用中」的基本稽核需求。

### 10.5 與「信任外部帶入級職等級」決議的關聯

第 8.3 節「級職等級直接信任」之所以可被接受，前提正是本節的 API Key 驗證——確保只有已授權的外部系統才能呼叫這個端點；請求內容裡宣稱的員工級職數字本身沒有再對 HR 系統或既有 `JOB_TITLE_LEVELS` 做二次交叉驗證，信任邊界建立在「呼叫系統本身可信」而非「員工身分本身經過驗證」。若未來需要更嚴格的保證（例如防範某個已授權系統本身被入侵後偽造任意員工級職），需另外規劃，本次不在範圍內。

### 10.6 上線注意事項

`/api/external/chat` 目前已是無驗證狀態上線（見 2026-07-17 實作紀錄），本次調整屬於「收緊」而非「放寬」，不會有既有已授權呼叫端因此被擋下的風險（因為目前根本還沒有真正的外部應用接入）；但實作時仍需確認是否已有任何人工測試腳本／工具依賴目前無驗證行為，避免默默中斷測試。

---

## 11. 決策紀錄（2026-07-17，第二輪）

先前第 11 節列出的 4 項待確認事項已由使用者請 AI 代為決策並整理如下，決策細節已回填至對應章節：

| # | 項目 | 決議 | 詳見章節 |
|:---|:---|:---|:---|
| 1 | 部門代號遷移策略 | 採用**選項 2（過渡期雙軌比對）**：同時接受代號與名稱比對，不寫一次性遷移腳本，靠往後的重新編輯儲存自然收斂 | 8.4 |
| 2 | `ExternalChatLog.sources_summary` 完整度 | 只存精簡中繼資料（檔名／chunk_id／段落編號／分數），不存片段全文；`custom_system_prompt` 改存實際使用的完整文字 | 9.3 |
| 3 | API Key 管理介面稽核欄位豐富度 | 維持最小可用版本（`name`／`key_prefix`／`is_active`／`created_at`／`last_used_at`），不加使用次數等統計 | 10.4 |
| 4 | `rag_chat_stream()` 介面調整方式 | **不分裂 Schema**：直接在共用 `ChatParams` 新增 `external_user` 欄位，`external.py` 沿用既有 `ChatRequest`，管線內新增一個判斷分支即可 | 8.5 |

## 12. Proposed Changes（第 8～10 節，尚未實作，僅列出預期會動到的範圍）

### 後端
- **[NEW]** `backend/models/external_chat_log.py`（9.3 節，含 `SourceSummaryItem`／`ExternalChatLog`）
- **[NEW]** `backend/models/external_api_key.py`（10.2 節）
- **[NEW]** `backend/routers/external_api_keys.py`（金鑰管理 CRUD，10.4 節，掛 `get_current_user`）
- **[MODIFY]** `backend/models/department.py` — 新增 `code` 欄位（8.4 節）
- **[MODIFY]** `backend/models/user_profile.py` — 新增 `department_code` 欄位（8.4 節）
- **[MODIFY]** `backend/routers/users.py` — 部門／模擬使用者 CRUD 支援代號欄位（8.4 節）
- **[MODIFY]** `backend/routers/rag.py` — `ChatParams` 新增 `external_user: Optional[ExternalUserInfo]`（8.5 節，與 `custom_system_prompt` 同一批共用欄位）；`rag_chat_stream()` 解析使用者身分處新增 `external_user` 優先分支（8.5 節）
- **[MODIFY]** `backend/routers/external.py` — 掛上 `Depends(verify_external_api_key)`，包一層問答紀錄寫入邏輯 `_external_chat_with_logging()`（9.4、10.3 節）；不需要新的 Request Schema
- **[MODIFY]** `backend/services/permission_service.py` — 新增 `get_user_from_external_info()`；部門比對邏輯改為代號／名稱雙軌比對（8.4、8.5 節）
- **[NEW/MODIFY]** `verify_external_api_key` 依賴函式（放置位置待實作時決定，可能新增 `backend/utils/external_auth.py` 或併入 `utils/security.py`）（10.3 節）
- **[MODIFY]** `backend/models/mongodb.py` — 於 `init_beanie` 註冊 `ExternalChatLog`／`ExternalApiKey`
- **[MODIFY]** `backend/main.py` — 註冊 `external_api_keys.router`

### 前端
- **[MODIFY]** `frontend/src/views/RoleSettingsView.vue` — 部門表單新增代號欄位、新增外部 API 金鑰管理分頁（8.4、10.4 節）
- **[MODIFY]** `frontend/src/components/embedding/VectorManagementTab.vue` — 機密權限控管設定改用部門代號（8.4 節）
- **[MODIFY]** `frontend/src/components/params/ApiJsonPreviewPanel.vue` — 欄位說明改為 `external_user` 物件，補上 `X-API-Key` Header 說明（8.5、10.3 節）
- **[MODIFY]** `frontend/src/views/ExternalApiTestView.vue` 或新增元件 — 讓使用者能在測試頁輸入這 6 個模擬欄位與 API Key（尚待實作階段細部設計 UI 呈現方式）

以上第 8～12 節僅為規劃記錄，本次對話**未修改任何程式碼**。所有先前待確認事項已由 AI 決策並整理進本文件，待使用者複核第 8～12 節整體內容確認無誤後，再排入實際實作。
