# 多輪對話指代消解（Conversational Reference Resolution）規劃文件

> 狀態：Batch 1-3、5 已實作完成（2026-07-08）；Batch 4 人工測試待使用者驗證，見第 9 節 Checklist（2026-07-08 已與使用者確認所有開放問題，細節見第 8 節）
> 影響範圍：`backend/services/embedding_service.py`（`query_to_semantic_json` 新增可選參數）、`backend/routers/rag.py`（呼叫處新增 chat_history／pinned_filename 傳遞邏輯、`semantic_analysis` 步驟新增透明度顯示）、`backend/config.py`（新增設定值）、`frontend/src/components/params/RagParamsPanel.vue`（新增歷史則數輸入 + 手動指定檔案下拉選單）、`frontend/src/stores/paramsStore.js`／`chatStore.js`（新增對應狀態與 payload 欄位）。**不觸碰** `vector`／`hybrid`／`semantic_db_query` 的既有邏輯。

## 1. 目標與範圍

### 目標
`EmbeddingService.query_to_semantic_json(question, filenames=None, tags=None, structured_metadata=None)`（[embedding_service.py:108](../../backend/services/embedding_service.py)）目前只接收當次 `question` 字串，不帶歷史對話，導致 `search_type` 為 `semantic_hybrid`／`semantic_hybrid_feedback`／`semantic_hybrid_attachment` 三種查詢法在使用者追問（例如「那份文件的第二點是什麼」）時，語義 JSON 解析階段（`embeddings_input`／`sparse_keywords`）無法正確指代消解出真正要查的文件/實體，即使最終回答 LLM 呼叫（[rag.py:655-663](../../backend/routers/rag.py)）本身有拿到 `chat_history`，检索階段已經先用錯誤關鍵字撈錯內容。

新增兩種讓使用者/系統協助指代消解的機制，兩者可並用：
1. **自動指代消解**：讓語義 JSON 轉換階段也能看到最近幾輪對話，由 Instruct LLM 自行從歷史脈絡解析「那份文件」等指示詞，使用者可在前端調整要帶入的歷史則數。
2. **手動鎖定檔案**：使用者在前端直接從知識庫既有檔案清單中選定一個檔案，系統直接鎖定該檔案為本次查詢範圍，不需依賴 LLM 猜測，優先權高於自動判斷。

每次分析結果（實際帶入了幾則歷史、是否有手動鎖定檔案）都會透過既有 SSE `semantic_analysis` 步驟卡片呈現，讓使用者能事後檢視。

### 明確不動的部分
- `search_type in ("vector", "hybrid")` 完全不呼叫 `query_to_semantic_json`（[rag.py:288](../../backend/routers/rag.py) 的判斷式維持不動），因此本次修改對這兩種查詢法**零影響**。
- `semantic_db_query`（[rag.py:64](../../backend/routers/rag.py) 的 `_run_semantic_db_query`）使用的是完全獨立的 `AIDBQueryService`，不呼叫 `query_to_semantic_json`，**不受影響**。
- `query_to_semantic_json` 既有的 4 個參數簽章、JSON Schema、【嚴格核心規則】1-5、【Few-Shot Examples】範例 1-4（[embedding_service.py:117-193](../../backend/services/embedding_service.py)）**完全不修改**，新增內容以「新增獨立區塊 + 新的可選參數」的加法方式插入，未帶歷史/未指定檔案時（`chat_history=None`、`pinned_filename=None`）系統提示字串與現在**逐字元相同**，行為零改變。
- 既有 fallback JSON（[embedding_service.py:236-248](../../backend/services/embedding_service.py)）與重試溫度序列 `[0.1, 0.5]`（[embedding_service.py:272-289](../../backend/services/embedding_service.py)）邏輯不變。
- `rag.py:655-663` 既有「把 `chat_history` 塞進最終回答 Prompt」的邏輯不變，本功能是新增「語義 JSON 轉換階段」也能看到歷史，兩處各自獨立使用同一份 `request.chat_history`，互不影響。
- 既有 `GET /api/knowledge-bases/{id}/metadata`（[knowledge_base.py:125-146](../../backend/routers/knowledge_base.py)）**直接重用**作為前端「手動指定檔案」下拉選單的資料來源，不新增後端列舉端點。

## 2. 名詞定義

| 名詞 | 說明 |
|---|---|
| 指代消解（Reference Resolution） | 將對話中「那個」「這份文件」「剛才提到的」等指示代詞，依照上文脈絡解析回具體實體（檔名、關鍵字）的過程。 |
| 語義 JSON 轉換階段 | 指 `EmbeddingService.query_to_semantic_json()` 這一步，把使用者問題轉成 `{embeddings_input, sparse_keywords, metadata}` 結構化 JSON，供後續向量/稀疏檢索使用。 |
| 歷史對話窗口（History Window） | 實際塞進 Prompt 的最近 N 則歷史訊息，N 由使用者於前端輸入（`history_context_turns`），未輸入時使用後端預設值 `SEMANTIC_JSON_HISTORY_TURNS`。 |
| 手動鎖定檔案（Pinned Filename） | 使用者於前端下拉選單直接選定的知識庫既有檔案名稱（`pinned_filename`），用來取代/優先於 AI 自動判斷的 `filter_filename`，讓使用者不需要依賴指代消解也能精準鎖定查詢範圍。 |

## 3. 架構設計

### 3.1 `query_to_semantic_json` 新增可選參數

`backend/services/embedding_service.py:108`：

```python
@classmethod
async def query_to_semantic_json(
    cls, question: str, filenames: list = None, tags: list = None,
    structured_metadata: list = None,
    chat_history: list = None,     # 新增：List[dict]，每筆 {"role": "user"/"assistant", "content": str}
    pinned_filename: str = None    # 新增：使用者手動鎖定的檔案名稱
) -> dict:
```

- 兩個新參數預設值皆為 `None`，維持向後相容；`rag.py` 若未來有任何其他呼叫點忘記傳入，行為與現況相同。
- `chat_history` 型別選用 `list[dict]`（而非直接依賴 `rag.py` 的 `ChatHistoryItem` pydantic model），避免 `embedding_service.py` 額外 import `routers.rag`，維持既有 service 層不依賴 router 層的分層慣例。

### 3.2 系統提示新增「【近期對話歷史】」與「【使用者已手動鎖定檔案】」區塊

在 [embedding_service.py:215](../../backend/services/embedding_service.py)（`structured_metadata`/`filenames`/`tags` 區塊組完之後、`url = ...`（[embedding_service.py:223](../../backend/services/embedding_service.py)）之前）新增：

```python
if pinned_filename:
    system_prompt += (
        f"\n\n【使用者已手動鎖定檔案】\n"
        f"使用者已明確指定本次查詢範圍為檔案「{pinned_filename}」，"
        f"請優先針對此檔案內容組織 embeddings_input／sparse_keywords，"
        f"不需要再自行從歷史對話猜測要查詢的文件；metadata.source_file 請直接填入「{pinned_filename}」。\n"
    )
if chat_history:
    system_prompt += "\n\n【近期對話歷史（由舊到新，僅供指代消解與背景理解，不可作為新增檢索關鍵字的唯一依據）】\n"
    for msg in chat_history:
        role_label = "使用者" if msg.get("role") == "user" else "AI助手"
        system_prompt += f"- {role_label}：{msg.get('content', '')}\n"
    system_prompt += (
        "\n【指代消解規則】\n"
        "若當前問題出現「那個」「這份」「剛才」「上面提到的」等指示詞，"
        "請優先參考上方近期對話歷史，將其解析回具體的檔案名稱、實體或關鍵字，"
        "並反映在 embeddings_input 與 sparse_keywords 中；"
        "但仍必須遵守【反幻想限制】（規則2）：只能基於歷史對話或當前問題中明確出現過的實體進行解析，"
        "不可自行想像歷史對話中未提及的新背景。\n"
    )
```

- `pinned_filename` 區塊放在 `chat_history` 區塊之前，讓 LLM 優先看到「已經有明確答案」的鎖定檔案，減少不必要的歷史推理。
- 沿用 [rag.py:658-660](../../backend/routers/rag.py) 既有的 `role`/`content` 迭代風格（同樣的欄位命名），降低理解成本。
- 兩個區塊皆放在【嚴格核心規則】【Few-Shot Examples】之後、`當前日期為：` 之前，確保「規則2」等相對引用位置在文字更前面。
- **不修改**既有 JSON Schema 結構、不新增 JSON 欄位（已與使用者確認不需要 `resolved_reference` 欄位，見第 8 節）——歷史/鎖定檔案只影響 LLM「怎麼想」，不改變「輸出什麼形狀」，確保下游 `parsed["embeddings_input"]`/`parsed["sparse_keywords"]`/`parsed["metadata"]["source_file"]` 解析邏輯（[embedding_service.py:268-270](../../backend/services/embedding_service.py)）完全不用改。
- **不截斷歷史訊息長度**（已與使用者確認，見第 8 節）：每則歷史訊息內容完整帶入，不比照 `RerankService.CONTENT_PREVIEW_LEN` 做截斷。

### 3.3 `rag.py` 呼叫處新增歷史與鎖定檔案傳遞

[rag.py:307-309](../../backend/routers/rag.py)：

```python
# 既有程式碼
semantic_json = await EmbeddingService.query_to_semantic_json(
    question, filenames=filenames, tags=tags, structured_metadata=structured_metadata
)
```

修改為：

```python
effective_history_turns = (
    request.params.history_context_turns
    if request.params and request.params.history_context_turns is not None
    else settings.SEMANTIC_JSON_HISTORY_TURNS
)
history_window = _build_history_window(request.chat_history, effective_history_turns)
pinned_filename = request.params.pinned_filename if request.params else None

semantic_json = await EmbeddingService.query_to_semantic_json(
    question, filenames=filenames, tags=tags, structured_metadata=structured_metadata,
    chat_history=history_window, pinned_filename=pinned_filename
)
```

新增一個小 helper 函式（放在 `rag.py` 內部，不需要獨立 service）：

```python
def _build_history_window(chat_history, max_turns: Optional[int]) -> Optional[list]:
    """
    截取最近 N 則訊息（非 user+assistant 成對計算，
    與既有 rag.py:658-660 塞入最終 Prompt 時「整份 chat_history 全帶」的作法不同，
    此處刻意限縮視窗，避免語義 JSON 轉換的 Prompt 過長影響 Instruct LLM 精準度）。
    N 由使用者於前端輸入（history_context_turns），未輸入時使用後端預設值。
    只保留 user／assistant 訊息（過濾掉未來若混入 system 等其他 role 的訊息，
    避免污染指代消解用的歷史脈絡——系統提示本身已獨立宣告，不應混入對話歷史）。
    """
    if not chat_history or max_turns is None or max_turns <= 0:
        return None
    filtered = [m for m in chat_history if m.role in ("user", "assistant")]
    recent = filtered[-max_turns:]
    return [{"role": m.role, "content": m.content} for m in recent] or None
```

- 呼叫點只有這一處（[rag.py:307-309](../../backend/routers/rag.py)），因為 `query_to_semantic_json` 只在 `search_type in ("semantic_hybrid", "semantic_hybrid_feedback", "semantic_hybrid_attachment")` 分支被呼叫（[rag.py:288](../../backend/routers/rag.py)），這也是唯一需要修改的呼叫點。
- `retrieval.py`／`evaluation.py` 若有測試流程也呼叫到 `query_to_semantic_json`（純檢索測試通常沒有多輪歷史概念），維持不傳 `chat_history`/`pinned_filename`（沿用預設 `None`），不強制所有呼叫點都要改。
- `_build_history_window` 對 `max_turns` 新增 `is None` 防禦性檢查：雖然 [rag.py:100-104](../../backend/routers/rag.py) 呼叫處的三元運算子理論上已保證 `effective_history_turns` 一定是 int（使用者未指定時退回 `settings.SEMANTIC_JSON_HISTORY_TURNS`），但 helper 本身多一行 `None` 檢查成本極低，可避免未來若有其他呼叫點誤傳 `None` 導致 `TypeError` 中斷查詢。
- 新增 `role in ("user", "assistant")` 過濾：避免 `chat_history` 未來若混入非標準 role（例如工具訊息）時，被 [embedding_service.py](../../backend/services/embedding_service.py) 的 `role_label = "使用者" if ... else "AI助手"` 邏輯誤判為 AI 助手發言，污染指代消解脈絡。

### 3.4 `pinned_filename` 覆寫 `filter_filename`（優先權高於 AI 自動判斷）

[rag.py:286](../../backend/routers/rag.py) 現況：

```python
filter_filename = None
```

...([rag.py:315-317](../../backend/routers/rag.py)) AI 語義 JSON 回傳後才自動判斷：

```python
metadata = semantic_json.get("metadata", {})
if metadata and metadata.get("source_file"):
    filter_filename = metadata.get("source_file")
```

修改為：使用者手動鎖定檔案時，直接指定 `filter_filename`，且 AI 自動判斷**不覆蓋**使用者的手動選擇：

```python
filter_filename = pinned_filename  # 使用者手動鎖定優先；若未鎖定則為 None

metadata = semantic_json.get("metadata", {})
if metadata and metadata.get("source_file") and not filter_filename:
    filter_filename = metadata.get("source_file")
```

- 優先權：**使用者手動指定 > AI 自動判斷 > 不篩選**。
- `pinned_filename` 沿用既有 `filter_filename` 變數，不新增檢索層參數，`QdrantService.search_similar_two_step`/`search_similar` 完全不用修改。

## 4. API 設計

### 4.1 `ChatParams` 新增欄位

`backend/routers/rag.py:27-38`：

```python
class ChatParams(BaseModel):
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    repetition_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    top_k: Optional[int] = None
    score_threshold: Optional[float] = None
    filter_tags: Optional[List[str]] = None
    search_type: Optional[str] = "vector"
    context_summarize_trigger_tokens: Optional[int] = None
    read_attachment_content: Optional[bool] = False
    history_context_turns: Optional[int] = None   # 新增：使用者指定的歷史則數，None＝用後端預設值
    pinned_filename: Optional[str] = None          # 新增：使用者手動鎖定的檔案名稱，None＝不鎖定
```

兩個欄位皆只影響 `semantic_hybrid`／`semantic_hybrid_feedback`／`semantic_hybrid_attachment` 三種查詢法（[rag.py:288](../../backend/routers/rag.py) 判斷式範圍內），對 `vector`/`hybrid`/`semantic_db_query` 無效（傳入也不會被讀取）。

## 5. 前端設計

### 5.1 `RagParamsPanel.vue` 新增「自動指代消解」勾選框 + 「歷史則數」數字輸入

新增一個勾選框作為總開關，讓使用者可以明確選擇「是否要自動使用對話歷史做指代消解」，而不是靠把則數設成 0 來間接關閉。勾選框預設為**勾選**（維持功能上線後的預設行為：沿用後端預設值 `SEMANTIC_JSON_HISTORY_TURNS=3` 自動帶入歷史）。數字輸入只有在勾選框開啟時才可編輯／才會實際送出：

```html
<div class="flex flex-col gap-2">
  <label class="flex items-center gap-2 text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">
    <input type="checkbox" v-model="paramsStore.autoContextEnabled" class="accent-[#8b5cf6]" />
    自動指代消解（使用對話歷史）(Auto Reference Resolution)
  </label>
</div>
<div class="flex flex-col gap-2" :class="{ 'opacity-40 pointer-events-none': !paramsStore.autoContextEnabled }">
  <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">指代消解歷史則數 (History Turns)</label>
  <input
    type="number" min="0"
    v-model.number="paramsStore.historyTurnCount"
    :disabled="!paramsStore.autoContextEnabled"
    placeholder="預設 3（後端設定值）"
    class="bg-white/5 border border-white/8 rounded-lg text-white px-3 py-2 text-xs focus:outline-none focus:border-[#8b5cf6] transition-all"
  />
</div>
```

比照 [RagParamsPanel.vue:90-103](../../frontend/src/components/params/RagParamsPanel.vue)（`contextSummarizeThreshold` 數字輸入）同樣的 `v-model.number` + `type="number"` + placeholder 顯示後端預設值的模式，額外加上勾選框控制整組欄位是否生效。此勾選框與 5.2 節「手動鎖定檔案」下拉選單是**兩個獨立的控制項**，可同時使用（使用者可以同時鎖定檔案、又讓自動指代消解處理其他指示詞）。

### 5.2 `RagParamsPanel.vue` 新增「手動指定檔案」下拉選單

比照 [RetrievalTestView.vue:543-556](../../frontend/src/views/RetrievalTestView.vue) 既有的檔案下拉選單樣式，選項來源重用既有 `GET /api/knowledge-bases/{id}/metadata`（[knowledge_base.py:125-146](../../backend/routers/knowledge_base.py)）回傳的 `filenames` 陣列（比照 [VectorManagementTab.vue:71-73](../../frontend/src/components/embedding/VectorManagementTab.vue) 的呼叫方式）：

```html
<div class="flex flex-col gap-2">
  <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">手動鎖定檔案 (Pinned Filename)</label>
  <select v-model="paramsStore.pinnedFilename" class="bg-white/5 border border-white/8 rounded-lg text-white px-3 py-2 text-xs focus:outline-none focus:border-[#8b5cf6] transition-all">
    <option :value="null" class="bg-[#111827] text-white">不鎖定（由 AI 自動判斷）</option>
    <option v-for="fn in availableFilenames" :key="fn" :value="fn" class="bg-[#111827] text-white">{{ fn }}</option>
  </select>
</div>
```

`<script setup>` 新增一個 `watch`（監聽目前選定的 `knowledgeBaseId`）呼叫 `GET /api/knowledge-bases/${knowledgeBaseId}/metadata` 取得 `availableFilenames`，比照 `RetrievalTestView.vue:41-43` 的既有寫法（`response.data?.filenames || []`）。

**必須處理知識庫切換時的殘留鎖定檔案**：若使用者在知識庫 A 選定 `pinnedFilename = "HR手冊.pdf"`，切換到知識庫 B 後若不重置，該檔名會繼續留在 payload 中送給後端，但知識庫 B 沒有這個檔案，會導致 `filter_filename` 命中 0 筆而使用者不知道原因（檢索結果無聲變成空的）。因此 `watch` 內必須在重新取得 `availableFilenames` 後，比對目前 `pinnedFilename` 是否還存在於新清單中，不存在就重置為 `null`：

```js
watch(() => paramsStore.knowledgeBaseId, async (newKbId) => {
  if (!newKbId) {
    availableFilenames.value = []
    paramsStore.pinnedFilename = null
    return
  }
  try {
    const response = await api.get(`/api/knowledge-bases/${newKbId}/metadata`)
    availableFilenames.value = response.data?.filenames || []
    // 切換知識庫後，若原本鎖定的檔案不在新清單中，自動重置，避免無聲檢索 0 筆
    if (paramsStore.pinnedFilename && !availableFilenames.value.includes(paramsStore.pinnedFilename)) {
      paramsStore.pinnedFilename = null
    }
  } catch (err) {
    console.error('Failed to fetch filenames:', err)
    availableFilenames.value = []
    paramsStore.pinnedFilename = null
  }
}, { immediate: true })
```

### 5.3 `paramsStore.js` 新增狀態

`frontend/src/stores/paramsStore.js`「Retrieval parameters」群組新增：

```js
autoContextEnabled: true,  // 自動指代消解總開關，預設開啟（維持功能上線後的預設行為）
historyTurnCount: null,    // null = 使用後端預設值 SEMANTIC_JSON_HISTORY_TURNS（僅在 autoContextEnabled 為 true 時生效）
pinnedFilename: null,      // null = 不鎖定，由 AI 自動判斷
```

（`historyTurnCount`/`pinnedFilename` 沿用既有 `dbQueryMaxRows`/`contextSummarizeThreshold` 用 `null` 代表「留空、交給後端預設值」的既有慣例；`autoContextEnabled` 是新增的布林總開關）

### 5.4 `chatStore.js` payload 組裝

`frontend/src/stores/chatStore.js`（`filter_tags` 旁）新增：

```js
// autoContextEnabled 為 false 時強制送出 0（明確關閉），不論 historyTurnCount 欄位內容為何
const rawTurns = paramsStore.autoContextEnabled ? paramsStore.historyTurnCount : 0
// 正規化：<input type="number"> 被清空時 v-model.number 可能保留為空字串 ''（parseFloat('') 是 NaN，
// Vue 的 .number 修飾符會退回原始字串），若原樣送出會被 Pydantic Optional[int] 判成 422 Validation Error
const history_context_turns = (rawTurns === '' || rawTurns === null || Number.isNaN(rawTurns)) ? null : rawTurns
```

```js
history_context_turns,
pinned_filename: paramsStore.pinnedFilename,
```

不需要新增對外 API 欄位——勾選框只是前端 UX 層，最終仍透過既有 `history_context_turns` 單一欄位送出（勾選框關閉時等同使用者把則數設為 `0`，沿用 `_build_history_window()` 既有的 `max_turns <= 0 → 不帶歷史` 邏輯，見第 3.3 節），後端 `ChatParams`／`_build_history_window()` 完全不用因為這個勾選框新增任何程式碼。空字串正規化為 `null` 而非 `0`，是因為使用者「清空輸入框」語意上更接近「沒有指定」（回退到後端預設值），而非「明確要求 0 則」。

### 5.5 事後透明度：延伸既有 `semantic_analysis` 步驟卡片內容

**注意：`rag.py` 的 `semantic_analysis` 步驟實際上會 yield 兩次**（[rag.py:321-331](../../backend/routers/rag.py) 的 `running` 狀態、緊接著 [rag.py:337-350](../../backend/routers/rag.py) 的 `success` 狀態），前端步驟卡片是依 `step` 鍵值就地更新內容，`success` 事件的 `content` 會整個覆蓋掉 `running` 事件的內容。若只在 `running` 那次加上透明度資訊，使用者會看到「歷史則數／鎖定檔案」提示在查詢完成的瞬間突然消失。因此 `history_note`／`pinned_note` 必須**同時**寫進兩處：

```python
history_note = f"帶入歷史訊息數：{len(history_window) if history_window else 0} 則（設定值：{effective_history_turns} 則）"
pinned_note = f"手動鎖定檔案：{pinned_filename}" if pinned_filename else "手動鎖定檔案：未指定（由 AI 自動判斷）"

# 第一次 yield（running，[rag.py:321-331]）
step_data = {
    "step": "semantic_analysis",
    "status": "running",
    "content": (
        f"【地端 AI 語義分析結果】\n"
        f"{history_note}\n{pinned_note}\n"
        f"結構化 JSON：\n"
        f"```json\n{json_str}\n```\n"
        f"正在產生密集向量（輸入：\"{embeddings_input}\"，模型：{settings.EMBEDDING_MODEL}）..."
    )
}
yield f"event: step\ndata: {json.dumps(step_data, ensure_ascii=False)}\n\n"

# ...既有轉換密集向量邏輯不變...

# 第二次 yield（success，[rag.py:337-350]）——同樣要帶上 history_note／pinned_note，否則會被覆蓋消失
step_data = {
    "step": "semantic_analysis",
    "status": "success",
    "content": (
        f"【地端 AI 語義密集嵌入】\n"
        f"{history_note}\n{pinned_note}\n"
        f"結構化 JSON：\n"
        f"```json\n{json_str}\n```\n"
        f"密集向量模型: {settings.EMBEDDING_MODEL}\n"
        f"Base URL: {settings.LLAMACPP_BASE_URL}\n"
        f"向量維度: {len(query_vector)}\n"
        f"部分向量: {vector_preview}"
    )
}
```

前端「語義分析」步驟卡片沿用既有純文字/Markdown 渲染機制，不需要額外修改渲染邏輯即可顯示新增的兩行透明度資訊。

## 6. 執行流程設計

```
使用者於 RagParamsPanel.vue：
  勾選/取消「自動指代消解」（autoContextEnabled，預設勾選）
  + 視需要調整「歷史則數」（例如 5）
  + 視需要另外設定「手動鎖定檔案」（例如「HR手冊.pdf」，與自動指代消解可並用）
  │
  ▼
chatStore payload 組裝：
  history_context_turns = autoContextEnabled ? historyTurnCount : 0   ← 勾選框關閉時強制送 0
  pinned_filename = pinnedFilename
  │
  ▼
rag.py: search_type in (semantic_hybrid 家族) 分支
  │
  ▼
effective_history_turns = request.params.history_context_turns ?? SEMANTIC_JSON_HISTORY_TURNS
history_window = _build_history_window(request.chat_history, effective_history_turns)
pinned_filename = request.params.pinned_filename
  │
  ▼
EmbeddingService.query_to_semantic_json(question, ..., chat_history=history_window, pinned_filename=pinned_filename)
  │
  ├─ 兩者皆無 → 系統提示與現況逐字元相同（向後相容）
  │
  ├─ 有 pinned_filename → 系統提示追加【使用者已手動鎖定檔案】，LLM 直接鎖定該檔案
  │
  └─ 有 chat_history → 系統提示追加【近期對話歷史】+【指代消解規則】，LLM 依歷史脈絡解析「那份文件」
        │
        ▼
     輸出 embeddings_input / sparse_keywords / metadata.source_file（已消解指代或已鎖定）
        │
        ▼
     沿用既有 retry-with-temperature（[0.1, 0.5]）與 fallback 機制，完全不變
        │
        ▼
filter_filename = pinned_filename，若無則採用 AI 判斷的 metadata.source_file（優先權：使用者 > AI）
        │
        ▼
     SSE「語義分析」步驟卡片顯示本次實際帶入的歷史則數／鎖定檔案（事後透明度）
        │
        ▼
     後續向量檢索、Rerank、回饋加權等既有流程完全不受影響地繼續執行
```

失敗處理：若因為歷史區塊塞入過長內容導致 Instruct LLM 輸出超時或 JSON 格式錯誤，仍會被既有的重試機制（[embedding_service.py:276-289](../../backend/services/embedding_service.py)）捕捉並在第二次以更高溫度重試，兩次皆失敗才降級為 `fallback_json`（不帶歷史脈絡，退回目前行為），不會讓整個 RAG 對話中斷。

## 7. 新增設定值（`backend/config.py`）

| 變數 | 預設值 | 用途 |
|---|---|---|
| `SEMANTIC_JSON_HISTORY_TURNS` | `3` | 語義 JSON 轉換階段納入的最近對話則數之**後端預設值**，僅在使用者於前端未輸入 `history_context_turns`（留空）時採用；使用者輸入後以前端數值為準。設為 `0` 等同關閉此功能。 |

## 8. 決策紀錄／待確認事項

**已確認（2026-07-08 與使用者確認，本次規劃前提）**：
- 純加法式修改：`query_to_semantic_json` 新增可選參數，未傳入時行為與現況完全相同；`vector`/`hybrid`/`semantic_db_query` 三種查詢法完全不受影響。
- **歷史視窗大小不採固定後端常數，改為前端可調整**：使用者於 `RagParamsPanel.vue` 直接輸入要帶入的歷史訊息則數（`history_context_turns`），未輸入時才使用後端預設值 `SEMANTIC_JSON_HISTORY_TURNS`（第 8 節原問題 1 的解法，見第 3.3、5.1、7 節）。
- **新增「手動鎖定檔案」控制**：使用者可從知識庫既有檔案清單（重用 `GET /api/knowledge-bases/{id}/metadata`）手動選定一個檔案，優先權高於 AI 自動判斷的 `filter_filename`（見第 3.4、5.2 節）。
- **不新增 `resolved_reference` JSON 欄位**（原問題 2 的解法）：維持既有 JSON Schema 完全不變，向後相容優先。
- **不截斷歷史訊息長度**（原問題 3 的解法）：每則歷史訊息完整帶入 Prompt，不比照 `RerankService.CONTENT_PREVIEW_LEN` 做截斷。
- **需要事後透明度**：延伸既有 `semantic_analysis` SSE 步驟卡片內容，顯示本次實際帶入的歷史則數與是否有手動鎖定檔案（見第 5.5 節），不新增 SSE 事件種類。
- **新增「自動指代消解」勾選框總開關**（2026-07-08 補充決策）：除了「手動鎖定檔案」下拉選單，另外新增一個獨立的布林勾選框 `autoContextEnabled`，讓使用者能明確開關「是否要自動使用對話歷史做指代消解」，而不是只能靠把則數設為 `0` 間接關閉。預設**勾選**（維持功能上線後預設沿用後端 `SEMANTIC_JSON_HISTORY_TURNS` 的既有行為）。此勾選框純粹是前端 UX 層（關閉時前端強制送出 `history_context_turns=0`），**不需要新增任何後端欄位或程式碼**，見第 3.3、5.1、5.4 節。此勾選框與「手動鎖定檔案」是兩個獨立控制項，可同時使用。

**已確認（2026-07-08 經 Gemini 複查後採納，健全性/邊界情況修正）**：
- **知識庫切換時重置 `pinnedFilename`**：`RagParamsPanel.vue` 的 `watch(knowledgeBaseId)` 除了重新取得檔名清單，還須比對目前鎖定的檔名是否還在新清單中，不存在就重置為 `null`，避免切換知識庫後殘留的鎖定檔名導致檢索無聲變成 0 筆（見第 5.2 節）。
- **SSE `running`／`success` 兩次 yield 都要帶上透明度資訊**：`rag.py` 的 `semantic_analysis` 步驟實際上會 yield 兩次（`running` 於 [rag.py:321-331](../../backend/routers/rag.py)、`success` 於 [rag.py:337-350](../../backend/routers/rag.py)），`success` 會覆蓋掉 `running` 的內容，若只在其中一處加上 `history_note`／`pinned_note`，使用者會看到提示在查詢完成瞬間消失，因此兩處都要加（見第 5.5 節）。
- **`_build_history_window` 新增 `max_turns is None` 防禦性檢查**、**過濾 `chat_history` 只保留 `role in ("user", "assistant")` 的訊息**：前者防止未來若有呼叫點誤傳 `None` 導致 `TypeError` 中斷查詢；後者避免未來若混入非標準 role（例如工具訊息）污染指代消解脈絡（見第 3.3 節）。
- **前端 payload 正規化空字串為 `null`**：`<input type="number">` 被清空時 `v-model.number` 可能保留為空字串 `''`，原樣送出會被 Pydantic `Optional[int]` 判定為 422 Validation Error，`chatStore.js` 組裝 payload 時需正規化（見第 5.4 節）。
- **維持「不加歷史訊息長度上限」的原決策**（重新確認）：曾評估是否要加一個寬鬆的安全上限（例如每則 2000 字）防範使用者貼入極長內容拖垮地端 LLM 推論速度，但與使用者討論後**維持不截斷**，風險可接受，若未來實測發現問題再另行規劃。

本文件所有已知待確認事項皆已決策完畢，暫無殘留開放問題；若實作過程中發現新的技術細節需要確認，屆時再補充本節。

## 9. 分階段實作 Checklist

### Batch 1：後端核心邏輯
- [x] `backend/config.py` 新增 `SEMANTIC_JSON_HISTORY_TURNS`（預設 3，作為前端未輸入時的後端預設值）
- [x] `backend/services/embedding_service.py`：`query_to_semantic_json()` 新增可選參數 `chat_history: list = None`、`pinned_filename: str = None`，插入【使用者已手動鎖定檔案】＋【近期對話歷史】＋【指代消解規則】區塊（兩者皆為空時系統提示逐字元不變）
- [x] `backend/routers/rag.py`：
  - [x] 新增 `_build_history_window()` helper（含 `max_turns is None` 防禦性檢查、過濾 `role in ("user", "assistant")`）
  - [x] [rag.py:307-309](../../backend/routers/rag.py) 呼叫處傳入 `chat_history`/`pinned_filename`
  - [x] [rag.py:286](../../backend/routers/rag.py)／[rag.py:315-317](../../backend/routers/rag.py)：`filter_filename` 優先採用 `pinned_filename`，其次才是 AI 自動判斷
  - [x] [rag.py:321-331](../../backend/routers/rag.py)（`running`）與 [rag.py:337-350](../../backend/routers/rag.py)（`success`）**兩處** `semantic_analysis` 步驟卡片內容都要新增歷史則數／鎖定檔案透明度資訊，避免 `success` 覆蓋掉 `running` 顯示的提示

### Batch 2：API／Schema 串接
- [x] `backend/routers/rag.py`：`ChatParams` 新增 `history_context_turns`／`pinned_filename` 欄位

### Batch 3：前端 UI
- [x] `frontend/src/stores/paramsStore.js` 新增 `autoContextEnabled: true`／`historyTurnCount: null`／`pinnedFilename: null`
- [x] `frontend/src/components/params/RagParamsPanel.vue`：新增「自動指代消解」勾選框（預設勾選，關閉時歷史則數輸入框連動 disabled）+ 歷史則數數字輸入 + 手動鎖定檔案下拉選單（`watch` 知識庫切換時呼叫 `GET /api/knowledge-bases/{id}/metadata` 取得 `filenames`，並在切換時比對重置殘留的 `pinnedFilename`）
- [x] `frontend/src/stores/chatStore.js` payload 組裝新增 `history_context_turns`（`autoContextEnabled ? historyTurnCount : 0`，並正規化空字串/`NaN` 為 `null`）／`pinned_filename`

### Batch 4：驗證與回歸測試（待使用者人工測試，見下方逐項；本次僅完成 `python -m py_compile` 與 `npm run build` 靜態驗證）
- [ ] 人工測試：對同一份知識庫先問「XXX文件講什麼」，追問「那份文件的第二點是什麼」，確認 `embeddings_input`/`sparse_keywords` 正確帶出前一輪提及的檔名，且步驟卡片正確顯示帶入則數（`running`／`success` 兩個狀態都要有）
- [ ] 人工測試：手動於下拉選單鎖定某檔案後提問，確認 `filter_filename` 確實被鎖定，且步驟卡片顯示鎖定的檔名
- [ ] 人工測試：取消勾選「自動指代消解」後追問指示詞問題，確認不再自動帶入歷史（`history_context_turns` 送出 `0`），行為等同關閉本功能
- [ ] 人工測試：於知識庫 A 鎖定某檔案後切換到知識庫 B，確認 `pinnedFilename` 自動重置為未鎖定，不會殘留無效檔名導致檢索無聲變成 0 筆
- [ ] 人工測試：把「歷史則數」輸入框清空後送出，確認前端正規化為 `null` 而非空字串，不會觸發後端 422 Validation Error
- [ ] 回歸確認：`vector`/`hybrid`/`semantic_db_query` 三種查詢法呼叫路徑未受影響（無 `chat_history`/`pinned_filename` 參數傳入，行為不變）
- [ ] 回歸確認：兩個新參數皆未設定（新對話第一輪、未選鎖定檔案、勾選框維持預設勾選）時，`query_to_semantic_json` 輸出與修改前完全一致（防止意外破壞既有 fallback/重試行為）

### Batch 5：文件更新
- [x] `docs/03_API_CONTRACT.md`：`ChatParams` 補上 `history_context_turns`／`pinned_filename` 欄位說明
- [x] `docs/DevelopmentProcess/NewFeatures.md`：實作完成後記錄本次新增
