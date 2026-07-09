# 查詢法自動路由（Automatic Query-Type Routing）規劃文件

> 狀態：規劃中，待使用者確認後執行
> 影響範圍：新檔案 `backend/services/query_router_service.py`、`backend/routers/rag.py`（新增 `search_type="auto"` 解析分支）、`frontend/src/components/params/RagParamsPanel.vue`（新增選項）。**不修改**既有 6 種 `search_type` 各自的內部邏輯，路由層只負責「選哪一條既有分支執行」。

## 1. 目標與範圍

### 目標
目前使用者必須在 `RagParamsPanel.vue` 手動於下拉選單（[RagParamsPanel.vue:62-72](../../frontend/src/components/params/RagParamsPanel.vue)）選擇 6 種 `search_type` 之一（`vector`／`hybrid`／`semantic_hybrid`／`semantic_hybrid_feedback`／`semantic_hybrid_attachment`／`semantic_db_query`）。新增第 7 種可選值 `auto`，選擇後由一個新的輕量分類器 Service 依問題文字 + 知識庫既有 metadata，判斷應該實際執行哪一種既有查詢法，執行完分類後**直接沿用該既有 search_type 分支跑完全部既有邏輯**，路由層完全不介入檢索/生成細節。

### 明確不動的部分
- 6 種既有 `search_type` 各自的檢索/Rerank/回饋加權/附件/DB查詢邏輯（[rag.py:264-436](../../backend/routers/rag.py) 全部分支）**完全不修改**，路由只是在這些既有分支「之前」多一個步驟，把 `search_type` 從 `"auto"` 換成分類器判斷出的具體值，之後程式碼路徑與現況完全相同。
- `frontend/src/stores/chatStore.js:122` 的 `search_type: paramsStore.searchMode` 傳值方式不變，新增的 `"auto"` 只是這個欄位新增的一個合法值。
- `retrieval.py`／`evaluation.py` 兩處**不強制**支援 `auto`（純檢索測試/批次評估通常需要固定、可重現的查詢法以利比較基準，是否支援見第 8 節待確認事項），本次規劃範圍鎖定在 `rag.py` 對話測試流程。

## 2. 名詞定義

| 名詞 | 說明 |
|---|---|
| 查詢法路由（Query Routing） | 依據問題內容自動判斷該用哪一種既有 `search_type` 執行，取代使用者手動選擇。 |
| `QueryRouterService` | 新增的獨立 Service，比照 `RerankService`（[rerank_service.py](../../backend/services/rerank_service.py)）的 httpx + JSON Schema + 優雅降級模式，呼叫 Instruct LLM 做輕量分類。 |
| 安全預設值（Safe Default） | 分類器失敗或回傳非法值時的降級目標，本規劃選定 `semantic_hybrid`（目前功能最完整、涵蓋範圍最廣的查詢法）。 |

## 3. 架構設計

### 3.1 新 Service：`backend/services/query_router_service.py`

完全比照 `rerank_service.py`（[rerank_service.py:1-81](../../backend/services/rerank_service.py)）的既有慣例：httpx `AsyncClient` POST 到 `{DENSE_VECTOR_LLAMACPP_BASE_URL}/v1/chat/completions`，`response_format: {"type": "json_object"}`，Markdown fence 清理，`json.loads`，任何例外都優雅降級，**不做重試**（與 `embedding_service.py` 的 retry-with-temperature 模式不同，比照 `rerank_service.py` 的「失敗直接降級」風格，因為路由分類屬於「錦上添花」的入口決策，不值得為此增加額外延遲重試）。

```python
import httpx
import json
import logging
from typing import Dict, Any, List, Optional
from config import settings

logger = logging.getLogger("airag.query_router")

class QueryRouterService:
    """
    輕量 Instruct LLM 分類器：依問題文字 + 知識庫既有 metadata，
    判斷 6 種既有 search_type 中哪一種最適合本次查詢。
    任何失敗皆優雅降級為安全預設值，不中斷 RAG 對話流程（比照 RerankService 的降級風格）。
    """
    VALID_SEARCH_TYPES = [
        "vector", "hybrid", "semantic_hybrid",
        "semantic_hybrid_feedback", "semantic_hybrid_attachment", "semantic_db_query"
    ]
    SAFE_DEFAULT = "semantic_hybrid"

    @classmethod
    async def route(
        cls, question: str,
        filenames: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        has_db_query_profiles: bool = False
    ) -> str:
        system_prompt = (
            "你是專業的檢索策略路由助手。請依照使用者的問題內容，"
            "從以下清單中選出最適合的檢索模式：\n"
            "- vector：單純語意相似度檢索，適合措辭清楚、無需額外語意重寫的簡單問題。\n"
            "- hybrid：向量+關鍵字混合檢索，適合包含明確代號/檔名/程式識別碼的問題。\n"
            "- semantic_hybrid：先用 AI 語意理解問題再混合檢索，適合措辭模糊、口語化或需要語意重寫的問題。\n"
            "- semantic_hybrid_feedback：同 semantic_hybrid，並額外套用歷史人工回饋加權，"
            "適合可能過去已被人工標註過準確度的常見問題類型。\n"
            "- semantic_hybrid_attachment：同 semantic_hybrid，並額外查詢關聯附件，"
            "適合問題提及「附件」「圖片」「檔案」等需要額外查閱附加檔案的情境。\n"
            "- semantic_db_query：問題明確要求查詢資料庫/表格/欄位數據（例如「幾筆」「查詢...資料庫」），"
            "而非查閱文件內容時使用。\n"
            "只能輸出符合以下 Schema 的單一 JSON，不要包含任何額外文字或 Markdown：\n"
            '{"search_type": "<上述清單其中一個字串>"}'
        )
        metadata_hint = ""
        if filenames:
            metadata_hint += f"\n知識庫現有檔案樣例：{json.dumps(filenames[:20], ensure_ascii=False)}"
        if tags:
            metadata_hint += f"\n知識庫現有標籤：{json.dumps(tags, ensure_ascii=False)}"
        if has_db_query_profiles:
            metadata_hint += "\n此知識庫已設定資料庫查詢設定檔，可考慮 semantic_db_query。"

        user_prompt = f"問題：{question}{metadata_hint}"

        url = f"{settings.DENSE_VECTOR_LLAMACPP_BASE_URL.rstrip('/')}/v1/chat/completions"
        payload = {
            "model": settings.DENSE_VECTOR_INSTRUCT_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.1,
            "max_tokens": 64,
            "response_format": {"type": "json_object"}
        }

        try:
            async with httpx.AsyncClient(timeout=settings.QUERY_ROUTER_TIMEOUT_SECONDS) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                result = response.json()
                content = result["choices"][0]["message"]["content"].strip()

                if content.startswith("```"):
                    lines = content.split("\n")
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].startswith("```"):
                        lines = lines[:-1]
                    content = "\n".join(lines).strip()

                parsed = json.loads(content)
                chosen = parsed.get("search_type")
                if chosen not in cls.VALID_SEARCH_TYPES:
                    raise ValueError(f"分類器回傳非法 search_type: {chosen}")
                logger.info(f"[QueryRouter] 問題「{question[:30]}...」路由至 search_type={chosen}")
                return chosen
        except Exception as e:
            logger.warning(f"[QueryRouter] 分類失敗，降級為安全預設值 {cls.SAFE_DEFAULT}: {e}")
            return cls.SAFE_DEFAULT
```

- `has_db_query_profiles` 參數：是否要在路由判斷時考慮該知識庫是否已設有 `DBQueryProfile`，讓分類器有機會選到 `semantic_db_query`，需要一次額外的 Mongo 查詢（`DBQueryProfile.find(knowledge_base_id=...).count() > 0`），屬於效能與判斷精準度的取捨，見第 8 節待確認事項。

### 3.2 `rag.py` 新增 `auto` 解析分支

`rag_chat_stream()` 中，`search_type` 確定之後（[rag.py:240-241](../../backend/routers/rag.py) 讀完 `request.params.search_type`）、實際分支判斷之前（[rag.py:264](../../backend/routers/rag.py) 的 `if search_type == "semantic_db_query"` 之前），新增：

```python
if search_type == "auto":
    yield f"event: step\ndata: {json.dumps({'step': 'query_routing', 'status': 'running', 'content': '正在自動判斷最適合的檢索模式...'}, ensure_ascii=False)}\n\n"
    from services.query_router_service import QueryRouterService
    route_filenames, route_tags, has_profiles = [], [], False
    if request.knowledge_base_id:
        try:
            kb_for_route = await KnowledgeBase.get(PydanticObjectId(request.knowledge_base_id))
            if kb_for_route:
                route_meta = await QdrantService.get_unique_metadata(kb_for_route.qdrant_collection_name)
                route_filenames = route_meta.get("filenames", [])
                route_tags = route_meta.get("tags", [])
        except Exception as route_meta_err:
            logger.warning(f"[QueryRouter] 取得知識庫 metadata 失敗，改用空清單繼續路由: {route_meta_err}")
    search_type = await QueryRouterService.route(
        question, filenames=route_filenames, tags=route_tags, has_db_query_profiles=has_profiles
    )
    yield f"event: step\ndata: {json.dumps({'step': 'query_routing', 'status': 'success', 'content': f'已自動選定檢索模式：{search_type}'}, ensure_ascii=False)}\n\n"
```

- **重用**既有 `QdrantService.get_unique_metadata()`（[rag.py:298](../../backend/routers/rag.py) 同一支方法，已有 TTL 快取機制，[qdrant_service.py:832-837](../../backend/services/qdrant_service.py)），不新增查詢負擔（快取命中時幾乎零成本）。
- 分類完成後，`search_type` 這個區域變數被覆寫成具體值，後續 [rag.py:264](../../backend/routers/rag.py) 開始的既有 `if/elif` 分支鏈**完全不需要修改**，直接吃到覆寫後的值繼續往下走，這是「路由只決定跑哪個既有分支、不介入分支內部邏輯」的關鍵設計。
- 新增一個 SSE `step: "query_routing"` 事件，讓前端能顯示「AI 正在判斷檢索模式」與「已選定：xxx」，比照既有 `semantic_analysis`/`vector_search` 的 running/success 兩段式事件風格（[rag.py:279-284](../../backend/routers/rag.py)）。

## 4. API 設計

`ChatParams.search_type`（[rag.py:36](../../backend/routers/rag.py)）欄位型別不變（仍是 `Optional[str]`），**只是新增一個合法字串值 `"auto"`**，不需要新增 Pydantic 欄位或修改 schema 結構。

`docs/03_API_CONTRACT.md` 的 `search_type` 列舉值說明需要更新為：`"vector | hybrid | semantic_hybrid | semantic_hybrid_feedback | semantic_hybrid_attachment | semantic_db_query | auto"`。

## 5. 前端設計

### 5.1 `RagParamsPanel.vue` 新增選項

[RagParamsPanel.vue:62-72](../../frontend/src/components/params/RagParamsPanel.vue) 下拉選單新增一個選項（建議放在清單最前面，作為推薦的預設便利選項）：

```html
<select v-model="paramsStore.searchMode" ...>
  <option value="auto" class="bg-[#111827] text-white">🤖 自動判斷 (Auto Routing)</option>
  <option value="vector" ...>向量查詢 (Vector Search)</option>
  ...（其餘既有選項不變）
</select>
```

### 5.2 `chatStore.js` SSE 事件顯示

`chatStore.js` 目前 `steps` 陣列初始化邏輯（沿用 `NewFeaturesPlan_ContextMapReduceSummaryPlan.md` 已實作的「所有查詢模式都建立 steps 陣列」改動），`query_routing` 這個新 step key 若不在既有初始清單中，會走 ContextMapReduce 規劃已實作的「找不到 key 時動態插入新 step」邏輯（`frontend/src/stores/chatStore.js`），**不需要額外修改** `chatStore.js`，直接受益於前一個功能已經做好的通用機制。

## 6. 執行流程設計

```
使用者於 RagParamsPanel.vue 選擇「🤖 自動判斷」
  │
  ▼
paramsStore.searchMode = "auto" → chatStore 送出 params.search_type = "auto"
  │
  ▼
rag_chat_stream()：search_type == "auto"
  │
  ├─ 有 knowledge_base_id → 取得該 KB 的 filenames/tags（重用 get_unique_metadata 快取）
  │
  ▼
QueryRouterService.route(question, filenames, tags, has_db_query_profiles)
  │
  ├─ 分類成功 → search_type 覆寫為分類器選定的既有值（例如 "semantic_hybrid"）
  │
  └─ 分類失敗（timeout/JSON錯誤/非法值）→ search_type 覆寫為 SAFE_DEFAULT = "semantic_hybrid"
        （降級路徑，記錄 warning log，不中斷對話）
  │
  ▼
後續完全沿用該 search_type 既有分支的所有邏輯（[rag.py:264-436] 起）
  → 檢索、Rerank、回饋加權、附件查詢、DB查詢 皆與使用者手動選擇該模式時完全一致
```

## 7. 新增設定值（`backend/config.py`）

| 變數 | 預設值 | 用途 |
|---|---|---|
| `QUERY_ROUTER_TIMEOUT_SECONDS` | `10.0` | 分類器 httpx 呼叫逾時秒數（比照 `RerankService` 20 秒、`embedding_service.py` 15 秒的量級，但分類任務輸出極短，可設較短逾時） |
| `QUERY_ROUTER_DEFAULT_SEARCH_TYPE` | `"semantic_hybrid"` | 分類失敗時的安全降級目標，對應 `QueryRouterService.SAFE_DEFAULT`（建議做成可設定值而非寫死常數，方便未來調整） |

## 8. 決策紀錄／待確認事項

**已確認（本次規劃前提）**：
- 路由層完全獨立於既有 6 種查詢法的內部邏輯，只負責在既有分支判斷之前，把 `search_type` 從 `"auto"` 換成具體值，之後程式碼路徑不變。
- 分類失敗時降級為 `semantic_hybrid`（功能最完整、涵蓋範圍最廣），不中斷 SSE 串流。

**待使用者確認的開放問題**：
1. **是否要讓分類器也能選中 `semantic_db_query`**：這需要額外查詢該知識庫是否已設定 `DBQueryProfile`（一次 Mongo count 查詢），若知識庫沒有任何查詢設定檔卻被路由到 `semantic_db_query`，會直接落入「查無設定檔」的中止流程（`NewFeaturesPlan_SemanticDatabaseQueryPlan.md` 第 6 節步驟 2），對使用者體驗不友善。建議選項：(a) 分類器可選但額外查詢一次 profile 是否存在；(b) 分類器提示詞中直接排除 `semantic_db_query`，該模式維持只能手動選擇。待確認採用哪一種。
2. **`retrieval.py`／`evaluation.py` 是否需要支援 `auto`**：批次評估通常需要固定可重現的查詢法作為比較基準，暫定本次不支援，若使用者需要「評估路由準確度本身」這個更進階的需求，需另外規劃（例如記錄路由決策供事後人工複核），不在本次範圍。
3. **`semantic_hybrid_attachment` 與 `semantic_hybrid_feedback` 的路由判斷精準度**：這兩者與 `semantic_hybrid` 的差異主要在「歷史回饋加權」與「附件查詢」，僅憑問題文字本身有時難以準確判斷（例如使用者未明說「附件」但確實想查附件內容），实测后可能需要調整 System Prompt 的判斷提示語句，建議實作後先以人工測試集驗證路由準確度，非阻塞性問題但需列入驗收項目。

## 9. 分階段實作 Checklist

### Batch 1：後端核心邏輯
- [ ] `backend/config.py` 新增 `QUERY_ROUTER_TIMEOUT_SECONDS`／`QUERY_ROUTER_DEFAULT_SEARCH_TYPE`
- [ ] `backend/services/query_router_service.py`（新檔，`QueryRouterService.route()`，比照 `RerankService` 的 httpx/JSON-schema/優雅降級模式）

### Batch 2：API／Schema 串接
- [ ] `backend/routers/rag.py`：`rag_chat_stream()` 新增 `search_type == "auto"` 解析分支（含 `query_routing` SSE step 事件），覆寫後沿用既有分支邏輯

### Batch 3：前端 UI
- [ ] `frontend/src/components/params/RagParamsPanel.vue` 下拉選單新增「🤖 自動判斷 (Auto Routing)」選項

### Batch 4：驗證與文件更新
- [ ] 人工測試集驗證：至少涵蓋 6 種既有查詢法各自的典型問題範例，確認路由準確度可接受（依第 8 節待確認事項 3）
- [ ] `docs/03_API_CONTRACT.md`：`ChatParams.search_type` 列舉值補上 `auto`
- [ ] `docs/DevelopmentProcess/NewFeatures.md`：實作完成後記錄本次新增（含路由準確度實測結果摘要）
