<!-- BUG修正(最新紀錄放最前面) -->

## 2026-07-27 附件 `.doc` 解析亂碼與含大量內嵌圖片 `.docx` 同步逾時修正

### 背景
使用者同步知識庫附件時回報兩個問題：

1. **`.doc` 解析出亂碼**：例如 `會議記錄_專案會議_110329 教育訓練.doc` 在向量庫中的段落內容為
   `ÇŒ™e`、`h˜®U-ŠŠ+^ÿË¡ÃS±` 這類無意義字元，且夾雜 `HYPERLINK "http://..."` 等 Word 功能代碼。
   原因：`parse_doc_to_markdown()` 依序嘗試 textract → pypandoc → comtypes → 二進位字串擷取，但
   `requirements.txt` 從未安裝 textract / pypandoc（pypandoc 本身也不支援讀取舊版 `.doc`），
   comtypes 僅限 Windows 而實際部署為 Linux 容器。四段 fallback 必定全數落到最後的
   「逐位元組取可列印字元」，等於把 OLE2 二進位內容當文字讀，產生的亂碼還會被 embedding 寫入 Qdrant。
2. **`.docx` 同步失敗**：`ERP Tiptop災難實境演練.docx` 在 worker 中報 `TimeoutError`：
   ```text
   300.00s ! a8661c8177d24708b216683cc964e66c:process_ingest_task failed, TimeoutError:
     File "/app/services/ingest_service.py", line 227, in _process_upsert
       extracted_images = list(await asyncio.gather(*[process_one_image(img) for img in raw_images]))
   ```
   文字解析與圖片抽取其實都正常（1773 字、19 張圖片），真正原因是 `worker.py` 的 `WorkerSettings`
   未設定 `job_timeout`，沿用 arq 預設值 300 秒；19 張圖片在 `IMAGE_CAPTION_CONCURRENCY=3` 下
   至少需 7 輪多模態描述，必定超出 300 秒。另外 `describe_image()` 內的 `timeout=300.0` 是 httpx
   的單次讀取逾時，串流模式下無法約束單張圖片的總生成時間，整份文件耗時因此不可預估。

### 變更內容
1. `backend/services/word_parent_child_chunker.py`：
   - 新增 `_extract_doc_pieces()`，改以 OLE2 Compound File 直接解析舊版 `.doc`：從 `WordDocument`
     stream 的 FIB flags（offset `0x000A`）判斷 table stream 為 `1Table` 或 `0Table`，讀取
     `FibRgFcLcb97` 的 `fcClx`/`lcbClx`（offset `0x01A2`）取得 Clx，跳過 Prc（`0x01`）後解析
     Pcdt（`0x02`）內的 PlcPcd piece table，再依各 piece 的 `fc` 旗標分別以 UTF-16LE 或
     cp950（失敗才退 cp1252）解碼，可正確還原繁體中文內容。
   - 新增 `_clean_doc_text()`：移除 field instruction（`\x13`…`\x14` 之間的 `HYPERLINK` 等代碼）
     只保留顯示結果，並把儲存格結束 `\x07`、手動換行 `\x0b`、分頁 `\x0c`、段落結束 `\r` 統一轉為換行。
   - `parse_doc_to_markdown()` 改以上述解析為唯一路徑；副檔名為 `.doc` 但實際是 OOXML（`PK` 開頭）
     時轉交 `parse_docx_to_markdown()`；非 OLE2 檔案（RTF / HTML 另存）直接拋出可讀錯誤訊息。
     **移除二進位字串擷取 fallback**，解析失敗改為明確 `ValueError`，避免亂碼污染向量庫。
2. `backend/requirements.txt`：新增 `olefile>=0.47`（純 Python、無編譯依賴）。
3. `backend/worker.py`：`WorkerSettings` 新增 `job_timeout = settings.INGEST_JOB_TIMEOUT` 與
   `max_tries = settings.INGEST_JOB_MAX_TRIES`，避免逾時任務以預設 5 次反覆重跑消耗 vLLM 資源。
4. `backend/services/ingest_service.py`：`process_one_image()` 內的 `LLMService.describe_image()`
   改以 `asyncio.wait_for(..., timeout=settings.IMAGE_CAPTION_TIMEOUT)` 包裹，逾時走既有
   `caption_failed` 佔位描述邏輯，讓整份文件的圖片處理時間上限可預估
   （最壞情況約 `ceil(圖片數 / IMAGE_CAPTION_CONCURRENCY) × IMAGE_CAPTION_TIMEOUT`）。
5. `backend/config.py`、`backend/.env.example`：新增 `IMAGE_CAPTION_TIMEOUT`（預設 180 秒）、
   `INGEST_JOB_TIMEOUT`（預設 3600 秒）、`INGEST_JOB_MAX_TRIES`（預設 2），並補上原本未列於
   `.env.example` 的 `IMAGE_CAPTION_CONCURRENCY`。

### 驗證
- `DocumentParser.parse_file()` 實測兩份問題檔案：
  - `會議記錄_專案會議_110317 教育訓練.doc`：1327 字、`U+FFFD` 取代字元 0 個，會議主題／參與人員／
    系統設定路徑等內容完整正確，`HYPERLINK` 功能代碼已不出現，表格儲存格正確斷行；切分後 3 個 chunk。
  - `ERP Tiptop災難實境演練.docx`：1773 字、`U+FFFD` 0 個，標題階層與 Markdown 表格正常；
    切分後 8 個 chunk，圖片抽取 19 張（0.84 MB）皆成功。
- `python tests/test_word_chunker.py` 通過（exit code 0，需以 `PYTHONIOENCODING=utf-8` 執行，
  否則 Windows cp950 主控台在列印 `✔` 時會 `UnicodeEncodeError`，屬既有環境問題非本次變更）。
- `worker.py` / `config.py` import 檢查通過，`job_timeout=3600`、`max_tries=2`、
  `IMAGE_CAPTION_TIMEOUT=180` 讀取正確。

### 已知限制
- 舊版 `.doc` 仍不會抽取內嵌圖片做描述（`ingest_service.py` 的圖片抽取僅涵蓋 `pdf` / `docx` / `dotx`），
  此次未變更該行為。
- `.doc` 解析結果為純文字（無 Markdown 標題階層），Parent-Child 切分會視為單一 parent；
  舊版格式無可靠的 outline 資訊，維持現狀。
- 需重新 `docker-compose up -d --build`（含 worker）讓 `olefile` 與新設定生效，並對先前寫入亂碼的
  `.doc` 附件重新觸發一次同步以覆蓋舊 chunk。

---

## 2026-07-22 Qdrant 啟用 API Key 時 AsyncQdrantClient 誤用 HTTPS 導致 SSL 握手失敗修正

### 背景
為支援多應用存取與提升安全性，於 `docker-compose.yml` 中為 Qdrant 服務啟用 `QDRANT__SERVICE__API_KEY` 認證。設定後，前端「知識庫管理」無法建立知識庫 Collection（報錯：「無法在向量資料庫中建立對應的知識集合」），且「自訂資料向量化」無法讀取 Collection metadata。
檢視 `airag-backend` 容器日誌發現錯誤：
```text
[ERROR] airag.qdrant: Failed to create Qdrant collection '...': [SSL: WRONG_VERSION_NUMBER] wrong version number (_ssl.c:1016)
```
原因：Python 官方 `qdrant-client` SDK 存在預設特性，當連線參數包含 `api_key` 且未指定 `https` 時，SDK 會預設開啟 `https=True`。因 Docker 容器內部 Qdrant (埠 6333) 為 HTTP 協定，後端發送 HTTPS 握手給 HTTP 服務導致 SSL 協定版本錯誤，進而使所有 Qdrant 操作失效。

### 變更內容
1. `docker-compose.yml`：
   - `qdrant` 服務新增環境變數 `QDRANT__SERVICE__API_KEY`。
   - `backend` 服務環境變數同步新增 `QDRANT_API_KEY` 傳遞金鑰。
2. `backend/.env`：新增 `QDRANT_API_KEY` 環境變數。
3. `backend/config.py`：新增 `QDRANT_API_KEY: Optional[str] = os.getenv("QDRANT_API_KEY", None)` 支援讀取金鑰。
4. `backend/services/qdrant_service.py`：
   - 初始化 `AsyncQdrantClient` 時帶入 `api_key=settings.QDRANT_API_KEY`。
   - **關鍵修正**：明確加上 `https=False` 參數，強制連線採用 HTTP 協定，防止 SDK 因設定 `api_key` 誤啟用 HTTPS 導致 SSL 握手失敗。

### 驗證
- 執行 `docker-compose up -d --build backend` 重新編譯並啟動後端容器。
- 檢視 `airag-backend` 容器日誌，`SSL: WRONG_VERSION_NUMBER` 錯誤訊息已消失。
- 前端「知識庫管理」建立 Collection 及「自訂資料向量化」檢索功能已恢復正常運作。

---

## 2026-07-17 `Department.code` 新增唯一索引導致既有部署啟動失敗修正

### 背景
同日稍早實作「外部 API 真實使用者身分」功能時，為 `Department` 新增了 `code: Indexed(str, unique=True)` 欄位。使用者實際部署後，MongoDB 啟動時建立索引即失敗並讓整個後端無法啟動：
```
E11000 duplicate key error collection: airag.departments index: code_1 dup key: { code: null }
```
原因：`departments` collection 在此欄位新增前已存在部門文件，這些舊文件完全沒有 `code` 欄位；一般（非 sparse）unique index 會把「缺少該欄位」的多筆文件一律視為值相同的 `null`，因此建置索引時判定為重複鍵值而失敗，屬於「對既有 Collection 新增必填唯一欄位」的典型陷阱，實作當下未預先評估既有資料相容性。

### 變更內容
- `backend/models/department.py`：`code` 欄位改為 `Optional[Indexed(str, unique=True, sparse=True)] = None`。`sparse=True` 讓唯一性索引只對「確實有 `code` 欄位」的文件生效，缺少此欄位的舊部門文件會被索引直接略過、不參與唯一性判斷，因此不會再互相衝突；新建立的部門（`POST /api/users/departments` 的 `code` 欄位本來就已要求必填）則仍受正常的唯一性保護。
- `backend/routers/users.py`：`DepartmentResponse.code` 同步改為 `Optional[str] = None`，避免舊部門（`code` 為 `None`）回傳時被 Pydantic Response Model 驗證擋下。
- `frontend/src/views/RoleSettingsView.vue`：部門 Chip 顯示代號時，若為 `null` 顯示「未設定代號」而非空白。
- `frontend/src/components/embedding/VectorManagementTab.vue`：`fetchDepartments()` 對缺少 `code` 的舊部門，UI 送出／比對值改為退回使用部門名稱（`dept.code || dept.name`），並改用 `dept.id` 作為 `v-for` 的 `:key`（避免多筆缺少代號的部門在複選框中因 `:key`/`:value` 相同而互相衝突）；此退回行為與後端 `PermissionService` 的代號／名稱雙軌比對邏輯一致。

### 驗證
- `python -m py_compile` 通過。
- 以 venv Python 驗證 `Department.code` 欄位為 `Optional`、`default=None`；`DepartmentResponse(code=None)` 可正常建構不拋出驗證錯誤。
- 無法在本機沙箱環境連線實際 MongoDB 重現索引建置流程，已對照 MongoDB 官方文件確認 `sparse` unique index 對「欄位缺失」文件的排除行為（僅排除欄位完全缺失者，不影響本次修正的既有資料情境）；請使用者於實際環境重新部署後端服務驗證啟動是否成功。
- `npm run build` 通過。

---

## 2026-07-14 AI 總結相似度門檻 Hard Cutoff 相關 4 項問題修正 (8.1 ~ 8.4)

### 背景
依據 [`NewFeaturesPlan_SimilaritySummaryThresholdPlan.md`](NewFeaturesPlan_SimilaritySummaryThresholdPlan.md) 第 8 節 Code Review Findings 進行修正。針對 Early Exit 前端警示未渲染、附件查詢法被 Early Exit 誤殺、死碼欄位清理、無知識庫 step 提示遺漏進行修復。

### 變更內容
1. `frontend/src/stores/chatStore.js` (8.1)：補齊 `event: message` SSE 處置邏輯，修復跳過總結時訊息泡泡留白問題。
2. `backend/routers/rag.py` (8.2 & 8.4)：
   - 新增 `has_attachments` 判斷，防止 Early Exit 誤殺包含有效附件內容的檢索請求。
   - 補回非 DB 模式且未指定知識庫時發送 `略過語義分析` / `略過向量查詢` 步驟事件。
3. `backend/schemas/retrieval.py` (8.3)：移除 `SearchParams` 中無實際作用之 `ai_summary_score_threshold` 死碼宣告。

---

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

