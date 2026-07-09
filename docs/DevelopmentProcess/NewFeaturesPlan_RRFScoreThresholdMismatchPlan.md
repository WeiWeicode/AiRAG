# RRF 混合檢索分數與 Score Threshold 尺度不匹配（嚴重問題）規劃文件

> 狀態：問題已確認，**已決議採用方案 C 之子選項 C-2**（見第 7 節決策紀錄），待排入實作。
> 嚴重性：**高** —— 直接影響本專案 signature pipeline（`semantic_hybrid*`）的可觀測性，且是 [`NewFeaturesPlan_RetrievalStatsDashboardPlan.md`](NewFeaturesPlan_RetrievalStatsDashboardPlan.md) Batch 1 的前置阻塞事項。
> 影響範圍：已決議修改範圍限縮在 `backend/services/qdrant_service.py`（`search_similar()` 新增可比較分數欄位，**不**過濾候選、**不**改變回傳筆數）；`rerank_service.py`／`feedback_boost_service.py`／`config.py` 暫不需修改（詳見第 7 節）。

## 1. 問題摘要

本專案 `hybrid`／`semantic_hybrid`／`semantic_hybrid_feedback`／`semantic_hybrid_attachment`（以下統稱 `semantic_hybrid*` 家族，是 [CLAUDE.md](../../CLAUDE.md) 定義的 signature pipeline）在检索時，`QdrantService.search_similar()` 使用 Qdrant 的 RRF（Reciprocal Rank Fusion）融合查詢取得候選結果。**這條路徑回傳的 `score` 欄位是 RRF 融合分數，量級遠低於（且與）本專案原本用來表示「cosine 相似度是否達標」的 `score_threshold`（預設 0.65～0.7）不同尺度**。

任何目前或未來把 `score >= score_threshold` 當作「本次檢索是否命中／是否達到品質門檻」判斷依據的邏輯，只要用在 `semantic_hybrid*` 或 `hybrid` 查詢法上，都會产生系統性錯誤：幾乎恆為 False，即使實際檢索到的內容高度相關。

此問題是在規劃 [檢索命中分析儀表板](NewFeaturesPlan_RetrievalStatsDashboardPlan.md) 時發現的（該功能的 `hit_count`／零命中判斷直接依賴這個比較），但問題本身存在於既有檢索管線，不是新功能引入的 bug，值得獨立記錄與決議。

## 2. 問題成因與程式碼佐證

### 2.1 RRF 融合查詢完全沒有套用 `score_threshold`

`QdrantService.search_similar()` 中，當 `search_type in ["hybrid", "semantic_hybrid"]` 時走 RRF 融合路徑：

```python
# backend/services/qdrant_service.py:371-379
response = await client.query_points(
    collection_name=collection_name,
    prefetch=prefetch_list,
    query=models.FusionQuery(
        fusion=models.Fusion.RRF
    ),
    limit=search_limit
)
results = response.points
```

`query_points()` 的這個呼叫**沒有帶入 `score_threshold` 參數**。相對地，同一個方法裡另外兩條路徑都有帶：

- 純向量降級路徑（RRF 失敗時的 fallback）：[qdrant_service.py:384-390](../../backend/services/qdrant_service.py)，帶 `score_threshold=score_threshold`
- 純向量常規路徑（`search_type` 不屬於 hybrid 系列時）：[qdrant_service.py:404-410](../../backend/services/qdrant_service.py)，帶 `score_threshold=score_threshold`

也就是說，**只有 `semantic_hybrid*`／`hybrid` 這個本專案最主要的查詢法，其候選結果完全沒有經過 `score_threshold` 過濾**，所有 RRF 排序後的結果（無論實際相關性高低）都會被回傳（受 `search_limit` 筆數限制，而非分數限制）。

### 2.2 RRF 分數的量級遠低於 `score_threshold` 的預期尺度

RRF 是排名融合演算法，其分數公式為 `score = Σ 1/(k + rank)`（業界慣例常數 `k = 60`，源自原始 RRF 論文，Qdrant 官方文件亦採此慣例）。以此估算：

- 單一 prefetch 來源中排名第 1 的項目，貢獻約 `1/60 ≈ 0.0167`
- 本專案的 RRF 融合通常有 2～3 路 prefetch（dense + sparse，或再加 exact keyword boost，見 [qdrant_service.py:310-367](../../backend/services/qdrant_service.py)），即使三路都排名第 1，理論最高分也僅約 `3 × 0.0167 ≈ 0.05`
- 實務上大多數候選的分數會落在 `0.01～0.03` 之間

而本專案的 `score_threshold` 預設值為 `0.65`（[rag.py:231](../../backend/routers/rag.py)）或 `0.7`（`config.py` 的 `DEFAULT_SCORE_THRESHOLD`），這是為 cosine 相似度（範圍 0～1，語意相關的文本通常落在 0.6 以上）設計的門檻。**兩者相差一個數量級以上，`score >= score_threshold` 這個比較式對 RRF 分數而言幾乎恆為 `False`。**

> 上述 RRF 分數估算基於 Qdrant 官方文件所述的慣例常數，建議在決定最終方案前，於測試環境對 `semantic_hybrid` 查詢實際印出 `score` 值分布做一次實測校驗（見第 6 節建議行動）。

### 2.3 下游處理不會把分數轉換回可比較的尺度

- `RerankService.rerank()`（[rerank_service.py](../../backend/services/rerank_service.py)）：只依賴地端 Instruct LLM 對候選重新排序，**完全不觸碰 `score` 欄位**，原始 RRF 分數原封不動保留。
- `FeedbackBoostService.apply_feedback_boost()`（[feedback_boost_service.py:70](../../backend/services/feedback_boost_service.py)）：`item["score"] = item.get("score", 0.0) * (1 + weight * boost)`，只是在原分數上做等比例加權（`FEEDBACK_BOOST_WEIGHT` 預設 0.2，最大乘數 1.2 倍），**仍停留在 RRF 尺度**，不會把 0.01～0.05 的分數放大回 0.6～1.0 的範圍。

因此無論候選經過多少道後處理，最終送到前端／或任何依賴 `score_threshold` 比較的下游邏輯時，分數尺度問題都沒有被修正。

### 2.4 現有程式碼其實已經意識到這個尺度差異

`search_similar_two_step()` 的第二階段（鄰居搜尋）刻意使用了獨立、寬鬆許多的門檻常數：

```python
# backend/services/qdrant_service.py:539-540（函式簽章）
neighbor_score_threshold: float = 0.1
```

註解明確寫道（[qdrant_service.py:547-548](../../backend/services/qdrant_service.py)）：「鄰居屬於補充性關聯內容，門檻獨立於核心搜尋的 `score_threshold`，預設較寬鬆，避免與核心搜尋同等嚴格的門檻把大部分鄰居過濾掉」。這印證了開發者已經知道 RRF/混合檢索分數不能直接套用核心搜尋的 `score_threshold`（0.65~0.7）——只是這個認知目前只反映在「鄰居搜尋」這一處，核心的 `search_similar()` 主查詢路徑（2.1 節）本身仍完全沒有套用任何門檻。

## 3. 影響範圍評估

| 使用情境 | 是否受影響 | 說明 |
|---|---|---|
| `search_type == "vector"`（純向量） | 否 | Qdrant 端已套用 `score_threshold`，回傳結果必定全部達標，分數尺度與門檻一致 |
| `search_type == "hybrid"` | **是** | 走 RRF 融合，無門檻過濾，分數尺度不匹配 |
| `search_type in ("semantic_hybrid", "semantic_hybrid_feedback", "semantic_hybrid_attachment")` | **是（且為本專案主力查詢法）** | 同上，且是 [CLAUDE.md](../../CLAUDE.md) 定義的 signature pipeline，使用頻率最高 |
| `search_type == "semantic_db_query"` | 不適用 | 完全不同資料流，沒有 `score`/`score_threshold` 概念 |
| 現有 RAG 對話功能本身（`rag.py` 的 `rag_chat_stream()`） | **目前無實際影響** | 現有程式碼從未把 `score >= score_threshold` 當作「是否放進 context」的過濾條件——`search_similar()`/`search_similar_two_step()` 回傳什麼就全部塞進 `context_parts`，所以這個尺度問題目前**不影響**使用者實際看到的 RAG 回答品質 |
| [檢索命中分析儀表板](NewFeaturesPlan_RetrievalStatsDashboardPlan.md) 規劃中的 `hit_count`／零命中判斷 | **是，直接失真** | 這是本問題被發現的起點，也是目前唯一一個會把 `score >= score_threshold` 當作判斷依據、且會被使用者看到聚合結果的功能 |

**關鍵結論**：這個尺度不匹配問題目前是「潛伏」狀態——不影響現有 RAG 對話的實際回答品質（因為現有流程不靠這個比較做過濾），但只要有任何新功能（如檢索命中儀表板）開始依賴 `score >= score_threshold` 做判斷，就會立刻在 `semantic_hybrid*` 查詢法上產生系統性錯誤結果。

## 4. 量化影響推估

以近似估算，若某知識庫的 `semantic_hybrid` 查詢在 RRF 融合下典型分數落在 0.01～0.05 區間，而 `score_threshold` 維持預設 0.65：

- 幾乎 100% 的 `semantic_hybrid*` 查詢都會被判定為 `hit_count == 0`（零命中）
- 儀表板上「近 7 日無命中問題比例」對主力查詢法會顯示接近 100%，而非反映真實的知識庫缺口情況
- 使用者若信任此指標並據此判斷「知識庫嚴重缺乏內容」，會做出錯誤的營運決策（例如誤判需要大量補充文件，但實際上檢索本身運作正常）

## 5. 待決方案選項

### 選項 A：對 `hybrid`／`semantic_hybrid*` 家族另外設計命中判斷邏輯，不比較絕對分數

不依賴 `score >= score_threshold`，改用排名或相對訊號判斷「是否命中」，例如：
- 只要 `total_candidates > 0`（RRF 有回傳任何候選）就視為命中，`total_candidates == 0` 才算零命中
- 或改採「候選數是否 ≥ 某個最小筆數」作為品質訊號

優點：不需要修改既有檢索管線（`qdrant_service.py`），風險最低，可與 [檢索命中分析儀表板](NewFeaturesPlan_RetrievalStatsDashboardPlan.md) 同批實作。
缺點：喪失「分數高低」這個更細緻的品質訊號，`avg_score`/`min_score`/`max_score` 這幾個統計欄位對 `hybrid` 系列仍然只有相對排名意義，無法跨查詢法比較（`semantic_hybrid` 的 0.03 不能拿來跟 `vector` 的 0.75 比較優劣）。

### 選項 B：儀表板上明確標註限制，命中率指標只對 `vector` 查詢法有意義

不改動任何檢索邏輯，`hit_count`/`score` 相關欄位維持記錄 RRF 原始分數，但在 [檢索命中分析儀表板](NewFeaturesPlan_RetrievalStatsDashboardPlan.md) 的 UI 與文件上明確加註「此指標目前僅反映 `vector` 查詢法」，`semantic_hybrid*` 的統計只呈現 `total_candidates`/零候選比例，不呈現「命中率」用詞。

優點：實作最簡單，誠實呈現限制。
缺點：儀表板對主力查詢法的可用性大打折扣，使用者仍可能誤讀（除非 UI 說明夠顯眼）。

### 選項 C：在 Qdrant 檢索層額外保留可比較的原始分數（例如改用純向量 cosine 分數做二次評分，或正規化 RRF 分數）

修改 `search_similar()`，讓 RRF 融合結果額外附帶一個「與 `score_threshold` 同尺度」的分數（例如：對 RRF 選出的候選，用其 dense 向量與 query 向量重新計算一次 cosine 相似度，作為獨立於排名融合的品質分數）。

優點：從根本解決尺度不一致問題，`avg_score` 等統計對所有查詢法都能保持一致語意，未來任何依賴 `score_threshold` 的功能都不用再顧慮這個陷阱。
缺點：需要修改 `search_similar()` 的回傳結構（新增欄位或調整 `score` 語意），影響面包含前端「來源片段」分數顯示（目前 UI 上呈現的 `RRF Score` 標籤，見 [rag.py:539](../../backend/routers/rag.py)）、[檢索測試頁](../../frontend/src/views/RetrievalTestView.vue) 等既有功能，需要更完整的回歸測試，工作量明顯高於 A/B。

**方案 C 內部還有一個未明講的分岔，需一併決議**：新算出的可比較分數，算出來之後要不要真的拿去過濾候選？

- **C-1（查詢層過濾）**：`search_similar()` 內部直接把重算分數 `< score_threshold` 的候選丟棄，行為對齊現有 `vector` 查詢法。但這會**改變 signature pipeline 現有的實際檢索行為**，不只是分數呈現變了——目前 RAG 對話流程從未把 `score >= score_threshold` 當作是否放進 context 的過濾條件（見第 3 節現況表格），採 C-1 會讓某些現在能進 context 但重算後未達門檻的候選被踢除，直接影響使用者現在看到的 RAG 回答內容，需要額外做回歸測試。
- **C-2（僅新增欄位，不過濾）**：`search_similar()` 回傳的候選集合與筆數完全不變，只是每筆多一個可比較分數欄位；要不要拿這個欄位跟 `score_threshold` 比、判斷「命中」，留給呼叫方（儀表板／評估功能）自己決定。不改變現有 RAG 對話的實際回答內容，風險與回歸測試範圍小很多。

## 6. 建議後續行動（決議前）

1. 在測試環境對至少一個知識庫執行 `semantic_hybrid` 查詢，實際記錄 `raw_results` 的 `score` 分布，驗證第 2.2 節的量級估算是否準確，作為決議依據的實測數據。
2. 待使用者從 A/B/C 三個方案中選定方向後，回填本文件第 7 節「決策紀錄」，並同步更新 [`NewFeaturesPlan_RetrievalStatsDashboardPlan.md`](NewFeaturesPlan_RetrievalStatsDashboardPlan.md) 第 0 節、第 8 節與 Batch 0/1 的對應內容。

## 7. 決策紀錄

**選定方案：方案 C，子選項 C-2**（於 `search_similar()` 為 `hybrid`／`semantic_hybrid*` 家族的候選額外附帶一個與 `score_threshold` 同尺度的可比較分數欄位；**不**在查詢層過濾候選、**不**改變現有回傳的候選集合與筆數）。

**理由**：
- 方案 A／B 只是繞開「`score` 與 `score_threshold` 尺度不匹配」這個根因、不觸及成因本身，長期仍會讓「分數高低」這個品質訊號對 `hybrid` 系列失去意義；方案 C 從根本解決尺度不一致，未來任何依賴 `score_threshold` 的功能都不用再顧慮這個陷阱。
- C 方案內部的 C-1／C-2 分岔中，選 C-2 是因為本問題的觸發點是[檢索命中儀表板](NewFeaturesPlan_RetrievalStatsDashboardPlan.md)的統計失真，不是 RAG 回答品質有問題；C-1 會改變 signature pipeline 現有的實際檢索行為（讓目前完全不受 `score_threshold` 過濾的 `semantic_hybrid*` 候選，第一次真的被門檻篩掉），影響面擴大到使用者現在看到的 RAG 回答內容本身，需要額外的回歸驗證，超出本問題需要解決的最小範圍。C-2 維持現有候選集合與筆數不變，只新增一個可比較欄位，風險與回歸測試範圍最小，且已經達成「讓分數可以正確比較」這個根本目的。
- 是否要進一步採用 C-1（查詢層真正過濾），列為**未來如有需要再獨立評估的議題**，不在本次決議範圍內。

**後續影響到的檔案／文件**：
- `backend/services/qdrant_service.py`：**必須同時涵蓋 `search_similar()` 與 `search_similar_two_step()` 兩處 RRF 分支**（原決議只涵蓋前者，屬遺漏，已於 2026-07-09 補正，見下方補充說明）。
  - `search_similar()` 的 RRF 融合路徑（`search_type in ["hybrid", "semantic_hybrid"]`，約 371-379 行）需在 `query_points` 呼叫加上 `with_vectors=[""]`（**不要用 `with_vectors=True`**，見下方補充說明）取回候選密集向量，並在結果轉換階段（約 413 行起的 `temp_results` 迴圈）用候選向量與 `query_vector` 重新計算 cosine 相似度，寫入新欄位（暫定命名 `semantic_score`，待實作時確認是否與既有欄位命名慣例衝突）。原本的 RRF `score` 欄位維持不變、不覆蓋。
  - `search_similar_two_step()` 的第二階段鄰居搜尋（約 600-710 行）需比照辦理：該段落的 RRF 融合查詢（約 642-648 行）同樣要重算 cosine；結果包裝迴圈（約 682-710 行）目前是獨立組裝 `neighbor_results` 字典、完全不經過 `search_similar()` 的轉換邏輯，需另外補上 `semantic_score` 欄位，否則核心片段（1st-hop）與鄰居片段（2nd-hop）會出現「一個有分數、一個沒有」的不一致。
  - 所有分支（`search_similar()` 的 RRF／fallback／常規向量三條路徑，以及 `search_similar_two_step()` 鄰居搜尋的 RRF／純向量／scroll 三條路徑）都必須統一寫入 `semantic_score`，映射規則為：**RRF 分支** → 重算 cosine；**fallback／常規／鄰居純向量分支** → 因 `score` 本身即為 cosine，直接 `semantic_score = score`；**無向量的 scroll 分支** → `semantic_score = None`。缺一不可，否則下游（尤其是 `RetrievalStatsDashboardPlan` 的 `avg_score`/`min_score`/`max_score` 聚合）會因為部分候選缺欄位而失真。
  - 實作細節：本 collection 同時有預設密集向量（未命名，`using=""`）與具名的 `sparse-text` 稀疏向量（見 22-49 行 `create_collection`），若誤用 `with_vectors=True` 會連稀疏向量一起拉回、且 `point.vector` 會是 `dict`（如 `{"": [...], "sparse-text": ...}`）而非 `list`，直接餵給 cosine 計算會出錯；務必用 `with_vectors=[""]` 只取密集向量，並在計算前判斷 `vector.get("") if isinstance(vector, dict) else vector`。
- `backend/services/rerank_service.py`、`backend/services/feedback_boost_service.py`：本次決議範圍**不**修改（兩者皆以整個 dict 原地重排/加權，`semantic_score` 欄位會自然隨候選一起保留，不需額外處理）。
- `backend/config.py`：本次決議範圍**不**新增設定項。
- `backend/schemas/retrieval.py`、`backend/routers/retrieval.py`：**本次決議範圍不修改**。`RetrievalResultItem` 目前無 `semantic_score` 欄位，且 `routers/retrieval.py` 是逐欄位具名建構 Pydantic 物件，若未來要讓 `/api/retrieval/search`（檢索測試頁）也能讀到此分數供調試，需要另案評估——這與本次決議刻意縮小範圍（見下方前端項）的原則一致，非本次必要項。
- 前端 `RRF Score` 標籤（[rag.py:539](../../backend/routers/rag.py) 對應的前端顯示邏輯）：本次決議範圍**不**變更顯示邏輯，新欄位暫不上前端呈現。
- [`NewFeaturesPlan_RetrievalStatsDashboardPlan.md`](NewFeaturesPlan_RetrievalStatsDashboardPlan.md)：需同步更新第 0 節、第 8 節與 Batch 0/1，改為依賴新的 `semantic_score` 欄位（而非 RRF 原始 `score`）判斷 `hit_count`／零命中；且該文件 `RetrievalStatsService.record()` 的草稿（`scores = [item.get("score", 0.0) for item in raw_results]`）需同步改為讀取 `semantic_score`，本文件的修正需視為該規劃文件 Batch 1 的前置依賴。

**實作前建議動作**（沿用第 6 節）：於測試環境對至少一個知識庫的 `semantic_hybrid` 查詢實際印出候選的重算 cosine 分數分布，確認落點是否符合 `score_threshold`（0.65～0.7）的預期尺度，作為後續 `RetrievalStatsDashboardPlan` 判斷「命中」邏輯的驗證依據。

**決議日期**：2026-07-09（初次決議：選定方案 C-2）／2026-07-09（補充修正：經第二方 AI 審查意見交叉驗證後，補上 `search_similar_two_step()` 二階 RRF 分支的遺漏範圍、統一分數映射規則、`with_vectors` 實作細節；審查建議中「擴大修改 `schemas/retrieval.py`／`routers/retrieval.py` 讓前端可讀」與「numpy 缺失時的純 Python fallback」兩項經評估後不採納，前者超出本次刻意縮小的範圍、後者屬不會發生情境的過度防禦）
