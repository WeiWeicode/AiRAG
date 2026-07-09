<!-- BUG修正(最新紀錄放最前面) -->

## 2026-07-09 RRF 混合檢索分數與 Score Threshold 尺度不匹配修正

### 背景
依規劃文件 [NewFeaturesPlan_RRFScoreThresholdMismatchPlan.md](NewFeaturesPlan_RRFScoreThresholdMismatchPlan.md) 實作（已決議方案 C-2）。`QdrantService.search_similar()`／`search_similar_two_step()` 在 `search_type in ["hybrid", "semantic_hybrid"]` 時走 Qdrant RRF 融合查詢，回傳的 `score` 是排名融合分數，量級與本專案用來表示「cosine 相似度是否達標」的 `score_threshold`（預設 0.65～0.7）不同尺度，任何把 `score >= score_threshold` 當作命中判斷依據的邏輯在 `hybrid`／`semantic_hybrid*`（本專案 signature pipeline）上都會系統性失真。此問題是在規劃[檢索命中分析儀表板](NewFeaturesPlan_RetrievalStatsDashboardPlan.md)時發現，該功能的 Batch 1 依賴本次修正結果。

### 變更內容
- `backend/services/qdrant_service.py`：
  - 新增三個 helper：`_extract_dense_vector()`（從 `point.vector` 取出預設密集向量，處理多向量 collection 回傳 `dict` 的情況）、`_cosine_similarity()`（純 Python 實作，未新增 numpy 依賴）、`_compute_semantic_score()`（重算候選與查詢向量的 cosine 相似度）。
  - `search_similar()` 與 `search_similar_two_step()` 的 RRF 融合查詢（`query_points` 呼叫）皆加上 `with_vectors=[""]`（只取回預設密集向量，避免連 `sparse-text` 稀疏向量一併拉回、避免 `point.vector` 型態變成不可直接運算的 `dict`），並在各自的結果轉換迴圈為每筆候選新增 `semantic_score` 欄位：RRF 分支重算 cosine；純向量分支因 `score` 本身即為 cosine，直接沿用；無查詢向量的 scroll 分支則為 `None`。
  - `search_similar_two_step()` 的第二階段鄰居搜尋（獨立組裝 `neighbor_results`，不經過 `search_similar()` 的轉換邏輯）比照辦理，確保核心片段（1st-hop）與鄰居片段（2nd-hop）都有一致的 `semantic_score`。
  - 原本的 RRF `score` 欄位完全不變、不覆蓋；候選集合與筆數不變，未在查詢層套用任何過濾（決議方案 C-2，非 C-1）。
- `rerank_service.py`／`feedback_boost_service.py`／`config.py`／前端「RRF Score」顯示邏輯／`schemas/retrieval.py`／`routers/retrieval.py`：本次決議範圍不修改（決策理由見規劃文件第 7 節）。
- 同步更新 [NewFeaturesPlan_RetrievalStatsDashboardPlan.md](NewFeaturesPlan_RetrievalStatsDashboardPlan.md) 第 0/2/3.1/3.2/8/9 節，改為依賴新的 `semantic_score` 欄位判斷 `hit_count`／零命中。

### 驗證
- `python -m ast` 語法檢查通過；於 host `.venv` 單元測試 `_cosine_similarity`／`_extract_dense_vector`／`_compute_semantic_score` 三個 helper 的邊界情況（相同向量→1.0、正交向量→0.0、`dict`／`list`／`None` 輸入）皆正確。
- 於容器 `airag-backend`（fastembed 可正常載入，走真正的 RRF 路徑而非 fallback）對既有知識庫 collection（`kb_6a389dc83578b9d3d717244d`）執行實測：`search_similar(search_type="semantic_hybrid")`、`search_similar(search_type="vector")`、`search_similar_two_step(search_type="semantic_hybrid")` 三者皆正確回傳 `semantic_score`。實測同時證實 RRF `score` 與重算後 `semantic_score` 確實不具線性關係（例：RRF 排名第 1 的候選 `score=1.0` 但 `semantic_score≈0.75`；另一筆 `score=0.5` 的候選反而 `semantic_score=1.0`，恰為查詢向量本身的來源點位），驗證了本次修正的必要性與正確性。純向量路徑（`search_type="vector"`）驗證 `semantic_score == score` 恆成立。
- 未自行開瀏覽器測試前端；容器內程式碼已透過 bind mount 生效，但 `airag-backend` 進程沿用啟動時載入的舊模組，需重啟該容器（`docker compose restart backend` 或等其他變更一併重建）後，實際 API 呼叫才會使用新程式碼，留待使用者決定重啟時機。

