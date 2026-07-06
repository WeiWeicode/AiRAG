# 檢索內容分批摘要（Context Map-Reduce Summary）規劃文件

> 狀態：**已實作，全部已知問題（第 10、12 節）皆已修正**。對應
> `docs/DevelopmentProcess/NewFeatures.md`／`BackendCorrection.md`／`FrontendCorrection.md` 2026-07-06 條目。

## 1. 問題背景

`rag.py` 的 `rag_chat_stream()` 目前在 [rag.py:369-403](../../backend/routers/rag.py) 組完 `context_parts` 後，
直接把所有檢索片段串成一個 `context_str` 塞進最終結論 Prompt（見 [rag.py:435-446](../../backend/routers/rag.py)），
中間**沒有任何 token 估算或保護機制**。當使用者把 Top-K 設太高、或命中片段內容偏長時，
`system_prompt + chat_history + context_str` 的總 token 數會超過 vLLM 端實際設定的 context length（目前 9 萬），
vLLM 直接回 400，整輪對話失敗、沒有任何降級處理。

## 2. 解法：分批摘要（Map）→ 合併整理（Reduce）

比照使用者提出的具體範例設計演算法。假設使用者把「分批摘要門檻」設為 **5 萬 token**（可調整），
本次檢索到 5 個區塊，token 數分別是 1萬、1.5萬、2萬、3萬、4萬（依檢索排序，總計 11.5 萬，已超過門檻）：

```
依序累加分組（Bin-Packing，不拆散任何一個區塊）：
  區塊1(1萬) + 區塊2(1.5萬) + 區塊3(2萬) = 4.5萬 ≤ 5萬 → 累加下一塊會超過門檻，分組1 = [區塊1,2,3]
  區塊4(3萬)                            = 3萬  ≤ 5萬 → 累加下一塊會超過門檻，分組2 = [區塊4]
  區塊5(4萬)                            = 4萬  ≤ 5萬 → 已無下一塊，分組3 = [區塊5]

Map 階段（可在前端即時看到每一批的輸入與整理結果）：
  分組1 → LLM 摘要 → 摘要S1
  分組2 → LLM 摘要 → 摘要S2
  分組3 → LLM 摘要 → 摘要S3

Reduce 階段：
  S1 + S2 + S3 的 token 總量 <= 門檻 → 再呼叫一次 LLM，將 3 份摘要整合成一份最終上下文
  （若 S1+S2+S3 仍超過門檻，代表資料量極大，遞迴套用同一套 Bin-Packing + Map 流程，
   直到合併後低於門檻，並設上限次數避免無窮迴圈，見第 6 節）
```

這與使用者描述的「1+1.5+2 整理一次、3萬整理一次、4萬整理一次，最後把 3 個整理過的再整理一次」完全對應。

**核心原則（對應需求 1：以區塊為主，避免上下文被截斷）**：
分組演算法只會把「完整的區塊」湊在一起送進同一次 LLM 呼叫，**絕不會把單一區塊從中間截斷**。
若單一區塊本身的 token 數就超過門檻（例如検索片段異常長），該區塊仍會獨立成一組整批送進 Map，
不做字元截斷——這是唯一的例外情況，見第 7 節「已知限制」。

## 3. 新增設定值（`backend/config.py`）

| 變數 | 預設值 | 用途 |
|---|---|---|
| `DEFAULT_CONTEXT_SUMMARIZE_THRESHOLD_TOKENS` | `50000` | 觸發分批摘要的門檻，同時也是每一批 Bin-Packing 的容量上限（沿用使用者範例中「一個數字兩種用途」的設計，前端可覆寫） |
| `CONTEXT_SUMMARIZE_MAX_ROUNDS` | `3` | Reduce 遞迴輪數上限，避免異常情況下無窮迴圈 |

不新增獨立的「vLLM context length」設定值——由使用者自行把門檻設在明顯低於地端 vLLM 實際 context length（目前 9 萬）之下即可，門檻與模型上限是否留有安全餘裕由使用者判斷，程式不做額外校驗假設。

## 4. Token 估算方式

專案目前沒有任何 tokenizer（唯一先例是 `ai_db_query_service.py` 用字元數粗估，非真正 token 數）。
依討論結果，新增 `tiktoken` 依賴（`requirements.txt`），在 `backend/utils/token_counter.py` 新增：

```python
import tiktoken

_encoding = tiktoken.get_encoding("cl100k_base")

def count_tokens(text: str) -> int:
    return len(_encoding.encode(text))
```

**重要限制需記錄**：`cl100k_base` 是 OpenAI 的編碼表，並非 Qwen 系列實際使用的 tokenizer，估算值只會是近似值
（門檻建議抓保守一點，不要卡在剛好等於 9 萬的邊界）。另外 tiktoken 預設會在**第一次呼叫時從網路下載**編碼檔，
但本專案是地端部署（Docker 容器內只跑 vLLM/llama.cpp/MongoDB/Qdrant，不保證有對外網路），
因此需要在 `backend/Dockerfile` build 階段預先下載好 `cl100k_base` 的快取檔並烘進映像檔
（設定 `TIKTOKEN_CACHE_DIR` 環境變數指向已快取好的目錄），比照現有烘 Oracle Instant Client 的做法，
否則正式環境第一次呼叫會因無法連網而失敗。

## 5. 後端服務設計：`backend/services/context_summarizer_service.py`

比照 `AIDBQueryService`／`FeedbackBoostService` 的獨立 service 模式，讓 `rag.py`／`retrieval.py`／`evaluation.py`
未來若要共用同一套摘要邏輯時不必重複實作。因為是 async generator 需要邊跑邊 yield SSE 進度事件，
比照 `rag.py` 裡 `_run_semantic_db_query()` 的模式，最終結果透過呼叫端傳入的 mutable dict 取回：

```python
class ContextSummarizerService:
    @classmethod
    async def maybe_summarize(
        cls,
        question: str,
        blocks: list[dict],       # 每個 dict: {"text": str, "label": str}，label 用於前端顯示與保留來源
        threshold_tokens: int,
        result: dict,             # 呼叫端傳入，寫入 result["context_str"] / result["was_summarized"]
        round_no: int = 1,
    ):
        total = sum(count_tokens(b["text"]) for b in blocks)
        if total <= threshold_tokens:
            result["context_str"] = "\n---\n".join(b["text"] for b in blocks)
            result["was_summarized"] = round_no > 1
            return

        groups = _bin_pack(blocks, threshold_tokens)  # 依序累加分組，不拆散區塊

        summaries = []
        for i, group in enumerate(groups, start=1):
            step_key = f"context_summarize_r{round_no}_batch_{i}"
            label = f"第 {round_no} 輪・分批整理 {i}/{len(groups)}（{len(group)} 個區塊，約 {sum(count_tokens(b['text']) for b in group)} token）"
            yield f"event: step\ndata: {json.dumps({'step': step_key, 'status': 'running', 'content': f'{label}\\n\\n原始內容：\\n' + ...}, ensure_ascii=False)}\n\n"

            summary_text = await LLMService.chat_completion(
                messages=_build_map_prompt(question, group),
                temperature=0.2,
                max_tokens=1500,
            )
            summaries.append({"text": summary_text, "label": f"摘要（第 {round_no} 輪批次 {i}）"})

            yield f"event: step\ndata: {json.dumps({'step': step_key, 'status': 'success', 'content': f'{label}\\n\\n整理結果：\\n{summary_text}'}, ensure_ascii=False)}\n\n"

        if round_no >= settings.CONTEXT_SUMMARIZE_MAX_ROUNDS:
            # 安全閥：已達遞迴上限，直接合併現有摘要，不再遞迴檢查
            result["context_str"] = "\n---\n".join(s["text"] for s in summaries)
            result["was_summarized"] = True
            return

        if len(summaries) == 1:
            # 單一超大區塊整批 Map 後已是最終結果，不需要再做 Reduce 合併
            result["context_str"] = summaries[0]["text"]
            result["was_summarized"] = True
            return

        # Reduce：至少 2 份摘要，遞迴呼叫自己檢查合併後是否已在門檻內
        # （若仍超過門檻，遞迴會再次進入 Map 分組，即「最後再整理一次」之後還太大時的下一輪）
        reduce_step_key = f"context_summarize_r{round_no}_reduce"
        yield f"event: step\ndata: {json.dumps({'step': reduce_step_key, 'status': 'running', 'content': f'正在將 {len(summaries)} 份摘要整合成一份最終上下文...'}, ensure_ascii=False)}\n\n"
        async for evt in cls.maybe_summarize(question, summaries, threshold_tokens, result, round_no=round_no + 1):
            yield evt
        yield f"event: step\ndata: {json.dumps({'step': reduce_step_key, 'status': 'success', 'content': result['context_str']}, ensure_ascii=False)}\n\n"
```

（上方為設計示意，非最終逐字實作；實際實作時把 SSE 字串組裝抽成小 helper 避免重複。）

**Map 摘要 Prompt 設計要點**：
- 明確要求「根據使用者原始問題，從這批段落中萃取相關重點，去除無關內容」，避免變成無差別壓縮丟失關鍵資訊。
- **必須要求保留來源標記**（格式沿用既有的『[文件名] 段落: #段落編號』），否則最終結論階段（[rag.py:442-444](../../backend/routers/rag.py)）要求的引用格式會失去依據，前端 `SourceChunks.vue` 顯示的來源面板雖然不受影響（`sources` 陣列本來就是用原始未壓縮片段組成，見下一節），但答案內文的引用聲明會對不上。
- 摘要呼叫用**主模型 vLLM（Qwen3.6-35B-A3B-FP8）**執行（`LLMService.chat_completion`，非串流），與最終結論用同一模型，避免品質落差；`temperature` 調低（如 0.2）讓摘要更穩定收斂。

## 6. `rag.py` 整合點

- **套用範圍**：所有 `search_type`（`vector`／`hybrid`／`semantic_hybrid`／`semantic_hybrid_feedback`／`semantic_db_query`）通用，
  在 [rag.py:395-403](../../backend/routers/rag.py) 組完 `context_parts` 之後、[rag.py:422](../../backend/routers/rag.py) 建構結論 Prompt 之前插入。
- **`sources`（前端來源面板用）維持不動**：`sources` 陣列在組 `context_parts` 的同一段迴圈中就已經組好（[rag.py:372-387](../../backend/routers/rag.py)），
  摘要只會替換掉餵給 LLM 的 `context_str`，不影響 `SourceChunks.vue` 顯示的原始片段引用列表。
- `ChatParams`（[rag.py:25-34](../../backend/routers/rag.py)）新增可選欄位 `context_summarize_trigger_tokens: Optional[int] = None`，
  未帶值時 fallback 到 `settings.DEFAULT_CONTEXT_SUMMARIZE_THRESHOLD_TOKENS`。

## 7. 前端設計

### 7.1 可調整門檻（對應需求 2）

`frontend/src/stores/paramsStore.js` 新增 `contextSummarizeThreshold: null`
（比照既有 `dbQueryMaxRows`/`dbQueryMaxChars` 的「留空即沿用後端全域預設值」慣例）。

`frontend/src/components/params/RagParamsPanel.vue` 新增一個輸入框（放在既有 Top-K／相似度閾值下方）：

```
分批摘要門檻 (Context Summarize Threshold, tokens)
[ 輸入框，placeholder="預設 50000" ]
說明文字：檢索內容 token 數超過此值時，會先分批摘要再送進主模型，避免超出模型上下文長度而回傳 400。
```

`chatStore.js` 的 `_streamChat()` 組 payload 時（[chatStore.js:114-122](../../frontend/src/stores/chatStore.js)）新增：
```js
context_summarize_trigger_tokens: paramsStore.contextSummarizeThreshold || undefined
```

### 7.2 動態顯示每一批整理過程（對應需求 3）

現況兩個限制需要一併修正，否則新的 SSE step 事件無法顯示：

1. **`msg.steps` 目前只在 3 種查詢法才初始化**（[chatStore.js:73](../../frontend/src/stores/chatStore.js) 的
   `['semantic_hybrid', 'semantic_hybrid_feedback', 'semantic_db_query'].includes(...)`），`vector`/`hybrid` 兩種模式
   目前完全不建立 `steps` 陣列，導致後端送出的 `step` 事件全部被忽略（[chatStore.js:244](../../frontend/src/stores/chatStore.js) 的
   `if (stepObj)` 找不到就直接丟棄）。既然分批摘要要對所有 `search_type` 通用，這裡要**改成一律建立 `steps` 陣列**
   （拿掉查詢法限制），讓 `vector`/`hybrid` 模式也能看到分析/檢索/摘要步驟。
2. **`steps` 陣列目前是寫死的固定 4 筆**，分批數量是依實際 token 量動態決定的（可能 0 批、可能 5 批以上），
   無法預先寫死。因此把 [chatStore.js:244-250](../../frontend/src/stores/chatStore.js) 的比對邏輯改成：
   找不到對應 `key` 的 step 時，**動態插入一筆新的 step 物件**到 `llm_thinking` 之前（維持時間順序），
   而不是直接丟棄：
   ```js
   } else if (msg.steps) {
     let stepObj = msg.steps.find(s => s.key === data.step)
     if (!stepObj) {
       stepObj = { key: data.step, name: data.label || data.step, status: 'pending', content: '', expanded: false }
       const insertAt = msg.steps.findIndex(s => s.key === 'llm_thinking')
       msg.steps.splice(insertAt === -1 ? msg.steps.length : insertAt, 0, stepObj)
     }
     stepObj.status = data.status
     stepObj.content = data.content
     if (data.label) stepObj.name = data.label
   }
   ```
   後端每個分批/合併 step 事件都要帶 `label` 欄位（例如「第 1 輪・分批整理 1/3（3 個區塊，約 4.5萬 token）」），
   前端才能顯示有意義的步驟名稱，不需要前端事先知道會有幾批。
   `MessageBubble.vue`（[MessageBubble.vue:65-115](../../frontend/src/components/chat/MessageBubble.vue)）本身用
   `v-for="step in message.steps"` 泛用渲染，**不需要改動**就能顯示動態新增的步驟，包含展開查看該批「原始內容 / 整理結果」的完整過程。

## 8. 已知限制與邊界情況

1. **單一區塊本身超過門檻**：例如檢索片段異常長導致單一區塊 token 數就大於門檻值，該區塊仍會獨立整批送進 Map
   （見第 2 節），不做字元截斷；此情況下該次 Map 呼叫的 prompt 仍可能逼近 vLLM 實際 context length，
   屬於刻意接受的邊界情況（優先保證「不拆散區塊」而非「絕對不超過門檻」），日常情境下（分片預設約 512 字）極少發生。
2. **遞迴上限 `CONTEXT_SUMMARIZE_MAX_ROUNDS`**：正常情況下 Map 過的摘要會遠小於原文，1-2 輪即可收斂到門檻內；
   達到上限仍未收斂時直接合併現有摘要送出，並在對應 step 內容註記「已達整理輪數上限，直接合併」，不無限迴圈、不靜默失敗。
3. **token 估算為近似值**（見第 4 節），不是 Qwen 真正的 tokenizer 計算結果，門檻建議保守設定。
4. **`semantic_db_query` 查詢法**的 `context_str` 是資料庫查詢結果文字（非文件段落引用格式），Map 摘要 prompt
   需要有一個分支識別是否為資料庫查詢結果（不要求保留『[文件名] 段落: #段落編號』格式，改為保留『表格/欄位』脈絡），
   避免摘要規則對不上內容型態。

## 9. 分階段實作 Checklist

- [x] `requirements.txt` 新增 `tiktoken`；`backend/Dockerfile` 預先下載並烘入 `cl100k_base` 快取（設定 `TIKTOKEN_CACHE_DIR`）
- [x] `backend/utils/token_counter.py`（新檔，`count_tokens()`）
- [x] `backend/config.py` 新增 `DEFAULT_CONTEXT_SUMMARIZE_THRESHOLD_TOKENS`（50000）／`CONTEXT_SUMMARIZE_MAX_ROUNDS`（3）
- [x] `backend/services/context_summarizer_service.py`（新服務，`maybe_summarize()` 遞迴 Map-Reduce + SSE 進度事件）
- [x] `backend/routers/rag.py`：`ChatParams` 新增 `context_summarize_trigger_tokens`；組完 `context_parts` 後、結論 Prompt 前接上摘要服務（所有 `search_type` 通用）
- [x] `frontend/src/stores/paramsStore.js` 新增 `contextSummarizeThreshold`
- [x] `frontend/src/components/params/RagParamsPanel.vue` 新增門檻輸入框
- [x] `frontend/src/stores/chatStore.js`：
  - [x] `sendQuestion()` 移除 `steps` 初始化的查詢法限制，一律建立 base steps
  - [x] `_streamChat()` payload 帶入 `context_summarize_trigger_tokens`
  - [x] `step` 事件處理改為找不到 key 時動態插入新 step（含 `label`），而非丟棄
- [x] `docs/02_ARCHITECTURE.md` 補充 Map-Reduce 摘要步驟到 pipeline 描述
- [x] `docs/03_API_CONTRACT.md` 補充 `ChatParams.context_summarize_trigger_tokens` 欄位說明
- [x] `docs/DevelopmentProcess/NewFeatures.md` 記錄本次新增（實作完成後）

## 10. 實作後 Code Review 發現的問題（2026-07-06，已全部修正）

實作完成後對照本規劃文件檢查程式碼，方向正確、與規劃一致，發現以下事項，已於 2026-07-06 全部修正：

1. **【中，已修正】Map/Reduce 呼叫失敗時會讓整個 SSE 串流直接中斷，沒有降級**
   [context_summarizer_service.py:188-197](../../backend/services/context_summarizer_service.py) 在 Map 階段呼叫 LLM 失敗時，
   會先 yield 一個 `failed` step，然後 `raise e`；但 [rag.py:444-451](../../backend/routers/rag.py) 呼叫這個 generator 時
   沒有包 try/except，例外會一路往上炸穿整個 `rag_chat_stream()`，導致 `llm_thinking`/`conclusion`/`sources`/`done`
   這些收尾事件全部發不出去，前端串流會卡住或直接連線中斷。這跟現有程式碼的錯誤處理慣例不一致——
   同檔案的 `LLMService.query_rewrite()`/`hyde_generation()`、以及 `rag.py` 本身對向量檢索失敗、vLLM 串流失敗的處理，
   都是「local catch + 降級成友善訊息繼續往下走」，不會讓整個 generator 掛掉。
   這個情境滿容易真的發生：`LLMService.chat_completion()` 非串流呼叫寫死 `timeout=60.0`
   （[llm_service.py:38](../../backend/services/llm_service.py)），Map 階段一次要送 4-5 萬 token 的內容給地端 vLLM，
   60 秒很可能不夠，一旦 timeout 就會整輪對話失敗。
   **修法**：在 [rag.py:454-471](../../backend/routers/rag.py) 呼叫 `ContextSummarizerService.maybe_summarize()` 處包 try/except，
   失敗時 log 錯誤、yield 一個 `context_summarize_error` failed step 告知使用者，並保留原始未摘要的 `context_str` 繼續往下走，
   不中斷整個回答流程（`context_summary` 也會保留失敗前已完成的 `batch_count`/`rounds`，`was_summarized` 維持預設 `False`）。
   已用模擬測試驗證：即使摘要中途丟出例外，串流仍會正常送出 `llm_thinking`/`sources`/`done`，不會卡死或中斷連線。

2. **【低，已修正】`rag.py` 組 block 時 `label` 欄位有重複 `#` 的小 bug**
   [rag.py:451](../../backend/routers/rag.py)：`chunk_idx_str` 已經是 `f"#{chunk_idx}"`，
   原本後面又寫 `label = f"...#{chunk_idx_str}"` 多加了一個 `#`，變成 `"檔名.md ##12"`；
   已改成 `label = f"...{chunk_idx_str}"`，確認輸出為 `"檔名.md #12"`。此欄位目前仍是死欄位（沒有下游讀取），
   純粹修正資料正確性，不影響現有行為。

3. **【已確認無問題】`event_data` 重構已正確修掉 f-string 反斜線語法錯誤**
   `BackendCorrection.md` 記錄的「Python 3.11 下 f-string 反斜線導致 SyntaxError」問題，
   已確認目前 `context_summarizer_service.py` 全部改成先組 `event_data` dict 再 `json.dumps()`，沒有殘留問題
   （`backend/Dockerfile` 使用 `python:3.11-slim`，若殘留會導致整個後端在容器內啟動失敗，需特別留意日後不要重新引入這類寫法）。

4. **【設計確認，非問題】`vector`/`hybrid` 模式現在也會顯示步驟明細**
   [chatStore.js:73-78](../../frontend/src/stores/chatStore.js) 把 `steps` 陣列改成所有查詢模式都會初始化
   （原本只有 3 種進階查詢法才有），這是本規劃需要的改動（否則 `vector`/`hybrid` 模式的摘要步驟事件會被前端丟棄），
   但附帶效果是這兩種最基本的查詢模式，即使沒有觸發摘要，現在也會顯示「語義分析／向量資料查詢」步驟卡片，
   是預期內的 UI 變動，手動測試時留意即可。

## 11. 追加功能：前端顯示每個 Chunk 的 Token 數與總計/切分次數（2026-07-06）

在「參考文檔引用 (Chunks)」列表補上使用者可直接檢視的統計資訊，方便判斷是否觸發、如何觸發了分批摘要。

### 後端

- `backend/routers/rag.py`：
  - 匯入 `utils.token_counter.count_tokens`。
  - 一般檢索路徑（[rag.py:379-393](../../backend/routers/rag.py)）與 `semantic_db_query` 路徑
    （`_run_execute()` 內的 `sources.append(...)`）都新增 `"token_count": count_tokens(...)` 欄位，逐一 chunk 記錄實際 token 數。
  - 新增 `context_summary` dict（`total_tokens`／`batch_count`／`rounds`／`was_summarized`／`threshold_tokens`），
    在函式一開始給預設值（全 0／False），組完 `context_str` 後把 `total_tokens` 設為所有來源 chunk 的 `token_count` 加總；
    若有實際呼叫 `ContextSummarizerService.maybe_summarize()`，再從其 `result` dict 補上 `batch_count`／`rounds`／`was_summarized`。
  - 最終 `event: sources` 事件（[rag.py:559](../../backend/routers/rag.py)）夾帶 `context_summary` 欄位一起送給前端。
- `backend/services/context_summarizer_service.py`：
  - `maybe_summarize()` 進入時無條件記錄 `result["rounds"] = round_no`（遞迴時會被覆寫成最後到達的輪數）。
  - 每次真正跑 Map 分組時累加 `result["batch_count"] = result.get("batch_count", 0) + len(groups)`，
    讓遞迴多輪時的批次數可以正確加總（對應使用者說的「切分幾次思考」）。

### 前端

- `frontend/src/stores/chatStore.js`：`sources` SSE 事件處理時，一併把 `data.context_summary` 存進 `msg.contextSummary`；
  初始 assistant 訊息物件新增 `contextSummary: null`。
- `frontend/src/components/chat/MessageBubble.vue`：`<SourceChunks>` 新增 `:context-summary="message.contextSummary"`。
- `frontend/src/components/chat/SourceChunks.vue`：
  - 新增 `contextSummary` prop，在清單最上方顯示一列統計摘要：總計 Token 數，以及是否觸發分批摘要
    （觸發時顯示「切分 N 次整理 / M 輪思考」，未觸發時顯示「未超過門檻，未進行分批摘要」）。
  - 每個 chunk 項目在原本的 `Similarity` 徽章旁新增 `Tokens: N` 徽章（`source.token_count`）。

### 已知限制

- `total_tokens` 是**所有來源 chunk 原始內容**的 token 加總，跟 `ContextSummarizerService` 內部實際送進 Map 呼叫的
  區塊 token 數（含「【來源文件：...】」等包裝文字）會有些微落差（包裝文字造成的少量額外 token），
  這是刻意選擇——讓「總計」等於畫面上每個 chunk 顯示數字的加總，兩者可以互相對得起來，避免使用者疑惑加總對不上。
- 若後端 Map/Reduce 呼叫中途失敗（見第 10 節問題 1），`context_summary` 只會反映失敗前已完成的批次數，
  不是最終正確值；等問題 1 修正後這裡的數字才會在失敗情境下也保持準確。

## 12. 實測回饋（2026-07-06）：新發現 Bug + Top-K 上限調整

### 12.1【已修正，2026-07-06】Bug：遞迴 Reduce 進入下一輪後，當前輪的「合併最終摘要」步驟永遠卡在執行中

**現象**（使用者實測畫面）：`第 1 輪・分批整理 1/2`、`第 1 輪・分批整理 2/2` 都正常顯示 ✓ 完成，
`第 1 輪・合併最終摘要` 卻永遠停在「執行中」轉圈圈，同時 `第 2 輪・合併最終摘要` 已經顯示 ✓ 完成，
接著 `思考中` 也已經在跑——三個步驟的圈圈同時存在畫面上，看起來像「第一輪跟最終結論同時思考」，
但實際上第 1 輪已經真正跑完了，只是**UI 狀態沒有收尾**，並非後端真的同時平行執行两段摘要。

**根因**：[context_summarizer_service.py:222-240](../../backend/services/context_summarizer_service.py) 的遞迴 Reduce 分支：
```python
reduce_step_key = f"context_summarize_r{round_no}_reduce"
event_data = {"step": reduce_step_key, "status": "running", ...}
yield f"event: step\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"

async for evt in cls.maybe_summarize(question, blocks=summaries, threshold_tokens, result, round_no=round_no + 1, is_db=is_db):
    yield evt
# ← 遞迴呼叫（下一輪）結束後，直接 return，從未針對「當前這一輪」的 reduce_step_key 補發 status: "success"
```
只 yield 了 `running` 事件就直接遞迴進下一輪，遞迴呼叫回傳的都是**下一輪自己的** step 事件（`context_summarize_r{round_no+1}_...`），
當前輪的 `context_summarize_r{round_no}_reduce` 這個 key 從此再也沒有事件更新它，前端 [chatStore.js](../../frontend/src/stores/chatStore.js)
找到既有 step 物件後只會更新 `status`/`content`，沒有事件進來就永遠停在最後一次收到的 `running` 狀態——這與規劃文件第 5 節
原始設計示意（遞迴呼叫結束後應該要再補一個 `success` 事件）不一致，是實作時漏掉的收尾步驟。

**建議修法**：在 `async for evt in cls.maybe_summarize(...)` 迴圈結束之後，補發一個該輪 `reduce_step_key` 的 `success` 事件，
例如：
```python
async for evt in cls.maybe_summarize(
    question=question, blocks=summaries, threshold_tokens=threshold_tokens,
    result=result, round_no=round_no + 1, is_db=is_db
):
    yield evt

event_data = {
    "step": reduce_step_key,
    "status": "success",
    "content": f"已將 {len(summaries)} 份摘要整合完成，交由下一輪繼續處理。",
    "label": f"第 {round_no} 輪・合併最終摘要"
}
yield f"event: step\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"
```
（內容故意不直接塞 `result["context_str"]`，因為那是**最終**結果，遞迴中間輪次顯示「交由下一輪繼續處理」比較不會誤導使用者
以為這輪的輸出就是最終答案；只有真正的最後一輪——命中函式開頭 `total <= threshold_tokens` 的 `else` 分支——才會顯示合併後的實際內容。）

**修正結果**：使用者已依上述修法自行修正 [context_summarizer_service.py:242-248](../../backend/services/context_summarizer_service.py)。
用 mock LLM 模擬使用者實測的分組情境（1萬/1.5萬/2萬/3萬/4萬 token、門檻 5萬）驗證：
`context_summarize_r1_reduce` 現在會在遞迴的下一輪（`r2_reduce`）完全結束後正確收到 `success` 事件，
沒有任何 step key 停留在 `running` 未收尾；最終 `result` 正確回傳 `rounds=2`、`batch_count=3`、`was_summarized=True`。

### 12.2【已實作】檢索數量 (Top-K) 滑桿上限從 15 調整為 50

**動機**：上限 15 太低，不容易在「RAG 功能測試」頁面手動測出需要觸發 Map-Reduce 分批摘要的情境
（Top-K 越高、召回片段越多，越容易累積超過分批摘要門檻），調高上限方便測試本功能與其他大量召回情境。

**修改內容**：[RagParamsPanel.vue:23-29](../../frontend/src/components/params/RagParamsPanel.vue) 的 Top-K 滑桿 `max` 由 `15` 改為 `50`
（`min="1"` 不變）。已直接修改並確認 `npm run build` 通過。

**範圍說明**：`frontend/src/views/RetrievalTestView.vue`（檢索測試頁）有另一個獨立的 Top-K 滑桿（目前 `max="20"`），
跟這次調整的 RAG 對話測試頁滑桿是兩份獨立程式碼，這次沒有一併調整，如果之後也需要調高再另外處理。

## 13. 最終複查（2026-07-06）：收尾三項小修正

功能整體確認完成後做最後一輪複查，額外處理以下三點（第 10 節的兩個待修事項 + 一個環境衛生問題）：

1. **Map/Reduce 失敗降級**（對應第 10 節問題 1）：已在 [rag.py:454-471](../../backend/routers/rag.py) 加上 try/except，
   修法與驗證方式見第 10 節該問題的更新內容。
2. **`label` 重複 `#` 修正**（對應第 10 節問題 2）：已修正，見第 10 節該問題的更新內容。
3. **`.gitignore` 補上 `.tiktoken_cache/`**：複查時發現本機執行時 tiktoken 會在 `backend/.tiktoken_cache/` 產生快取檔案，
   `backend/.gitignore` 原本只有 `.cache`（比對不到 `.tiktoken_cache` 這個目錄名），導致這個二進位快取目錄一直顯示在
   `git status` 的 untracked 清單中，之後若不小心 `git add -A` 可能誤把它加進版本控制。已在 `backend/.gitignore` 新增
   `.tiktoken_cache/` 規則（正式環境的快取是在 Docker build 階段烘進映像檔的 `/app/.tiktoken_cache`，跟本機這份無關，
   不需要進版本控制）。

修正後重新跑過 `py_compile`（全部通過）與 `npm run build`（通過），確認沒有引入新問題。**至此本功能第 10、12、13 節列出的
問題全部處理完畢，無待辦事項。**
