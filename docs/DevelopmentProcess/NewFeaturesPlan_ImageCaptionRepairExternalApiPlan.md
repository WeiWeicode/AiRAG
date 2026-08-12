# 功能規劃案：外部應用「僅重試失敗圖片 AI 描述與向量更新」API (Image Caption Repair External API)

## 0. 文件資訊

* **對象**：AiRAG 開發團隊與公司內網外部應用（如 GigaSolarKnowledgeBase, BPM 等）前端與後端開發者。
* **建立日期**：2026-08-12。
* **最後修訂**：2026-08-12（v2：對照實際程式碼修正定位方式、執行模式與回寫機制，見 0.1 節）。
* **關聯文件**：
  * [08_EXTERNAL_INGEST_API_GUIDE.md](../08_EXTERNAL_INGEST_API_GUIDE.md)（外部 Ingest API 串接指南）
  * [MULTI_APP_RAG_SYNC_PLAN.md](MULTI_APP_RAG_SYNC_PLAN.md)（多應用 RAG 向量同步架構）
  * [NewFeaturesPlan_IngestImageCaptionTimeoutPlan.md](NewFeaturesPlan_IngestImageCaptionTimeoutPlan.md)（圖片描述逾時與 retry 機制規劃）

### 0.1 v2 修訂摘要（初版有誤，實作請以本版為準）

| # | 初版寫法 | 問題 | v2 決議 |
|---|---|---|---|
| 1 | 只用 `filename` 定位要修的圖片段落，且 `filename` 標為選填 | `QdrantService.get_image_points()` 無 `point_ids` 時**必須**有 `filename`，選填會直接查不到；且 `filename` 是 `title or f"{app_id}_{source_id}"`，跨 App 共用 collection 時會撞名、改過標題就靜默修 0 筆 | 改用 payload 既有的 `app_id` + `doc_type` + `source_id` 複合條件定位（比照 `delete_by_app_source`），`filename` 降為純顯示欄位 |
| 2 | `source_id: Union[int, str]` | Qdrant `MatchValue(2048)` ≠ `MatchValue("2048")`，型別不一致會查不到 | 統一 `int`，與 `IngestTriggerRequest` 一致 |
| 3 | 同步處理後回 `200 OK` | 描述併發預設 1、單張上限 180 秒，5 張失敗圖最壞 15 分鐘掛在同一條 HTTP 連線上 | 改為 `202 Accepted` + arq 背景佇列，與 `/ingest/trigger` 一致 |
| 4 | 未回寫來源應用的失敗計數 | KB 的「⚠ 圖片描述失敗 X」讀的是 `rag_sync_status.caption_failed_count`，不回寫則標籤永遠不會消失（初版 §5.2 驗收條件必然失敗） | 任務完成後重新計數並回寫（`direct_db` 直寫 / `webhook` 回調） |
| 5 | `onlyFailed` 對外開放 | `false` 等於重算整份文件所有圖片，正是本功能要避免的昂貴操作 | 外部 API 不開放此參數，固定 `only_failed=True`（內部端點維持原樣） |
| 6 | 前端範例欄位對不上 client 簽章 | `sourceType`/`title` 與 `docType`/`filename` 不符、缺 `appId`/`knowledgeBaseId`，會 422 | 見 §5.2 修正版程式碼 |

---

## 1. 背景與痛點分析

在多應用 RAG 向量同步架構中，當外部應用（如 `GigaSolarKnowledgeBase`）同步 PDF 或 DOCX 等包含內嵌圖片的文件至 AiRAG 時，可能因 LLM 多模態模型短暫連線逾時或 Rate Limit，導致部分內嵌圖片標記為「AI 描述產生失敗 (`caption_failed=True`)」。

目前 `GigaSolarKnowledgeBase` 的管理介面（`AdminView.vue`）針對這類文件雖有顯示 `⚠ 圖片描述失敗 X` 的警示標籤，但勾選後點擊「指定執行切分」時，觸發的是全量重新切分 (`POST /api/external/ingest/trigger` with `action: "upsert"`)。

**全量重轉的痛點**：
1. **資源浪費**：整份文件所有的文字段落、正確產生描述的圖片段落都會被重新提取、切分與計算 Embedding。
2. **耗時較長**：大檔案重新解析與重新 Embedding 需要較長時間。
3. **可能再次逾時**：大量圖片全部重新呼叫多模態模型，再次觸發逾時的風險較高。

**解決思維**：
AiRAG 內部已具備 `ImageCaptionRepairService`（[backend/services/image_caption_repair_service.py](../../backend/services/image_caption_repair_service.py)），能夠利用磁碟上保留的原圖二進位檔，**僅針對描述失敗的圖片段落**重新呼叫多模態模型生成描述、計算 Embedding，並以相同的 `point_id` 直接覆蓋 Qdrant 中舊的失敗點位（完全不變動文字段落與其他成功段落）。

因此，只需為外部應用開放一個專用的 External API (`POST /api/external/ingest/repair-captions`)，即可實現「前端一鍵僅重轉描述失敗的圖片」，無須全量重轉。

**現有可複用資產（實作前先確認這些沒有變動）**：

| 資產 | 位置 | 本案如何使用 |
|---|---|---|
| `ImageCaptionRepairService.repair()` | [image_caption_repair_service.py:70](../../backend/services/image_caption_repair_service.py:70) | 核心修復邏輯，本案需擴充定位參數 |
| `ImageCaptionRepairService.is_caption_failed()` | [image_caption_repair_service.py:28](../../backend/services/image_caption_repair_service.py:28) | 任務完成後重新計數剩餘失敗數 |
| `QdrantService.get_image_points()` | [qdrant_service.py:1545](../../backend/services/qdrant_service.py:1545) | 本案需擴充 app/doc/source 過濾條件 |
| `QdrantService.delete_by_app_source()` | [qdrant_service.py:1164](../../backend/services/qdrant_service.py:1164) | **filter 寫法的範本**，照抄其三段式 `FieldCondition` |
| payload 的 `app_id`/`doc_type`/`source_id` | [ingest_service.py:468](../../backend/services/ingest_service.py:468) | 定位依據 |
| `IngestReportService` | [ingest_report_service.py](../../backend/services/ingest_report_service.py) | 回寫剩餘失敗數 |
| arq 佇列 (`ArqPool` / `worker.py`) | [worker.py](../../backend/worker.py) | 背景執行 |

---

## 2. 架構設計與 API 契約

### 2.1 API 基本資訊

* **Method**: `POST`
* **Path**: `/api/external/ingest/repair-captions`
* **Authentication Header**: `X-API-Key: <AIRAG_INGEST_API_KEY>`（`scope="ingest"` 的金鑰，與 chat 金鑰互不相通）
* **Content-Type**: `application/json`
* **執行模式**：非同步。端點僅做驗證與排入佇列，立即回 `202`；實際修復由 arq worker 執行，結果透過 §4 的回寫機制通知來源應用。

### 2.2 Request Body 欄位 (camelCase)

| 欄位名稱 | 型態 | 必填 | 說明 | 範例 |
|---|---|---|---|---|
| `appId` | String | **是** | 外部應用識別碼，同時作為定位條件 | `"kb"` |
| `docType` | String | **是** | 文件類型（`attachment_file` 或 `article`），同時作為定位條件 | `"attachment_file"` |
| `sourceId` | **Integer** | **是** | 來源系統主鍵 ID，同時作為定位條件。**必須是整數**，與 `/ingest/trigger` 一致 | `2048` |
| `knowledgeBaseId` | String | **是** | 寫入的 AiRAG 知識庫 ID（**純 24 位 hex 的 MongoDB ObjectId，無前綴**） | `"6a389dc83578b9d3d7172440"` |
| `callbackUrl` | String | 條件必填 | App 的 `report_mode` 為 `webhook` 時必填，修復完成後回調此網址 | `"http://bpm-backend.company.internal/api/v1/rag-sync/caption-repair-callback"` |
| `filename` | String | 否 | **僅供 log 與訊息顯示，不參與定位**，可省略 | `"EFGP-ReleaseNote.pdf"` |

> **不提供 `onlyFailed` 參數**：外部 API 固定只修描述失敗的段落。需要重算整份文件所有圖片時，請走內部端點 `POST /api/retrieval/knowledge-bases/{id}/images/regenerate-captions`（需 JWT 登入）。

### 2.3 Response 規範

#### 排入成功 (`202 Accepted`)

```json
{
  "success": true,
  "message": "圖片描述修復任務已排入佇列",
  "taskId": "b1f0c2e4d5a6478f9c0e1a2b3c4d5e6f"
}
```

#### 錯誤回應

| 狀態碼 | 情境 | `detail` 範例 |
|---|---|---|
| `400` | `appId` 未登錄 / 已停用 / `knowledgeBaseId` 格式錯誤或不存在 / webhook 模式缺 `callbackUrl` | 比照 [external.py:134-156](../../backend/routers/external.py:134) 既有訊息風格 |
| `401` | `X-API-Key` 無效或 scope 非 `ingest` | — |
| `409` | 同一份文件的修復任務已在佇列中（去重機制，見 §3.4） | `"appId='kb' docType='attachment_file' sourceId=2048 的圖片描述修復任務已在處理中，請稍候"` |

---

## 3. AiRAG 後端實作細節

### 3.1 擴充 `QdrantService.get_image_points()`（[qdrant_service.py:1545](../../backend/services/qdrant_service.py:1545)）

新增 `app_id` / `doc_type` / `source_id` 三個選填參數，`scroll_filter` 的 `must` 依有值的條件動態組裝；`chunk_type == "image"` 恆常保留。既有兩個呼叫端（內部端點、`ImageCaptionRepairService`）行為完全不變。

```python
    async def get_image_points(
        cls,
        collection_name: str,
        filename: Optional[str] = None,
        point_ids: Optional[List[str]] = None,
        app_id: Optional[str] = None,
        doc_type: Optional[str] = None,
        source_id: Optional[Any] = None
    ) -> List[Dict[str, Any]]:
        ...
        if point_ids:
            ...  # 維持原樣

        must = [models.FieldCondition(key="chunk_type", match=models.MatchValue(value="image"))]
        if filename:
            must.append(models.FieldCondition(key="filename", match=models.MatchValue(value=filename)))
        if app_id:
            must.append(models.FieldCondition(key="app_id", match=models.MatchValue(value=app_id)))
        if doc_type:
            must.append(models.FieldCondition(key="doc_type", match=models.MatchValue(value=doc_type)))
        if source_id is not None:
            must.append(models.FieldCondition(key="source_id", match=models.MatchValue(value=source_id)))
        if len(must) == 1:
            # 只剩 chunk_type 條件等於掃全庫圖片段落，必定是呼叫端漏帶條件，直接失敗而非誤修全庫
            raise ValueError("get_image_points() 需要 point_ids、filename 或 (app_id, doc_type, source_id) 其中一組定位條件")
```

**注意**：`source_id` 的型別必須與寫入時一致（int）。`MatchValue(value="2048")` 不會匹配到 payload 中的 `2048`。

### 3.2 擴充 `ImageCaptionRepairService.repair()`（[image_caption_repair_service.py:70](../../backend/services/image_caption_repair_service.py:70)）

同步新增 `app_id` / `doc_type` / `source_id` 三個選填參數並原樣往下傳給 `get_image_points()`，其餘邏輯（併發、覆蓋 point、統計）完全不動。

### 3.3 Schema 定義 (`backend/schemas/ingest.py`)

```python
class RepairImageCaptionsTriggerRequest(BaseModel):
    """
    POST /api/external/ingest/repair-captions 的 Request Body。
    以 (app_id, doc_type, source_id) 定位要修復的圖片段落，與 delete_by_app_source 的定位鍵一致；
    filename 僅供 log／訊息顯示，不參與 Qdrant 過濾。
    """
    model_config = ConfigDict(populate_by_name=True)

    app_id: str = Field(..., alias="appId")
    doc_type: str = Field(..., alias="docType")
    source_id: int = Field(..., alias="sourceId")
    knowledge_base_id: str = Field(..., alias="knowledgeBaseId")
    callback_url: Optional[str] = Field(None, alias="callbackUrl")
    filename: Optional[str] = None
```

### 3.4 路由端點 (`backend/routers/external.py`)

新增 `/ingest/repair-captions`，驗證邏輯與 `trigger_ingest()` 完全對稱（[external.py:122](../../backend/routers/external.py:122)）：

1. `Depends(verify_ingest_api_key)`。
2. `AppRegistration` 存在且 `is_active`（未登錄／已停用分開回報，比照既有訊息）。
3. `report_mode == "webhook"` 時必須帶 `callbackUrl`。
4. `PydanticObjectId(knowledge_base_id)` 轉型 + `KnowledgeBase.get()` 存在性檢查。
5. 以固定 job id 排入 arq 佇列，回 `202`。

```python
@router.post("/ingest/repair-captions", status_code=202)
async def repair_image_captions(
    request: RepairImageCaptionsTriggerRequest,
    api_key: ExternalApiKey = Depends(verify_ingest_api_key)
):
    # ...（1~4 的驗證比照 trigger_ingest）...

    job_payload = {
        "app_id": request.app_id,
        "doc_type": request.doc_type,
        "source_id": request.source_id,
        "knowledge_base_id": request.knowledge_base_id,
        "callback_url": request.callback_url,
        "filename": request.filename
    }

    # 同一份文件短時間內重複觸發（誤觸連點／兩位管理員同時操作）會讓地端 vLLM 承受雙倍負載，
    # 以 5 分鐘時間桶併入 job id 去重：擋得住連點，又不影響「稍後想再重試一次」
    bucket = int(time.time() // 300)
    job_id = f"repair-captions:{request.app_id}:{request.doc_type}:{request.source_id}:{bucket}"

    pool = await ArqPool.get_pool()
    job = await pool.enqueue_job("process_caption_repair_task", job_payload, _job_id=job_id)
    if job is None:
        raise HTTPException(
            status_code=409,
            detail=(f"appId='{request.app_id}' docType='{request.doc_type}' "
                    f"sourceId={request.source_id} 的圖片描述修復任務已在處理中，請稍候")
        )

    return {"success": True, "message": "圖片描述修復任務已排入佇列", "taskId": job.job_id}
```

> **arq 去重的已知行為**：`enqueue_job` 在同 `_job_id` 已存在時回 `None`，且該 id 會被佔用到結果過期（`keep_result` 預設 3600 秒）。若用完全固定的 job id，一小時內無法對同一份文件再修一次——因此才加時間桶。

### 3.5 arq 任務註冊 (`backend/worker.py`)

```python
async def process_caption_repair_task(ctx, payload: dict):
    """
    arq 背景任務進入點：處理 POST /api/external/ingest/repair-captions 排入的圖片描述修復任務。
    """
    from services.ingest_service import IngestService
    await IngestService.process_caption_repair(payload)


class WorkerSettings:
    functions = [process_ingest_task, process_caption_repair_task]
```

**務必記得加進 `functions` 清單**（[worker.py:34](../../backend/worker.py:34)），否則 arq 會以「未知任務名」拒絕執行，而端點仍照常回 202，症狀是「按了沒反應也沒錯誤」。`job_timeout`（`INGEST_JOB_TIMEOUT`）與 `max_jobs` 沿用既有設定，不另外調整。

### 3.6 任務主體 `IngestService.process_caption_repair()`

放在 `IngestService`（[ingest_service.py](../../backend/services/ingest_service.py)）而非新建服務：它與 `process()` 共用同一組 `AppRegistration` / `KnowledgeBase` 解析與 `IngestReportService` 回報流程。

流程：

1. 取 `AppRegistration`（不存在或停用 → 記 error log 後中止，比照 [ingest_service.py:44-50](../../backend/services/ingest_service.py:44)）。
2. 取 `KnowledgeBase` → `qdrant_collection_name`。
3. 呼叫 `ImageCaptionRepairService.repair(collection_name, app_id=..., doc_type=..., source_id=..., only_failed=True)`。
4. `repaired_count > 0` 時：`QdrantService.invalidate_metadata_cache(collection_name)`，並更新 `kb.updated_at`（比照內部端點 [retrieval.py:670-673](../../backend/routers/retrieval.py:670)）。
5. **重新計數剩餘失敗數**：再次 `QdrantService.get_image_points(...)` 掃該文件的圖片段落，以 `ImageCaptionRepairService.is_caption_failed()` 計數。
   *不直接用 `result["failed_count"]` 推算*——重新掃描才是權威值，可涵蓋舊資料只有佔位文字沒有 `caption_failed` 欄位、以及中途有其他寫入的情況。
6. 呼叫 `IngestReportService.report_caption_repair()` 回寫（見 §4）。
7. 全程輸出 log：`[CaptionRepair] app_id=... doc_type=... source_id=... 修復 N 筆／仍失敗 M 筆`。例外一律 `logger.error` 後往外拋（讓 arq 記錄任務失敗），不吞。

### 3.7 例外與部分失敗的處理原則

* 單張圖失敗（原圖不存在、模型再次逾時）由 `repair()` 內部收斂為該筆 `status="failed"`，**不影響其他圖片，也不會讓任務整體失敗**。
* 磁碟原圖不存在（`FileNotFoundError`，[image_caption_repair_service.py:46](../../backend/services/image_caption_repair_service.py:46)）是真實可能情境（舊資料、降級圖片），屬「這筆修不了」而非系統錯誤，計入剩餘失敗數並回寫。
* 只有 App/KB 解析失敗、Qdrant 或 Embedding 整體不可用等才視為任務失敗。

---

## 4. 回寫來源應用的失敗計數（初版遺漏，必要）

KB 介面上的 `⚠ 圖片描述失敗 X` 來自 SQL 的 `rag_sync_status.caption_failed_count`，是同步完成時由 [`_report_direct_db`](../../backend/services/ingest_report_service.py:112) 寫入的。修復流程若不回寫，前端重新載入後標籤依舊存在，等於「修好了但看不出來」。

### 4.1 新增 `IngestReportService.report_caption_repair()`

```python
    @classmethod
    async def report_caption_repair(
        cls,
        app_reg: AppRegistration,
        *,
        source_type: str,
        source_id: Any,
        repaired_count: int,
        caption_failed_count: int,
        callback_url: Optional[str] = None
    ) -> None:
        """
        圖片描述修復完成後回寫剩餘失敗數。與 report() 分開是因為本流程不改變同步狀態：
        不動 status / progress / last_synced_version，只更新 caption_failed_count。
        """
```

* **`direct_db`（目前僅 `kb`）**：
  ```sql
  UPDATE rag_sync_status SET caption_failed_count=? WHERE source_type=? AND source_id=?
  ```
  **刻意不帶 `target_version` 條件**：修復針對的是「目前已索引的內容」，而非某個特定版本；帶版本條件反而會在版本欄位不一致時靜默不更新，標籤永遠清不掉。代價是若同一份文件正好有全量重切在跑，計數可能被覆寫——以 §3.4 的 job 去重與「實務上不會同時操作」為緩解，並在 log 留下寫入紀錄。
* **`webhook`**：POST 至 `callback_url`，body 明確標示事件型別，讓來源應用能與同步回調區分：
  ```json
  {
    "event": "caption_repair",
    "appId": "bpm",
    "docType": "attachment_file",
    "sourceId": 2048,
    "repairedCount": 2,
    "captionFailedCount": 0,
    "repairedAt": "2026-08-12T06:31:22.114Z"
  }
  ```
  沿用既有的 `X-RAG-Sync-Key` 標頭與 15 秒 timeout；失敗只記 error log，不重試（比照 [_report_webhook](../../backend/services/ingest_report_service.py:82)）。

### 4.2 回寫時機

任務正常執行完（即使 `repaired_count == 0`）就回寫。修復後已無失敗圖時寫入 `0`，正是清除警示標籤的關鍵；反之若全部再次失敗，寫回原數字，讓管理者知道要改查別的原因（例如 vLLM 掛了、原圖遺失）。

---

## 5. GigaSolarKnowledgeBase 前後端整合規劃

### 5.1 後端整合 (`GigaSolarKnowledgeBase/backend/src/services/aiRagIngestClient.js`)

```javascript
async repairImageCaptions({ appId, docType, sourceId, knowledgeBaseId, filename }) {
  const res = await axios.post(`${this.baseUrl}/api/external/ingest/repair-captions`, {
    appId,
    docType,
    sourceId,
    knowledgeBaseId,
    filename
  }, {
    headers: { 'X-API-Key': this.ingestApiKey },
    timeout: 15000
  })
  return res.data   // { success, message, taskId }
}
```

`sourceId` 傳出前確保是 Number（`Number(row.sourceId)`），字串會導致 AiRAG 端定位不到。

### 5.2 前端介面整合 (`GigaSolarKnowledgeBase/frontend/src/views/AdminView.vue`)

1. **按鈕區塊**：在「指定執行切分」旁新增「重試圖片描述」。

   ```html
   <el-button
     type="warning"
     plain
     :disabled="!ragStatusSelection.length"
     :loading="repairCaptionsLoading"
     @click="executeRepairImageCaptionsManual"
   >
     重試圖片描述
   </el-button>
   ```

2. **處理邏輯（修正版）**：修掉初版的欄位錯置、逐筆錯誤中斷與錯誤訊息取值問題。

   ```javascript
   async function executeRepairImageCaptionsManual() {
     if (!ragStatusSelection.value.length) return ElMessage.warning('請先勾選項目')

     repairCaptionsLoading.value = true
     let queued = 0
     const failures = []
     try {
       for (const row of ragStatusSelection.value) {
         try {
           await ragSyncService.repairImageCaptions({
             appId: AIRAG_APP_ID,                       // 與後端登錄的 app_id 一致
             docType: row.sourceType,                   // KB 的 sourceType 對應 AiRAG 的 docType
             sourceId: Number(row.sourceId),
             knowledgeBaseId: AIRAG_KNOWLEDGE_BASE_ID,  // 與「指定執行切分」使用同一個來源
             filename: row.title
           })
           queued += 1
         } catch (e) {
           // 單筆失敗不能中斷其餘文件
           failures.push(`${row.title}：${e.response?.data?.detail || e.message}`)
         }
       }

       if (queued) ElMessage.success(`已排入 ${queued} 份文件的圖片描述修復任務，完成後請重新整理列表`)
       if (failures.length) ElMessage.error(`${failures.length} 份文件排入失敗：${failures.join('；')}`)

       await loadRagStatusList()
     } finally {
       repairCaptionsLoading.value = false
     }
   }
   ```

3. **非同步結果呈現**：端點回 202，修復需要數十秒到數分鐘。前端沿用既有「指定執行切分」的做法（排入後提示 + 由既有列表重新載入／輪詢呈現），`caption_failed_count` 更新後 `⚠ 圖片描述失敗 X` 標籤自然消失。**不要**用回應內容顯示「已修復 N 筆」——那個數字在排入當下並不存在。

4. **列層級快速觸發（可選）**：點擊 `⚠ 圖片描述失敗 X` 標籤時彈確認框，確認後對該列單筆呼叫同一支 API。

---

## 6. 驗證測試計畫

### 6.1 AiRAG 後端

| # | 案例 | 預期 |
|---|---|---|
| 1 | 對含 `caption_failed=True` 圖片段落的文件呼叫 API | 回 202；worker 完成後該 point 以**相同 point_id** 被覆蓋，`caption_failed=False`、`content` 只有 `[主要內容]` 之後的本文被換掉，前綴保留 |
| 2 | 同一文件的**文字段落** | point_id、payload、向量完全未變動（比對修復前後的 scroll 結果） |
| 3 | **跨 App 隔離**：兩個 App 在同一 collection 有同名 `filename` 的文件，各自都有失敗圖 | 只修 `appId` 相符那份，另一份完全不動（這是初版 filename 定位會出錯的案例） |
| 4 | `sourceId` 傳字串 `"2048"` | 422（Pydantic 型別驗證擋下），不會出現「回 202 但修 0 筆」 |
| 5 | **原圖不存在**（手動刪除 `FileAttachments/image/xxx.png`） | 任務不整體失敗，該筆計為失敗，剩餘失敗數回寫正確，其他圖片照常修復 |
| 6 | 已無失敗圖的文件 | `repaired_count=0`、回寫 `caption_failed_count=0`（標籤清除） |
| 7 | **重複觸發**：5 分鐘內連續兩次同一文件 | 第二次回 409，vLLM 不會收到雙倍請求 |
| 8 | `appId` 未登錄 / 已停用 / `knowledgeBaseId` 不存在 | 400 且訊息可區分（比照 trigger） |
| 9 | 非 `ingest` scope 的金鑰 | 401 |
| 10 | 修復後立即檢索 | metadata cache 已 invalidate，新描述可被檢索到 |

### 6.2 GigaSolarKnowledgeBase 聯調

1. 勾選帶 `⚠ 圖片描述失敗` 的文件 → 點「重試圖片描述」→ 確認 AiRAG **沒有**觸發全量切分（檢查 log 無 `process_ingest_task`、Qdrant 文字段落 point_id 未變）。
2. 等待任務完成後重新載入列表，確認 `rag_sync_status.caption_failed_count` 歸零、警示標籤消失。
3. 勾選多筆（含一筆會失敗的，如 `appId` 錯誤）→ 確認其餘文件仍正常排入，錯誤訊息顯示 AiRAG 回傳的 `detail`。

---

## 7. 需同步更新的文件

* `docs/08_EXTERNAL_INGEST_API_GUIDE.md`：新增本端點章節。**順手修正既有的 `knowledgeBaseId` 範例**（現為 `"kb_6a389dc83578b9d3d717244d"`，實際程式碼是 `PydanticObjectId(...)`，前綴會直接 400）。
* `docs/03_API_CONTRACT.md`：補上 `POST /api/external/ingest/repair-captions`。
* `docs/DevelopmentProcess/NewFeatures.md`：依 AGENT.md 規定記錄本次新功能。
* 若前端／後端有對應調整，另記 `FrontendCorrection.md` / `BackendCorrection.md`。

---

## 8. 不在本次範圍（已知但刻意不處理）

* **API Key 未綁定 App**：`ExternalApiKey` 沒有 `app_id` 欄位（[external_api_key.py](../../backend/models/external_api_key.py)），任何 ingest 金鑰都能宣稱自己是任一 `appId`——這是 `/ingest/trigger` 既有的性質，本案不擴大處理，僅記錄於此。
* **內部端點 `/api/retrieval/.../regenerate-captions`** 維持原樣（含 `only_failed=False` 的全量重算能力與 snake_case 回應）。
* **`IMAGE_CAPTION_CONCURRENCY` 調校**：修復沿用與 ingest 相同的併發與逾時設定，本案不調整。

---

## 附錄 A：為什麼不用同步 `200 OK`

`IMAGE_CAPTION_CONCURRENCY` 預設 `1`、`IMAGE_CAPTION_TIMEOUT` 預設 `180` 秒、非逾時錯誤重試至多 `IMAGE_CAPTION_MAX_ATTEMPTS=3` 次（[config.py:73-89](../../backend/config.py:73)、[llm_service.py:413](../../backend/services/llm_service.py:413)）。

單一文件最壞耗時約 `失敗圖片數 × 180 秒`：5 張圖就是 15 分鐘。同步端點會讓呼叫端 HTTP 連線、中間的 nginx／反向代理與瀏覽器全都在等，且前端逐筆迴圈時倍數放大。`/ingest/trigger` 當初改成 202 + arq 正是同一個原因（[external.py:127-131](../../backend/routers/external.py:127)），本端點沒有理由走回頭路。
