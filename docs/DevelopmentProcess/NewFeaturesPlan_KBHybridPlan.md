# 新增集團知識庫混合查詢法 (`KB_hybrid`) 規劃文件

> 狀態：**已完成實作 (Implemented, 2026-07-30)**，第 8 節兩項開放問題已由使用者確認（見該節）
> 影響範圍：`backend/routers/rag.py`、`backend/routers/retrieval.py`、`backend/services/permission_service.py`（僅註解）、
> `frontend/src/components/params/RagParamsPanel.vue`、`frontend/src/views/RetrievalTestView.vue`、
> `frontend/src/components/params/ApiJsonPreviewPanel.vue`、`frontend/src/components/eval/TestSetManager.vue`、
> `docs/03_API_CONTRACT.md`。**不新增檔案、不改資料庫欄位、不改 Qdrant Collection 結構。**

---

## 1. 目標與範圍

### 目標
目前已有「集團知識庫語義混合查詢法」(`KB_semantic_hybrid`，見 [NewFeaturesPlan_KBSemanticHybridPlan.md](NewFeaturesPlan_KBSemanticHybridPlan.md))：問題先經地端 Instruct LLM 轉換為結構化 JSON（`embeddings_input`/`sparse_keywords`）才進行雙階段混合檢索。此語義轉換步驟需要多一次 LLM 呼叫，會拖慢回應速度。

新增「**集團知識庫混合查詢法**」(`KB_hybrid`)：**完全比照 `KB_semantic_hybrid` 的檢索管線與權限機制**（雙階段 Two-Step Hybrid Retrieval、RRF 融合、Rerank、`is_public` 專屬機密權限過濾、Top-K／相似度閾值／AI 總結門檻等既有參數），**唯一差異是拿掉「語義查詢」這一步**——不呼叫 Instruct LLM 做問題語義理解與 JSON 轉換，改用問題原文直接產生密集向量與稀疏查詢文字（做法與既有 `hybrid` 模式相同）。藉此讓使用者能少等一次 LLM 往返，更快取得資料。

### 明確不動的部分
- `vector`／`hybrid`／`semantic_hybrid`／`semantic_hybrid_feedback`／`semantic_hybrid_attachment`／`KB_semantic_hybrid`／`semantic_db_query` 既有 7 種 `search_type` 的內部邏輯**完全不修改**，`KB_hybrid` 是新增的第 8 種選項，走既有程式碼路徑的不同組合，不影響其他分支。
- Qdrant `search_similar()` / `search_similar_two_step()`（[qdrant_service.py:330](../../backend/services/qdrant_service.py)、[qdrant_service.py:636](../../backend/services/qdrant_service.py)）完全不修改，其內部本來就是依傳入的 `search_type` 參數字面值（`"hybrid"` 或 `"semantic_hybrid"`）決定要不要做 RRF 雙路融合，這兩個字串本身已足夠涵蓋新模式的需求，不需要改函式簽章或新增分支。
- `PermissionService.filter_results_kb_semantic_hybrid()`（[permission_service.py:208](../../backend/services/permission_service.py)）**不改邏輯、不改名**，直接讓 `KB_hybrid` 共用（該方法判斷的是 `is_public`/`access_dept`/`access_level`/`access_members` 這組「集團知識庫權限矩陣」，與是否經過語義查詢無關，屬於可共用的權限規則，見第 8 節決策紀錄）。
- `backend/routers/evaluation.py` 批次評估流程與 `frontend/src/components/eval/TestSetManager.vue` 的檢索邏輯**不特別串接** `KB_hybrid`（現況 `KB_semantic_hybrid` 也未特別串接評估流程的雙階段/權限過濾，只在 `TestSetManager.vue` 下拉選單可選，屬於既有落差，本次維持與其一致的範圍，不擴大修正，見第 8 節）。

## 2. 名詞對照

| 既有模式 | 語義查詢步驟 (Instruct LLM JSON) | 雙階段檢索 | Rerank | KB 專屬權限過濾 |
|---|---|---|---|---|
| `hybrid` | 無 | 無（單階段 `search_similar`） | 無 | 無（走通用 `filter_results`） |
| `semantic_hybrid` | 有 | 有 | 有 | 無（走通用 `filter_results`） |
| `KB_semantic_hybrid` | 有 | 有 | 有 | **有**（`filter_results_kb_semantic_hybrid`） |
| **`KB_hybrid`（新增）** | **無** | **有** | 有 | **有**（沿用 `filter_results_kb_semantic_hybrid`） |

`KB_hybrid` 可理解為「`KB_semantic_hybrid` 拿掉語義查詢步驟」，也可理解為「`hybrid` 加上雙階段檢索 + Rerank + 集團知識庫權限過濾」。

## 3. 後端設計

### 3.1 `backend/routers/rag.py` — `rag_chat_stream()`

現況第 333 行判斷是否要跑「語義解析」分支：
```python
if search_type in ("semantic_hybrid", "semantic_hybrid_feedback", "semantic_hybrid_attachment", "KB_semantic_hybrid"):
    # 呼叫 EmbeddingService.query_to_semantic_json(...) 取得 embeddings_input / sparse_keywords
    ...
else:
    query_vector = await EmbeddingService.get_embedding(question)   # 直接對問題原文做嵌入
    search_query_text = question
```
**`KB_hybrid` 不加入這個判斷式**，讓它自然落入 `else` 分支，取得問題原文的密集向量、`search_query_text = question`，不呼叫 Instruct LLM。這正是移除「語義查詢」步驟的關鍵改動點——不需要新增程式碼，只是「不要」把 `KB_hybrid` 加進這個 tuple。

現況第 434 行判斷是否要跑「雙階段檢索 + Rerank」分支：
```python
if search_type in ("semantic_hybrid", "semantic_hybrid_feedback", "semantic_hybrid_attachment", "KB_semantic_hybrid"):
    raw_results = await QdrantService.search_similar_two_step(
        collection_name=kb.qdrant_collection_name,
        query_vector=query_vector,
        query_text=search_query_text,
        search_type="semantic_hybrid",   # 字面值固定，觸發 Qdrant RRF 融合，與外層 search_type 變數無關
        top_k=top_k,
        score_threshold=score_threshold,
        filter_tags=filter_tags,
        filter_filename=filter_filename,
        sparse_keywords=sparse_keywords   # KB_hybrid 情況下為 None（沒有語義層抽取的關鍵字），交由函式內部退回正則抽取
    )
    if raw_results:
        raw_results = await RerankService.rerank(question, raw_results, top_k)
    ...
    if search_type == "KB_semantic_hybrid":
        raw_results, excluded_items = PermissionService.filter_results_kb_semantic_hybrid(raw_results, simulated_user)
    else:
        raw_results, excluded_items = PermissionService.filter_results(raw_results, simulated_user)
```
**需要修改兩處**：
1. 第 434 行的 tuple **加入 `"KB_hybrid"`**，讓它進入雙階段檢索 + Rerank 分支（`sparse_keywords` 此時是 `None`，`search_similar_two_step` 會呼叫 `_extract_exact_keywords()` 對 `query_text` 做正則關鍵字抽取，行為與既有 `hybrid` 模式一致）。
2. 第 457 行的權限過濾判斷改為：
   ```python
   if search_type in ("KB_semantic_hybrid", "KB_hybrid"):
       raw_results, excluded_items = PermissionService.filter_results_kb_semantic_hybrid(raw_results, simulated_user)
   else:
       raw_results, excluded_items = PermissionService.filter_results(raw_results, simulated_user)
   ```

**不需要修改**：
- 第 450 行 `semantic_hybrid_feedback` 專屬回饋加權、第 463 行 `semantic_hybrid_attachment` 專屬附件查詢，皆用 `==` 精確比對其專屬 `search_type`，`KB_hybrid` 不會誤觸發。
- Top-K／相似度閾值／AI 總結門檻套用邏輯（第 505-612 行整理 Context 與 `passed_ai_threshold` 判斷）完全共用，不分 `search_type`，`KB_hybrid` 自動繼承。
- 第 544 行 `score_label = "RRF Score" if search_type in [...] else "Score"` 這份清單**目前未包含 `KB_semantic_hybrid`**（屬於既有小瑕疵，`KB_semantic_hybrid` 現況顯示的 SSE 文字說明也是退回 `"Score"` 字樣，但數值上其實就是 RRF 分數）。本次**維持與 `KB_semantic_hybrid` 一致的既有行為，不在本次一併修正**，避免範圍外變更（見第 8 節）。

### 3.2 `backend/routers/retrieval.py` — `POST /api/retrieval/search`

此端點的查詢向量本來就是直接對 `request.query` 做 `EmbeddingService.get_embedding()`（[retrieval.py:47-52](../../backend/routers/retrieval.py)），從未呼叫語義 JSON 轉換——語義轉換只存在於獨立端點 `POST /api/retrieval/semantic-hybrid-search`。因此 `KB_hybrid` 天生就適合直接掛在 `/search` 端點，不需要新增端點。

需要修改兩處（皆與 `rag.py` 的改法完全對應）：
```python
# 第 55 行
is_semantic_hybrid_family = request.params.search_type in (
    "semantic_hybrid", "semantic_hybrid_feedback", "semantic_hybrid_attachment", "KB_semantic_hybrid", "KB_hybrid"
)
...
# 第 87 行
if request.params.search_type in ("KB_semantic_hybrid", "KB_hybrid"):
    raw_results, excluded = PermissionService.filter_results_kb_semantic_hybrid(raw_results, simulated_user)
else:
    raw_results, excluded = PermissionService.filter_results(raw_results, simulated_user)
```
`POST /api/retrieval/semantic-hybrid-search` 端點**不需要修改**（`KB_hybrid` 本來就不該經過這支語義專用端點）。

### 3.3 `backend/services/permission_service.py`

不改邏輯。僅將 `filter_results_kb_semantic_hybrid()` 的 docstring（[permission_service.py:214-219](../../backend/services/permission_service.py)）補充一句，說明此方法同時服務 `KB_hybrid`，避免未來讀者誤以為方法名稱代表僅適用語義混合模式。

## 4. API 設計

`ChatParams.search_type`（[rag.py:40](../../backend/routers/rag.py)）與 `RetrievalRequest.params.search_type` 型別皆不變（`Optional[str]`），只新增一個合法字串值 `"KB_hybrid"`，不需新增 Pydantic 欄位。

`docs/03_API_CONTRACT.md` 需更新的 `search_type` 列舉值：
- [03_API_CONTRACT.md:51](../../docs/03_API_CONTRACT.md)（`POST /api/rag/chat`）：`"... | KB_semantic_hybrid | KB_hybrid | semantic_db_query"`
- [03_API_CONTRACT.md:166](../../docs/03_API_CONTRACT.md)（`POST /api/retrieval/search`）：目前這行**遺漏了 `KB_semantic_hybrid`**（既有文件落差），本次一併補上 `KB_semantic_hybrid` 與新增的 `KB_hybrid`，改為：
  `"vector | hybrid | semantic_hybrid | semantic_hybrid_feedback | semantic_hybrid_attachment | KB_semantic_hybrid | KB_hybrid | semantic_db_query"`

## 5. 前端設計

### 5.1 `RagParamsPanel.vue`（對話測試頁參數面板）

[RagParamsPanel.vue:145](../../frontend/src/components/params/RagParamsPanel.vue) 下拉選單新增一個選項，緊接在 `KB_semantic_hybrid` 之後：
```html
<option value="KB_semantic_hybrid" ...>集團知識庫語義混合查詢 (KB Semantic Hybrid)</option>
<option value="KB_hybrid" class="bg-[#111827] text-white">集團知識庫混合查詢 (KB Hybrid)</option>
```

[RagParamsPanel.vue:212](../../frontend/src/components/params/RagParamsPanel.vue) 「多輪對話指代消解／手動鎖定檔案」面板的 `v-if` 清單**不加入 `KB_hybrid`**：該面板的「自動指代消解」是把對話歷史帶入 Instruct LLM 語義 JSON 轉換步驟（[rag.py:352](../../backend/routers/rag.py) `_build_history_window` 只在語義解析分支被使用），`KB_hybrid` 已移除該步驟，勾了也不會有作用；若只保留其中的「手動鎖定檔案」欄位又會讓面板顯示不完整的殘留控制項，故整塊面板對 `KB_hybrid` 維持隱藏，避免顯示無效果的設定項造成誤解（見第 8 節開放問題，若使用者認為手動鎖定檔案仍需保留，可再拆分此區塊）。

### 5.2 `RetrievalTestView.vue`（檢索測試頁）

[RetrievalTestView.vue:617](../../frontend/src/views/RetrievalTestView.vue) 下拉選單新增：
```html
<option value="KB_hybrid" class="bg-[#111827] text-white">集團知識庫混合查詢 (KB Hybrid)</option>
```

**不加入** [RetrievalTestView.vue:161](../../frontend/src/views/RetrievalTestView.vue)、[:188](../../frontend/src/views/RetrievalTestView.vue) 的 `isSemanticHybridFamily`／`semanticSteps` 判斷清單——這兩處決定是否顯示「語義分析」步驟卡片、以及是否改呼叫 `retrievalService.semanticHybridSearch()`（對應後端 `/semantic-hybrid-search` 端點）。`KB_hybrid` 應維持呼叫一般的 `retrievalService.search()`（對應 `/api/retrieval/search`，見 3.2 節），不顯示語義分析步驟卡片，與 `hybrid`／`vector` 現況一致。

**需要加入** [RetrievalTestView.vue:520](../../frontend/src/views/RetrievalTestView.vue)、[:522](../../frontend/src/views/RetrievalTestView.vue) 的 RRF Score 顯示判斷清單：
```html
{{ ['hybrid', 'semantic_hybrid', 'KB_semantic_hybrid', 'KB_hybrid'].includes(searchType) ? 'RRF Score' : 'Score' }}
```
此清單本來就已正確包含 `KB_semantic_hybrid`（與後端 [rag.py:544](../../backend/routers/rag.py) 那份遺漏的清單不同份），`KB_hybrid` 確實會走 RRF 雙路融合，理應比照加入。

### 5.3 `ApiJsonPreviewPanel.vue`

[ApiJsonPreviewPanel.vue:44](../../frontend/src/components/params/ApiJsonPreviewPanel.vue) 的說明文字：
```
'檢索模式：vector / hybrid / semantic_hybrid / semantic_hybrid_feedback / semantic_hybrid_attachment / KB_semantic_hybrid / KB_hybrid / semantic_db_query'
```

### 5.4 `TestSetManager.vue`

[TestSetManager.vue:185](../../frontend/src/components/eval/TestSetManager.vue) 下拉選單新增：
```html
<option value="KB_hybrid" class="bg-[#111827] text-white">集團知識庫混合查詢 (KB Hybrid)</option>
```
（僅新增選項供測試集標記使用，不修改 `evaluation.py` 批次評估的檢索邏輯，見第 1 節「明確不動的部分」與第 8 節。）

## 6. 執行流程設計

```
使用者於 RagParamsPanel.vue / RetrievalTestView.vue 選擇「集團知識庫混合查詢 (KB Hybrid)」
  │
  ▼
params.search_type = "KB_hybrid"
  │
  ▼
rag_chat_stream() / retrieval.search()
  │
  ├─ 不進入語義解析分支 → 直接對問題原文呼叫 EmbeddingService.get_embedding(question)
  │  → search_query_text = question（無 sparse_keywords，交由 _extract_exact_keywords 正則抽取）
  │
  ▼
QdrantService.search_similar_two_step(..., search_type="semantic_hybrid", ...)
  │  ├─ 1st-hop：dense + sparse RRF 融合核心檢索
  │  └─ 2nd-hop：若核心結果帶 links_to，對關聯檔案做過濾式混合檢索補充鄰居段落
  │
  ▼
RerankService.rerank(question, raw_results, top_k)   ← 與 KB_semantic_hybrid 相同，沿用既有 Rerank
  │
  ▼
PermissionService.filter_results_kb_semantic_hybrid(raw_results, simulated_user)
  │  依 is_public / access_dept / access_level / access_members 過濾（與 KB_semantic_hybrid 完全相同規則）
  │
  ▼
沿用既有 Top-K／score_threshold／ai_summary_score_threshold／分批摘要／System Prompt 組裝與串流回答邏輯
  （rag.py 第 499 行之後完全不分 search_type，KB_hybrid 自動繼承）
```

## 7. 不需新增的設定值

不需要新增 `backend/config.py` 設定值——`KB_hybrid` 完全複用既有的 `top_k`／`score_threshold`／`ai_summary_score_threshold`／`DEFAULT_CONTEXT_SUMMARIZE_THRESHOLD_TOKENS` 等既有參數與預設值，也不需要新的逾時或模型設定（不呼叫額外的 Instruct LLM）。

## 8. 決策紀錄／待確認事項

**已確認（本次規劃前提）**：
- `KB_hybrid` 與 `KB_semantic_hybrid` 共用同一個權限過濾方法 `filter_results_kb_semantic_hybrid()`，不重新命名、不新增別名方法，因為該方法的判斷邏輯是「集團知識庫的權限矩陣」而非「語義查詢專屬」。
- `rag.py:544` 的 RRF Score 顯示文字清單維持現況（`KB_semantic_hybrid` 也未被包含在內），不在本次一併修正，避免範圍外變更。
- `evaluation.py`／`TestSetManager.vue` 的批次評估檢索邏輯不特別串接 `KB_hybrid`，與 `KB_semantic_hybrid` 現況一致。

**使用者確認結果（2026-07-30）**：
1. **「手動鎖定檔案」保留** — 已依此拆分 `RagParamsPanel.vue` 該區塊：面板本身對 `KB_hybrid` 顯示，但「自動指代消解」與「指代消解歷史則數」兩個欄位對 `KB_hybrid` 隱藏（無語義解析步驟故無作用），「手動鎖定檔案」保留可用（`filter_filename` 在後端是不分 `search_type` 的通用邏輯）。5.1 節原本預設整塊隱藏的寫法已被此決策取代。
2. **名稱確認採用**「集團知識庫混合查詢 (KB Hybrid)」。

**實作階段發現的額外必要改動（規劃時未預見）**：
- `rag.py` 的非語義 else 分支從未初始化 `sparse_keywords`，而 `KB_hybrid` 是第一個「不走語義解析卻要呼叫 `search_similar_two_step(sparse_keywords=...)`」的模式，若不補 `sparse_keywords = None` 會直接 `UnboundLocalError`（既有 `vector`/`hybrid` 走的是 `search_similar()` 且未帶此參數，故從未觸發）。已於實作時補上。

## 9. 分階段實作 Checklist

### Batch 1：後端核心邏輯
- [ ] `backend/routers/rag.py`：第 434 行 tuple 加入 `"KB_hybrid"`；第 457 行權限過濾判斷改為 `in ("KB_semantic_hybrid", "KB_hybrid")`
- [ ] `backend/routers/retrieval.py`：第 55 行 `is_semantic_hybrid_family` 加入 `"KB_hybrid"`；第 87 行權限過濾判斷改為 `in ("KB_semantic_hybrid", "KB_hybrid")`
- [ ] `backend/services/permission_service.py`：`filter_results_kb_semantic_hybrid()` docstring 補充同時服務 `KB_hybrid` 的說明

### Batch 2：前端 UI
- [ ] `frontend/src/components/params/RagParamsPanel.vue`：新增下拉選項（依 8.1 開放問題決定是否拆分鎖定檔案面板）
- [ ] `frontend/src/views/RetrievalTestView.vue`：新增下拉選項；RRF Score 顯示清單加入 `KB_hybrid`；確認不誤入 `semanticHybridSearch` 呼叫路徑
- [ ] `frontend/src/components/params/ApiJsonPreviewPanel.vue`：更新 `search_type` 列舉說明文字
- [ ] `frontend/src/components/eval/TestSetManager.vue`：新增下拉選項

### Batch 3：文件更新
- [ ] `docs/03_API_CONTRACT.md`：`/api/rag/chat`、`/api/retrieval/search` 兩處 `search_type` 列舉值補上 `KB_hybrid`（`/search` 一併補上現況遺漏的 `KB_semantic_hybrid`）
- [ ] `docs/DevelopmentProcess/NewFeatures.md`：實作完成後記錄本次新增

### Batch 4：驗證
- [ ] 人工測試：同一問題分別以 `KB_semantic_hybrid` 與 `KB_hybrid` 查詢，確認除了少一次語義分析 SSE 步驟、回應速度較快之外，Top-K／相似度閾值／AI 總結門檻／模擬使用者權限排除結果一致
- [ ] 人工測試：模擬不同部門/職級使用者，確認 `KB_hybrid` 的 `is_public`/`access_dept`/`access_level`/`access_members` 權限排除行為與 `KB_semantic_hybrid` 一致
