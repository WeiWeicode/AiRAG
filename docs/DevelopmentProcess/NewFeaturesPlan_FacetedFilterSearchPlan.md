# Tag／類別篩選式檢索（Faceted Filter Search）規劃文件

> 狀態：規劃中，待使用者確認後執行
> 影響範圍：`backend/services/qdrant_service.py`（`search_similar`/`search_similar_two_step` 新增 `filter_classes` 參數）、`backend/routers/rag.py`／`backend/schemas/retrieval.py`（新增 `filter_classes` 欄位）、`frontend/src/components/params/RagParamsPanel.vue`（新增多選篩選 UI）。**不觸碰**既有 `filter_tags` 邏輯與 `vector`/`hybrid` 兩種查詢法在未設定新篩選時的行為。

## 1. 目標與範圍

### 目標
目前 Qdrant 上傳時的 payload（[embedding.py:427-444](../../backend/routers/embedding.py)）已經寫入 `class`（陣列型別的類別欄位），但 `QdrantService.search_similar()`（[qdrant_service.py:251-262](../../backend/services/qdrant_service.py)）目前只對 `tags` 建立 `FieldCondition`（[qdrant_service.py:275-281](../../backend/services/qdrant_service.py)），完全沒有針對 `class` 的過濾條件。新增一個與 `filter_tags` 完全對稱的 `filter_classes` 篩選條件，讓使用者可以在前端 UI 用「類別」縮小檢索範圍（Faceted Search），而不只是靠標籤。

### 明確不動的部分
- `filter_classes` 預設為 `None`，`must_conditions` 只有在使用者實際選取類別時才會多加一條 `FieldCondition`；未設定時 `must_conditions` 組成方式與現況完全相同，`vector`/`hybrid`/`semantic_hybrid*` 所有查詢法在**未使用此新參數**時行為零改變。
- 既有 `filter_tags` 的 `MatchAny` 邏輯（[qdrant_service.py:275-281](../../backend/services/qdrant_service.py)）與 `filter_filename` 的 `MatchValue` 邏輯（[qdrant_service.py:282-288](../../backend/services/qdrant_service.py)）**完全不修改**，新條件是在同一個 `must_conditions` 列表中新增第三個 `append`。
- `must_not: source == "db_query_profile"` 的既有隔離規則（[qdrant_service.py:290-300](../../backend/services/qdrant_service.py)）不受影響，新條件加在 `must` 而非 `must_not`。
- `search_similar_two_step()`（[qdrant_service.py:528-563](../../backend/services/qdrant_service.py)）目前單純把 `filter_tags`/`filter_filename` 轉發給 `search_similar()`（[qdrant_service.py:552-563](../../backend/services/qdrant_service.py)），`filter_classes` 比照同樣的轉發模式新增，不改變其兩階段檢索（1st-hop/2nd-hop）的核心邏輯。

## 2. 名詞定義

| 名詞 | 說明 |
|---|---|
| 類別（Class） | Qdrant payload 中既有的 `class`（陣列型別，[embedding.py:437](../../backend/routers/embedding.py)），與 `tags`（標籤）是兩個獨立的分類維度；管理清單存在 MongoDB `class_options` collection（`backend/models/class_option.py`）。 |
| 類別選項（Class Option） | MongoDB `ClassOption` Document，既有的可選類別名稱清單，已有 `GET /api/embedding/classes`（[embedding.py:586-599](../../backend/routers/embedding.py)）／`POST /api/embedding/classes`（[embedding.py:601-619](../../backend/routers/embedding.py)）CRUD 端點，本功能**直接重用**，不重新設計清單來源。 |
| Faceted Search（分面篩選檢索） | 讓使用者透過多個獨立維度（本例為 標籤 + 類別）交集縮小檢索範圍的檢索模式，本功能新增「類別」這一個分面。 |

## 3. 架構設計

### 3.1 `QdrantService.search_similar()` 新增 `filter_classes` 參數

`backend/services/qdrant_service.py:251-262`，簽章新增一個可選參數（緊接在 `filter_tags` 後面，維持相關參數群聚）：

```python
async def search_similar(
    cls,
    collection_name: str,
    query_vector: Optional[List[float]] = None,
    query_text: Optional[str] = None,
    search_type: str = "vector",
    top_k: int = 5,
    score_threshold: float = 0.7,
    filter_tags: Optional[List[str]] = None,
    filter_classes: Optional[List[str]] = None,   # 新增：與 filter_tags 完全對稱
    filter_filename: Optional[str] = None,
    disable_parent_merge: bool = False,
    sparse_keywords: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
```

在 [qdrant_service.py:274-288](../../backend/services/qdrant_service.py) 的 `must_conditions` 組裝區塊，比照 `filter_tags` 的寫法新增：

```python
must_conditions = []
if filter_tags:
    must_conditions.append(
        models.FieldCondition(key="tags", match=models.MatchAny(any=filter_tags))
    )
if filter_classes:
    must_conditions.append(
        models.FieldCondition(key="class", match=models.MatchAny(any=filter_classes))
    )
if filter_filename:
    must_conditions.append(
        models.FieldCondition(key="filename", match=models.MatchValue(value=filter_filename))
    )
```

- 使用 `MatchAny`（OR 邏輯，命中任一選取類別即可），與 `filter_tags` 一致的篩選語意；`filter_tags` 與 `filter_classes` 兩者之間彼此是 AND（都在 `must_conditions` 內，Qdrant `Filter.must` 語意為 AND），符合一般分面篩選「標籤 AND 類別」的直覺。
- **不影響** [qdrant_service.py:324-368](../../backend/services/qdrant_service.py) hybrid 三路 prefetch 的 `exact_filter`（用於 exact keyword boost），因為 `exact_filter` 只帶 `must=must_conditions if must_conditions else None`（[qdrant_service.py:355-358](../../backend/services/qdrant_service.py)），`must_conditions` 已經包含新的 `filter_classes` 條件，同樣自動生效，無需額外修改。

### 3.2 `search_similar_two_step()` 轉發新參數

`backend/services/qdrant_service.py:528-563`，簽章與呼叫轉發都比照 `filter_tags` 新增：

```python
async def search_similar_two_step(
    cls,
    collection_name: str,
    query_vector: Optional[List[float]] = None,
    query_text: Optional[str] = None,
    search_type: str = "vector",
    top_k: int = 5,
    score_threshold: float = 0.7,
    filter_tags: Optional[List[str]] = None,
    filter_classes: Optional[List[str]] = None,   # 新增
    filter_filename: Optional[str] = None,
    disable_parent_merge: bool = False,
    neighbor_limit: int = 10,
    neighbor_score_threshold: float = 0.1,
    sparse_keywords: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    raw_results = await cls.search_similar(
        collection_name=collection_name,
        query_vector=query_vector,
        query_text=query_text,
        search_type=search_type,
        top_k=top_k,
        score_threshold=score_threshold,
        filter_tags=filter_tags,
        filter_classes=filter_classes,   # 新增
        filter_filename=filter_filename,
        disable_parent_merge=disable_parent_merge,
        sparse_keywords=sparse_keywords
    )
    ...
```

第二階段（2nd-hop 鄰居搜尋）目前**不**帶 `filter_tags`/`filter_filename`（比對 [qdrant_service.py:568](../../backend/services/qdrant_service.py) 之後的邏輯，鄰居搜尋是依 `links_to` 關聯名稱查找，非重新套用 filter），`filter_classes` 同樣**不**帶入第二階段，維持與 `filter_tags` 一致的既有行為邊界，不擴大新篩選條件的作用範圍。

## 4. API 設計

### 4.1 `ChatParams` 新增欄位

`backend/routers/rag.py:27-38`：

```python
class ChatParams(BaseModel):
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    repetition_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    top_k: Optional[int] = None
    score_threshold: Optional[float] = None
    filter_tags: Optional[List[str]] = None
    filter_classes: Optional[List[str]] = None   # 新增
    search_type: Optional[str] = "vector"
    context_summarize_trigger_tokens: Optional[int] = None
    read_attachment_content: Optional[bool] = False
```

### 4.2 `rag.py` 讀取與傳遞

`rag_chat_stream()` 比照既有 `filter_tags` 的讀取方式（[rag.py:220](../../backend/routers/rag.py) 初始化、[rag.py:238-239](../../backend/routers/rag.py) 覆寫）：

```python
filter_tags = None
filter_classes = None   # 新增初始化
...
if request.params.filter_tags is not None:
    filter_tags = request.params.filter_tags
if request.params.filter_classes is not None:   # 新增
    filter_classes = request.params.filter_classes
```

並在 [rag.py:382-392](../../backend/routers/rag.py)（`semantic_hybrid*` 家族呼叫 `search_similar_two_step`）與 [rag.py:428-436](../../backend/routers/rag.py)（`vector`/`hybrid` 呼叫 `search_similar`）兩處呼叫都新增 `filter_classes=filter_classes` 參數傳遞。

### 4.3 `backend/schemas/retrieval.py` 新增欄位（供檢索測試頁使用）

比照既有 `filter_tags: Optional[List[str]] = Field(default=None)`（`schemas/retrieval.py:9`），新增：

```python
filter_classes: Optional[List[str]] = Field(default=None)
```

`backend/routers/retrieval.py` 的 `search()` 呼叫 `search_similar_two_step`/`search_similar` 處（[retrieval.py:54-64](../../backend/routers/retrieval.py)、[retrieval.py:70 起](../../backend/routers/retrieval.py)）同樣比照 `filter_tags` 新增 `filter_classes=request.params.filter_classes` 轉發。

### 4.4 類別清單來源（沿用既有端點，不新增查詢）

`GET /api/embedding/classes`（[embedding.py:586-599](../../backend/routers/embedding.py)）已經回傳 `ClassOption.find_all()` 的完整名稱清單，**直接重用**作為前端多選篩選器的選項來源，不需要新增「列出唯一類別」的 Qdrant 查詢，因為這個端點已經存在且是類別管理的唯一真實來源，比從 Qdrant payload 反查更準確、更快。

## 5. 前端設計

### 5.1 `RagParamsPanel.vue` 新增類別多選篩選器

`frontend/src/components/params/RagParamsPanel.vue:48-57`（既有「標籤過濾篩選」文字輸入框）下方新增一組類別多選：

```html
<!-- Class Filter -->
<div class="flex flex-col gap-2">
  <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">類別篩選 (Filter Classes)</label>
  <select
    v-model="paramsStore.filterClasses"
    multiple
    class="bg-white/5 border border-white/8 rounded-lg text-white px-3 py-2 text-xs focus:outline-none focus:border-[#8b5cf6] transition-all min-h-[80px]"
  >
    <option v-for="opt in availableClasses" :key="opt" :value="opt" class="bg-[#111827] text-white">{{ opt }}</option>
  </select>
</div>
```

`<script setup>` 新增 `onMounted` 呼叫 `GET /api/embedding/classes` 取得 `availableClasses` 選項清單（比照既有頁面呼叫 axios 的簡單風格，不需要新的 service 檔案，直接用既有的 `api` 實例）。

### 5.2 `paramsStore.js` 新增狀態

`frontend/src/stores/paramsStore.js:11`（`filterTagsString` 旁）新增：

```js
filterClasses: [],   // 多選類別篩選，留空陣列 = 不篩選
```

（採用陣列型別而非字串，因為是多選 UI，不需要像 `filterTagsString` 那樣手動逗號分割）

### 5.3 `chatStore.js` payload 組裝

`frontend/src/stores/chatStore.js:121`（`filter_tags` 旁）新增：

```js
filter_classes: paramsStore.filterClasses.length > 0 ? paramsStore.filterClasses : undefined,
```

### 5.4 `RetrievalTestView.vue` 同步新增

比照既有 `filter_tags`（[RetrievalTestView.vue:163](../../frontend/src/views/RetrievalTestView.vue)）的 payload 組裝方式，新增 `filter_classes` 欄位與對應的類別多選 UI 元件（可直接重用 `RagParamsPanel.vue` 抽出的同一段 UI 邏輯，或複製貼上維持該頁面現有的獨立表單風格）。

## 6. 執行流程設計

```
使用者於 RagParamsPanel.vue 勾選類別（例如「財務」「HR」）
  │
  ▼
paramsStore.filterClasses = ["財務", "HR"]
  │
  ▼
chatStore._streamChat() 組 payload：params.filter_classes = ["財務", "HR"]
  │
  ▼
POST /api/rag/chat → ChatParams.filter_classes = ["財務", "HR"]
  │
  ▼
rag_chat_stream()：filter_classes = request.params.filter_classes
  │
  ▼
QdrantService.search_similar_two_step(..., filter_classes=filter_classes)
  或 search_similar(..., filter_classes=filter_classes)
  │
  ▼
must_conditions 新增 FieldCondition(key="class", match=MatchAny(any=["財務","HR"]))
  │
  ▼
Qdrant 只回傳 payload.class 陣列中「至少包含財務或HR其中一個值」的點位
  （與既有 filter_tags 條件 AND 交集）
  │
  ▼
未勾選任何類別時：filter_classes = None/[] → must_conditions 不新增此條件
  → 檢索行為與功能上線前完全相同（回歸驗證重點）
```

## 7. 新增設定值（`backend/config.py`）

本功能**不需要新增任何 `config.py` 設定值**——沒有預設門檔或閾值需要調整，篩選條件完全由使用者在前端即時決定，留空即不篩選。

## 8. 決策紀錄／待確認事項

**已確認（本次規劃前提）**：
- `filter_classes` 完全比照 `filter_tags` 的 `MatchAny` 語意與參數傳遞模式，是加法式新增，未使用時對 `vector`/`hybrid`/`semantic_hybrid*` 所有既有查詢法零影響。
- 類別選項清單直接重用既有 `GET /api/embedding/classes` 端點，不新增新的列舉查詢或管理介面。

**待使用者確認的開放問題**：
1. **`filter_tags` 與 `filter_classes` 之間的布林邏輯**：目前設計是兩者皆為 AND（都必須符合），單一維度內部（多選標籤之間／多選類別之間）為 OR（`MatchAny`）。若使用者期望「標籤 OR 類別」（符合任一維度即可），需要改用 `should` 而非 `must` 組裝，屬於資料表達方式的重大差異，需要提前確認，避免實作後語意跟使用者預期不符。
2. **`evaluation.py`／`TestSetManager.vue` 評估流程是否也需要支援類別篩選**：目前設計範圍限定在 `rag.py`（對話測試）與 `retrieval.py`（檢索測試）兩處，`evaluation.py` 批次評估流程若也要支援，需要額外在測試集資料結構中新增 `filter_classes` 欄位並在批次執行迴圈中讀取，不在本次範圍內，待確認是否要一併納入。

## 9. 分階段實作 Checklist

### Batch 1：後端核心邏輯（Qdrant 篩選條件）
- [ ] `backend/services/qdrant_service.py`：
  - [ ] `search_similar()` 新增 `filter_classes` 參數 + `must_conditions` 新增 `FieldCondition(key="class", match=MatchAny(...))`
  - [ ] `search_similar_two_step()` 新增 `filter_classes` 參數並轉發

### Batch 2：API／Schema 串接
- [ ] `backend/routers/rag.py`：`ChatParams` 新增 `filter_classes` 欄位；`rag_chat_stream()` 讀取並傳入兩處 Qdrant 呼叫
- [ ] `backend/schemas/retrieval.py`：`RetrievalParams`（或對應 params 類別）新增 `filter_classes` 欄位
- [ ] `backend/routers/retrieval.py`：`search()` 傳入 `filter_classes` 到 Qdrant 呼叫

### Batch 3：前端 UI
- [ ] `frontend/src/stores/paramsStore.js` 新增 `filterClasses: []`
- [ ] `frontend/src/components/params/RagParamsPanel.vue` 新增類別多選篩選 UI，`onMounted` 呼叫 `GET /api/embedding/classes` 取得選項
- [ ] `frontend/src/stores/chatStore.js` payload 組裝新增 `filter_classes`
- [ ] `frontend/src/views/RetrievalTestView.vue` 同步新增類別篩選 UI 與 payload 欄位

### Batch 4：文件更新
- [ ] `docs/03_API_CONTRACT.md`：`ChatParams`／`RetrievalRequest.params` 補上 `filter_classes` 欄位說明
- [ ] `docs/DevelopmentProcess/NewFeatures.md`：實作完成後記錄本次新增
