# 手動建立與選擇 Qdrant 知識庫 (Knowledge Base / Collections) 規劃文件

> 狀態：已完成 (2026-07-16)
> **本次任務僅產出規劃文件本身（放入 `docs/DevelopmentProcess/`），不修改任何程式碼。**

---

## 1. 背景與目標

### 為什麼要做這個功能
目前所有測試（RAG 對話、向量搜尋、準確度評估、自訂資料向量化、人工回饋）共用同一批 Qdrant Collection 資料。未來會有其他部門或應用需要把各自的文件單獨向量化、彼此的知識庫互相隔離，因此需要能「手動建立多個 Qdrant Collection（知識庫）」，並在各測試頁面手動選擇要查詢哪一個知識庫，避免測試資料與正式/其他部門資料混在一起。

### 重要發現：後端多知識庫的地基已經存在
探索程式碼後發現，`KnowledgeBase` 這個抽象（Mongo Document + 對應一個 Qdrant Collection）**已經是這個專案既有的設計**，而非本次新增概念：

- [`backend/models/knowledge_base.py`](../../backend/models/knowledge_base.py)：`KnowledgeBase.qdrant_collection_name` 欄位，建立時自動產生 `kb_<ObjectId>` 命名。
- [`backend/routers/knowledge_base.py`](../../backend/routers/knowledge_base.py)：`POST/GET/DELETE /api/knowledge-bases` 已完整實作——建立時會呼叫 `QdrantService.create_collection()` 在 Qdrant 開一個新 Collection，刪除時兩邊（Mongo + Qdrant）都會清除。
- [`backend/services/qdrant_service.py`](../../backend/services/qdrant_service.py) 的 `create_collection()`／`upsert_chunks()` 等方法**本來就是 collection-name-agnostic**（呼叫端傳什麼名稱就用什麼名稱），Point payload 結構（`content`/`filename`/`tags`/`links_to`/`parent_id`...）與向量結構（unnamed dense + `sparse-text` 稀疏向量）在所有 Collection 間完全一致——符合使用者要求的「Point 結構參考預設 Collections 即可」，**不需要新增或調整 Point Schema**。
- `retrieval.py`／`rag.py`／`embedding.py` 各路由**都已經**依請求帶的 `knowledge_base_id` 解析出對應的 `kb.qdrant_collection_name` 再操作 Qdrant，不是寫死單一 Collection。
- 前端已有 [`components/common/KnowledgeBaseSelector.vue`](../../frontend/src/components/common/KnowledgeBaseSelector.vue) 下拉選單元件（讀 `GET /api/knowledge-bases`，綁定共用的 `paramsStore.knowledgeBaseId`），且**已經**被 RAG 測試（`RagParamsPanel.vue`）、向量搜尋測試（`RetrievalTestView.vue`）、自訂資料向量化（`ChunkingParams.vue`，涵蓋所有 embedding 分頁）三處使用。

**也就是說，使用者提出的九項需求中，多數在後端與部分前端已經完成。** 本規劃聚焦在真正的缺口上，而不是重做一套多知識庫機制。

### 缺口清單（本次規劃真正要處理的範圍）

| # | 需求 | 現況 | 缺口 |
|---|---|---|---|
| 前端-1a | RAG 測試手動選 Collection | ✅ 已完成 | 無 |
| 前端-1b | 向量搜尋測試手動選 Collection | ✅ 已完成 | 無 |
| 前端-1c | 自訂資料向量化手動選 Collection | ✅ 已完成 | 無 |
| 前端-1d | 準確度評估手動選 Collection | ❌ 前端寫死 `'tech_specs'`/`'hr_docs'` 字串，後端有對應的舊相容分支 | **需修正** |
| 前端-2 | 人工回饋與標註歷史顯示 Collection | ⚠️ 後端已記錄 `knowledge_base_id`，但 API 回應與前端列表都沒有回傳/顯示 | **需修正** |
| 後端-1 | Qdrant 能手動建立 Collection | ✅ API 已存在（`POST /api/knowledge-bases`） | 缺少**前端管理介面**去呼叫它 |
| 後端-2 | Feedback 於 MongoDB 記錄 Collection | ✅ `Feedback.knowledge_base_id` 已存在且建立時已寫入 | 缺少對外顯示（同前端-2） |
| （新增）| 手動建立/管理知識庫的操作介面 | ❌ 完全沒有 UI | **需新增一個管理頁面** |

已與使用者確認（透過 `AskUserQuestion`）：
1. 知識庫管理介面採**新增獨立頁面**（比照 `RoleSettingsView.vue` 的既有模式），不塞進 Dashboard。
2. 管理頁面**包含刪除 Collection** 功能（後端 API 已存在），刪除前要有二次確認提示。
3. 回饋歷史顯示 Collection 時，顯示**知識庫名稱**（非原始 ObjectId），後端需解析並多回傳一個欄位。

### 審查後補充的隱性細節（Edge Cases）

第一版規劃經人工審查後，發現 4 個需要補進規劃的細節，皆已查證程式碼確認屬實，詳見對應章節（3.2、4.0、4.3）：
1. `paramsStore.js`／`KnowledgeBaseSelector.vue` 殘留的舊字串預設值 `'hr_docs'` 不是合法 `PydanticObjectId`，會導致選單載入完成前或知識庫清單為空時送出的請求被後端 400 拒絕（見 4.0）。
2. 新增的「知識庫管理頁」刪除 Collection 後，若刪除的正是全域 `paramsStore.knowledgeBaseId` 目前選用的 KB，需連動重置，避免其他頁面仍持有已刪除的 ID（見 4.3）。
3. `feedback.py` 批次查詢知識庫名稱時，`knowledge_base_id` 可能包含歷史髒資料（如舊的 `'hr_docs'`、空字串），需在查詢前過濾掉無法轉型為 `PydanticObjectId` 的值（見 3.2）。
4. 側邊選單新項目需指定風格一致的 SVG 圖示（見 4.3）。

---

## 2. 明確不做的事（Out of Scope）

- 不重新設計 Point 結構、不新增/調整向量欄位（沿用現有 `create_collection`/`upsert_chunks` 的預設結構）。
- 不更動 `KnowledgeBase` 已建立的自動命名規則 `kb_<ObjectId>`，使用者不能自訂 Qdrant Collection 的實際名稱（只能設定顯示用的 `name`/`description`）。
- 不重構 `RagParamsPanel.vue`／`RetrievalTestView.vue` 已經運作正常的 `KnowledgeBaseSelector` 用法（一個是共用面板、一個是頁面內聯，雖然實作方式不同但都能動，非本次任務範圍）。
- 不處理 `frontend/src/services/feedbackService.js`（疑似未被使用的重複模組）——與本次任務無關，不順手清理。
- 不修改 `evaluation.py` 裡 `list_datasets()` 對 `dataset_id` 的舊相容字串轉換邏輯（那是測試集 ID 的邏輯，與知識庫選擇是兩件事）。

---

## 3. 後端設計

### 3.1 準確度評估：接上真正的知識庫選擇

**問題點**：[`backend/routers/evaluation.py:184-198`](../../backend/routers/evaluation.py)
```python
if payload.knowledge_base_id:
    if payload.knowledge_base_id in ["tech_specs", "hr_docs"]:
        # 尋找預設或第一個知識庫
        kb = await KnowledgeBase.find_one(KnowledgeBase.name == "預設知識庫")
        if not kb:
            kb = await KnowledgeBase.find_all().first_or_none()
    else:
        try:
            kb_id = PydanticObjectId(payload.knowledge_base_id)
            kb = await KnowledgeBase.get(kb_id)
        except Exception:
            pass
if not kb:
    kb = await KnowledgeBase.find_all().first_or_none()
```
這段的 `["tech_specs", "hr_docs"]` 分支是配合前端目前寫死字串的舊相容代碼。前端改成傳真正的 `knowledge_base_id`（見 4.1）之後，這個字串比對分支永遠不會命中，屬於死碼，應移除，簡化為：
```python
kb = None
if payload.knowledge_base_id:
    try:
        kb_id = PydanticObjectId(payload.knowledge_base_id)
        kb = await KnowledgeBase.get(kb_id)
    except Exception:
        pass
if not kb:
    kb = await KnowledgeBase.find_all().first_or_none()
```
保留「沒有指定或指定無效時 fallback 第一個知識庫」的行為，維持向後相容（避免舊資料/未帶欄位時整個評估失敗）。

### 3.2 Feedback：回應補上知識庫名稱

**現況**：[`backend/models/feedback.py`](../../backend/models/feedback.py) 的 `Feedback.knowledge_base_id` 欄位建立時已經寫入（[`backend/routers/feedback.py:76`](../../backend/routers/feedback.py)），但對外回應的 `FeedbackItem`（[`feedback.py:34-43`](../../backend/routers/feedback.py)）沒有這個欄位，`create_feedback`（82-92 行）與 `list_feedbacks`（123-136 行）組裝回應時都沒有帶出來。

**修改**：
1. `FeedbackItem` schema 新增 `knowledge_base_id: Optional[str] = None` 與 `knowledge_base_name: Optional[str] = None`。
2. `create_feedback()`：`feedback.insert()` 後，若 `feedback.knowledge_base_id` 有值，`await KnowledgeBase.get(PydanticObjectId(feedback.knowledge_base_id))` 取得名稱（單筆查詢，無效 ID 或查無資料時 `knowledge_base_name` 留 `None`，不丟例外，比照現有 try/except pass 慣例），一併塞進回傳的 `FeedbackItem`。
3. `list_feedbacks()`：**避免 N+1 查詢**——先蒐集這一頁 `feedbacks` 裡所有不重複的 `knowledge_base_id`，一次 `KnowledgeBase.find({"_id": {"$in": [...]}}).to_list()` 批次查出，組成 `{kb_id_str: kb.name}` 的 dict，再逐筆組裝 `FeedbackItem` 時查表帶入 `knowledge_base_name`（查無對應時為 `None`，前端顯示「未指定」）。
   - **安全轉型（審查補充）**：`Feedback.knowledge_base_id` 是自由字串欄位，歷史資料可能存在非合法 ObjectId 的髒值（例如本規劃 4.0 節提到的舊預設值 `'hr_docs'`、空字串或 `None`）。組出 `$in` 清單前，需逐一 `try: PydanticObjectId(kb_id) except Exception: continue` 過濾，只把能成功轉型的 ID 丟給 `KnowledgeBase.find()`，避免整個查詢因單一髒資料而失敗，比照 [`feedback.py:152-157`](../../backend/routers/feedback.py) `export_to_dataset()` 既有的 ID 過濾寫法。

不需要改動 `Feedback` model 本身（欄位已存在），也不需要改動 `export_feedback`／`export-to-dataset` 這兩支既有端點（使用者沒有要求匯出檔案也要含這個欄位，保持最小變動）。

---

## 4. 前端設計

### 4.0（前置修正）共用狀態的舊預設值清理

**問題點**（審查補充，查證屬實）：
- [`frontend/src/stores/paramsStore.js:6`](../../frontend/src/stores/paramsStore.js)：`knowledgeBaseId: 'hr_docs'`。
- [`frontend/src/components/common/KnowledgeBaseSelector.vue:38`](../../frontend/src/components/common/KnowledgeBaseSelector.vue)：無可用知識庫時的 `<option>` 寫死 `value="hr_docs"`。

`'hr_docs'` 不是合法的 `PydanticObjectId` 格式。後端所有解析 `knowledge_base_id` 的端點（[`retrieval.py:31-36`](../../backend/routers/retrieval.py) 等）都是 `try: PydanticObjectId(...) except: raise HTTPException(400, "無效的知識庫 ID 格式")`，因此只要請求送出時這個值還沒被 `KnowledgeBaseSelector.vue` 的 `onMounted` fetch 覆蓋掉（例如頁面剛掛載的極短暫時間差），或是**系統裡目前一個知識庫都還沒建立**（`knowledgeBases.value.length === 0`，這種狀態在本次新增「知識庫管理頁」之前不會發生，但功能上線後全新環境很可能會遇到），就會讓 RAG 測試／向量搜尋測試／本次新增的準確度評估選擇器持續送出 `'hr_docs'`，被後端 400 拒絕。

**修改**：
- `paramsStore.js` 的 `knowledgeBaseId` 預設值改為 `null`。
- `KnowledgeBaseSelector.vue` 無資料時的 `<option>` 的 `value` 改為 `''`（空字串），並讓文字仍顯示「-- 無可用知識庫 --」。
- 這兩處目前被 RAG 測試／向量搜尋測試／自訂資料向量化共用，修改後三者行為不變（沒有知識庫時本來就無法查詢），只是失敗時机從「送出無效 ID 被 400」提前變成「介面本來就沒有可選項，選單被 disable」，屬於防呆強化而非既有邏輯調整，不算違反第 2 節「不重構已運作正常元件」的原則。

---

### 4.1 準確度評估頁：加入知識庫選擇器

檔案：[`frontend/src/views/EvaluationView.vue`](../../frontend/src/views/EvaluationView.vue)

- Import `useParamsStore`（`import { useParamsStore } from '../stores/paramsStore'`）與 `KnowledgeBaseSelector`（`import KnowledgeBaseSelector from '../components/common/KnowledgeBaseSelector.vue'`），比照 `RagParamsPanel.vue` 的用法。
- 在 `<TestSetManager ... />`（[`EvaluationView.vue:228-232`](../../frontend/src/views/EvaluationView.vue)）附近的參數設定區塊，加入 `<KnowledgeBaseSelector />`，讓使用者選擇的值寫入共用的 `paramsStore.knowledgeBaseId`（與 RAG 測試/向量搜尋測試共用同一個全域 store，天然同步）。
- 修正 [`EvaluationView.vue:118`](../../frontend/src/views/EvaluationView.vue) 的 payload 組裝：
  ```js
  // 修改前
  knowledge_base_id: datasetId === 'dataset_tech' ? 'tech_specs' : 'hr_docs',
  // 修改後
  knowledge_base_id: paramsStore.knowledgeBaseId,
  ```
- 這是唯一需要改的邏輯行；`startEvaluation()` 其餘的 SSE 手動解析（`fetch` + `response.body.getReader()`，[`EvaluationView.vue:128-144`](../../frontend/src/views/EvaluationView.vue)）維持原樣，不需要改用 `evalService.runEvaluation()`（該函式走 axios、非串流，與現有 SSE 解析邏輯不相容，貿然替換會是不必要的重構）。

### 4.2 人工回饋與標註歷史頁：顯示 Collection 名稱

檔案：[`frontend/src/views/FeedbackView.vue`](../../frontend/src/views/FeedbackView.vue)

- 表格新增一欄「知識庫 (Knowledge Base)」，插入位置：[`記錄編號`欄（221行）](../../frontend/src/views/FeedbackView.vue) 之後、[`問答與回饋標記比對`欄（222行）](../../frontend/src/views/FeedbackView.vue) 之前，比照既有 `<th>`/`<td>` 的 class 風格。
- 對應的 `<td>` 顯示 `item.knowledge_base_name || '未指定'`（沿用 [263-265 行](../../frontend/src/views/FeedbackView.vue) `created_at` 欄位「無資料則顯示預設值」的既有寫法模式）。
- `frontend/src/stores/feedbackStore.js` 不需要改動（純轉發 `response.data`，後端回應多帶欄位會自動透傳）。
- 不需要改動 `FeedbackPanel.vue`（送出回饋時已經帶 `knowledge_base_id: paramsStore.knowledgeBaseId`，見 [`FeedbackPanel.vue`](../../frontend/src/components/chat/FeedbackPanel.vue)）。

### 4.3 新增：知識庫管理頁（手動建立/刪除 Collection）

比照既有 `RoleSettingsView.vue` 的新增模式（同一次專案史上的先例，見 [`docs/DevelopmentProcess/Seizure/NewFeaturesPlan_ConfidentialAccessControlPlan.md` 第 6.2 節](Seizure/NewFeaturesPlan_ConfidentialAccessControlPlan.md)）：

**新增 `frontend/src/services/knowledgeBaseService.js`**（目前不存在，其餘功能模組都各自有一支 service 檔案，例如 [`userService.js`](../../frontend/src/services/userService.js)）：
```js
list()            // GET  /api/knowledge-bases
create(payload)   // POST /api/knowledge-bases   { name, description }
remove(id)        // DELETE /api/knowledge-bases/{id}
```
三支都是既有後端端點的直接映射，不需要新增後端 API。

**新增 `frontend/src/views/KnowledgeBaseSettingsView.vue`**，沿用專案既有深色卡片風格（`bg-[#111827]/70 border border-white/8 rounded-2xl`，比照 [`RoleSettingsView.vue`](../../frontend/src/views/RoleSettingsView.vue) 或 [`VectorManagementTab.vue`](../../frontend/src/components/embedding/VectorManagementTab.vue)），分兩個區塊：
- **建立知識庫**：文字輸入框（名稱，必填）+ 文字輸入框（描述，選填）+「建立」按鈕，呼叫 `knowledgeBaseService.create()`，成功後重新整理清單。
- **知識庫清單**：表格列出既有知識庫（名稱／描述／已向量化段落數 `chunk_count`／建立時間／刪除按鈕）。刪除前彈出確認對話框（需輸入或再次確認名稱，比照專案內其他刪除動作的二次確認慣例），呼叫 `knowledgeBaseService.remove(id)`，並在對話框文字明確警示「將一併刪除 Qdrant 內該知識庫所有向量資料，且無法復原」。
  - **連動重置全域選取狀態（審查補充）**：刪除成功後，需 `import { useParamsStore }` 並判斷 `if (deletedId === paramsStore.knowledgeBaseId)`；若相符，將 `paramsStore.knowledgeBaseId` 重置為剩餘清單第一筆的 `id`（若清單已空則設為 `null`，呼應 4.0 節的預設值防呆）。原因：`paramsStore.knowledgeBaseId` 是 RAG 測試／向量搜尋測試／準確度評估／自訂資料向量化共用的全域狀態，若刪除的正是目前選用中的知識庫卻不重置，其他頁面會繼續拿著已不存在的 ID 送出請求，被後端 404（`KnowledgeBase.get()` 查無資料）拒絕，且使用者不容易理解原因。

**路由與側邊選單**：
- [`frontend/src/router/index.js`](../../frontend/src/router/index.js)：新增 `{ path: '/knowledge-base-settings', name: 'KnowledgeBaseSettings', component: KnowledgeBaseSettingsView, meta: { requiresAuth: true } }`，比照 [69-72 行](../../frontend/src/router/index.js) `role-settings` 路由的寫法。
- [`frontend/src/components/common/AppSidebar.vue`](../../frontend/src/components/common/AppSidebar.vue) 的 `menuItems` 陣列（[12-48 行](../../frontend/src/components/common/AppSidebar.vue)）新增一筆「知識庫管理 (Knowledge Base)」項目，比照現有項目格式插入（建議放在「自訂資料向量化」與「標註與人工回饋歷史」之間，貼近使用情境）。圖示建議選用資料庫/櫃體意象的 SVG（例如 Feather/Lucide 的 `database` 圖示：三個疊層橢圓的圓柱體造型），與既有項目一致採 `stroke="currentColor" stroke-width="2"` 線稿風格、`class="w-[18px] h-[18px]"`，不使用實心填色圖示。

---

## 5. 需同步更新的文件（依 AGENT.md 第 9 節要求）

實作完成後需記錄：
- [`docs/DevelopmentProcess/NewFeatures.md`](NewFeatures.md)：新增本次功能的實作紀錄段落。
- [`docs/DevelopmentProcess/FrontendCorrection.md`](FrontendCorrection.md)：`paramsStore.js`/`KnowledgeBaseSelector.vue` 預設值修正、`EvaluationView.vue`、`FeedbackView.vue`、新增的 `KnowledgeBaseSettingsView.vue`/`knowledgeBaseService.js`、路由與側邊選單變更。
- [`docs/DevelopmentProcess/BackendCorrection.md`](BackendCorrection.md)：`evaluation.py`、`feedback.py`（schema 與兩支端點）變更。
- [`docs/03_API_CONTRACT.md`](../03_API_CONTRACT.md)：`GET/POST /api/feedback` 回應補上 `knowledge_base_id`/`knowledge_base_name`；`POST /api/evaluation/run` 的 `knowledge_base_id` 欄位說明更新（不再是 `tech_specs`/`hr_docs` 字串，改為真正的知識庫 ID）；確認 `/api/knowledge-bases` 三支端點的既有文件描述正確（若尚未記載於文件中則補上）。

---

## 6. 執行步驟 Checklist（供後續實際動工時使用）

**後端**
- [x] `backend/routers/evaluation.py`：移除 `["tech_specs", "hr_docs"]` 舊相容分支，簡化知識庫解析邏輯
- [x] `backend/routers/feedback.py`：`FeedbackItem` 新增 `knowledge_base_id`/`knowledge_base_name`；`create_feedback()` 單筆查詢知識庫名稱；`list_feedbacks()` 批次查詢知識庫名稱時先過濾非法 ObjectId 字串再查（避免 N+1 與髒資料查詢失敗）

**前端**
- [x] `paramsStore.js` 的 `knowledgeBaseId` 預設值改為 `null`；`KnowledgeBaseSelector.vue` 無資料選項的 `value` 改為 `''`
- [x] `EvaluationView.vue`：加入 `KnowledgeBaseSelector`，修正 payload 的 `knowledge_base_id` 來源
- [x] `FeedbackView.vue`：新增「知識庫」欄位顯示
- [x] 新增 `frontend/src/services/knowledgeBaseService.js`
- [x] 新增 `frontend/src/views/KnowledgeBaseSettingsView.vue`（建立表單 + 清單 + 刪除確認 + 刪除後連動重置 `paramsStore.knowledgeBaseId`）
- [x] `router/index.js` + `AppSidebar.vue` 新增路由與選單項目（含 database 意象 SVG 圖示）

**文件**
- [x] 更新 `docs/03_API_CONTRACT.md`
- [x] 完成後於 `NewFeatures.md`／`FrontendCorrection.md`／`BackendCorrection.md` 留紀錄

---

## 7. 驗證方式

- 後端：啟動 `uvicorn main:app --reload --port 53020`，手動呼叫 `POST /api/knowledge-bases` 建立新知識庫、確認 Qdrant 出現對應 Collection；呼叫 `POST /api/evaluation/run` 帶不同 `knowledge_base_id` 確認評估結果來自對應的 Collection；呼叫 `GET /api/feedback` 確認回應含 `knowledge_base_name`。
- 前端：由使用者於瀏覽器手動測試（依專案慣例，AI 不需要自行開瀏覽器驗證）——確認新知識庫管理頁可建立/刪除 Collection、下拉選單即時反映；準確度評估頁選擇不同知識庫後評估結果确實對應該知識庫內容；回饋歷史列表正確顯示知識庫名稱。
