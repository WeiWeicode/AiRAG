<!-- BUG修正(最新紀錄放最前面) -->

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
