<!-- BUG修正(最新紀錄放最前面) -->

## 2026-07-08（已實作，後續發現）標頭格式修正後問題仍在：Map-Reduce 分批摘要區塊重建時遺漏攤平的圖片描述，且 Citation 範例數量錨定模型只引用少數段落

### 問題描述
延續同日稍早的「Context 標頭格式污染」修正（見下一則條目），使用者依相同問題（「說明GP51建立備份營運中心.docx包含圖片」）重新測試後，畫面確認：
- 前端「同段落」標籤與 Token 統計已正常顯示（上一次修正的前端／Token 部分確認有效）。
- 但 AI 回覆的結論**仍然**只引用總結 1~2 筆段落，其餘 10 幾筆同段落圖片描述依然完全沒有出現在回答中——證明「標頭格式污染」並非唯一根因，該修正是必要但不充分的。

再次透過 Explore／Plan 子代理交叉調查並逐一核對現行程式碼後，定位出兩個疊加的新根因。

### 根本原因

**1.（主因，新發現）Map-Reduce 分批摘要重建 `blocks` 時只採用 `sources`，遺漏攤平進 `context_parts` 的周邊文字與圖片描述，導致「未達門檻直接合併」的分支用不完整內容覆蓋掉原本正確的 `context_str`**

`backend/routers/rag.py`：
- 第 439-514 行組裝的 `context_parts`／`context_str` 是完整的（核心命中＋周邊文字＋攤平的同段落圖片描述皆在內）。
- 但第 563-578 行另外重建的 `blocks`（供 `ContextSummarizerService.maybe_summarize` 判斷是否需要分批摘要）**只從 `sources` 陣列逐筆建立**，而 `sources` 只有每個 `raw_results` 核心命中一筆，從未包含攤平進 `context_parts` 的周邊文字／圖片描述區塊。
- `ContextSummarizerService.maybe_summarize`（`context_summarizer_service.py:113-120`）在 `blocks` 總 token 數未達門檻（本例遠低於預設 50,000）時，會直接 `result["context_str"] = "\n---\n".join(b["text"] for b in blocks)`——用這個**不完整的 `blocks`** 重建 `context_str`。
- `rag.py:599-600` 再把這個不完整的重建結果**覆蓋掉**原本正確、完整的 `context_str`。

也就是說，不論標頭格式再乾淨，這些同段落圖片描述在送進最終 `system_prompt` 之前就已經被這個重建流程整批丟棄，LLM 根本沒看到它們。畫面顯示的「總計 Token」是在這個覆蓋動作**之前**另外計算的（`rag.py:561`），因此完全看不出內容已經被砍掉，這也是為何先前的 Token 數字檢查沒能抓到這個問題。

**2.（次因，新發現）System Prompt 的引用格式範例只示範 3 筆，可能錨定模型只引用少量段落**

`rag.py` 的 `elif context_str:` system prompt 規則 1 只說「儘量使用參考資料中的資訊來回答」（軟性、非強制窮盡），規則 4 唯一示範「引用多個段落」的範例固定只列出 3 個段落編號（`#43`、`#45`、`#10`），且沒有任何說明表示實際數量可以遠不只 3 筆。全專案 grep 未發現任何「必須逐一列舉所有相關內容」的既有規則寫法。這很可能讓模型即使真的收到 10 幾筆圖片描述，也會被這個範例錨定，傾向只挑 2~3 筆具代表性的段落引用。

### 解決方案
1. **`rag.py` 第 571-578 行附近**：`blocks`（非 `is_db` 分支）改為直接沿用組裝 `context_parts` 時已完整組好的文字區塊清單（`for idx, part_text in enumerate(context_parts): blocks.append({"text": part_text, "label": f"context_block_{idx + 1}"})`），取代原本只從 `sources` 重建的邏輯，確保分批摘要門檻判斷與「未達門檻直接合併」的結果都以實際送進 LLM 的完整內容為準，不會再遺漏周邊文字／圖片描述。同時修正了一個潛在的正確性問題：若真實 context（含攤平圖片）超過摘要門檻但 `sources`-only 加總沒超過，先前會誤判不需要摘要。
2. **`rag.py` 的 `elif context_str:` system prompt**：規則 4 補上一句明確說明「範例僅為格式示範，並非引用數量上限」，並新增條件式規則 5——僅在 `context_str.count("[圖片描述]") >= 2`（確實存在多張圖片描述）時才附加，要求模型針對每一張圖片逐一說明或至少提及，不要只挑一張作代表；並保留「若問題明顯只針對特定圖片則可聚焦」的例外，避免影響一般大 `top_k` 純文字問答的正常摘要行為。

### 修改檔案
- `backend/routers/rag.py`

### 驗證
- `python -c "import ast; ast.parse(...)"` 驗證語法正確。
- **待使用者實機驗證**：重新提問同一問題，確認 AI 回覆會引用/提及大多數（而非僅 1~2 筆）圖片段落；並用先前 top_k=23 的一般純文字問題回歸測試，確認規則 5 不會被觸發、答案不會被強迫塞入過多不必要的引用。

## 2026-07-08（已實作）Context 標頭格式污染導致 AI 排除多筆圖片來源引用，且前端相似度／Token 統計皆為失真數值

### 問題描述
使用者在 RAG 測試頁提問「說明GP51建立備份營運中心.docx包含圖片」，發現：
- 前端「參考圖片引用 (Image Chunks)」列表成功顯示 7 筆圖片區塊（`#3~5`、`#6~10`、`#11`、`#12~14`、`#15`、`#16~20`、`#21~24`）。
- 但 AI 回覆的結論中，僅引用並總結了其中 1 筆（`#3~5`），其餘 6 筆圖片描述完全沒有出現在回答文字中（雖然仍正常顯示在畫面下方的來源清單）。
- 另外前端列表中這 7 筆圖片的 `Similarity` 全部顯示相同的 `1.50`，「總計 Token」也明顯偏低（僅 1,079）。

本問題先由 Claude 與 Gemini 分別進行根因排查並交叉比對，取交集中證據最充分、且已對照實際程式碼行號驗證屬實的三項根因，記錄如下，待使用者確認後再進行實作。

### 根本原因

**1.（主因，已核對程式碼確認）Context 標頭格式污染，導致 LLM 為遵守嚴格引用規則而排除格式不乾淨的來源**

`backend/routers/rag.py` 組裝 `context_parts` 時，把附加說明直接寫進「段落編號」欄位本體：
- `rag.py:473-476`（周邊文字區塊）：`f"【來源文件：{filename} | 段落編號：{parent_idx_str}（周邊文字）】"`
- `rag.py:488-491`（圖片描述區塊）：`f"【來源文件：{filename} | 段落編號：{img_chunk_idx_str}（圖片描述）】"`

但 system prompt（`rag.py:615-617`）明確要求引用格式必須是乾淨的 `#段落編號`（例如「依據 [文件名] 段落: #6~10 做出以下結論」）。當某筆來源的段落編號被寫成 `#6~10（圖片描述）` 時，不符合這個乾淨格式規範；LLM 為了遵守「只能引用參考資料、不可編造內容」的嚴格規則，傾向直接不引用/不使用這些格式不乾淨的來源，只保留格式乾淨的核心命中結果（`#3~5`，無後綴），這解釋了為何只有一筆圖片被總結、其餘 6 筆（皆帶有 `（圖片描述）` 後綴）被完全忽略。

**2.（已核對程式碼確認）前端「同段落圖片」的 Similarity 分數是偽造的**

`frontend/src/components/chat/SourceChunks.vue:22-60` 的 `imageSources` 在組「同段落圖片」（`nestedImages`）時，直接沿用帶出這些圖片的宿主來源的 `score`：
```js
nestedImages.push({ ..., score: s.score, ... })
```
但這些圖片其實是透過 `parent_id` 撈出的「同段落兄弟節點」（`get_image_siblings`/`get_siblings_and_merge`，`backend/services/qdrant_service.py:1409-1479`），本身是用 Qdrant `scroll` 取得、完全沒有相似度分數，前端卻讓全部 7 筆圖片顯示同一個繼承來的分數（`1.50`），讓使用者誤以為 7 張圖片都被向量檢索獨立、高度命中，但實際上只有 1 張是查詢真正命中的。

**3.（已核對程式碼確認）Token 統計低估，未涵蓋攤平塞入 Context 的周邊文字與圖片描述**

- 前端 `SourceChunks.vue:42` 的 `nestedImages` 項目把 `token_count` 硬編碼為 `0`。
- 後端 `rag.py:544`：`context_summary["total_tokens"] = sum(s.get("token_count", 0) for s in sources) + att_tokens` 只加總 `sources` 陣列（本次為 3 筆文字來源）自身的 token 數，完全沒有計入 `rag.py:473-476`／`rag.py:488-491` 額外攤平進 `context_parts` 的「周邊文字」與 7 張圖片描述的 token 數。畫面顯示的「總計 Token: 1,079」是低估值，實際送進 LLM 的 context 更大，也可能影響「是否超過分批摘要門檻（50,000）」判斷的準確性。

### 解決方案
1. **淨化 Context 標頭（對應主因）**：`rag.py` 的周邊文字／圖片描述區塊，「段落編號」欄位改回純數字/純區間格式（例如 `段落編號：#6~10`，不再附加後綴），附加說明改成內容區塊的類型前綴（`內容：[周邊文字] ...`／`內容：[圖片描述] ...`），符合 system prompt 要求的 `#段落編號` 乾淨引用格式。
2. **Token 統計精確化**：新增 `extra_context_tokens` 累加變數，在組裝周邊文字／圖片描述 context 片段時同步累加其 token 數，`context_summary["total_tokens"]` 計算時一併納入（`sum(...) + att_tokens + extra_context_tokens`）；`sources[].metadata.image_chunks` 內每筆也補上真實 `token_count`（`count_tokens(ic["content"])`），不再是前端寫死的 `0`。
3. **前端相似度顯示修正**：`SourceChunks.vue` 的 `nestedImages` 不再沿用宿主 source 的 `score`，改標記 `isSibling: true`；樣板依此條件顯示灰色「同段落」標籤取代假造的 `Similarity` 數字（真正被向量檢索命中的圖片——`directImages`——仍正常顯示真實分數），`token_count` 改用後端補上的真實值。

### 修改檔案
- `backend/routers/rag.py`
- `frontend/src/components/chat/SourceChunks.vue`

### 驗證
- **程式碼語法**：使用 `python -c "import ast; ast.parse(...)"` 驗證 `rag.py` 語法正確。
- **前端編譯**：使用 `npm run build` 驗證 Vite 專案編譯正常。
- **待使用者實機驗證**：重新提問「說明GP51建立備份營運中心.docx包含圖片」，確認 AI 回覆會引用全部（或明顯更多筆）圖片段落而非只有 1 筆；確認「同段落圖片」改顯示「同段落」標籤而非假造的 `Similarity: 1.50`；確認「總計 Token」數值提高（反映實際攤平進 context 的周邊文字與圖片描述）。

## 2026-07-08 修正 RAG 檢索段落去重飢餓、圖片 Chunk 命中遺失周邊文字、以及圖片索引號顯示 #? 錯誤

### 問題描述
使用者在進行 RAG 測試提問「跟我說明 GP51 建立備份營運中心.docx 文件與圖片」時，發現以下問題：
1. **去重飢餓與段落遺失**：AI 只總結了 1 筆包含圖片的段落，其他純文字段落（段落 0, 1, 2）完全沒有被加入總結中。
2. **段落索引顯示錯誤**：前端的引用來源區中，圖片對應的段落編號顯示為 `#?`。

**根本原因**：
1. **去重飢餓**：`qdrant_service.py` 相似度檢索在 Qdrant 查詢時直接使用 `limit=top_k`（如 5）。當檢索出的 top_k 點位均為同一段落（`parent_id` 相同）下的不同圖片區塊時，經依 `parent_id` 去重後僅剩 1 筆結果，造成嚴重的結果飢餓（Starvation），其他段落無法被召回。
2. **圖片命中時遺失周邊文字**：當圖片 Chunk 自己是 top hit 時，其內容維持為圖片描述。但此時去重邏輯完全丟棄了該 `parent_id` 對應的 `parent_content`（純文字段落），導致 AI 只看得到該圖片描述，卻看不到旁邊的純文字段落內容。
3. **圖片索引 `#?`**：前端 `SourceChunks.vue` 在攤平收集 `image_chunks` 兄弟節點時，未將 metadata 中的 `chunk_index` 複製過去，導致前端 template 因讀不到 `chunk_index` 而 fallback 顯示為 `?`。
4. **缺少 RAG 檔名過濾**：語義解析轉出的 `source_file` 資訊未被透傳給 Qdrant 檢索，導致檢索範圍未限定在使用者指定的單一檔案。

### 解決方案
1. **擴大查詢召回**：在 `qdrant_service.py` 的 `search_similar()` 中，若啟用 parent 融合去重（`disable_parent_merge=False`），則 Qdrant 查詢的 limit 擴大至 `max(top_k * 4, 20)`，在完成 `parent_id` 去重後再 slice 限制回 `top_k`，確保召回數量足夠且不飢餓。
2. **保留並併入周邊文字**：在 `qdrant_service.py` 的 `search_similar()` 中，當 `is_image_chunk` 為真時，額外將 `parent_content` 儲存於 `item["metadata"]["parent_content"]` 中。並在 `rag.py` 組合 `context_parts` 時，若命中圖片 Chunk 且存在 `parent_content`，則將其以「`【來源文件：... | 段落編號：#X（周邊文字）】`」的格式作為獨立 context 區塊塞入，確保 AI 能同時接收圖片描述與相鄰純文字。
3. **修復前端欄位對齊**：修改 `SourceChunks.vue` 的 `nestedImages` 收集 mapping 邏輯，補上 `chunk_index: img.metadata?.chunk_index`。
4. **套用檔名過濾**：在 `rag.py` 的語義混合檢索分支中，從 `semantic_json` 中提取 `source_file` 並作為 `filter_filename` 參數傳遞給 `search_similar_two_step`。

### 修改檔案
- `backend/services/qdrant_service.py`
- `backend/routers/rag.py`
- `frontend/src/components/chat/SourceChunks.vue`

### 驗證
- **程式碼編譯與語法**：使用 `py_compile` 驗證 Python 檔案語法正確。
- **前端編譯**：使用 `npm run build` 驗證 Vite 專案編譯正常。

## 2026-07-08 修正圖片描述重複偵測因全局長技術詞統計而導致的誤判（False Positive）失敗問題

### 問題描述
使用者上傳包含 `Createdb dbname 4 ---> 建立一個指定來源的資料庫(非DS資料庫 )` 上下文段落之 Word 文件時，多張圖片在解析描述階段（`describe_image`）頻繁觸發「`Detected repeated reasoning loop while describing image, aborting early``」警告，導致圖片描述大量顯示為「描述失敗」或「描述可能被截斷」狀態。

**根本原因**：既有的 `_is_repeating_tail` 重複偵測邏輯為「取累積文字的最後 25 個字（`tail`），若其在整個已累積字串中的出現次數 >= 4 次即視為迴圈」。這在技術型圖片描述中極易誤判：模型在長推理/描述過程中，正常地多次提及上下文提示或長技術名詞（如上述長達 45 字的詞），使得最後結尾包含該名詞時，整個段落中的計數直接達到 4 次，進而觸發誤判（非真正無限迴圈）。

### 解決方案
將 `backend/services/llm_service.py` 中的 `_is_repeating_tail` 升級為**連續週期性重複（Consecutive Loop）**演算法：
1. **連續性重複判定**：只有在最近的尾端區域中（視窗大小限制為 `ngram_size * (trigger_count + 1)`，預設 125 字），該長度為 P（3 <= P <= 250）的區塊連續重覆出現達 `trigger_count` 次時，才判定為無限迴圈。
2. **Alphanumeric 字元過濾保護**：為避免 Markdown 排版（如寬表格分隔線 `|---|---|---|`）、純空格、換行或標點符號的連續出現被誤判為內容迴圈，過濾要求重複區塊中必須包含至少一個字母或數字（`any(c.isalnum() for c in suffix)`）。
3. **完全向前相容**：維持原本的 `ngram_size` 與 `trigger_count` 參數介面不變，RAG 路由及其他呼叫端無須進行任何調整。

### 修改檔案
- `backend/services/llm_service.py`

### 驗證
使用獨立測試腳本進行多情境模擬驗證：
- **正常技術描述（分散提及同一關鍵字 4 次）** -> 正常通過（不誤判）
- **寬 Markdown 表格排版分隔符號** -> 正常通過（不誤判）
- **真實的連續重複迴圈** -> 精準中斷（觸發攔截）

## 2026-07-07 修正圖片描述因固定 60 秒逾時而失敗、且錯誤訊息空白無法診斷的問題（9.11）

### 問題描述（詳見 `docs/DevelopmentProcess/DocumentImageEmbeddingPlan.md` 第 9 節 9.11）
使用者實測上傳含密集文字/表格截圖的 Word 文件，圖片描述產生失敗（畫面顯示「描述失敗」徽章），Docker 後端日誌三行錯誤訊息冒號後**完全是空字串**，無法判斷真正原因；但同一張圖片使用者確認在 OpenWebUI 可正常讀取，代表模型本身具備視覺能力。

**根本原因**：`backend/services/llm_service.py` 的 `chat_completion()` 固定使用 `httpx.AsyncClient(timeout=60.0)`，`describe_image()` 也共用這 60 秒上限；但 9.8 修正時已把 `max_tokens` 大幅提高（目前 8192），對文字/表格密集的圖片，自架 vLLM 生成完整描述很容易超過 60 秒，導致 httpx 提早判定逾時中斷連線。Python 的逾時類例外（`httpx.ReadTimeout`／`asyncio.TimeoutError`）字串化通常是空字串，原本的 `logger.error(f"...: {e}")` 因此印不出任何有意義的診斷資訊。

### 解決方案
1. `chat_completion()` 新增可選參數 `timeout: float = 60.0`，改用 `httpx.AsyncClient(timeout=timeout)`；既有呼叫端不傳入此參數則行為不變（仍是 60 秒）。
2. `describe_image()` 呼叫時改傳入 `timeout=300.0`（5 分鐘），讓內容複雜的圖片有足夠時間完整生成描述。
3. `chat_completion()`、`describe_image()`、`routers/embedding.py` 三處的例外 log 訊息改成 `f"...: {type(e).__name__}: {e!r}"`，即使 `str(e)` 是空字串也一定會印出例外類別名稱與 `repr()`，未來能直接從 log 判斷是逾時、連線失敗還是其他原因。

### 修改檔案
- `backend/services/llm_service.py`
- `backend/routers/embedding.py`
- `docs/DevelopmentProcess/DocumentImageEmbeddingPlan.md`（記錄複查發現與修正結果）

### 驗證
- 已用 `python -c "import ast; ast.parse(...)"` 驗證語法正確。
- 需使用者重新上傳同一份含密集文字/表格截圖的文件，確認描述能在 5 分鐘內完整產生；若仍逾時，Docker log 應能明確看到 `ReadTimeout`/`ConnectTimeout` 等具體例外類別名稱，而非空白訊息。

## 2026-07-07 修正圖片功能剩餘中低風險問題（9.3-9.9），並發現修正 get_by_parent_id 遺漏 chunk_type 投影的高風險問題（9.10）

### 問題描述（詳見 `docs/DevelopmentProcess/DocumentImageEmbeddingPlan.md` 第 9 節 9.3-9.10）
延續同日稍早修正的三項高風險問題，本次處理第 9 節剩餘的中低風險項目，並在修正 9.6 效能項目時，複查 `get_by_parent_id()` 發現一項先前未被列入清單、但影響更根本的高風險問題：
1. **【中】對話畫面圖片來源重複顯示兩次**：`SourceChunks.vue` 與 `MessageBubble.vue` 各自獨立渲染同一組圖片來源。
2. **【中】DOCX 表格儲存格內的圖片不會被擷取**：`extract_images_from_docx()` 只處理段落、未處理 `Table` 項目。
3. **【中】結構化 Prompt 強化模式下，圖片描述預覽多出樣板文字**：`get_siblings_and_merge()` 收集 `image_chunks` 時未清洗 `[主要內容]` 樣板前綴。
4. **【低】每筆帶 `parent_id` 的結果都多一次 Qdrant 查詢**：快取分支仍會重新執行完整合併運算才能取得 `image_chunks`。
5. **【低】圖片 `<img>` 的 fallback 網址一定會 401**：多處元件的 fallback 寫法在 blob 載入失敗時退回一個必定失敗的網址。
6. **【中，使用者提出】上傳解析圖片時前端沒有等待動畫**：`FileUploader.vue` 只有靜態文字、無 spinner，容易誤以為卡住。
7. **【高，複查發現】`get_by_parent_id()` 缺少 `chunk_type`／`image_filename` 欄位投影**：導致 `get_siblings_and_merge()` 的文字/圖片兄弟節點分離邏輯（9.1、9.5 的核心機制）實際上完全沒有作用——圖片兄弟節點仍會被誤判為文字、繼續混入合併結果，「同段落圖片」（`image_chunks`）也永遠是空陣列。此問題比同日稍早修正的三項高風險問題更根本，直接讓 9.1/9.5 的修正失去實際效果。

### 解決方案
1. `SourceChunks.vue` 移除圖片渲染邏輯，圖片統一由 `MessageBubble.vue` 的「相關參考圖片」畫廊呈現。
2. `document_parser.py` 的 `extract_images_from_docx()` 重構出共用的 rid 擷取／圖片收集函式，新增對 `docx.table.Table` 的走訪。
3. `qdrant_service.py` 的 `clean_and_extract_content` 提升為共用靜態方法 `_strip_structured_content_prefix()`，`get_siblings_and_merge()` 收集 `image_chunks` 時一併套用。
4. 新增輕量方法 `QdrantService.get_image_siblings()`，快取分支改用它取代完整的 `get_siblings_and_merge()`，省下不必要的合併運算（Qdrant 查詢次數因架構限制無法完全避免，已於文件中如實記錄）。
5. `FileUploader.vue`、`SingleIndexingTab.vue`、`MessageBubble.vue`、`VectorManagementTab.vue`、`ChunkPreview.vue` 的圖片 `<img>` 改為三態渲染（載入中 spinner／載入失敗佔位圖／成功顯示），移除會 401 的 fallback 網址；`FileUploader.vue` 另外加上上傳中 spinner 與依 `extractImages` 顯示不同提示文字。
6. `qdrant_service.py` 的 `get_by_parent_id()` 補上 `chunk_type`／`image_filename` 兩個欄位投影。

### 修改檔案
- `backend/services/qdrant_service.py`
- `backend/services/document_parser.py`
- `frontend/src/components/chat/SourceChunks.vue`
- `frontend/src/components/chat/MessageBubble.vue`
- `frontend/src/components/embedding/ChunkPreview.vue`
- `frontend/src/components/embedding/SingleIndexingTab.vue`
- `frontend/src/components/embedding/VectorManagementTab.vue`
- `frontend/src/components/embedding/FileUploader.vue`
- `docs/DevelopmentProcess/DocumentImageEmbeddingPlan.md`（記錄複查發現與修正結果）

### 驗證
- 已用 `python -c "import ast; ast.parse(...)"` 驗證所有修改過的 Python 檔案語法正確。
- 已用 `npm run build` 驗證所有修改過的 Vue 元件編譯正常，無樣板錯誤。
- 圖片功能的端到端驗證（重新上傳含圖片文件、檢查 Qdrant payload、RAG 對話命中測試）仍需使用者手動測試，依專案慣例不由 AI 開瀏覽器驗證。

## 2026-07-07 程式碼複查後修正圖片 Chunk 內容被覆蓋、圖片描述被截斷、開發文件與程式碼不符三項高風險問題

### 問題描述（詳見 `docs/DevelopmentProcess/DocumentImageEmbeddingPlan.md` 第 9 節）
1. **【高】圖片 Chunk 命中時內容被覆蓋**：`qdrant_service.py` 的 `search_similar()`／`search_similar_two_step()` 對每一筆帶 `parent_id` 的檢索結果一律用 `get_siblings_and_merge()` 回傳的「同段落純文字合併結果」覆蓋 `item["content"]`；但該函式已將圖片兄弟節點排除在合併結果之外。當圖片 Chunk 自己就是最相關的命中結果時（Word 文件內嵌圖片必然帶 `parent_id`），其自身的圖片描述會被換成旁邊的純文字段落，導致 AI 看不到圖片描述本身，直接打破「問架構圖能被說明」的核心驗收情境。
2. **【高，使用者實測發現】圖片描述常在複雜表格/BOM 圖片上被硬性截斷**：`llm_service.py` 的 `describe_image()` 呼叫 vLLM 時 `max_tokens=512`，表格/BOM 類圖片逐行描述很容易在還沒描述完就被強制中斷；且 `chat_completion()` 從未讀取 `finish_reason`，截斷的半截描述會被當成正常結果直接寫入 Qdrant，使用者與系統都無法察覺內容不完整，須事後人工檢查 Qdrant payload 才能發現（見使用者提供的截圖：BOM 表格描述在「第3行」戛然而止）。
3. **【高】開發紀錄與 DB Schema 文件內容與實際程式碼不符**：`NewFeatures.md`／`04_DB_SCHEMA.md` 誤寫成使用「地端多模態 AI (MiniCPM-V)」與 `EXTRACTED_IMAGES_DIR`/`ExtractedImages/` 目錄，但實際程式碼是呼叫 vLLM 主模型 `Qwen3.6-35B-A3B-FP8`，圖片存於 `FILE_ATTACHMENTS_DIR` + `FILE_ATTACHMENTS_IMAGE_SUBDIR`（`backend/FileAttachments/image/`），全專案 grep 不到前者字樣。

### 解決方案
1. `backend/services/qdrant_service.py`：`search_similar()`（461-508 行）與 `search_similar_two_step()` 鄰居合併段落新增 `is_image_chunk` 判斷，圖片 Chunk 命中時不再用 `parent_content` 覆蓋自己的 `content`；同時排除圖片自己出現在自己的 `image_chunks` 清單中。
2. `backend/services/llm_service.py`：`chat_completion()` 新增可選參數 `return_finish_reason`（預設 `False`，不影響既有 7 處呼叫端）；`describe_image()` 的 `max_tokens` 由 512 提高到 2048，並依 `finish_reason == "length"` 判斷截斷、回傳 `(description, truncated)` tuple，截斷時記錄 warning log。`backend/schemas/embedding.py` 的 `ExtractedImageItem` 新增 `caption_truncated` 欄位，`backend/routers/embedding.py` 同步更新呼叫端；`frontend/src/components/embedding/SingleIndexingTab.vue` 新增橘色「描述可能被截斷」徽章。
3. 更正 `docs/DevelopmentProcess/NewFeatures.md`（2026-07-07 條目）與 `docs/04_DB_SCHEMA.md` 的 `image_filename` 欄位說明，改為實際使用的模型與目錄設定。

### 修改檔案
- `backend/services/qdrant_service.py`
- `backend/services/llm_service.py`
- `backend/schemas/embedding.py`
- `backend/routers/embedding.py`
- `frontend/src/components/embedding/SingleIndexingTab.vue`
- `docs/DevelopmentProcess/NewFeatures.md`
- `docs/04_DB_SCHEMA.md`
- `docs/DevelopmentProcess/DocumentImageEmbeddingPlan.md`（記錄複查發現與修正結果）

### 尚待處理
第 9 節中低風險項目（9.3 對話畫面圖片重複顯示、9.4 DOCX 表格內圖片未擷取、9.5 結構化模式下圖片描述含樣板文字、9.6 多餘 Qdrant 查詢、9.7 `<img>` fallback 必定 401）尚未修正，留待後續處理。

## 2026-07-07 修正 RAG 檢索同 parent_id 合併時圖片 Chunk 被混入文字與切分截斷問題、以及向量管理與切分預覽無法顯示圖片 bug

### 問題描述
1. **圖片 Chunk 與文字合併衝突**：在 parent-child 檢索召回多個兄弟節點並進行合併還原（`get_siblings_and_merge`）時，若召回的兄弟節點中包含圖片 Chunk（`chunk_type == "image"`，其 content 為圖片的 AI 語意描述），這些圖片內容會被當作一般文字兄弟節點一起送入去重合併與 range 截斷中。這導致圖片的語意描述被硬塞進檢索文字段落中，破壞了原本文件的純文字結構，並造成了「圖片描述文字截斷/排版錯亂」的現象；同時，這也使得前端無法以結構化的方式取得這些伴隨被召回的圖片，导致對話中只會顯示 0-1 張圖片。
2. **向量管理與切分預覽無圖片**：
   - 「自訂資料向量化.已向量化資料管理與刪除」頁面（`VectorManagementTab.vue`）中，雖然有針對 `chunk_type === 'image'` 顯示圖片的 UI 設計，但未在資料載入後呼叫 `loadChunkImage()` 方法以透過 Blob 載入授權圖片，導致圖片區塊全部呈現空白。
   - 「自訂資料向量化.資料切分與向量化寫入」的 Chunk 預覽組件（`ChunkPreview.vue`）中，未設計圖片 Chunk 的特殊預覽邏輯，僅以 text 欄位顯示描述，使得使用者切分完成後無法預覽擷取到的圖片。

### 解決方案
1. **分離兄弟節點中的圖片 Chunk**：
   - 修改 `backend/services/qdrant_service.py` 中的 `get_siblings_and_merge`：在撈取所有兄弟節點後，根據 `chunk_type == "image"` 將其分離為 `text_siblings` 與 `image_siblings`。
   - 僅對 `text_siblings` 進行去重合併，確保產出的段落文字純淨無污染。
   - 將 `image_siblings` 中的圖片資訊（`chunk_id`, `content`, `metadata` 如 `image_filename`, `page`, `filename`）打包成 `image_chunks` 列表，與合併後的 `display_content` 一起以 tuple 形式回傳。
   - 在 `search_similar` 與 `search_similar_two_step` 中捕捉 `image_chunks`，並將其注入至最終檢索點位的 metadata 字典的 `"image_chunks"` 欄位中。
2. **擴充 Schema 與 RAG 路由對應**：
   - 在 `backend/schemas/retrieval.py` 的 `RetrievalMetadata` schema 中新增 `image_chunks: Optional[List[Dict[str, Any]]] = Field(default_factory=list)`。
   - 在 `backend/routers/retrieval.py` 的各查詢路由，以及 `backend/routers/rag.py` 的 RAG `/chat/completions` 路由中，將 metadata 中的 `image_chunks` 正確透傳至對應的 response schemas 與 sources payload 中。
3. **前端 RAG 與引用組件升級**：
   - 修改 `frontend/src/components/chat/SourceChunks.vue` 與 `MessageBubble.vue`：擴充其 `imageSources` 計算屬性，除了過濾出 `sources` 中直接為 `chunk_type === 'image'` 的項目，更進一步從文字 sources 的 `metadata.image_chunks` 中拉取所有巢狀圖片點位，並依 `image_filename` 進行去重。這使得與同一段落關聯的所有圖片引用與對話卡片均能完美完整地呈現。
4. **前端向量管理與切分預覽圖片預覽修正**：
   - 修改 `VectorManagementTab.vue`：在 `loadManagementPoints` 成功載入點位後，走訪結果並對所有圖片點位呼叫 `loadChunkImage()` 載入其 Blob URL。
   - 修改 `ChunkPreview.vue`：導入 `imageService`，為 `chunk.metadata?.chunk_type === 'image'` 的 Chunk 增加專屬的圖片畫廊與 AI 描述呈現區塊，實現切分完成後的即時圖片預覽。

### 修改檔案
- `backend/schemas/retrieval.py`
- `backend/services/qdrant_service.py`
- `backend/routers/retrieval.py`
- `backend/routers/rag.py`
- `frontend/src/components/chat/SourceChunks.vue`
- `frontend/src/components/chat/MessageBubble.vue`
- `frontend/src/components/embedding/VectorManagementTab.vue`
- `frontend/src/components/embedding/ChunkPreview.vue`

## 2026-07-03 修正語義資料庫查詢法 SQL 產生時欄位名稱幻覺（跨表格套用 Few-Shot 範例欄位名）導致執行失敗問題

### 問題描述
查詢「查詢EFGP附件」（對應 `attachments` 表，實際欄位為 `title`/`description`/`created_by_name` 等，沒有 `content` 欄位）時，AI 產生的 SQL 為
`SELECT TOP 50 title, content, created_by_name FROM attachments WHERE title LIKE '%EFGP%' OR content LIKE '%EFGP%'`，
執行時資料庫回傳 `Invalid column name 'content'`，導致整段查詢失敗。
根本原因：`_generate_sql()` 的 Few-Shot 範例中，範例 2（articles 表）使用了 `content` 這個欄位名稱示範「排除資料類型詞」的寫法；由於範例緊接在規則說明之後，且沒有明確區隔「範例中的欄位名稱僅為示意」，模型在產生 `attachments` 表的 SQL 時把範例 2 的 `content` 欄位名稱直接套用過來，而非嚴格依照當次【資料表定義】列出的實際欄位（`description`）。

### 解決方案
1. **強化防幻想規則**（`backend/services/ai_db_query_service.py` `_generate_sql()`）：規則 2 明確加註「下方 Few-Shot 範例中出現的表格名稱與欄位名稱（如 attachments、articles、title、description、content）僅為示範 SQL 句型結構之用，與本次實際要查詢的表格/欄位完全無關，絕對不可以把範例中的欄位名稱直接套用到本次查詢」；範例改寫為「假設表格定義為 xxx(...)」的明確標註方式，並在【資料表定義】標題加註「本次實際查詢，只能用這裡列出的欄位」以加強對比。
2. **新增執行失敗自動修正重試**：`_generate_sql()` 新增 `retry_error`/`previous_sql` 參數，若提供則在 Prompt 中回饋「上一次 SQL 執行失敗的錯誤訊息」要求模型重新檢查【資料表定義】並修正；`execute()` 的 SQL 產生 → 驗證 → 執行流程改為最多嘗試 2 次的迴圈：第一次執行失敗（例如欄位不存在）就把資料庫實際回傳的錯誤訊息回饋給 AI 重新產生一次 SQL，仍失敗才正式拋出 `AIDBQueryError`（不做超過一次的無限重試）。

### 修改檔案
- `backend/services/ai_db_query_service.py`

## 2026-07-03 修正語義資料庫查詢法在等待語義分析/查詢期間，前端步驟列表完全沒有執行中動畫的問題

### 問題描述
使用者提問後，畫面上四個步驟（語義分析、向量資料查詢、思考中、結論）在等待期間全部顯示為灰色空心圓（pending），沒有任何轉動動畫或「執行中」提示，直到答案整個生成完才一次跳出所有步驟內容，體驗上像是卡住沒有反應，且與既有語義混合查詢法「逐步顯示執行中」的體驗不一致。
根本原因：`backend/routers/rag.py` 的 `_run_semantic_db_query()` 原本是一般 coroutine，內部用 `events.append(...)` 把所有 SSE 事件字串收集進一個 list，等**整個函式跑完**（包含呼叫 Instruct AI 選設定檔、產生 SQL、實際執行查詢等可能耗時數秒的步驟）才一次 `return events, ...`；呼叫端 `rag_chat_stream()` 也是 `await` 完整個函式後才用 `for evt in db_query_events: yield evt` 把事件一次性全部吐出。也就是說在函式執行期間，FastAPI 的 StreamingResponse 完全沒有送出任何資料給瀏覽器，SSE 串流事實上被這段邏輯「悶住」了，這與其餘 `vector`/`hybrid`/`semantic_hybrid*` 查詢法在 `rag_chat_stream()` 主體中一路用 `yield` 即時吐出事件的寫法不同。

### 解決方案
把 `_run_semantic_db_query()` 改寫成真正的 async generator（原本包在裡面的巢狀函式 `_run_execute()` 也一併改為 async generator），每個階段完成就立即 `yield` 對應的 SSE 事件字串，讓「語義分析：執行中」等事件能在呼叫 Instruct AI 之前就先送達前端、顯示轉動動畫。由於 async generator 不能用帶值的 `return` 回傳資料，`context_str`/`sources`/`should_stop` 改用呼叫端傳入的可變 `result: dict` 参數回傳，`rag_chat_stream()` 呼叫處改為：
```python
db_query_result = {}
async for evt in _run_semantic_db_query(request, question, db_query_result):
    yield evt
context_str = db_query_result.get("context_str", "")
sources = db_query_result.get("sources", [])
if db_query_result.get("should_stop", True):
    return
```

### 修改檔案
- `backend/routers/rag.py`

## 2026-07-03 修正 RAG 對話步驟列表下方多餘顯示「已完成思考」重複區塊的問題

### 問題描述
在 `frontend/src/components/chat/MessageBubble.vue` 新增「語義資料庫查詢法：候選查詢設定檔選取」區塊時，該區塊使用 `v-if`（因為需要與上方的 `message.steps` 結構化步驟列表**同時顯示**，而非取代它），但緊接在它後面的「Thinking Process Accordion (Fallback)」區塊卻寫成 `v-else-if`，導致該 `v-else-if` 被鏈接到候選選取區塊的 `v-if`，而非鏈接到最上方 `message.steps` 的 `v-if`。
結果：只要沒有在等待候選選取（絕大多數情況），候選選取區塊的條件為假，緊接的 `v-else-if` 就會成立，於是「已完成思考」這個獨立的思考過程收合區塊，會跟語義混合/語義混合回饋/語義資料庫查詢法三種本來就有結構化步驟列表（含「思考中」步驟）的訊息**重複顯示**，而這個區塊原本設計上只該在**沒有**結構化步驟列表時（即單純 `vector`/`hybrid` 查詢法）作為備援顯示。

### 解決方案
修改 `frontend/src/components/chat/MessageBubble.vue`：把該區塊的條件從 `v-else-if="message.thinking || message.isThinking"` 改為獨立判斷 `v-if="!(message.steps && message.steps.length > 0) && (message.thinking || message.isThinking)"`，明確只在訊息沒有結構化步驟列表時才顯示，不再受候選選取區塊顯示與否影響。

### 修改檔案
- `frontend/src/components/chat/MessageBubble.vue`

## 2026-07-03 修正語義資料庫查詢法多設定檔執行時步驟顯示被覆蓋、以及資料類型詞污染 SQL 關鍵字問題

### 問題描述
實測「不限定知識庫」多設定檔合併查詢（問題：「EFGP有附件跟文章嗎?」，AI 正確選出附件+文章兩個設定檔）後回報兩個問題：
1. **步驟顯示只剩一筆 SQL**：後端有依序執行兩個設定檔並各自送出 `vector_search` step 事件，但前端 `chatStore.js` 對同 key 的 step 事件是「覆蓋」而非累加——第二個設定檔（articles）的 success 事件把第一個（attachments）的內容整個蓋掉，畫面上只看得到最後一筆 SQL，且與最終結論對不起來。
2. **SQL 關鍵字被資料類型詞污染**：產生的 SQL 為 `WHERE title LIKE '%EFGP%' OR content LIKE '%附件%' OR content LIKE '%文章%'...`。「附件」「文章」是資料類型詞，其作用已在「選擇設定檔」階段用完（因此才選出兩張表），不該再當成內容關鍵字；結果 articles 表撈到的 2 筆只是內文剛好含有「附件/文章」字樣的無關資料，造成畫面顯示「查得 2 筆」但主模型結論說「文章沒查到（EFGP 相關）資料」的表面矛盾。

### 解決方案
1. **步驟內容改為累積式彙整**（`backend/routers/rag.py`）：`_run_semantic_db_query()` 新增 `executed_blocks` 清單，`_run_execute()` 每次執行完把該設定檔的明細（SQL + 筆數 + 耗時）加入清單，success 事件一律帶「到目前為止所有已執行設定檔」的完整彙整（多設定檔時每段以【設定檔 i/N：名稱】標頭區隔）；running 事件也會帶已完成的區塊，確保執行過程中先前結果不消失。前端零修改。
2. **SQL 產生 Prompt 新增「排除資料類型詞」規則**（`backend/services/ai_db_query_service.py` `_generate_sql()`）：模糊查詢規則新增 5.e——問題中僅描述資料類型/表格本身的詞（附件、文章、文件、資料、紀錄等，尤其與本表格名稱/用途相同的詞）不可當 LIKE 關鍵字，只保留真正的內容實體關鍵字；並新增以「EFGP有附件跟文章嗎?」為題的好/壞 Few-Shot 對照範例。
3. **查詢結果標頭強化**（`backend/services/ai_db_query_service.py` `_rows_to_text()`）：標頭改為「以下是設定檔『XXX』對資料表『YYY』（用途）的查詢結果」，並在查無資料時明確寫出「（此表格查無符合資料）」，讓主模型在多設定檔合併時能分別陳述各表格的結果、不會混淆。

### 修改檔案
- `backend/routers/rag.py`
- `backend/services/ai_db_query_service.py`

## 2026-07-03 修正語義資料庫查詢法 SQL 產生命中率過低、以及「查到資料卻仍回答無資料」問題

### 問題描述
實測回報兩個問題：
1. AI 產生的 SQL 常用 `=` 完全比對加上多重 `AND` 條件（例如 `WHERE title = 'zz_file' AND description LIKE '%程式資料建立作業%'`），使用者的用詞（檔名片段、口語描述）與資料庫實際內容往往不完全一致，導致查詢結果為 0 筆；且 SELECT 常常只挑使用者字面上問到的單一欄位（例如只選 `created_by_name`），即使有命中，回傳的資料也缺乏足夠上下文（如標題）供後續摘要判斷相關性。
2. 承上，即使 SQL 有查到資料，主模型摘要時仍回答「知識庫沒有相關資訊。」。原因是摘要階段沿用了既有文件 RAG 的通用 System Prompt，該 Prompt 要求「必須在回答中標註引用了哪個文件段落」的段落引用格式規則，資料庫查詢結果並非文件段落、無法套用此格式，導致模型過度保守地判定「不符合可回答的參考資料格式」而拒答。

### 解決方案
1. 修改 `backend/services/ai_db_query_service.py` 的 `_generate_sql()` Prompt：
   - 新增「模糊查詢規則」：要求先從問題拆解出 2-5 個核心關鍵字，文字型欄位一律用 `LIKE '%關鍵字%'` 而非 `=`，多關鍵字/多欄位之間一律用 `OR` 串接（不要用 `AND` 疊加縮小範圍），僅數值/日期/布林等非文字型欄位才用 `=`。
   - 新增「SELECT 欄位規則」：除非欄位過多（>10），SELECT 應包含設定檔中所有啟用欄位，而非只挑使用者字面問到的單一欄位。
   - 新增好/壞對照的 Few-Shot 範例，具體示範模糊查詢 + OR + 完整欄位的正確寫法。
2. 修改 `backend/routers/rag.py`（`rag_chat_stream`）與 `backend/routers/evaluation.py`（`run_evaluation`）：當 `search_type == "semantic_db_query"` 時，改用專用的總結 System Prompt（強調「資料庫查詢結果」是真實資料、不需段落引用格式、只要有任一筆合理對應問題就該回答，僅在結果為空或明顯無關時才回覆無相關資訊），既有四種文件檢索查詢法的 System Prompt 完全不變。

### 修改檔案
- `backend/services/ai_db_query_service.py`
- `backend/routers/rag.py`
- `backend/routers/evaluation.py`

## 2026-07-03 修正語義資料庫查詢法的步驟序列顯示與缺乏語義分析 JSON 可視性問題

### 問題描述
使用者實測「語義資料庫查詢法」後回報兩個問題：
1. RAG 對話的步驟時間軸顯示錯亂：「語義分析」步驟一直卡在「執行中」，但「向量資料查詢」已顯示完成、「思考中」也已經在跑，看起來像是還沒等語義分析做完就直接跳去執行 SQL。根本原因是兩段式流程（先回傳候選清單、使用者選定後才重新請求執行 SQL）橫跨兩次獨立的 HTTP/SSE 請求，但 `_run_semantic_db_query()` 只在**第一次**請求中送出「語義分析：執行中」事件，從未送出對應的「成功」事件；前端 `msg.steps` 狀態是跨兩次請求持續保留的，因此第二次請求（執行 SQL）的事件進來時，語義分析欄位仍停留在「執行中」。
2. 顯示內容過於陽春（`正在語義理解問題並比對查詢設定檔...原始提問："..."`），且結果內容裡的換行是用 `\\n` 兩個字元（反斜線+n）而非真正換行，導致「已選定設定檔：...\n產生的 SQL：...」整段擠在同一行、字面上出現 `\n` 文字。使用者希望能像既有「語義混合查詢」一樣看到結構化 JSON，藉此驗證語義理解是否正確。

### 解決方案
1. 修改 `backend/routers/rag.py` 的 `_run_semantic_db_query()`：拆成清楚的「一步一步」事件序列——語義理解完整跑完並送出 `status: success`（含結構化 JSON：`original_question`/`embeddings_input`/`scope`）之後，才送出「向量資料查詢：執行中」→ 找到/找不到候選的最終狀態，避免時間軸上出現顯示先後不一致的情形。
2. 將 `search_details`/`vector_search_success_content` 等組字串一律改用真正的換行字元 `\n`（原本誤用雙反斜線 `\\n` 產生字面上的兩個字元），並將產生的 SQL 包成 \`\`\`sql 區塊，讓前端等寬字型 + `whitespace-pre-wrap` 能正確斷行呈現。

### 修改檔案
- `backend/routers/rag.py`

## 2026-07-03 修正語義資料庫查詢法新增程式碼中的 f-string 巢狀反斜線語法錯誤（Python 3.11 相容性）

### 問題描述
新增「語義資料庫查詢法」功能時，`backend/routers/rag.py` 的 `_run_semantic_db_query()` 內有一段巢狀 f-string：
```python
f"...{json.dumps({..., 'content': f'...\"{question}\"'}, ...)}\n\n"
```
外層 f-string 的 `{}` 表達式內，包在 `json.dumps(...)` 裡的巢狀 f-string 又帶有跳脫雙引號 `\"`。Python 3.12（PEP 701）之後允許 f-string 表達式內出現反斜線，但正式部署用的 Docker 映像是 **Python 3.11**，該版本禁止 f-string 的 `{}` 表達式內含反斜線字元，導致容器啟動 `uvicorn main:app` 時直接 `SyntaxError: f-string expression part cannot include a backslash`，服務完全無法啟動。
本機開發用的 `backend/.venv` 為 Python 3.14（放寬了此限制），加上原本用 `python -m py_compile` 驗證語法時同樣是用本機 3.14 環境，因此在開發階段未能發現此問題，直到用實際生產用的 Python 3.11 容器啟動時才炸開。

### 解決方案
將該段巢狀 f-string 拆開，先把帶有跳脫字元的內容組成獨立變數，再把該變數以純變數參照的方式放入外層 f-string 的 `{}` 中（外層 `{}` 內僅剩函式呼叫與變數名稱，不含任何反斜線字元），即可相容 Python 3.11：
```python
analysis_content = f'正在語義理解問題並比對查詢設定檔...原始提問："{question}"'
events.append(
    f"event: step\ndata: {json.dumps({'step': 'semantic_analysis', 'status': 'running', 'content': analysis_content}, ensure_ascii=False)}\n\n"
)
```
同時掃描本次新增/修改的所有後端檔案，確認沒有其餘同類型的巢狀反斜線 f-string。

### 修改檔案
- `backend/routers/rag.py`

## 2026-07-01 修正雙階段檢索 (Two-Step Search) 關聯檔案全量載入與 context 稀釋問題

### 問題描述
原本的雙階段檢索在第一階段召回核心點位後，第二階段針對其 `links_to` 指定的關聯檔案，是採用無條件的 Qdrant Scroll API 直接把關聯檔案的所有向量點位（高達 50 筆 Chunks）全部抓取出來。這會導致關聯檔案中的大量無關點位（如非對應資料庫列/非對應段落）全部被塞入 RAG 上下文中，造成嚴重的 Context 稀釋與 Token 浪費。

### 解決方案
1. **二次檢索由 Scroll 改為語意/混合搜尋**：
   - 修改 `backend/services/qdrant_service.py` 中的 `search_similar_two_step` 方法。
   - 當召回關聯檔案 (`all_links`) 後，不再使用無差別的 `client.scroll`。
   - 改為對 Qdrant 進行過濾搜尋（以 `filename` 或 `custom_id` 匹配 `all_links` 作為 `should` 條件），並使用與使用者問題相同的 `query_vector`、`query_text` 進行密集與稀疏 Hybrid 檢索（支援 exact keyword boost 加速）。
   - 在密集向量 Prefetch 中套用 `score_threshold=score_threshold`，確保只有與查詢內容高度相關的鄰居片段才會被召回，完全隔絕無關點位。
2. **調降預設鄰居召回上限**：
   - 將 `neighbor_limit` 參數的預設值由 `50` 調降至 `10`，以防止過多邻居片段稀釋主要檢索脈絡，提升 LLM 回答的精準度。
3. **單元測試相容**：
   - 無查詢向量時，系統會自動安全降級為 Scroll，以確保原有單元測試程式碼及無向量檢索場景的運作正常。

### 修改檔案
- `backend/services/qdrant_service.py`


## 2026-06-30 修正 Oracle Instant Client CPU 架構不符（x86_64 zip 安裝於 ARM64 Ubuntu）

### 問題描述
Ubuntu 生產伺服器架構為 **ARM64（aarch64）**，但 backend/目錄放置的是 x86_64 版本的 Instant Client zip：
`instantclient-basic-linux.x64-19.31.0.0.0dbru.zip`

Docker build 成功（mv、ldconfig 均正常），`libclntsh.so` 也存在於容器的 `/opt/oracle/lib/` 中，
但 Python `oracledb.init_oracle_client()` 嘗試 `dlopen` 時，動態連結器因架構不符（ELF class mismatch）
無法載入，表現為 `No such file or directory`，導致退回 Thin Mode。

診斷指令確認：
```
/usr/lib/aarch64-linux-gnu/libaio.so.1  ← 系統為 ARM64
```

### 解決方案
1. **下載 ARM64 版本的 Oracle Instant Client**：
   前往 https://www.oracle.com/database/technologies/instant-client/linux-arm-aarch64-downloads.html
   下載 `instantclient-basic-linux.arm64-19.*.zip`，替換舊的 x64 zip。
2. **更新 Dockerfile COPY 的 glob pattern**：
   由 `instantclient-basic-linux.x64-19.*.zip` 改為 `instantclient-basic-linux.*.zip`，
   讓同一個 Dockerfile 能兼容 x64 和 arm64 兩種版本的 zip 檔。
3. **重新 build**：`docker compose build backend --no-cache && docker compose up -d backend`

### 修改檔案
- `backend/Dockerfile`



### 問題描述
第二次部署後 Oracle 連線仍失敗，錯誤與上次相同：
`DPI-1047: Cannot locate a 64-bit Oracle Client library: "/opt/oracle/lib/libclntsh.so"`
雖然 COPY 步驟成功（zip 已放入 backend/ 目錄且 Docker build 未報錯），但容器啟動時 `/opt/oracle/lib` 仍不存在。
根本原因：Dockerfile 中使用 `ln -s "$IC_DIR" /opt/oracle/lib 2>/dev/null || true` 建立 symlink，由於後面的 `|| true` 使得 `ln -s` 的失敗（可能因為路徑已存在或其他原因）被完全靜默忽略，`/opt/oracle/lib` 從未真正建立。

### 解決方案
1. **Dockerfile 改用 `mv` 直接重命名**：
   - 移除 `ln -s` 邏輯，改用 `mv /opt/oracle/instantclient_19_* /opt/oracle/lib` 直接將解壓出的目錄重命名，確保 `/opt/oracle/lib/libclntsh.so` 路徑必定存在。
   - 新增環境變數 `ORACLE_CLIENT_LIB_DIR=/opt/oracle/lib`。
2. **Python 明確傳入 `lib_dir`**：
   - 修改 `backend/routers/database_indexing.py`，加入 `import os`，讀取 `ORACLE_CLIENT_LIB_DIR` 環境變數，若存在則以 `oracledb.init_oracle_client(lib_dir=lib_dir)` 明確指定路徑；本地 Windows 開發環境無此環境變數時仍走自動偵測。

### 修改檔案
- `backend/Dockerfile`
- `backend/routers/database_indexing.py`





### 問題描述
當啟用 Thick Mode 連線時，`oracledb` 在 Linux 底下讀取 `ORACLE_HOME` 時，預設會從該路徑下的 `lib/` 子目錄中尋找 `libclntsh.so`。然而在原先的 `Dockerfile` 中，Oracle Instant Client 解壓後直接移到了 `/opt/oracle/instantclient` 下，沒有建立 `lib/` 目錄，導致在連線時拋出以下錯誤：
`Cannot locate a 64-bit Oracle Client library: "/opt/oracle/instantclient/lib/libclntsh.so: cannot open shared object file: No such file or directory"`

### 解決方案
修改 `backend/Dockerfile`，重構 Instant Client 的目錄放置結構：
1. 將 `ORACLE_HOME` 指向 `/opt/oracle`，並將 Instant Client 檔案解壓移至 `/opt/oracle/lib` 目錄中，使其完全匹配標準 Oracle 的 `/lib` 子資料夾結構。
2. 將動態連結器配置 `/etc/ld.so.conf.d/oracle-instantclient.conf` 與環境變數 `LD_LIBRARY_PATH` 調整為 `/opt/oracle/lib`，確保系統與 `python-oracledb` 能正確抓取到 `libclntsh.so`。

### 修改檔案
- `backend/Dockerfile`


## 2026-06-30 修正 Oracle Instant Client CPU 架構不符（x86_64 zip 安裝於 ARM64 Ubuntu）

### 問題描述
Ubuntu 生產伺服器架構為 **ARM64（aarch64）**，但 backend/目錄放置的是 x86_64 版本的 Instant Client zip：
`instantclient-basic-linux.x64-19.31.0.0.0dbru.zip`

Docker build 成功（mv、ldconfig 均正常），`libclntsh.so` 也存在於容器的 `/opt/oracle/lib/` 中，
但 Python `oracledb.init_oracle_client()` 嘗試 `dlopen` 時，動態連結器因架構不符（ELF class mismatch）
無法載入，表現為 `No such file or directory`，導致退回 Thin Mode。

診斷指令確認：
```
/usr/lib/aarch64-linux-gnu/libaio.so.1  ← 系統為 ARM64
```

### 解決方案
1. **下載 ARM64 版本的 Oracle Instant Client**：
   前往 https://www.oracle.com/database/technologies/instant-client/linux-arm-aarch64-downloads.html
   下載 `instantclient-basic-linux.arm64-19.*.zip`，替換舊的 x64 zip。
2. **更新 Dockerfile COPY 的 glob pattern**：
   由 `instantclient-basic-linux.x64-19.*.zip` 改為 `instantclient-basic-linux.*.zip`，
   讓同一個 Dockerfile 能兼容 x64 和 arm64 兩種版本的 zip 檔。
3. **重新 build**：`docker compose build backend --no-cache && docker compose up -d backend`

### 修改檔案
- `backend/Dockerfile`



### 問題描述
第二次部署後 Oracle 連線仍失敗，錯誤與上次相同：
`DPI-1047: Cannot locate a 64-bit Oracle Client library: "/opt/oracle/lib/libclntsh.so"`
雖然 COPY 步驟成功（zip 已放入 backend/ 目錄且 Docker build 未報錯），但容器啟動時 `/opt/oracle/lib` 仍不存在。
根本原因：Dockerfile 中使用 `ln -s "$IC_DIR" /opt/oracle/lib 2>/dev/null || true` 建立 symlink，由於後面的 `|| true` 使得 `ln -s` 的失敗（可能因為路徑已存在或其他原因）被完全靜默忽略，`/opt/oracle/lib` 從未真正建立。

### 解決方案
1. **Dockerfile 改用 `mv` 直接重命名**：
   - 移除 `ln -s` 邏輯，改用 `mv /opt/oracle/instantclient_19_* /opt/oracle/lib` 直接將解壓出的目錄重命名，確保 `/opt/oracle/lib/libclntsh.so` 路徑必定存在。
   - 新增環境變數 `ORACLE_CLIENT_LIB_DIR=/opt/oracle/lib`。
2. **Python 明確傳入 `lib_dir`**：
   - 修改 `backend/routers/database_indexing.py`，加入 `import os`，讀取 `ORACLE_CLIENT_LIB_DIR` 環境變數，若存在則以 `oracledb.init_oracle_client(lib_dir=lib_dir)` 明確指定路徑；本地 Windows 開發環境無此環境變數時仍走自動偵測。

### 修改檔案
- `backend/Dockerfile`
- `backend/routers/database_indexing.py`





### 問題描述
當啟用 Thick Mode 連線時，`oracledb` 在 Linux 底下讀取 `ORACLE_HOME` 時，預設會從該路徑下的 `lib/` 子目錄中尋找 `libclntsh.so`。然而在原先的 `Dockerfile` 中，Oracle Instant Client 解壓後直接移到了 `/opt/oracle/instantclient` 下，沒有建立 `lib/` 目錄，導致在連線時拋出以下錯誤：
`Cannot locate a 64-bit Oracle Client library: "/opt/oracle/instantclient/lib/libclntsh.so: cannot open shared object file: No such file or directory"`

### 解決方案
修改 `backend/Dockerfile`，重構 Instant Client 的目錄放置結構：
1. 將 `ORACLE_HOME` 指向 `/opt/oracle`，並將 Instant Client 檔案解壓移至 `/opt/oracle/lib` 目錄中，使其完全匹配標準 Oracle 的 `/lib` 子資料夾結構。
2. 將動態連結器配置 `/etc/ld.so.conf.d/oracle-instantclient.conf` 與環境變數 `LD_LIBRARY_PATH` 調整為 `/opt/oracle/lib`，確保系統與 `python-oracledb` 能正確抓取到 `libclntsh.so`。

### 修改檔案
- `backend/Dockerfile`

## 2026-06-30 修正 Oracle Thick Mode 啟動失敗時缺乏詳細底層報錯訊息問題

### 問題描述
當後端在 Ubuntu 環境下嘗試使用 `oracledb` 連線至舊版 Oracle 資料庫（例如 Oracle 11g）時，系統會因為 `oracledb.init_oracle_client()` 啟動失敗而自動降級為 Thin Mode。由於降級是靜默發生的（僅記錄於容器日誌），前端在測試連線或執行操作時只會收到 `DPY-3010: connections to this database server version are not supported by python-oracledb in thin mode` 的錯誤，無法得知到底是因為缺少 `libaio`、Instant Client 檔案缺失、抑或是 `LD_LIBRARY_PATH` 載入路徑不正確等具體原因，導致除錯極為困難。

### 解決方案
1. **全域捕獲初始化異常**：在 `backend/routers/database_indexing.py` 中引入 `oracle_init_error` 全域變數，捕獲並暫存 `oracledb.init_oracle_client()` 的 Exception 物件。
2. **連線報錯訊息擴充**：在 Oracle 連線建立失敗的 `except Exception as e` 區塊中，若 `oracle_init_error` 不為空，則拋出帶有該初始化錯誤詳細資訊的 `RuntimeError`，從而使 `/api/database-indexing/test-connection` 能將具體的底層載入失敗原因（例如：`DPI-1047: Cannot locate a 64-bit Oracle Client library`）一同透過 API 回傳至前端。

### 修改檔案
- `backend/routers/database_indexing.py`

## 2026-06-30 修正 Python 3.11 環境下 RAG API 產生的 f-string 語法錯誤與 settings 未定義問題


### 問題描述
後端 Docker 容器在啟動時（採用 Python 3.11 運作環境），Uvicorn 啟動失敗並拋出以下錯誤：
`SyntaxError: f-string expression part cannot include a backslash`（在 `backend/routers/rag.py` 第 73 行）。
原因在於 Python 3.12 之前的版本中，f-string 內部 `{...}` 運算式中不允許包含反斜線符號（如 `\n` 或 `\"`）。此外，`backend/routers/rag.py` 內使用了 `settings` 變數但並未導入 `config` 中的 `settings`。

### 解決方案
1. **獨立 JSON 字典宣告**：將 `json.dumps` 內的字典（例如含有 `\\n` 或 `\n` 換行的 content 訊息）從雙引號 f-string 巢狀運算式中抽離，在 `yield` 前先定義為常規的 `step_data` 字典，再以 `json.dumps(step_data)` 序列化傳入，消除 f-string 內的反斜線。
2. **導入 settings**：於 `backend/routers/rag.py` 頂部導入 `from config import settings`。

### 修改檔案
- `backend/routers/rag.py`

## 2026-06-30 修正批次上傳 MD 檔案無法解析切分之問題

### 問題描述
在「自動分批寫入」分頁中，上傳並解析 `.md` 檔案時，前端會拋出「切分後未生成任何 Chunks」的錯誤且無法解析。原因在於：
1. 後端 `backend/routers/embedding.py` 的 `/chunk` 路由在判斷 `parent_child` 模式時，未特別處理 `.md` 副檔名，使其進入 fallback 機制，被當作 `.4gl` 程式碼檔案呼叫 `parse_4gl_to_parents` 解析。因為 Markdown 檔案不含 4GL 的 `FUNCTION ... END FUNCTION` 等宣告，導致解析結果為空，無法生成 any Chunks。
2. 前端 `BatchIndexingTab.vue` 中在選擇 `.md` 限制副檔名時，預設將 `batchChunkModeExt` 切分模式設為 `'standard'`（標準字元切分），但當使用者想要套用 Markdown 父子雙層（Parent-Child）結構切分時，缺乏合適的預設對接，且後端亦未提供 API 連接。

### 解決方案
1. **後端支援 Markdown 父子區塊切分 API 整合**：
   - 於 `backend/services/markdown_parent_child_chunker.py` 中重構 `chunk_markdown_file`，將其實作解耦並抽離出 `chunk_markdown_content` 函數，支援直接在記憶體中處理字串形式的 Markdown 文本內容。
   - 修改 `backend/routers/embedding.py` 的 `/chunk` 端點，加入對 `.md` 與 `.markdown` 檔案的識別分流。當在 `parent_child` 模式或偵測為 Markdown 檔案時，自動呼叫 `chunk_markdown_content` 進行大小雙層切分與標題路徑重建。
   - 在 Markdown 切分完成後，動態計算並注入 `parent_chunk_index_range` 索引範圍 metadata，確保與既有的 Qdrant 還原拼接機制完美相容。
2. **前端參數預設對接優化**：
   - 修改 `frontend/src/components/embedding/BatchIndexingTab.vue`，當使用者在批次寫入下拉選單中選取限制上傳副檔名為 `Markdown (.md)` 時，自動將 `batchChunkModeExt` 預設切分模式切換為 `parent_child`，並預設帶入推薦的 `child_size`（250字元）與 `child_overlap`（50字元）。

### 修改檔案
- `backend/services/markdown_parent_child_chunker.py`
- `backend/routers/embedding.py`
- `frontend/src/components/embedding/BatchIndexingTab.vue`

## 2026-06-30 修正 SQL Server/FreeTDS 伺服器 IP/主機名含有尾隨空格導致連線失敗之問題

### 問題描述
當使用者在資料庫連線設定中輸入或貼上含有尾隨空格的伺服器 IP (例如 `10.10.130.220 `) 時，後端在呼叫 pyodbc 使用 FreeTDS 驅動程式進行連線時，會因為 FreeTDS 對主機名解析極為嚴格，從而拋出 `[FreeTDS][SQL Server]Unable to connect to data source (0) (SQLDriverConnect)` 的連線失敗錯誤（錯誤代碼 `08001`）。

### 解決方案
1. **後端連線端點參數修剪 (Trim)**：
   修改 `backend/routers/database_indexing.py` 的 `get_db_connection` 函數，在構建連線字串前，主動對傳入的 `host`、`database` 及 `username` 進行 `.strip()` 修剪，去除任何意外夾帶的前後空格與換行字元。
2. **後端資料庫設定儲存修剪**：
   在 `create_config` 與 `update_config` 端點中，同樣對寫入/更新 MongoDB 的 `name`、`db_type`、`host`、`database` 與 `username` 執行 `.strip()`，確保儲存於資料庫中的設定檔乾淨無空格。
3. **前端輸入欄位發送修剪**：
   修改 `frontend/src/components/embedding/DatabaseIndexingTab.vue`，在儲存設定檔 `handleSaveDbConfig` 與測試連線 `handleTestDbConnection` 發送 API 請求前，先對 `host`、`database` 與 `username` 執行 `.trim()`。

### 修改檔案
- `backend/routers/database_indexing.py`
- `frontend/src/components/embedding/DatabaseIndexingTab.vue`

## 2026-06-29 修正 .4fd 畫面定義檔缺乏標準 Layout 標籤時切分後無 Chunks 產生之問題

### 問題描述
某些簡化或舊版 Genero .4fd 畫面定義檔（例如 `q_smy.4fd`）並未包含 `<Layout>`、`<FormItems>`、`<BindFiles>` 或 `<ScreenRecords>` 等外層包裹元素，而是將 `<Grid>` 與 `<RecordView>` 直接配置於根節點 `<Form>` 下。這導致大小雙層解析器因查無任何預設的父級目標節點，回傳空 Parent Chunks 列表，進而引發「切分後未生成任何 Chunks」的錯誤。

### 解決方案
1. **加入 root 根節點 Fallback 機制**：
   修改 `backend/services/parent_child_chunker.py`（與 CLI 腳本 `scripts/parent_child_chunker.py`）中的 `parse_4fd_to_parents` 方法。若經遍歷後未尋得任何標準的四大父標籤，則自動將根節點（通常為 `<Form>`）封裝為單一 Parent Chunk 回傳。
2. **依直屬子節點進行 Slicing**：
   當 parent_type 為 `Form` 時，`slice_4fd_to_children` 會自動套用 `else` 分支，將其直屬的 `<Grid>` 及 `<RecordView>` 等子項目成功拆分為獨立的 Child Chunks，保留完整結構的同時，確保 100% 的 `.4fd` 檔案均能成功切分與索引。

### 修改檔案
- `backend/services/parent_child_chunker.py`
- `scripts/parent_child_chunker.py`

## 2026-06-29 修正大小雙層切分不支援大寫或混用大小寫 XML 標籤導致切分失敗

### 問題描述
當使用者上傳含大寫 XML 標籤（例如 `<LAYOUT>`、`</LAYOUT>`）的 `.4fd` 畫面定義檔時，切分過程會提示 `切分後未生成任何 Chunks`。這是因為原本的 `.4fd` XML 切分與解析邏輯在過濾 `Layout`、`FormItems` 等關鍵 Parent Chunks 以及 `FormItem`、`Grid`、`Table` 等 Child Chunks 時，採用了區分大小寫的字串比對，導致大寫或非標準 PascalCase 的標籤無法被正確識別與抓取。

### 解決方案
1. **大小寫無感匹配**：
   修改 `backend/services/parent_child_chunker.py`（與 CLI 腳本 `scripts/parent_child_chunker.py`），在 `parse_4fd_to_parents` 中將目標標籤對應轉換為小寫後進行比對，並統一映射回標準的 PascalCase 作為 Parent 類別與 ID 以利下游定位。
2. **子區塊無感比對**：
   在 `slice_4fd_to_children` 方法中，將子節點標籤比對（如 `FormItem`、`Grid`、`Table`）改為小寫無感比對（`.lower()`），確保任何大小寫風格的節點都能精確切割為 Child Chunks。
3. **新增測試案例**：
   在 `tests/test_parent_child_chunker_4fd.py` 中新增 `test_xml_chunker_4fd_case_insensitive` 測試，模擬全大寫標籤之 `.4fd` 檔案切分以維持持續驗證。

### 修改檔案
- `backend/services/parent_child_chunker.py`
- `scripts/parent_child_chunker.py`
- `tests/test_parent_child_chunker_4fd.py`

## 2026-06-29 修正上傳 .4fd 畫面定義檔時拋出 400 Bad Request 錯誤

### 問題描述
當使用者在批次上傳/寫入分頁上傳 `.4fd` 畫面定義檔時，後端 `/api/embedding/upload` 接口返回 `400 Bad Request` 錯誤，提示：「目前不支援 .4fd 的檔案格式。支援的格式有 PDF, DOCX, TXT, MD, 4GL」。這是因為後端解析引擎中的 `DocumentParser.parse_file` 方法未將 `.4fd` 加入合法文字檔案格式清單。

### 解決方案
1. **新增 .4fd 至 DocumentParser 支援副檔名**：
   修改 `backend/services/document_parser.py` 中的 `parse_file` 方法，在文字解碼分流（`cls.parse_text`）中加入 `"4fd"` 副檔名。
2. **更新錯誤提示訊息**：
   同步更新不支援檔案格式時所引發的 ValueError 提示訊息，將其追加為支援 `4FD` 格式。

### 修改檔案
- `backend/services/document_parser.py`

## 2026-06-29 修正資料庫匯入向量化調用不存在方法 delete_by_filter 造成 500 錯誤

### 問題描述
在「資料庫匯入向量化」頁面進行匯入時，後端 `/api/database-indexing/ingest` 端點拋出 `500 Internal Server Error`，錯誤訊息為 `type object 'QdrantService' has no attribute 'delete_by_filter'`。這是因為後端在寫入前嘗試清理舊的同名資料庫備份點時，誤呼叫了不存在的 `delete_by_filter` 方法。

### 解決方案
1. **替換為 delete_by_filename**：
   修改 `backend/routers/database_indexing.py`，將誤呼叫的 `QdrantService.delete_by_filter` 修正為既有的 `QdrantService.delete_by_filename`，傳入參數為 `import_filename`（即 `DB_IMPORT_{table_name}`）。
2. **精準計數更新**：
   在刪除舊資料庫備份點時取得被刪除的點數量 `deleted_count`，隨後更新 MongoDB 中的 `kb.chunk_count` 時，使用 `max(0, kb.chunk_count - deleted_count + inserted_total)` 進行精確加減，避免重複計數，維持知識庫向量數量之一致性。

### 修改檔案
- `backend/routers/database_indexing.py`

## 2026-06-25 修正批次寫入大型檔案時 Request Entity Too Large 413 錯誤 (優化 Qdrant 資料量與 Nginx 設定)

### 問題描述
在自動分批寫入大型 `.4gl` 檔案（如 `p_zta.4gl`，約 938.5 KB，包含 2110 個 chunks）時，調用 `/api/embedding/vectorize` 接口返回 `413 Request Entity Too Large` 錯誤。原因如下：
1. **Nginx 預設限制**：前端採用 Nginx 作為反向代理，預設 `client_max_body_size` 限制為 `1M`。
2. **向量 Payload 資料膨脹**：原先為了還原 Parent Chunk 內容，我們在每個 Child Chunk 的 metadata 中重複注入了整個 `parent_content`（整個函數程式碼）。若單個函數區塊較大，2110 個 chunks 中重複存儲相同的數百 KB 程式碼，會導致傳遞給後端的 JSON 體積與寫入 Qdrant 的 Payload 呈千倍爆炸式增長，不僅觸發 413 限制，更存在硬碟與記憶體耗盡的風險。

### 解決方案
1. **移除 `parent_content` 寫入（杜絕資料膨脹）**：
   - 修改 `backend/routers/embedding.py`，在分切時不再向 child chunk metadata 中注入龐大的 `parent_content`，僅保留輕量級的索引範圍 `parent_chunk_index_range`（如 `"4~16"`）。這使每個向量寫入請求的體積恢復至正常大小（數 KB）。
   - 檢索端完全切換至「動態拼接還原（原情況 A）」，依 `parent_id` 即時自 Qdrant 撈取兄弟節點並去重合併，達成 100% 準確的還原效果，且無任何資料庫膨脹與傳輸限制。
2. **調整 Nginx 上傳限制**：
   - 修改專案根目錄的 `nginx.conf`，在 `server` 區塊下新增 `client_max_body_size 100m;` 設定，以支持大型檔案解析上傳及大批次向量寫入。
   - 執行非同步指令 `docker exec airag-frontend nginx -s reload` 動態重載前端 Nginx 服務，使配置立即生效。

### 修改檔案
- `backend/routers/embedding.py`
- `nginx.conf`

## 2026-06-25 修正 Parent-Child 切分檢索無法還原完整函數程式碼 (段落索引範圍合併) 之問題

### 問題描述
在 Parent-Child (大小雙層) 切分模式下，`.4gl` 的程式碼函數（如 `p_qry_cs()`）會被切分為數個子片段 (Child Chunks，如段落編號 `#4~16`)。
在搜尋 `FUNCTION p_qry_cs` 時，只有帶有函數簽名的子片段（如 `#4`）會因為語意或關鍵字匹配被檢索出來。其餘子片段（`#5~16`）因缺少關鍵特徵而未被召回，導致使用者在檢索結果或 RAG 對話中無法獲得完整的程式碼。

### 解決方案
1. **注入預存 Parent Metadata (優化寫入)**：
   - 修改 `backend/routers/embedding.py`，在 Parent-Child 或 `.4gl` 切分時，將完整的 `parent_content`（整個父節點程式碼內容）與 `parent_chunk_index_range`（如 `"4~16"` 的索引字串範圍）寫入每個 Child Chunk 的 `metadata` 中，並保存至 Qdrant Payload。
2. **改變 Pydantic Schema 型態限制**：
   - 修改 `backend/schemas/retrieval.py` 中的 `RetrievalMetadata`，將 `chunk_index` 的類型由 `Optional[int]` 修改為 `Optional[Any]`，以支援像 `"4~16"` 的範圍字串。
3. **Qdrant 檢索自動去重與還原合併**：
   - 修改 `backend/services/qdrant_service.py` 中的 `search_similar` 方法。
   - **兄弟去重**：針對同一個 `parent_id` 的子片段檢索結果，在 list 中進行去重，僅保留分數最高的那一個，防止重複顯示相同的 parent 區塊。
   - **內容還原與相容舊資料**：
     - 情況 A：如果 Payload 中有預存的 `parent_content`，則直接讀取它；若是結構化文字（`[檔案名稱]` 開頭），則自動拼裝出包含新索引範圍（如 `第 4~16 段`）的結構化標頭並覆寫內容。
     - 情況 B：如果是舊索引資料（無預存 `parent_content`），則透過新實作的 `get_siblings_and_merge` 方法，依 `parent_id` 非同步自 Qdrant 撈取該 parent 下的所有兄弟 child chunks，依 `chunk_index` 排序後以去重拼接（`merge_two_strings_with_overlap`，排除 overlapping 邊界重複文字）自動拼接還原為完整程式碼與索引範圍。

### 修改檔案
- `backend/routers/embedding.py`
- `backend/schemas/retrieval.py`
- `backend/services/qdrant_service.py`

## 2026-06-23 修正回饋歷史篩選錯誤分類下拉選單白字底看不清問題

### 問題描述
在「人工回饋與標註歷史」頁面中，錯誤分類篩選下拉選單的選項在部分瀏覽器原生渲染時出現「白色背景搭配白色文字」的狀況，導致選單內的文字完全隱形看不清。這是因為選項繼承了父元件的 `text-white`，但瀏覽器預設將下拉選項底色渲染為白色。

### 解決方案
1. **指定選項背景與文字顏色**：在 `frontend/src/views/FeedbackView.vue` 錯誤分類下拉選單的每一個 `<option>` 標籤中，顯式添加 `class="bg-[#111827] text-white"` 以覆寫原生樣式，確保背景為深色且文字為白色。

### 修改檔案
- `frontend/src/views/FeedbackView.vue`

## 2026-06-23 修正 RAG 功能測試回饋無法在「人工回饋與標註歷史」中顯示之問題

### 問題描述
使用者在進行 RAG 功能測試回饋後，POST `/api/feedback` 雖然回傳 `200 OK`，但在「人工回饋與標註歷史」頁面中看不到任何已提交的回饋紀錄。原因如下：
1. 後端 `backend/routers/feedback.py` 中的回饋 API 端點全是 Stub 模擬端點，並未對資料庫進行任何讀取或寫入。
2. 後端對話為無狀態 (Stateless) 設計，並未在資料庫持久化儲存 `ChatMessage` 與 `ChatSession`，而前端傳遞的 `chat_message_id` 是前端暫時生成的字串（如 `"msg_assistant_1782202045238"`）。因此，後端無法僅依據 `chat_message_id` 從資料庫查找問題 `question` 與 AI 回覆 `ai_answer`，且該 ID 也無法通過 Beanie 模型原本定義的 `PydanticObjectId` 格式驗證。

### 解決方案
1. **修改前端提交資料**：修改 `frontend/src/components/chat/FeedbackPanel.vue`，在提交回饋時，除原本欄位外，主動送出問題（`props.query`）與 AI 回覆（`props.content`）至後端 API。
2. **調整後端資料庫模型**：修改 `backend/models/feedback.py` 中的 `Feedback` 模型，將 `chat_message_id` 欄位類型從 `PydanticObjectId` 調整為 `str`，且將 `session_id` 設為 `Optional[str] = None`（預設為 `None`），以相容前端的暫時性欄位。
3. **實作後端 API 端點邏輯**：重構 `backend/routers/feedback.py`，完整實作回饋紀錄的創建（`POST`）、分頁與篩選查詢（`GET`）、回饋紀錄同步/導出至測試數據集（`POST /export-to-dataset`）以及回饋紀錄導出為 CSV/JSON（`GET /export`，其中 CSV 使用 `utf-8-sig` 編碼防亂碼）。

### 修改檔案
- `frontend/src/components/chat/FeedbackPanel.vue`
- `backend/models/feedback.py`
- `backend/routers/feedback.py`

## 2026-06-23 修正無向量條件之 Scroll 檢索產生的 Record 物件無 score 屬性錯誤 (導致檔名/標籤純篩選查不到資料)

### 問題描述
在「Prompt 測試」或檢索搜尋時，若未輸入查詢關鍵字（即 Query 為空）但有設定「篩選檔案名稱」或「篩選標籤」，後端會跳過向量生成並執行 Qdrant 的 `client.scroll`。由於 `client.scroll` 回傳的點為 `Record` 物件而非向量檢索的 `ScoredPoint` 物件，而 `Record` 物件本身並無 `.score` 屬性，導致後端存取 `res.score` 時拋出 `AttributeError: 'Record' object has no attribute 'score'` 異常，最後使檢索結果回傳空陣列（查不到資料）。

### 解決方案
1. **安全讀取屬性**：修改 `backend/services/qdrant_service.py` 中的 `search_similar` 邏輯，對於每一個點物件使用 `getattr(res, "score", 0.0)` 進行安全讀取，並在值為 `None` 時 fallback 至 `0.0`。
2. **計算 distance**：利用安全讀取到的 `score` 重新計算 `distance = 1.0 - score`，避免直接存取無屬性的 `res.score` 造成系統崩潰。

### 修改檔案
- `backend/services/qdrant_service.py`

## 2026-06-23 修正 Prompt A/B 測試 Variant 生成長度受限 1024 Token 問題

### 問題描述
在「Prompt 測試」中，即使使用者透過右側參數面板（LlmParamsPanel）設定最大 Token 數（Max Tokens）為更高值（如 32768），A/B 測試時的回答依然會在達到 1024 tokens 時發生截斷/停住。此原因在於 `PromptTestView.vue` 的 `handleABTest` 中，傳入後端的 variants 參數裡的 `max_tokens` 被寫死（hardcoded）為 `1024`。

### 解決方案
1. **引用 paramsStore 的動態設定**：
   - 於 `frontend/src/views/PromptTestView.vue` 導入 `useParamsStore` 並進行實例化。
   - 將 `handleABTest` 中 Variant A 與 Variant B 的 payload 參數調整為 `max_tokens: paramsStore.maxTokens`，使 A/B 測試能直接讀取使用者於面板拉動的 Max Tokens 長度。

## 2026-06-23 修正 Prompt 測試與 A/B 測試預覽/生成無法連線與 Stub 模擬問題

### 問題描述
在「Prompt 測試」頁面中，點擊「預覽組合 Prompt」或「A/B 參數對照生成」會拋出連線失敗之錯誤，原因為前端 API 請求路徑（`/prompt/preview` 與 `/prompt/ab-test`）遺漏了統一的 `/api` 前綴，導致請求無法正確對接到後端對應端點；且後端 `backend/routers/prompt.py` 中該兩項 API 僅為 Stub 模擬空值，無實際渲染與 LLM 生成功能。

### 解決方案
1. **補全前端 API 前綴**：
   - 修改 `frontend/src/views/PromptTestView.vue`，將預覽組合與 A/B 參數對照的 API 請求路徑分別補正為 `/api/prompt/preview` 與 `/api/prompt/ab-test`（以 `/api` 為首）。
   - 修改 `frontend/src/components/API/prompt_api.js` 的 path，補齊 `/api` 前綴。
2. **後端實作 Prompt 渲染與估計**：
   - 重構 `backend/routers/prompt.py`，定義相關 Pydantic schemas。
   - 於 `POST /api/prompt/preview` 端點中，將 template 中的 `{context}` 與 `{question}` 以實際內容替換，並以 `length * 1.3` 作為 token 估計標準（與前端一致）返回給前端渲染。
3. **後端實作 A/B 測試大模型對比生成**：
   - 於 `POST /api/prompt/ab-test` 端點中，讀取多個 variants 參數，分別套用不同的 `system_prompt`、`user_prompt`、`temperature` 及 `max_tokens` 參數，呼叫 `LLMService.chat_completion` 取得各組大模型生成的回答，並計算與返回耗時。

### 修改檔案
- `frontend/src/views/PromptTestView.vue`
- `frontend/src/components/API/prompt_api.js`
- `backend/routers/prompt.py`

## 2026-06-23 修正 Python 3.11 環境下 Evaluation API 產生的 f-string 語法錯誤

### 問題描述
後端 Docker 容器在啟動時（採用 Python 3.11 運作環境），Uvicorn 啟動失敗並拋出 `SyntaxError: unterminated string literal`。
原因是在 `backend/routers/evaluation.py` 的第 376 行 `event: result` 的 `yield` 語句中，於雙引號 f-string（`f"..."`）中巢狀撰寫了多行的 `{json.dumps({...})}` 字典字面量，且內部包含單引號。在 Python 3.12 之前的版本中，f-string 不支援內嵌運算式跨多行或 quotes 解析限制，因此在 3.11 中編譯失敗。

### 解決方案
1. **獨立 JSON 字典宣告**：將 `result_data` 字典字面量從 f-string 運算式中完全抽離，在 `yield` 之前宣告為常規的多行 Python 字典物件。
2. **簡化 f-string 傳參**：將序列化後的 `json.dumps(result_data, ensure_ascii=False)` 以單個變數傳入 f-string，避免多行與巢狀引號衝突，維持完美的向下相容性。

### 修改檔案
- `backend/routers/evaluation.py`

## 2026-06-23 修正大模型評估指標分數全部為 0.00 之異常 (LLM-as-a-Judge 針對 Reasoning 模型的 JSON 提取異常修正)

### 問題描述
在自動化 RAG 評估執行時，雖然 LLM 生成了正常的回答，但四項指標打分（忠實度、相關性、精確率、召回率）全部呈現 `0.00`。
經診斷，後端所串接的本地 vLLM 大模型 `Qwen3.6-35B-A3B-FP8` 是一隻具有內建思考過程的 Reasoning 模型。由於 Reasoning 模型的思考鏈極其冗長，且 vLLM 預設將思考過程寫在 `choice.message.reasoning` 欄位中，導致：
1. 原本設定的 `max_tokens=256` 導致生成在思考階段就觸發長度限制中斷，`choice.message.content` 返回 `null`。
2. 即使調大 token，真正的 JSON 仍有可能寫在 `reasoning` 欄位中，而舊版 JSON 解析器只能解析 `content` 且無法容忍 JSON 外包覆的大量思考文字。

### 解決方案
1. **vLLM 思考欄位 Fallback**：修改 `backend/services/llm_service.py`，當請求非串流完成時，若 `content` 為空或 `null`，則自動 Fallback 到 `reasoning` 或 `reasoning_content` 的文字內容作為 LLM 的輸出返回。
2. **調高 Judge 最大生成長度**：在 `backend/routers/evaluation.py` 中，將 LLM-as-a-Judge 的 `max_tokens` 由 `256` 上調至 `1536`，給予充足的 Token 生成完整思考鏈及 JSON 指標。
3. **優化 JSON 提取器**：重構 `parse_judge_json` 方法，導入更強韌 (Robust) 的解析策略。先進行常規 JSON 解析，若失敗則使用正則表達式定位包含 `"faithfulness"` 欄位的完整 `{...}` JSON 結構，成功從冗長混雜的思考文字中精準擷取出打分 JSON。

### 修改檔案
- `backend/services/llm_service.py`
- `backend/routers/evaluation.py`

## 2026-06-23 修正無參考資料或參考資料不足時 AI 產生幻覺/回答既有知識之問題

### 問題描述
當 RAG 系統未檢索到任何相關參考資料，或檢索到的參考資料中不包含問題答案時，AI 仍會使用其既有知識回答，未符合僅針對知識庫內容回答的限制。

### 解決方案
1. **調整 System Prompt 規則**：
   - 修改 `backend/routers/rag.py`。當 `context_str` 為空時，System Prompt 設定為強制要求 AI 直接回覆『知識庫沒有相關資訊。』，不可輸出其他回答。
   - 當 `context_str` 有內容但資料不足以回答問題時，同樣要求 AI 直接回答『知識庫沒有相關資訊。』，防止產生幻覺或使用外部既有知識回答。

### 修改檔案
- `backend/routers/rag.py`

## 2026-06-22 自訂資料向量化失敗修正 (400 Bad Request)

### 問題描述
在「自訂資料向量化」頁面中，點擊「向量化並寫入資料庫」會拋出 `400 Bad Request` 錯誤。原因在於該頁面未提供選取知識庫的 UI，且 Pinia 中的 `knowledgeBaseId` 預設為字串 `'hr_docs'`，後端嘗試以 `PydanticObjectId` 轉換時引發格式錯誤。

### 解決方案
1. **新增知識庫選擇元件**：
   - 於 `frontend/src/components/params/ChunkingParams.vue` 引入並渲染 `<KnowledgeBaseSelector />` 元件，使自訂向量化頁面可以選擇目標知識庫。
2. **防呆自動選取與無知識庫狀態處理**：
   - 修改 `frontend/src/components/common/KnowledgeBaseSelector.vue`。獲取清單後若無可用知識庫，將選單設為 disabled 並預設為無可用知識庫提示；若有可用知識庫但目前 Pinia store 的 `knowledgeBaseId` 不存在於列表中（例如預設的 `'hr_docs'`），則自動將其設定為清單中的第一個合法知識庫 ID。
3. **後端資料庫引導種植 (Database Seeding)**：
   - 修改 `backend/models/mongodb.py`，於系統初始化時檢查 `KnowledgeBase` 集合。若其數量為 0（例如乾淨系統或測試後已清理），則自動建立一個「預設知識庫」並同步於向量資料庫 Qdrant 中建立對應的 Collection。

- `frontend/src/components/params/ChunkingParams.vue`
- `frontend/src/components/common/KnowledgeBaseSelector.vue`
- `backend/models/mongodb.py`

## 2026-06-22 修正 llama.cpp 連線設定與回傳格式解析問題

### 問題描述
當 `llama.cpp` 服務重新啟動後，本機 Docker 容器依然拋出 `Failed to generate embedding via llama.cpp: All connection attempts failed` 錯誤。原因有二：
1. `docker-compose.yml` 中的 `LLAMACPP_BASE_URL` 仍被強制覆寫為 `http://host.docker.internal:8081`（指向本機），而非使用 `.env` 中指定的外部伺服器 IP `10.10.130.45`。
2. 即使連線成功，由於新版 `llama.cpp` 的 `/embedding` 端點回傳格式為列表類型（例如 `[{"embedding": [[...]]}]`），而後端代碼中硬編碼使用 `data["embedding"]` 去取得向量，這會導致 Python 拋出 `TypeError: list indices must be integers or slices, not str`，進而觸發模擬降級防線（產出全零向量）。

### 解決方案
1. **修正 Docker Compose 覆寫**：
   - 移除 `docker-compose.yml` 下對 `VLLM_BASE_URL` 與 `LLAMACPP_BASE_URL` 的環境變數覆寫，使其直接讀取並套用 `backend/.env` 所設定的真實外部 IP（`10.10.130.45`）。
2. **重構向量解析邏輯**：
   - 修改 `backend/services/embedding_service.py` 中的 `get_embedding` 方法，加入彈性且強健的格式解析邏輯。相容於以下三種結構：
     - 新版列表包裝結構：`[{"embedding": [[...]]}]` 或 `[{"embedding": [...]}]`
     - 舊版物件包裝結構：`{"embedding": [...]}`
     - OpenAI 兼容的 vLLM 結構：`{"data": [{"embedding": [...]}]}`

- `docker-compose.yml`
- `backend/services/embedding_service.py`

## 2026-06-22 修正 AsyncQdrantClient 無 search 屬性錯誤

### 問題描述
在向量檢索搜尋測試中，後端拋出錯誤：`Failed to search similarity in Qdrant collection 'kb_...': 'AsyncQdrantClient' object has no attribute 'search'`。這是因為當前後端依賴的 `qdrant-client` 庫為較新版本，在該版本中，非同步客戶端已棄用且移除了舊版的 `.search` 方法。

### 解決方案
1. **重構搜尋 API 方法**：
   - 修改 `backend/services/qdrant_service.py` 中的 `search_similar` 方法。
   - 將原本的 `client.search` 替換為 Qdrant 新版推薦的統一查詢介面 `client.query_points`。
   - 提取回傳的 `QueryResponse` 物件中的 `points` 屬性，其內之 `ScoredPoint` 結構與舊版完全相容，維持了業務邏輯與回傳格式的完整性。

### 修改檔案
- `backend/services/qdrant_service.py`
