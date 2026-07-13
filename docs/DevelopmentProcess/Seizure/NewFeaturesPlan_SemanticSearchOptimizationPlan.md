<!-- 語義混合搜尋 (semantic_hybrid) 優化規劃 -->

# 語義混合搜尋優化規劃

> 狀態：**已完成**
> 建立日期：2026-07-02
> 範圍：`backend/services/qdrant_service.py`、`backend/services/embedding_service.py`（涉及 `retrieval.py`、`rag.py`、`evaluation.py` 三個呼叫端）

## 總覽

| # | 項目 | 目標 | 優先級 | 風險 |
|---|---|---|---|---|
| 1 | `get_unique_metadata` 快取 | 降低語義搜尋延遲 | 高 | 需處理快取失效時機 |
| 2 | 2nd-hop 鄰居搜尋門檻放寬 | 提升 Two-Step 檢索召回品質 | 高 | 門檻放太寬可能引入雜訊 |
| 3 | 融合後加入 Rerank 層 | 提升最終上下文精準度 | 中 | 增加延遲，需額外呼叫模型 |
| 4 | 語義 JSON 轉換失敗可觀測性 | 讓 Instruct AI 失敗率可被追蹤 | 中 | 純觀測性，風險低 |
| 5 | Exact keyword 正則支援中文 | 中文檔名/術語也能觸發精準比對加成 | 低 | 需避免中文分詞誤傷（過度匹配單字） |
| 6 | Instruct AI JSON 語法失敗修正 | 降低語義轉換 fallback 發生率 | 高（實測已發生兩次） | `response_format` 若不受支援需驗證降級行為 |

建議執行順序：**1 → 2 → 4 → 5 → 3**（3 影響範圍最大且需額外評估延遲成本，放最後）；**第 6 項為測試中新發現的問題，插入於第 5 項之後、第 3 項之前執行**。

---

## 1. `get_unique_metadata` 快取

### 現況問題
[qdrant_service.py:722](../../backend/services/qdrant_service.py#L722) 每次呼叫 `/semantic-hybrid-search`、`rag.py` 的 `semantic_hybrid` 分流、`evaluation.py` 的評估迴圈，都會重新對整個 collection 做 `scroll(limit=10000)` 來組「結構化知識庫地圖」。這份地圖只在知識庫**上傳新檔案、刪除檔案、更新 `links_to`** 時才會變動，其餘時間都是重複計算同樣結果，屬於明確的可快取讀取。

### 修改方案
- 於 `QdrantService` 新增一個類別層級的記憶體快取（`dict[collection_name] -> {"data": ..., "cached_at": ...}`），不引入新套件（`requirements.txt` 目前沒有 `cachetools`/`redis`，維持專案簡單性原則）。
- `get_unique_metadata` 呼叫時先檢查快取是否存在且未過期，命中則直接回傳；未命中才 scroll 並寫入快取。
- 在會改變向量資料的寫入路徑主動清除快取（比較準確，避免 TTL 過期前的資料不一致）：
  - `embedding.py` 上傳/切片/向量化完成後
  - `retrieval.py` 的 `delete_by_filename` / `batch_delete_points` / `update_file_links` 成功後
  - `knowledge_base.py` 若有刪除知識庫/collection 的操作
- 新增 `QdrantService.invalidate_metadata_cache(collection_name)` 供上述路徑呼叫。

### 待確認參數
- 是否需要 TTL 保底（例如 10 分鐘），防止有遺漏的寫入路徑未呼叫 invalidate？（建議：**是**，TTL 600 秒作為保險，主動 invalidate 為主要機制）

### 實作方式
依建議，TTL 600秒，主動invalidate

### 影響範圍
`qdrant_service.py`（新增快取邏輯）、`embedding.py`、`retrieval.py`、`knowledge_base.py`（補上 invalidate 呼叫點）。

### 驗收方式
- 連續呼叫兩次 `/semantic-hybrid-search`（同一 KB），第二次的 log 應顯示「使用快取」而非重新 scroll。
- 上傳新檔案後立即查詢，結構化地圖應包含新檔案（驗證 invalidate 生效）。

### 測試結果（2026-07-02，已驗證通過）
Docker log 確認第二次呼叫命中快取：
```
2026-07-02 03:29:27,872 [INFO] airag.qdrant: [Qdrant] 使用快取的結構化元資料 - collection: kb_6a389dc83578b9d3d717244d
```
狀態：**完成，已驗收**。

---

## 2. 2nd-hop 鄰居搜尋門檻放寬

### 現況問題
[qdrant_service.py:553](../../backend/services/qdrant_service.py#L553) 鄰居搜尋（用來擴充 `links_to` 關聯內容）套用了跟第一階段核心搜尋**相同**的 `score_threshold`（預設 0.4，來自 `SearchParams`）。但鄰居搜尋的語意設計本來就是「主題相關但不見得與查詢字面高度相似」的補充資訊，用同樣嚴格的門檻篩選，容易把大部分鄰居過濾光，導致 Two-Step 檢索的第二階段形同虛設。

### 修改方案
- `search_similar_two_step`（[qdrant_service.py:484](../../backend/services/qdrant_service.py#L484)）新增獨立參數 `neighbor_score_threshold`，預設值明顯低於核心門檻（例如核心 0.4 → 鄰居 0.1，或乾脆不設分數門檻，完全依賴 `neighbor_limit` 數量與 `links_to` 過濾範圍來控制雜訊）。
- 呼叫端（`retrieval.py`、`rag.py`、`evaluation.py`）暫不需改動介面，於 `search_similar_two_step` 內部給預設值即可，避免影響既有呼叫簽章。

### 待確認參數
- 鄰居門檻建議值：**0.1**（維持基本相關性下限）或 **完全不設門檻**（0.0，僅靠 `links_to` 過濾 + `neighbor_limit=10` 控制數量）？
  - 建議先採 **0.1**，避免完全不相關的鄰居污染 context；若測試後仍覺得召回不足，再降到 0。

### 實作方式
依建議，0.1。

### 影響範圍
`qdrant_service.py` 的 `search_similar_two_step` 內部兩處 query_points 呼叫（hybrid fallback 與 pure vector 分支）。

### 驗收方式
- 針對一組已知有 `links_to` 關聯設定的檔案提問，比對修改前後鄰居結果數量與內容差異。
- 確認 `disable_parent_merge=True` 時鄰居原始分數輸出，觀察目前有多少鄰居卡在 0.1~0.4 之間被誤刪。

### 實作狀態
已完成，`neighbor_score_threshold` 預設 0.1，待使用者測試驗收。

---

## 3. 融合後加入 Rerank 層

### 現況問題
目前 dense + sparse + exact-keyword 三路 prefetch 完全依賴 Qdrant 的 RRF（Reciprocal Rank Fusion）排序後直接送給 vLLM 生成答案。RRF 只看各路排名、不看實際語意分數的差距，precision 上限有限，尤其 exact-keyword boost 這一路（[qdrant_service.py:346](../../backend/services/qdrant_service.py#L346)）容易召回字面命中但語意不相關的段落。

### 修改方案（本專案目前**沒有**部署獨立 cross-encoder 模型，兩個選項）
- **方案 A（建議 / 低成本）**：借用既有的 Instruct LLM（`DENSE_VECTOR_LLAMACPP_BASE_URL`，Qwen3VL-8B-Instruct）做 LLM-based rerank：將 RRF 融合後的候選片段（如 top 15~20）連同原始查詢一起送入一次 prompt，要求輸出相關性排序或分數，取前 `top_k` 送給 vLLM 生成答案。不需新增模型部署，但會多一次 LLM 呼叫、增加延遲。
- **方案 B（未來考慮）**：額外部署專用 cross-encoder rerank 模型（如 BGE-reranker），精準度較高但需要新的模型服務與部署成本，超出目前優化範圍，先不列入本次執行。

### 待確認參數
- 是否採用方案 A？若採用，Rerank 候選數量與延遲上限（建議：候選 15~20 筆，rerank prompt 使用 `max_tokens` 限制在較小值以控制延遲）。

### 實作方式
先採用A方案，依建議20筆

- 此項是否要納入本次一併執行，或先觀察 #1、#2 調整後的效果再決定？（建議：**先觀察 #1、#2 效果**，因為 Rerank 屬於架構性變動，且會直接影響現有的串流回應時間，範圍較大。）

### 影響範圍
`qdrant_service.py`（`search_similar` / `search_similar_two_step` 之後、回傳前的新增 rerank 步驟）或抽成獨立 `RerankService`。`rag.py`、`retrieval.py`、`evaluation.py` 三個呼叫端皆會受影響（延遲增加）。

### 驗收方式
- 比較 rerank 前後同一查詢的 top_k 內容差異與人工判讀相關性。
- 量測端到端延遲增加量，確認是否在可接受範圍（尤其 `rag.py` SSE 串流的 `vector_search` step 耗時）。

### 實作狀態
已完成。新增 `backend/services/rerank_service.py`，`retrieval.py`/`rag.py`/`evaluation.py` 三個語義混合流程皆已接上（`evaluation.py` 額外調整為召回 20 筆候選池再裁切回 `top_k`，否則 rerank 無候選可排序）。僅套用於 `semantic_hybrid`，不影響 `/api/retrieval/search` 的 `vector`/`hybrid` 類型。待使用者測試驗收，請留意 log 中 `LLM rerank 完成` 訊息，並觀察端到端延遲增加幅度。

---

## 4. 語義 JSON 轉換失敗可觀測性

### 現況問題
[embedding_service.py:272](../../backend/services/embedding_service.py#L272) `query_to_semantic_json` 失敗時（Instruct AI 逾時、回傳非合法 JSON 等）會靜默降級回傳 `fallback_json`（用原始問題當 `embeddings_input`/`sparse_keywords`），只有一行 `logger.error`。目前沒有任何計數或統計，測試階段很難得知 Instruct AI 的實際失敗率，容易誤判「語義搜尋沒效果」其實是「語義轉換一直在 fallback」。

### 實測發現（2026-07-02，測試第 1 項時於 Docker log 中觀察到）
查詢 `p_zz.4gl` 時，Instruct AI 回傳的 JSON 格式不合法，觸發例外並靜默降級：
```
[ERROR] Failed to convert query to semantic JSON: Expecting property name enclosed in double quotes: line 10 column 5 (char 217)
```
緊接著的偵錯 log 顯示出的「結構化內容」其實是 `fallback_json`（`embeddings_input`/`sparse_keywords` 皆等於原始問題本身，並非 AI 真正解析結果），但目前完全沒有訊號可以區分這是 AI 解析成功還是降級結果：
```
已從 Instruct AI 取得結構化 JSON: {'text_content': 'p_zz.4gl', 'embeddings_input': 'p_zz.4gl', 'sparse_keywords': ['p_zz.4gl']}
```
→ 這是實際發生過的案例，直接印證本項優化的必要性，也代表 Instruct AI 目前輸出格式並非 100% 穩定合法（可能是多餘逗號等格式問題），值得在完成 `is_fallback` 標記後持續觀察實際發生頻率。

### 修改方案
- `fallback_json` 回傳時額外標記一個內部欄位（例如 `_fallback: true`，或獨立回傳 `(json, is_fallback: bool)`），讓呼叫端（`retrieval.py`）可以在 `RetrievalResponse` 中標示此次查詢是否為降級結果，方便測試時直接在前端/回應中看到。
- log 訊息維持 `logger.error`，但補充明確原因分類（逾時 / JSON 解析失敗 / HTTP 錯誤），方便之後篩選 log。

### 待確認參數
- 是否要把 `is_fallback` 這個標記也加進 `/semantic-hybrid-search` 的回應 Schema（`schemas/retrieval.py` 的 `RetrievalResponse`），讓你測試時能直接在前端看到「這次是不是降級」？（建議：**是**，測試階段這個訊號很有價值，且改動範圍小）

### 實作方式
依建議，將is_fallback加入回應。

### 影響範圍
`embedding_service.py`（回傳值調整）、`schemas/retrieval.py`（新增欄位）、`retrieval.py`（組裝回應時帶入）。

### 驗收方式
- 手動讓 Instruct AI 服務逾時或回傳錯誤格式，確認回應中 `is_fallback=true` 且 log 有明確分類訊息。

### 實作狀態
已完成。`query_to_semantic_json` 回傳值新增 `is_fallback`，並暴露到 `/semantic-hybrid-search` 的 `RetrievalResponse.is_fallback`。待使用者測試驗收（可直接用 2026-07-02 實測發現那次的查詢方式重現，確認這次 API 回應會顯示 `is_fallback: true`）。

---

## 5. Exact keyword 正則支援中文

### 現況問題
[qdrant_service.py:312](../../backend/services/qdrant_service.py#L312) `re.findall(r'[a-zA-Z0-9_]{3,}', query_text)` 只抓英數底線組成的詞彙，用來做 exact keyword boost（MatchText / function_name / parent_id 三路精準比對加成）。若知識庫或查詢是以中文為主的檔名、術語、欄位說明，這條加成路徑完全不會被觸發。

### 修改方案
- 改用 `sparse_keywords`（Instruct AI 已經抽取出的關鍵詞列表，含中英文）作為 exact keyword boost 的來源，取代現行對 `query_text` 做正則抽取的方式。這樣天然支援中文，且與語義層已抽取的關鍵字一致，不需要额外處理中文分詞。
- 注意：`search_similar`（[qdrant_service.py:248](../../backend/services/qdrant_service.py#L248)）目前是通用方法，`hybrid`（非語義）搜尋沒有 `sparse_keywords` 可用，需保留現行正則作為 fallback（`query_text` 沒有結構化關鍵字時才用正則抽取英數詞）。

### 待確認參數
- 中文關鍵字是否需要長度限制（避免單字「的」「與」等無意義字被當關鍵字）？（建議：長度 ≥ 2 個中文字元才納入 boost）

### 實作方式
依建議，長度 ≥ 2 個中文字元才納入 boost

### 影響範圍
`qdrant_service.py` 的 `search_similar` 與 `search_similar_two_step`，需新增參數讓呼叫端可傳入已知的 `sparse_keywords`（`retrieval.py`、`rag.py` 語義流程已有此資料）。

### 驗收方式
- 用純中文檔名/術語提問，確認 log 出現「Hybrid search exact keyword boost active」且關鍵字包含中文詞。

### 實作狀態
已完成。`_extract_exact_keywords` 靜態方法已加入 `qdrant_service.py`，`retrieval.py`/`rag.py`/`evaluation.py` 三個語義混合流程都已改為傳入 `sparse_keywords`。待使用者測試驗收。

---

## 6. Instruct AI JSON 語法失敗修正

### 現況問題
測試第 1、4 項時，於 Docker log 中兩次觀察到 `query_to_semantic_json`（[embedding_service.py:125](../../backend/services/embedding_service.py#L125)）呼叫 Instruct AI（Qwen3VL-8B-Instruct，經 llama.cpp）解析失敗：
```
Failed to convert query to semantic JSON: Expecting property name enclosed in double quotes: line 10 column 5 (char 217)
Failed to convert query to semantic JSON: Expecting ',' delimiter: line 9 column 31 (char 278)
```
兩次都是**語法層級**錯誤（缺逗號/多餘逗號等），不是欄位缺漏，錯誤位置也都在內容前段，排除是 `max_tokens=512` 截斷所致。目前每次語法錯誤都會直接降級為 `fallback_json`（已由第 4 項標記 `is_fallback: true`，但問題本身尚未修正），代表語義層的查詢重寫、關鍵字擴展、反幻想優化等效果完全喪失，退化成用原始問題直接檢索。

### 修改方案（兩者互補，建議一併執行）
1. **啟用 `response_format` 強制語法合法（根本修正）**：
   - 於 `query_to_semantic_json` 的 `payload` 中加入 `"response_format": {"type": "json_object"}`。llama.cpp 的 `/v1/chat/completions` 為 OpenAI 相容端點，多數近期版本支援以此觸發 grammar-constrained decoding，從生成層面強制輸出語法合法的 JSON（不保證欄位語意正確，但能消除「缺逗號」這類語法錯誤）。
   - 風險低：若目前部署的 llama.cpp 版本不支援此參數，預期行為是被忽略或該次請求出錯，兩者都已被現有 `try/except` 包住並降級為 `fallback_json`，不會比現況更差。
2. **解析失敗重試一次（務實補強）**：
   - `json.loads(content)` 拋出例外時，先重試一次同樣的請求（利用 LLM 抽樣隨機性），仍失敗才真正回傳 `fallback_json`。
   - 需在 log 中區分「重試後成功」與「重試後仍失敗」，方便後續統計重試的實際效益。

不採用的方案：用 regex 硬修補 JSON 字串（補逗號、修引號等）——治標不治本，容易在其他格式錯誤模式上失效，且會讓程式碼難以維護。

### 待確認參數
- 是否兩個方案一併執行？（建議：**是**，兩者互補且風險都低）
- 重試次數：建議 **1 次**（總共最多呼叫 2 次 Instruct AI），避免拖慢延遲過多。

### 影響範圍
`backend/services/embedding_service.py` 的 `query_to_semantic_json`（payload 調整 + 重試邏輯），呼叫端（`retrieval.py`、`rag.py`、`evaluation.py`）不需改動。

### 驗收方式
- 觀察後續測試中 `is_fallback: true` 的發生頻率是否明顯下降。
- 若 llama.cpp 版本不支援 `response_format`，log 應能看出降級（不影響現有 fallback 機制正常運作）。
- 確認重試邏輯不會讓單次語義搜尋延遲暴增（最壞情況下 Instruct AI 呼叫 2 次的耗時需在可接受範圍）。

### 實作狀態
已完成。`query_to_semantic_json` payload 已加入 `response_format: json_object`，並實作最多重試 1 次的邏輯（`_call_and_parse` 內部函式）。待使用者測試驗收，觀察 `is_fallback: true` 發生頻率是否下降，以及 llama.cpp 是否支援 `response_format`（若不支援，log 應能看出仍照舊降級，不影響現有機制）。

---

## 待你確認的決策點彙總

1. 快取失效策略：主動 invalidate + TTL 600 秒保底，可接受？ (已決定)
2. 鄰居門檻：先採 0.1，或直接設 0（不限制分數）？ (已決定)
3. Rerank（#3）是否本次一併執行，或先做 #1/#2/#4/#5 觀察效果後再議？ (已決定)
4. 是否需要把「降級 fallback」標記暴露到 API 回應供前端顯示？ (已決定)
5. 中文 exact keyword 最小長度門檻：2 個字元可接受？ (已決定)
6. Instruct AI JSON 語法失敗修正：`response_format` 強制合法 JSON + 失敗重試 1 次，兩者一併執行可接受？（待確認）

確認以上後即可依序執行，完成後會依 `AGENT.md` 規範將實際修改內容記錄到 `docs/DevelopmentProcess/BackendCorrection.md`。

---

## 待處理事項（2026-07-02 測試中新發現，尚未修正）

### 7. 語義 JSON 重試機制對「確定性失敗」無效（第 6 項補強）

**狀態：已完成**

第 6 項上線後於 Docker log 中觀察到：
```
05:21:55 [WARNING] 第 1 次嘗試失敗，將重試: Expecting ',' delimiter: line 9 column 31 (char 245)
05:22:06 [ERROR]   重試 2 次後仍失敗，降級為 fallback: Expecting ',' delimiter: line 9 column 31 (char 245)
```
兩次錯誤發生在**完全相同的位置**（line 9 column 31, char 245），代表 `temperature=0.1` 下 Instruct AI 對同一問題兩次生成了幾乎一致的錯誤輸出，暴露兩個問題：
- `response_format: json_object` 疑似**沒有實際生效**——若 grammar-constrained decoding 真的啟用，理論上不該仍產生語法錯誤；目前部署的 llama.cpp 版本可能不支援此參數或靜默忽略。
- 原地重試對這種「確定性失敗」沒有幫助，只多花了約 11 秒卻拿到同樣的錯誤結果。

**建議修正方向**：重試時提高 `temperature`（例如第 2 次嘗試改用 0.4~0.5），用抽樣隨機性打破確定性重複失敗，成本低、見效快。根本解法（確認 llama.cpp 版本/啟動參數是否真的支援 `response_format`/grammar）屬於部署設定層級，非本次程式碼可單方面保證，暫不在此規劃範圍內。

**影響範圍**：`backend/services/embedding_service.py` 的 `query_to_semantic_json` 重試邏輯。

**實作狀態**：已完成，重試溫度改為 `[0.1, 0.5]`，log 會標示每次嘗試使用的 temperature。待使用者測試驗收，確認同一容易失敗的查詢，第 2 次嘗試（temperature=0.5）是否成功解析出合法 JSON。

### 8. 可疑對外請求：`huggingface.co/api/agent-harnesses`（安全性觀察，非語義搜尋範疇）

**狀態：已釐清並處理**

已於兩次測試（2026-07-02 03:49、05:22）的 Docker log 中重複觀察到：
```
httpx: HTTP Request: GET https://huggingface.co/api/agent-harnesses "HTTP/1.1 200 OK"
```
此路徑並非 Hugging Face Hub 正常的 API 格式（正常應為 `/api/models/{repo_id}` 等），出現時機緊接在 `fastembed` 初始化 SPLADE 稀疏向量模型（`airag.sparse_embedding: Initializing fastembed SparseTextEmbedding model...`）之前，後面才是正常的模型下載流程（`/api/models/Qdrant/Splade_PP_en_v1`、`/tree/`、`/revision/main` 等）。

**判斷**：尚未確認是良性的第三方套件遙測行為，還是有相依套件被植入非預期行為（供應鏈風險）。本次未對此網址採取任何存取或動作。

**建議處理方式**：
- 檢查 `backend/requirements.txt` 內 `fastembed`、`huggingface_hub` 相依鏈的實際安裝版本與其原始碼／官方 release note，確認是否為官方已知行為。
- 若無法確認來源，考慮鎖定 `huggingface_hub` 版本、或在部署環境設定 `HF_HUB_OFFLINE=1` / 白名單網路出口，降低未知對外請求的風險。

**影響範圍**：非程式碼變更，屬於環境/相依套件稽核，需你進一步確認方向後才能規劃具體修正。

### 調查結果（2026-07-02）

直接進入運行中的 `airag-backend` 容器查證，確認容器內 `huggingface_hub` 版本為 **1.21.0**，原始碼中確實存在 `huggingface_hub/utils/_detect_agent.py`：這是官方合法功能，用途是偵測目前程序是否由 AI coding agent（Claude Code、Cursor 等）呼叫，藉此在對 Hub 的 HTTP 請求 `User-Agent` 標頭中標記 `agent/<harness>`，供 Hugging Face 統計 AI agent 帶來的流量。觸發鏈：`huggingface_hub/utils/_headers.py` 的 `http_user_agent()` 在組 User-Agent 時，只要沒關閉 telemetry 就會呼叫 `detect_agent()`；該函式會在本機快取 `{ENDPOINT}/api/agent-harnesses` 註冊表（TTL 24 小時），供本機比對環境變數用。`fastembed` 首次初始化 SPLADE 稀疏向量模型時透過 `huggingface_hub` 向 Hub 下載模型，因而觸發這條請求鏈。

**結論**：非惡意、非供應鏈風險，屬於官方套件既有行為，與本次語義搜尋優化程式碼無關。

**處理方式**：已採用「設定環境變數關閉此特定 telemetry」的最小處置，不修改任何 Python 程式碼：
- `docker-compose.yml`：`backend` service 的 `environment` 新增 `HF_HUB_DISABLE_TELEMETRY=1`。
- `backend/.env`：新增 `HF_HUB_DISABLE_TELEMETRY=1`，讓非 Docker 的本機開發（`uvicorn main:app --reload`）也套用同樣設定（`config.py` 透過 `load_dotenv()` 載入，會寫入實際的 process 環境變數）。

**驗收方式**：`docker-compose up --build -d backend` 重啟容器後，觸發一次語義混合搜尋（或任何會初始化 `fastembed` 稀疏向量模型的操作），確認 Docker log 不再出現 `GET https://huggingface.co/api/agent-harnesses`。
