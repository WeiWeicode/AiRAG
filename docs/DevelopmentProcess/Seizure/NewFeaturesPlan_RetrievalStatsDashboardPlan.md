# 檢索命中分析儀表板（Retrieval Stats Dashboard）規劃文件

> 狀態：規劃中，待使用者確認後執行
> 影響範圍：新檔案 `backend/models/retrieval_stats.py`（新 MongoDB collection）、`backend/routers/rag.py`（新增 best-effort 寫入點）、新檔案 `backend/routers/dashboard.py`（新增讀取/聚合端點）、`frontend/src/views/DashboardView.vue`（新增統計卡片）。**不修改**既有 `ChatMessage.source_chunks` 結構與寫入邏輯，也不影響既有 SSE 串流的正常/異常路徑。

## 1. 目標與範圍

### 目標
新增一個獨立的檢索命中統計儀表板，讓使用者能主動發現「哪些問題常檢索不到／分數偏低」，而非被動等待使用者透過 `feedback.py` 回報問題。統計資料寫入一個**新的、獨立的** MongoDB collection（`RetrievalStats`），在 `rag_chat_stream()` 完成檢索之後、以 best-effort（非阻塞、失敗不影響主流程）方式寫入，並在既有 `DashboardView.vue` 的 Quick Stats Grid 機制中新增 1-2 張統計卡片呈現聚合結果。

**已確認的技術方向（使用者決策，非待討論項）**：使用**新的、獨立的 MongoDB `RetrievalStats` beanie collection**，**不重用**既有 `ChatMessage.source_chunks`（[chat_message.py:12-17](../../backend/models/chat_message.py)）。理由：`ChatMessage.source_chunks` 目前缺少 `knowledge_base_id`／`search_type` 這兩個做聚合分析必要的維度欄位，且 `ChatMessage` 的主要用途是「還原對話畫面」，若把統計查詢的聚合邏輯疊加在同一個 collection 上，容易讓該 collection 的索引設計、查詢模式互相干擾，獨立 collection 更符合單一職責。

### 明確不動的部分
- `ChatMessage`／`SourceChunk`（[chat_message.py](../../backend/models/chat_message.py)）結構與既有寫入邏輯（供對話畫面還原、回饋機制比對來源片段用）**完全不修改**，新的 `RetrievalStats` 是額外並行寫入的獨立紀錄，兩者資料有重疊（都來自同一次檢索結果）但服務不同目的，允許輕度冗餘。
- `rag_chat_stream()` 既有的 SSE 事件流程（`step`/`chunk`/`sources`/`done`）**完全不變**，新增的統計寫入是在既有流程「之外」附加的旁路動作，即使寫入失敗也不能讓既有事件延遲或中斷（見第 6 節「執行流程設計」的 best-effort 要求）。
- `DashboardView.vue` 既有 `stats` 陣列機制（[DashboardView.vue:8-13](../../frontend/src/views/DashboardView.vue)）與 `fetchDashboardStats()`（[DashboardView.vue:15-35](../../frontend/src/views/DashboardView.vue)）**沿用同一套機制新增卡片**，不新增獨立的分析頁面/路由。

## 2. 名詞定義

| 名詞 | 說明 |
|---|---|
| `RetrievalStats` | 新增的 MongoDB beanie Document，每次檢索（無論是否命中）記錄一筆統計資料，獨立於 `ChatMessage`。 |
| 命中率（Hit Rate） | 檢索結果中，`score >= score_threshold` 的筆數占比；`hit_count == 0` 代表本次完全沒有命中任何內容（知識庫內容缺口的強訊號）。 |
| 無命中問題（Zero-Hit Query） | `hit_count == 0` 的檢索紀錄，是本儀表板最重要的關注指標之一。 |

## 3. 架構／資料模型設計

### 3.1 新 MongoDB Document：`backend/models/retrieval_stats.py`

比照 `backend/models/feedback.py`（[feedback.py:10-33](../../backend/models/feedback.py)）的既有 beanie 慣例（`Document`、`Field(default_factory=...)` 時間戳、`class Settings` 含 `name`/`indexes`）：

```python
from datetime import datetime
from typing import Optional, List
from beanie import Document, Indexed
from pydantic import Field

class RetrievalStats(Document):
    knowledge_base_id: Optional[str] = None
    search_type: str
    question: str
    top_k: int
    score_threshold: float
    retrieved_scores: List[float] = Field(default_factory=list)  # 本次所有候選片段的原始分數
    hit_count: int = 0            # score >= score_threshold 的筆數
    total_candidates: int = 0     # 本次檢索到的候選總數（去重合併前後擇一，見第 8 節待確認事項）
    avg_score: Optional[float] = None
    min_score: Optional[float] = None
    max_score: Optional[float] = None
    elapsed_ms: Optional[int] = None   # 檢索耗時（不含最終 LLM 生成時間）
    session_id: Optional[str] = None   # 選填，供未來需要時關聯回具體對話
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "retrieval_stats"
        indexes = [
            "knowledge_base_id",
            "search_type",
            "-created_at",
            [("knowledge_base_id", 1), ("created_at", -1)]
        ]
```

- `retrieved_scores` 保留完整分數陣列（而非只存聚合值），讓未來若需要更細緻的分數分布分析（例如直方圖）時不需要重新設計 schema，只是額外多一點儲存空間。
- 需在 `backend/models/mongodb.py` 的 `init_beanie(document_models=[...])` 清單新增 `RetrievalStats`（比照現有 14 個 collection 的註冊方式，[04_DB_SCHEMA.md](../../docs/04_DB_SCHEMA.md) 提到的既有註冊清單模式）。

### 3.2 寫入時機與位置

`backend/routers/rag.py` 的 `rag_chat_stream()` 中，在完成檢索（`raw_results` 已取得，[rag.py:379-436](../../backend/routers/rag.py) 兩種分支任一執行完畢）、組完 `context_parts`/`sources`（[rag.py:438 起](../../backend/routers/rag.py)）之後，新增一個 best-effort 寫入呼叫。**寫在 `try/except` 包裹的獨立區塊**，比照本專案「附件刪除時的清理」best-effort 慣例（失敗只記錄 warning，不拋出、不影響主流程）：

```python
try:
    await RetrievalStatsService.record(
        knowledge_base_id=request.knowledge_base_id,
        search_type=search_type,
        question=question,
        top_k=top_k,
        score_threshold=score_threshold,
        raw_results=raw_results if 'raw_results' in dir() else [],
        elapsed_ms=retrieval_elapsed_ms
    )
except Exception as stats_err:
    logger.warning(f"[RetrievalStats] 統計寫入失敗（不影響本次對話流程）: {stats_err}")
```

- `search_type == "semantic_db_query"` 分支（[rag.py:264-271](../../backend/routers/rag.py)）走的是完全不同的資料流（`db_query_result`），沒有 `raw_results`／`score` 概念，本次規劃**先不涵蓋**這個查詢法的統計（見第 8 節待確認事項），寫入呼叫只放在 `elif request.knowledge_base_id:` 分支內（[rag.py:272](../../backend/routers/rag.py) 之後）。
- 抽成獨立 Service（`backend/services/retrieval_stats_service.py`）而非直接在 `rag.py` 內組裝 Document，比照 `AIDBQueryService`／`ContextSummarizerService` 的既有分層慣例，讓聚合計算邏輯（`hit_count`/`avg_score` 等）可獨立單元測試，也方便未來若要在 `retrieval.py`（檢索測試頁）比照記錄時重用同一套邏輯：

```python
class RetrievalStatsService:
    @classmethod
    async def record(cls, knowledge_base_id, search_type, question, top_k,
                      score_threshold, raw_results, elapsed_ms=None, session_id=None):
        scores = [item.get("score", 0.0) for item in raw_results]
        hit_count = sum(1 for s in scores if s >= score_threshold)
        stats = RetrievalStats(
            knowledge_base_id=knowledge_base_id,
            search_type=search_type,
            question=question,
            top_k=top_k,
            score_threshold=score_threshold,
            retrieved_scores=scores,
            hit_count=hit_count,
            total_candidates=len(raw_results),
            avg_score=(sum(scores) / len(scores)) if scores else None,
            min_score=min(scores) if scores else None,
            max_score=max(scores) if scores else None,
            elapsed_ms=elapsed_ms,
            session_id=session_id
        )
        await stats.insert()
```

- **非阻塞要求**：`await stats.insert()` 是一次 MongoDB 寫入，延遲通常在毫秒級，可接受直接 `await`（不需要額外 fire-and-forget 背景任務機制）；但整段包在 `try/except` 內，寫入異常（例如 Mongo 暫時不可用）只記錄 warning，**絕不 raise**，確保 SSE 串流不受影響，符合「fail loudly but don't break the primary flow」慣例（比照附件刪除清理功能的既有做法：失敗記警告 log，主流程繼續）。

## 4. API 設計

新檔案 `backend/routers/dashboard.py`（掛在 `/api/dashboard`，需 `Depends(get_current_user)`）：

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/dashboard/retrieval-stats/summary` | 回傳聚合摘要：近 N 天（可用 query param `days`，預設 7）的「總檢索次數」「無命中問題數（zero-hit）」「平均分數」「依知識庫分組的平均分數」 |
| GET | `/api/dashboard/retrieval-stats/zero-hit-questions` | 回傳近 N 天內 `hit_count == 0` 的問題清單（分頁），供使用者具體檢視是哪些問題查無結果，方便針對性補充知識庫內容 |

`summary` 端點回應範例：

```json
{
  "period_days": 7,
  "total_queries": 342,
  "zero_hit_count": 28,
  "zero_hit_rate": 0.082,
  "avg_score": 0.71,
  "by_knowledge_base": [
    { "knowledge_base_id": "xxx", "knowledge_base_name": "HR文件庫", "avg_score": 0.68, "total_queries": 120 }
  ]
}
```

聚合邏輯使用 MongoDB aggregation pipeline（`$match` 依 `created_at` 篩選期間 → `$group` 依 `knowledge_base_id` 分組），效能上因為 `retrieval_stats` 是獨立小型 collection（不涉及 Qdrant 向量查詢），不需要額外快取機制即可接受。

## 5. 前端設計

### 5.1 `DashboardView.vue` 新增統計卡片

沿用既有 `stats` ref 陣列機制（[DashboardView.vue:8-13](../../frontend/src/views/DashboardView.vue)），新增 2 筆：

```js
const stats = ref([
  { id: 'kbs', label: '知識庫總數', ... },
  { id: 'feedback', label: '人工標註筆數', ... },
  { id: 'faithfulness', label: '綜合忠實度 (Faithfulness)', ... },
  { id: 'evaluations', label: '已執行自動評估', ... },
  // 新增
  { id: 'zero_hit_rate', label: '近7日無命中問題比例', value: '0%', desc: 'Zero-Hit Query Rate (7d)', icon: '<circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line>' },
  { id: 'avg_retrieval_score', label: '近7日平均檢索分數', value: '0.00', desc: 'Avg Retrieval Score (7d)', icon: '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline>' }
])
```

`fetchDashboardStats()`（[DashboardView.vue:15-35](../../frontend/src/views/DashboardView.vue)）比照既有 `kbs`／`feedback` 兩筆的 `try/catch` 獨立呼叫模式，新增第三個獨立 `try/catch` 區塊呼叫 `GET /api/dashboard/retrieval-stats/summary`：

```js
try {
  const statsResponse = await api.get('/api/dashboard/retrieval-stats/summary?days=7')
  if (statsResponse.data) {
    const zeroHitStat = stats.value.find(s => s.id === 'zero_hit_rate')
    if (zeroHitStat) zeroHitStat.value = `${(statsResponse.data.zero_hit_rate * 100).toFixed(1)}%`
    const avgScoreStat = stats.value.find(s => s.id === 'avg_retrieval_score')
    if (avgScoreStat) avgScoreStat.value = statsResponse.data.avg_score?.toFixed(2) || '0.00'
  }
} catch (error) {
  console.error('Failed to fetch retrieval stats:', error)
}
```

- 沿用既有卡片渲染樣式，**不需要修改 Quick Stats Grid 的排版邏輯**，因為卡片渲染是對 `stats` 陣列做 `v-for`（沿用既有 `DashboardView.vue` 模板，此處僅新增資料，不動渲染程式碼）。
- `/api/dashboard/retrieval-stats/zero-hit-questions` 端點暫不在本次 Dashboard 首頁呈現詳細清單（首頁只放彙總數字卡片），若使用者需要點擊卡片下鑽看到具體問題清單，屬於後續擴充（例如新增一個獨立的「檢索分析」子頁面），見第 8 節待確認事項。

## 6. 執行流程設計

```
使用者於 RAG 對話測試發送問題
  │
  ▼
rag_chat_stream()：完成向量檢索（vector/hybrid/semantic_hybrid* 任一分支，raw_results 已取得）
  │
  ▼
組完 context_parts / sources（既有邏輯，[rag.py:438 起]，完全不變）
  │
  ▼
【新增旁路】try: RetrievalStatsService.record(...) 寫入 RetrievalStats
  │
  ├─ 寫入成功 → 靜默完成，不影響任何既有 SSE 事件時序
  │
  └─ 寫入失敗（Mongo 暫時不可用等）→ except 捕捉，logger.warning 記錄，不 raise
        → 對使用者完全透明，主流程（LLM 生成、SSE 串流）不受任何影響
  │
  ▼
既有流程繼續：LLM 生成回答、SSE sources/done 事件（完全不變）

──────────────────────────────────────────────

（非同步/獨立時機）使用者開啟 Dashboard 首頁
  │
  ▼
fetchDashboardStats() 呼叫 GET /api/dashboard/retrieval-stats/summary?days=7
  │
  ▼
後端執行 MongoDB aggregation：$match(created_at >= now-7d) → $group(knowledge_base_id)
  → 計算 total_queries / zero_hit_count / zero_hit_rate / avg_score
  │
  ▼
前端更新兩張新統計卡片（無命中問題比例／平均檢索分數）
```

## 7. 新增設定值（`backend/config.py`）

| 變數 | 預設值 | 用途 |
|---|---|---|
| `DASHBOARD_STATS_DEFAULT_PERIOD_DAYS` | `7` | `GET /api/dashboard/retrieval-stats/summary` 未帶 `days` 參數時的預設統計期間 |
| `RETRIEVAL_STATS_ENABLED` | `True` | 是否啟用統計寫入的總開關（設為 `False` 時 `RetrievalStatsService.record()` 直接 no-op 返回，供未來若統計寫入造成非預期負擔時可快速關閉，不需改程式碼重新部署） |

## 8. 決策紀錄／待確認事項

**已確認（本次規劃前提，使用者決策）**：
- 使用**新的、獨立的 MongoDB `RetrievalStats` beanie collection**，不重用/擴充既有 `ChatMessage.source_chunks` 結構。
- 統計寫入採 best-effort（非阻塞、失敗僅記錄警告不中斷主流程），沿用本專案既有「不讓周邊功能拖垮核心 SSE 對話流程」的一貫慣例。
- Dashboard 呈現方式沿用 `DashboardView.vue` 既有 `stats` 陣列/Quick Stats Grid 機制新增卡片，不新增獨立分析頁面。

**待使用者確認的開放問題**：
1. **`semantic_db_query` 查詢法是否也要記錄統計**：目前規劃排除在外（因其資料流完全不同，沒有 `score`/`raw_results` 概念），若使用者希望未來也能看到「資料庫查詢的命中率」，需要另外設計適用於 SQL 查詢結果的統計維度（例如 `row_count == 0` 視為無命中），屬於本功能的自然延伸，建議列為第二階段。
2. **`total_candidates` 的計算基準**：目前 `search_similar()` 內部有「去重合併前」與「去重合併後（[qdrant_service.py:459](../../backend/services/qdrant_service.py) 的 `deduped_results[:top_k]`）」兩種候選數量，本規劃預設記錄的是傳入 `RetrievalStatsService.record()` 的 `raw_results`（即去重合併後、最終回傳給 `rag.py` 的結果），若使用者希望改記錄「合併前的原始 Qdrant 命中數」以更精準反映向量資料庫本身的召回能力，需要額外從 `search_similar()` 內部傳出這個中繼數字（目前該方法不對外暴露這個中繼值），需要評估是否值得為此修改既有方法的回傳結構。
3. **零命中清單端點（`zero-hit-questions`）是否需要在本次一併做前端呈現**：本文件規劃了 API 但前端首頁暫不呈現詳細清單（只放彙總卡片），若使用者希望能點擊卡片直接下鑽看到問題清單，需要額外規劃一個新的前端頁面/彈窗元件，屬於範圍擴充，待確認是否要納入本次 Batch 3。
4. **是否需要依「知識庫」維度在 Dashboard 卡片上做篩選**（目前彙总卡片是全站合併統計，`by_knowledge_base` 陣列目前只在 API 回應中存在但前端未消費），待確認是否需要在本次一併呈現，或留待後續擴充。

## 9. 分階段實作 Checklist

### Batch 1：後端核心邏輯
- [ ] `backend/models/retrieval_stats.py`（新模型）+ 註冊進 `backend/models/mongodb.py` 的 `document_models`
- [ ] `backend/config.py` 新增 `DASHBOARD_STATS_DEFAULT_PERIOD_DAYS`／`RETRIEVAL_STATS_ENABLED`
- [ ] `backend/services/retrieval_stats_service.py`（新服務，`record()` 聚合計算 + best-effort 寫入）
- [ ] `backend/routers/rag.py`：`rag_chat_stream()` 於檢索完成後新增 try/except 包裹的 `RetrievalStatsService.record()` 呼叫（僅 `vector`/`hybrid`/`semantic_hybrid*` 家族，`semantic_db_query` 依第 8 節待確認事項 1 決定是否納入）

### Batch 2：API／Schema 串接
- [ ] `backend/routers/dashboard.py`（新檔，`GET /retrieval-stats/summary`／`GET /retrieval-stats/zero-hit-questions`，含 MongoDB aggregation pipeline）
- [ ] 於 `backend/main.py`（或既有 router 註冊處）掛載新的 `dashboard` router

### Batch 3：前端 UI
- [ ] `frontend/src/views/DashboardView.vue`：`stats` 陣列新增「無命中問題比例」「平均檢索分數」兩筆，`fetchDashboardStats()` 新增獨立 try/catch 呼叫新端點
- [ ] （依第 8 節待確認事項 3）視需要新增零命中問題清單的下鑽檢視元件

### Batch 4：文件更新
- [ ] `docs/03_API_CONTRACT.md`：補上 `GET /api/dashboard/retrieval-stats/summary`／`GET /api/dashboard/retrieval-stats/zero-hit-questions` 兩個新端點說明
- [ ] `docs/04_DB_SCHEMA.md`：補上 `retrieval_stats` collection 的 schema 與索引說明，更新 MongoDB collection 總覽圖與 14→15 個 collection 的計數
- [ ] `docs/DevelopmentProcess/NewFeatures.md`：實作完成後記錄本次新增
