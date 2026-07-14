<!-- 新功能紀錄(最新紀錄放最前面) -->

## 2026-07-13 AI 總結相似度門檻與拒絕生成機制實作完成

### 背景
依規劃文件 [NewFeaturesPlan_SimilaritySummaryThresholdPlan.md](NewFeaturesPlan_SimilaritySummaryThresholdPlan.md)（A 方案）實作。於前端「檢索設定」新增可自訂之「AI 總結相似度門檻 (AI SUMMARY THRESHOLD)」。當檢索片段相似度低於此分數時自動排除於 LLM 脈絡外；當全數片段皆低於門檻時，觸發 Early Exit 硬防護跳過 LLM 總結，節省 100% vLLM 推論算力與 Token，並防範幻覺。

### 變更內容
- **後端 (`backend/routers/rag.py` / `backend/schemas/retrieval.py`)**：
  - `ChatParams` 與 `SearchParams` 新增 `ai_summary_score_threshold` 欄位（預設 `0.60`）。
  - 在 `raw_results` 遍歷時，比對 `semantic_score >= ai_summary_score_threshold`，僅達標片段進入 `context_parts`。
  - 當無任何片段達標時，觸發 Early Exit，由 SSE 直接回傳友善警示文字與 `sources`，無須呼叫 LLM 推論。
  - 每筆 `sources` 回傳 `semantic_score` 與 `metadata.included_in_ai_context` 狀態。
- **前端 (`frontend/src/stores/paramsStore.js` / `RagParamsPanel.vue` / `chatStore.js` / `SourceChunks.vue`)**：
  - `paramsStore.js` 新增 `aiSummaryScoreThreshold` (預設 0.60) 與 `aiSummaryScoreThresholdEnabled` (預設 true)。
  - `RagParamsPanel.vue` 在「相似度閾值 (Score Threshold)」下方加入專屬 Slider 與開關 Checkbox。
  - `chatStore.js` 發送請求時自動帶入 `ai_summary_score_threshold` 參數。
  - `SourceChunks.vue` 為達標與未達標片段標示「已採納」與「未採納」視覺徽章。
- **文件與紀錄**：
  - 更新 `docs/03_API_CONTRACT.md`。
  - 記錄於 `BackendCorrection.md` 與 `FrontendCorrection.md`。

### 驗證
- 後端 Python 檔 `py_compile` 檢查通過。
- 前端 `npm run build` 通過（產生最新生產部署 dist 包）。

## 2026-07-13 專用 Cross-Encoder Rerank 規劃取消

### 背景
依使用者確認，原定規劃 [NewFeaturesPlan_CrossEncoderRerankPlan.md](NewFeaturesPlan_CrossEncoderRerankPlan.md)（引進本地 fastembed `TextCrossEncoder` 進行 Rerank）經實作測試與評估後效果未達預期，取消此規劃項目，維持現行 `RerankService`（LLM listwise 排序）運作機制。

## 2026-07-09 檢索命中分析儀表板（Retrieval Stats Dashboard）實作完成

### 背景
依規劃文件 [NewFeaturesPlan_RetrievalStatsDashboardPlan.md](NewFeaturesPlan_RetrievalStatsDashboardPlan.md) 實作，新增獨立的檢索命中統計，讓使用者能主動發現「哪些問題常檢索不到／分數偏低」，而非被動等待使用者透過 `feedback.py` 回報問題。前置阻塞事項（RRF 分數與 `score_threshold` 尺度不匹配，見 [`NewFeaturesPlan_RRFScoreThresholdMismatchPlan.md`](NewFeaturesPlan_RRFScoreThresholdMismatchPlan.md)）已於同日先行修正並實測驗證。

### 變更內容
- `backend/models/retrieval_stats.py`（新檔）：新增 `RetrievalStats` beanie Document，獨立於既有 `ChatMessage.source_chunks`；已註冊進 `backend/models/mongodb.py` 的 `document_models`。
- `backend/config.py`：新增 `DASHBOARD_STATS_DEFAULT_PERIOD_DAYS`（預設 7）、`RETRIEVAL_STATS_ENABLED`（預設 `True`，總開關）。
- `backend/services/retrieval_stats_service.py`（新檔）：`RetrievalStatsService.record()` 讀取 `raw_results` 每筆候選的 `semantic_score`（而非原始 RRF `score`）計算 `hit_count`/`avg_score`/`min_score`/`max_score`，best-effort 寫入，失敗只記錄 warning。
- `backend/routers/rag.py`：`rag_chat_stream()` 於 `vector`/`hybrid`/`semantic_hybrid*` 檢索完成、`context_parts`/`sources` 組裝完畢後，新增 try/except 包裹的旁路呼叫 `RetrievalStatsService.record()`；`semantic_db_query` 查詢法不記錄。
- `backend/routers/dashboard.py`（新檔，掛載於 `/api/dashboard`）：`GET /retrieval-stats/summary`（`$facet` 聚合近 N 天總檢索次數/零命中數/平均分數/依知識庫分組）、`GET /retrieval-stats/zero-hit-questions`（分頁）。兩端點皆用記憶體 `{str(kb.id): kb.name}` 對照表解析 `knowledge_base_name`，不使用 `$lookup`；已刪除的知識庫回傳 `"(已刪除)"`。實作時發現本專案固定的 beanie 2.1.0／motor 3.7.1／pymongo 4.17.0 版本組合下，`Document.aggregate().to_list()` wrapper 會對 cursor 多 await 一次拋出 `TypeError`（與 `models/mongodb.py` 既有的 `append_metadata` 相容性補丁屬同一類問題），改為直接呼叫 `get_pymongo_collection().aggregate(pipeline)` 繞開。
- `backend/main.py`：掛載新的 `dashboard` router。
- `frontend/src/views/DashboardView.vue`：`stats` 陣列新增「近7日無命中問題比例」「近7日平均檢索分數」兩張卡片；新增零命中問題清單下鑽 Modal（表格呈現問題內容/所屬知識庫/查詢法/發生時間，支援分頁）；`zero_hit_rate` 卡片依規劃文件補上 `cursor-pointer`／hover 視覺提示，其餘卡片維持原樣。
- `docs/03_API_CONTRACT.md`：新增第 16 節，記錄兩個新端點。
- `docs/04_DB_SCHEMA.md`：新增第 3.14 節 `retrieval_stats` collection schema，collection 總數 14→15。

### 驗證
- 後端：`python -m ast` 語法檢查通過；於 `airag-backend` 容器內（fastembed/beanie 皆正常載入）對真實 MongoDB 執行端到端測試，涵蓋 `RetrievalStatsService.record()` 的一般命中/零命中/零候選三種情境（`hit_count`/`avg_score` 皆正確，空候選時 `avg_score=None`）、`dashboard.py` 兩個端點函式直接呼叫（`summary` 的 `$facet` 聚合、`knowledge_base_name` 解析含「已刪除」情境、`zero-hit-questions` 分頁與零命中判斷），並確認 MongoDB `$avg` 原生正確忽略 `None` 值（(0.633+0.075)/2 = 0.354，與已刪除知識庫記錄的 `avg_score=None` 未被計入一致）。測試記錄使用後皆已清除，未留下測試資料。透過 `main.app.openapi()` 確認兩個新端點已正確掛載於 `/api/dashboard/retrieval-stats/*`。
- 前端：`npm run build` 通過，無編譯錯誤。
- 未自行開瀏覽器做人工功能測試（依 CLAUDE.md 慣例，使用者手動驗證）；`airag-backend` 容器執行中的 API 進程仍是修改前載入的舊模組，需重啟容器後才會實際套用本次所有後端變更（含前一項 RRF 修正）。

## 2026-07-08 多輪對話指代消解（Conversational Reference Resolution）實作完成

### 背景
依規劃文件 [NewFeaturesPlan_ConversationalReferenceResolutionPlan.md](NewFeaturesPlan_ConversationalReferenceResolutionPlan.md) 實作，解決 `search_type` 為 `semantic_hybrid`／`semantic_hybrid_feedback`／`semantic_hybrid_attachment` 時，`EmbeddingService.query_to_semantic_json()` 語義 JSON 解析階段看不到對話歷史，導致使用者追問「那份文件的第二點是什麼」這類指代問題時容易撈錯內容的問題。

### 變更內容
- `backend/config.py`：新增 `SEMANTIC_JSON_HISTORY_TURNS`（預設 3），作為前端未指定歷史則數時的後端預設值。
- `backend/services/embedding_service.py`：`query_to_semantic_json()` 新增可選參數 `chat_history`、`pinned_filename`（皆預設 `None`，向後相容），並在系統提示中加法式插入【使用者已手動鎖定檔案】與【近期對話歷史】／【指代消解規則】兩個獨立區塊；既有 JSON Schema、Few-Shot Examples、fallback JSON、重試溫度序列皆未修改。
- `backend/routers/rag.py`：
  - 新增 `_build_history_window()` helper，依 `history_context_turns` 截取最近 N 則 `chat_history`（只保留 `role in ("user", "assistant")`）。
  - `ChatParams` 新增 `history_context_turns`／`pinned_filename` 欄位。
  - `filter_filename` 優先權調整為「使用者手動鎖定（`pinned_filename`） > AI 自動判斷（`metadata.source_file`） > 不篩選」。
  - `semantic_analysis` 步驟 SSE 事件（`running` 與 `success` 兩次皆會覆蓋前一次內容，因此兩處都要加）新增「帶入歷史訊息數」與「手動鎖定檔案」兩行事後透明度資訊。
  - 呼叫點僅 `search_type in ("semantic_hybrid", "semantic_hybrid_feedback", "semantic_hybrid_attachment")` 分支一處，`vector`／`hybrid`／`semantic_db_query` 三種查詢法完全不受影響。
- `frontend/src/stores/paramsStore.js`：新增 `autoContextEnabled`（預設 `true`）、`historyTurnCount`（預設 `null`）、`pinnedFilename`（預設 `null`）。
- `frontend/src/components/params/RagParamsPanel.vue`：於語義混合家族查詢法（`semantic_hybrid`／`semantic_hybrid_feedback`／`semantic_hybrid_attachment`）選定時，新增「自動指代消解」勾選框 + 歷史則數輸入框 + 「手動鎖定檔案」下拉選單；下拉選單選項重用既有 `GET /api/knowledge-bases/{id}/metadata`，並在知識庫切換時比對重置不存在新清單中的殘留鎖定檔名。
- `frontend/src/stores/chatStore.js`：payload 新增 `history_context_turns`（勾選框關閉時強制送 `0`，並將清空的輸入框正規化為 `null` 避免後端 422）、`pinned_filename`。
- `docs/03_API_CONTRACT.md`：`ChatParams` 補上 `history_context_turns`／`pinned_filename` 欄位說明，`semantic_analysis` 步驟說明補上透明度資訊格式。

### 驗證
後端 `python -m py_compile` 通過；前端 `npm run build` 通過。人工功能測試（追問指代消解、手動鎖定檔案、關閉自動指代消解、切換知識庫重置鎖定檔案）留待使用者手動驗證，未自行開瀏覽器測試。

## 2026-07-08 查詢法／功能優化建議清單（尚未實作，待使用者確認）

### 背景
使用者詢問 AiRAG 還可以增加什麼查詢法或功能，盤點現有已實作查詢法（`vector`／`hybrid`／`semantic_hybrid`／`semantic_hybrid_feedback`／`semantic_hybrid_attachment`／`semantic_db_query`）與 `docs/DevelopmentProcess/NewFeaturesPlan_SemanticSearchOptimizationPlan.md` 尚未執行的優化項後，提出以下新建議，先記錄成待辦，尚未開始實作。

### 待辦優先：既有規劃文件中尚未執行的項目
`NewFeaturesPlan_SemanticSearchOptimizationPlan.md` 內第 1、2、4、5、6 項（`get_unique_metadata` 快取、2nd-hop 鄰居搜尋門檻放寬、語義 JSON 轉換失敗可觀測性、中文關鍵字正則支援、Instruct AI JSON 語法失敗修正）皆仍為「規劃中」狀態，已完成分析與優先級排序，建議優先執行。該文件第 3 項「融合後加入 Rerank 層」實際上已於 [rag.py:395](../../backend/routers/rag.py) 透過 `RerankService`（LLM listwise 重排序）實作完成，文件狀態尚未同步更新，之後修訂該規劃文件時應一併更正。

### 新建議查詢法
1. **多輪對話指代消解**：目前 `EmbeddingService.query_to_semantic_json()`（呼叫處見 [rag.py:307](../../backend/routers/rag.py)）只傳入當次 `question`，不帶 `chat_history`，使用者追問「那份文件的第二點是什麼」這類依賴上文的問題，語義 JSON 解析容易失焦。建議把最近幾輪對話歷史一併帶入 Instruct AI 的 Prompt 做指代消解後，再產生 `embeddings_input`／`sparse_keywords`。詳細規劃見 [NewFeaturesPlan_ConversationalReferenceResolutionPlan.md](NewFeaturesPlan_ConversationalReferenceResolutionPlan.md)。
2. **Tag／類別篩選式檢索（Faceted Search）**：讓使用者在前端 UI 手動勾選標籤／類別，作為 Qdrant filter 條件縮小語義檢索範圍，對大型知識庫的精準度有幫助，但需要新增前端篩選器 UI 與對應的後端 filter 參數。詳細規劃見 [NewFeaturesPlan_FacetedFilterSearchPlan.md](NewFeaturesPlan_FacetedFilterSearchPlan.md)。
3. **查詢法自動路由**：現行需使用者手動於 UI 選擇 6 種查詢法之一，可加一層「先讓 AI 判斷該題適合用哪種查詢法」的路由層，減少手動操作，但會多一次 LLM 呼叫延遲，且有路由誤判風險。詳細規劃見 [NewFeaturesPlan_QueryTypeAutoRoutingPlan.md](NewFeaturesPlan_QueryTypeAutoRoutingPlan.md)。

### 新建議功能
4. **專用 Cross-Encoder Rerank 模型（已取消）**：原規劃引進本地 fastembed `TextCrossEncoder`。經實作評估後發現效果未達預期，已確認取消此項目。詳細規劃見 [NewFeaturesPlan_CrossEncoderRerankPlan.md](NewFeaturesPlan_CrossEncoderRerankPlan.md)。
5. **檢索命中分析儀表板**：統計哪些問題常檢索不到／分數偏低，結合既有 `backend/routers/feedback.py` 回饋機制，主動發現知識庫內容缺口，而非被動等待使用者回報。已與使用者確認技術方向為新增獨立的 MongoDB `RetrievalStats` collection（不重用 `ChatMessage.source_chunks`）。詳細規劃見 [NewFeaturesPlan_RetrievalStatsDashboardPlan.md](NewFeaturesPlan_RetrievalStatsDashboardPlan.md)。

### 後續
以上 5 項規劃文件皆已建立完成（2026-07-08），狀態皆為「規劃中，待使用者確認後執行」，每份文件內的「決策紀錄／待確認事項」章節列出仍需使用者逐一確認的技術細節（例如歷史視窗大小單位、篩選條件布林邏輯、cross-encoder 模型名稱等），待逐項確認後才會依文件內的分階段 Checklist 開始實作。本次僅新增規劃文件，未修改任何程式碼。
