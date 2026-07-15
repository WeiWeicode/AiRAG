# 檢索命中分析儀表板（Retrieval Stats Dashboard）規劃文件

> 狀態：**已實作完成**（2026-07-09，Batch 0-4 全數完成，見 [NewFeatures.md](NewFeatures.md) 2026-07-09 對應紀錄）。`airag-backend` 容器需重啟才會實際套用後端變更，前端已 `npm run build` 驗證通過。
> 影響範圍：新檔案 `backend/models/retrieval_stats.py`（新 MongoDB collection）、`backend/routers/rag.py`（新增 best-effort 寫入點）、新檔案 `backend/routers/dashboard.py`（新增讀取/聚合端點）、`frontend/src/views/DashboardView.vue`（新增統計卡片與零命中清單下鑽 UI）。**不修改**既有 `ChatMessage.source_chunks` 結構與寫入邏輯，也不影響既有 SSE 串流的正常/異常路徑。

## 0. 前置阻塞事項（Blocking Issue）—— 已決議且已實作完成

[`NewFeaturesPlan_RRFScoreThresholdMismatchPlan.md`](NewFeaturesPlan_RRFScoreThresholdMismatchPlan.md) 記錄的嚴重問題（`hybrid`／`semantic_hybrid*` 家族回傳的 `score` 是 Qdrant RRF 融合分數，與本文件 `hit_count` 判斷所依賴的 `score_threshold` 0.65～0.7 不同尺度）**已於 2026-07-09 決議採用方案 C-2 並完成實作**：`backend/services/qdrant_service.py` 的 `search_similar()` 與 `search_similar_two_step()` 會為每一筆候選（無論 RRF／純向量／scroll 分支）統一新增一個與 `score_threshold` 同尺度的 `semantic_score` 欄位（RRF 分支重算 cosine；純向量分支因 `score` 本身已是 cosine，直接 `semantic_score = score`；scroll 分支 `semantic_score = None`），**不**在查詢層過濾候選、**不**改變既有 `score`／候選集合。已於容器內對真實知識庫 collection 實測驗證：RRF `score` 與重算後 `semantic_score` 確實不具線性關係（例如 RRF 排名第 1 的候選 `semantic_score` 反而低於排名較後的候選），證實兩者不可互相替代。詳細成因、程式碼佐證與決策紀錄見獨立文件第 7 節、[BugFix.md](BugFix.md) 2026-07-09 對應紀錄。

**對本文件的具體影響**：`hit_count`／零命中判斷公式改為統一使用 `semantic_score >= score_threshold`（而非原本的 `score >= score_threshold`），此公式現在對**所有**查詢法（`vector`／`hybrid`／`semantic_hybrid*`）都同尺度成立，不再需要「只對 vector 成立」的限定說明。**注意**：`airag-backend` 容器目前執行中的進程仍是修改前載入的舊模組（`uvicorn` 未帶 `--reload`），需重啟容器後 API 才會實際套用新程式碼；Batch 1 開發時若要對真實 API 驗證 `semantic_score` 欄位存在，記得先重啟或重建 `backend` 容器。

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
| 命中率（Hit Rate） | 檢索結果中，`semantic_score >= score_threshold` 的筆數占比；`hit_count == 0` 代表本次完全沒有命中任何內容（知識庫內容缺口的強訊號）。 |
| 無命中問題（Zero-Hit Query） | `hit_count == 0` 的檢索紀錄，是本儀表板最重要的關注指標之一。 |
| `semantic_score` | [`NewFeaturesPlan_RRFScoreThresholdMismatchPlan.md`](NewFeaturesPlan_RRFScoreThresholdMismatchPlan.md) 決議新增的欄位，與 `score_threshold` 同尺度（cosine 相似度範圍）；`vector`/`hybrid`/`semantic_hybrid*` 皆會統一提供此欄位，取代原本量級不一致的 `score` 作為命中判斷依據。 |

> ✅ 上述「命中率」定義現在對**所有**查詢法（`vector`／`hybrid`／`semantic_hybrid*`）都同尺度成立，因為每個查詢分支都會統一提供 `semantic_score`（見第 0 節）。**前提是** [`NewFeaturesPlan_RRFScoreThresholdMismatchPlan.md`](NewFeaturesPlan_RRFScoreThresholdMismatchPlan.md) 的程式碼修改已實際落地——本文件的 Batch 1 不可早於該修改完成。

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
    retrieved_scores: List[float] = Field(default_factory=list)  # 本次所有候選片段的 semantic_score（與 score_threshold 同尺度，非原始 RRF score，見第 0 節）
    hit_count: int = 0            # semantic_score >= score_threshold 的筆數
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

`backend/routers/rag.py` 的 `rag_chat_stream()` 中，在完成檢索（`raw_results` 已取得，[rag.py:411-421](../../backend/routers/rag.py) 或 [rag.py:457-465](../../backend/routers/rag.py) 兩種分支任一執行完畢）、組完 `context_parts`/`sources`（[rag.py:467-550](../../backend/routers/rag.py)）之後，新增一個 best-effort 寫入呼叫。**寫在 `try/except` 包裹的獨立區塊**，比照本專案「附件刪除時的清理」best-effort 慣例（失敗只記錄 warning，不拋出、不影響主流程）。
> 行號會隨後續功能合併持續位移（例如本文件初版引用的行號已因 Rerank／回饋加權／附件查詢法等後續功能而過時），實作時請以當下程式碼實際結構重新定位插入點，不可完全依賴此處引用。

```python
try:
    await RetrievalStatsService.record(
        knowledge_base_id=request.knowledge_base_id,
        search_type=search_type,
        question=question,
        top_k=top_k,
        score_threshold=score_threshold,
        raw_results=raw_results,
        elapsed_ms=None  # 已決議：本次不新增額外計時邏輯，先留空，見第 8 節決策紀錄
    )
except Exception as stats_err:
    logger.warning(f"[RetrievalStats] 統計寫入失敗（不影響本次對話流程）: {stats_err}")
```

- 為避免「寫入點若被放在例外路徑之後、`raw_results` 尚未賦值」的邊界情況，實作時應在 `elif request.knowledge_base_id:` 分支開頭（[rag.py:293](../../backend/routers/rag.py) 之後）明確初始化 `raw_results: list = []`，而非用 `'raw_results' in dir()` 這類不直觀的存在性檢查寫法。
- `search_type == "semantic_db_query"` 分支（[rag.py:285-292](../../backend/routers/rag.py)）走的是完全不同的資料流（`db_query_result`），沒有 `raw_results`／`score` 概念。**已決議：本次不記錄此查詢法的統計**（見第 8 節決策紀錄），寫入呼叫只放在 `elif request.knowledge_base_id:` 分支內（[rag.py:293](../../backend/routers/rag.py) 之後）。
- 抽成獨立 Service（`backend/services/retrieval_stats_service.py`）而非直接在 `rag.py` 內組裝 Document，比照 `AIDBQueryService`／`ContextSummarizerService` 的既有分層慣例，讓聚合計算邏輯（`hit_count`/`avg_score` 等）可獨立單元測試，也方便未來若要在 `retrieval.py`（檢索測試頁）比照記錄時重用同一套邏輯：

```python
class RetrievalStatsService:
    @classmethod
    async def record(cls, knowledge_base_id, search_type, question, top_k,
                      score_threshold, raw_results, elapsed_ms=None, session_id=None):
        # 讀 semantic_score（而非原始 score）：qdrant_service.py 已統一為所有查詢法/分支
        # 補上此欄位（RRF 分支重算 cosine、純向量分支直接沿用 score），故此處不需再依
        # search_type 分流計算方式，見 NewFeaturesPlan_RRFScoreThresholdMismatchPlan.md 第 0/7 節
        scores = [item.get("semantic_score", 0.0) for item in raw_results]
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

**`knowledge_base_name` 解析機制**：`RetrievalStats`（3.1 節）只存 `knowledge_base_id`，不存名稱，因此 `summary` 回應中 `by_knowledge_base[].knowledge_base_name`、以及 `zero-hit-questions` 清單中每筆問題的「所屬知識庫」（見 5.2 節）都需要額外解析。採用**記憶體 ID→Name 對照表**：在 `dashboard.py` 端點內先呼叫 `KnowledgeBase.find_all().to_list()` 取得全部知識庫，建立 `{str(kb.id): kb.name}` 的字典，再對聚合/查詢結果逐筆比對填入名稱。不使用 MongoDB `$lookup` 聯表——本專案知識庫數量規模小（個位數至數十個），記憶體對照表更簡單且與既有程式碼慣例一致（[rag.py:295-296](../../backend/routers/rag.py) 也是以 `str` 形式的 `knowledge_base_id` 操作）。若對應的知識庫已被刪除（`knowledge_base_id` 在對照表中找不到），`knowledge_base_name` 回傳 `null`／`"(已刪除)"` 皆可，實作時擇一即可，不影響其他欄位。

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
- **已決議：本次維持全站合併統計，不依「知識庫」維度調整卡片**。`by_knowledge_base` 欄位 API 仍會回傳（供未來擴充），但前端首頁不消費、不呈現任何依知識庫拆分的 UI。

### 5.2 零命中問題清單下鑽（已決議：本次一併實作）

**已決議**：使用者需要能點擊「近7日無命中問題比例」卡片，下鑽檢視具體是哪些問題查無結果，不只是看彙總數字。

- 於 `zero_hit_rate` 卡片（[DashboardView.vue:163](../../frontend/src/views/DashboardView.vue) 新增的項目）加上點擊事件，開啟一個 Modal／側邊面板元件，呼叫 `GET /api/dashboard/retrieval-stats/zero-hit-questions?days=7`（分頁）。
- **可點擊視覺提示**：目前 Quick Stats Grid 的卡片渲染（[DashboardView.vue:100-113](../../frontend/src/views/DashboardView.vue)）是純靜態樣式，四張卡片共用同一組 class，沒有 `cursor-pointer`／hover 效果。需在 `v-for` 渲染中依 `stat.id === 'zero_hit_rate'` 動態加上指標樣式與 hover 回饋（例如額外綁定 `cursor-pointer` 與 hover 邊框/背景變化class），讓使用者能直觀分辨這張卡片可點擊、其餘三張（`kbs`/`feedback`/`faithfulness`/`evaluations`/`avg_retrieval_score`）維持原本的靜態樣式。
- 面板內容：以表格呈現「問題內容（`question`）」「所屬知識庫」「查詢法（`search_type`）」「發生時間（`created_at`）」，並支援分頁翻頁，供使用者具體判斷是哪些提問查無結果，以便針對性補充知識庫內容。
- 不新增獨立路由／頁面，Modal 關閉即回到 Dashboard 首頁，維持「不新增獨立分析頁面」的原則（見第 8 節決策紀錄）。
- 分頁與資料筆數皆依賴後端既有 API 設計（第 4 節），本節僅新增前端呈現邏輯，不需調整 API 契約。

## 6. 執行流程設計

```
使用者於 RAG 對話測試發送問題
  │
  ▼
rag_chat_stream()：完成向量檢索（vector/hybrid/semantic_hybrid* 任一分支，raw_results 已取得）
  │
  ▼
組完 context_parts / sources（既有邏輯，[rag.py:467-550]，完全不變）
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

## 8. 決策紀錄

**已確認（本次規劃前提，使用者決策）**：
- 使用**新的、獨立的 MongoDB `RetrievalStats` beanie collection**，不重用/擴充既有 `ChatMessage.source_chunks` 結構。
- 統計寫入採 best-effort（非阻塞、失敗僅記錄警告不中斷主流程），沿用本專案既有「不讓周邊功能拖垮核心 SSE 對話流程」的一貫慣例。
- Dashboard 呈現方式沿用 `DashboardView.vue` 既有 `stats` 陣列/Quick Stats Grid 機制新增卡片，不新增獨立分析頁面。
- **`semantic_db_query` 查詢法不記錄統計**：其資料流（`db_query_result`）沒有 `score`/`raw_results` 概念，本次不涵蓋。未來若需要「資料庫查詢命中率」（例如 `row_count == 0` 視為無命中），需另案規劃，不在本次範圍。
- **`total_candidates` 計算基準採「去重合併後」**：即傳入 `RetrievalStatsService.record()` 的 `raw_results`（`search_similar()` 內部 [qdrant_service.py:459](../../backend/services/qdrant_service.py) 去重後、`search_similar_two_step()` 再與鄰居合併去重後、最終回傳給 `rag.py` 的結果），不額外修改 `search_similar()` 的回傳結構去暴露「合併前原始命中數」這個中繼值。
- **零命中清單（`zero-hit-questions`）本次一併做前端呈現**：新增下鑽 Modal／面板元件，見第 5.2 節。
- **不依「知識庫」維度在 Dashboard 卡片上做篩選**：本次維持全站合併統計；`by_knowledge_base` 欄位 API 仍會回傳（供未來擴充），但前端首頁不消費、不呈現任何依知識庫拆分的 UI。
- **`elapsed_ms` 可留空白（`None`）**：本次不額外新增檢索計時邏輯（不修改 `rag.py` 加入 `time.time()` 起訖計時），`RetrievalStatsService.record()` 呼叫時直接傳 `elapsed_ms=None`；未來若需要耗時分析再另案處理。
- **補充修正（2026-07-09，經第二方 AI 審查意見交叉驗證後採納）**：第 4 節補上 `knowledge_base_name` 解析機制（記憶體 ID→Name 對照表，不用 `$lookup`）；第 5.2 節補上 `zero_hit_rate` 卡片需要可點擊視覺提示（原本四張統計卡片皆為純靜態樣式，無 hover/cursor 回饋）。審查意見中另兩項——「`retrieved_scores`／`RetrievalStatsService.record()` 程式碼草稿仍讀取原始 `score` 而非 `semantic_score`」與「MongoDB `$avg` 需額外防禦 null 值」——查核後不採納：前者是審查方引用了本文件在 [`NewFeaturesPlan_RRFScoreThresholdMismatchPlan.md`](NewFeaturesPlan_RRFScoreThresholdMismatchPlan.md) 決議並同步修正前的舊內容，第 3.1/3.2 節目前已正確讀取 `semantic_score`，並非現存問題；後者 MongoDB `$avg` accumulator 原生即會忽略 `null`／非數值欄位，且寫入端（3.2 節）與前端（5.1 節 `?.toFixed(2) || '0.00'`）皆已有保底防護，不需額外程式碼。

**已拆分至獨立文件，屬本文件的前置阻塞事項（已決議，待實作落地）**：
- `hybrid`／`semantic_hybrid*` 查詢法的 RRF 分數與 `score_threshold` 尺度不匹配，導致 `hit_count`／零命中判斷失真，詳見 [`NewFeaturesPlan_RRFScoreThresholdMismatchPlan.md`](NewFeaturesPlan_RRFScoreThresholdMismatchPlan.md)。**已決議採用方案 C-2**：`qdrant_service.py` 統一新增 `semantic_score` 欄位，本文件的 `hit_count` 判斷公式改用 `semantic_score >= score_threshold`（見第 0/2 節）。**Batch 1 動工前必須先確認該文件的程式碼修改（`search_similar()` 與 `search_similar_two_step()` 兩處）已實際合併上線**，否則 `RetrievalStatsService.record()` 讀不到 `semantic_score` 欄位，等同全部零命中。

## 9. 分階段實作 Checklist

### Batch 0：前置阻塞（規劃決議已完成，實作為獨立前置依賴，見第 0 節）
- [x] 確認 [`NewFeaturesPlan_RRFScoreThresholdMismatchPlan.md`](NewFeaturesPlan_RRFScoreThresholdMismatchPlan.md) 的處理方案 —— **已決議方案 C-2**：`qdrant_service.py` 統一新增 `semantic_score` 欄位，`hit_count` 判斷公式為 `semantic_score >= score_threshold`（2026-07-09）
- [x] **實作前置依賴**：`NewFeaturesPlan_RRFScoreThresholdMismatchPlan.md` 第 7 節所列的 `backend/services/qdrant_service.py` 程式碼修改（`search_similar()` 與 `search_similar_two_step()` 兩處 RRF 分支皆補上 `semantic_score`）已完成並實測驗證（2026-07-09，見 [BugFix.md](BugFix.md)）。**尚待**：`airag-backend` 容器重啟後，執行中的 API 進程才會實際套用此變更。

### Batch 1：後端核心邏輯 —— 已完成（2026-07-09）
- [x] `backend/models/retrieval_stats.py`（新模型）+ 註冊進 `backend/models/mongodb.py` 的 `document_models`
- [x] `backend/config.py` 新增 `DASHBOARD_STATS_DEFAULT_PERIOD_DAYS`／`RETRIEVAL_STATS_ENABLED`
- [x] `backend/services/retrieval_stats_service.py`（新服務，`record()` 聚合計算 + best-effort 寫入，讀取 `semantic_score`）
- [x] `backend/routers/rag.py`：初始化 `raw_results: list = []`，並在檢索完成後新增 try/except 包裹的 `RetrievalStatsService.record()` 呼叫

### Batch 2：API／Schema 串接 —— 已完成（2026-07-09）
- [x] `backend/routers/dashboard.py`（新檔，兩端點含 MongoDB aggregation pipeline 與 `knowledge_base_name` 解析）。實作時發現本專案 beanie/motor/pymongo 版本組合下 `Document.aggregate().to_list()` 會拋 `TypeError`，改用 `get_pymongo_collection().aggregate(pipeline)` 繞開，詳見 [NewFeatures.md](NewFeatures.md) 2026-07-09 對應紀錄。
- [x] 於 `backend/main.py` 掛載新的 `dashboard` router

### Batch 3：前端 UI —— 已完成（2026-07-09）
- [x] `frontend/src/views/DashboardView.vue`：`stats` 陣列新增「無命中問題比例」「平均檢索分數」兩筆，`fetchDashboardStats()` 新增獨立 try/catch 呼叫新端點
- [x] 新增零命中問題清單的下鑽 Modal 元件，呼叫 `GET /api/dashboard/retrieval-stats/zero-hit-questions` 並分頁呈現；`zero_hit_rate` 卡片已加上可點擊視覺提示

### Batch 4：文件更新 —— 已完成（2026-07-09）
- [x] `docs/03_API_CONTRACT.md`：新增第 16 節，補上兩個新端點說明
- [x] `docs/04_DB_SCHEMA.md`：新增第 3.14 節 `retrieval_stats` collection schema，collection 總數 14→15
- [x] `docs/DevelopmentProcess/NewFeatures.md`：已記錄本次實作完成
