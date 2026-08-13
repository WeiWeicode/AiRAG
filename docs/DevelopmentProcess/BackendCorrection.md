<!-- 後端修正紀錄(最新紀錄放最前面) -->

## 2026-08-13 MongoDB 存取認證與權限配置（docker-compose.yml）

### 背景
配合 [NewFeaturesPlan_MongoDBAuthPlan.md](NewFeaturesPlan_MongoDBAuthPlan.md) 規劃，於部署層啟用 MongoDB `--auth` 認證模式，並為 AiRAG 服務設定帶憑證之連線字串。

### 變更內容
- `docker-compose.yml`：
  - `mongodb` 服務：新增 `command: ["--auth"]` 啟用帳密驗證，並加註「帳號須先建、認證後開」的順序約束（重建 `mongo_data` volume 時同樣適用）。
  - `backend` 與 `worker` 服務：更新 `MONGODB_URL` 為 `mongodb://airag_admin:${MONGO_ADMIN_PASSWORD}@mongodb:27017/?authSource=admin`。
- `backend/models/mongodb.py`：新增 `mask_mongodb_url()`，`init_mongodb()` 的連線 log 改輸出遮蔽後的字串。
  原本 `logger.info(f"Connecting to MongoDB at: {settings.MONGODB_URL}")` 會把整串連線字串寫進容器 log，
  帳密加進去之後等於**把 root 密碼明文留在 `docker logs airag-backend` / `airag-worker`**
  （`init_mongodb()` 為兩者共用，見 `backend/worker.py:33`），缺口只是從「無認證」換成「密碼躺在 log」。
  遮蔽後保留 scheme / 帳號 / host / port / query，**只遮密碼**：帳號與 `authSource` 都不是機密（compose 與 `.env.example` 中本就可見），
  而 `Authentication failed` 最常見的原因正是「帳號打錯」「`authSource` 指錯 db」「compose 變數沒展開導致密碼為空」，
  三者都得靠這行 log 判讀。密碼為空時顯示 `<empty>` 以與「有值」區分。
- `backend/.env.example`：`MONGODB_URL` 補上帶憑證與 `authSource` 的範例格式、密碼字元集限制（含 `@ : / ? # [ ] %` 需 percent-encode），
  並註明 compose 的 `environment:` 會覆蓋此檔（`load_dotenv()` 不覆寫既有環境變數），避免新環境照抄成無認證設定。

### 驗證
`mask_mongodb_url()` 已以下列輸入實測：帶帳密、無帳密、密碼含 `%40`、`mongodb+srv://`、
非法 port、非 URL 字串、以及會讓 `urlsplit` 拋 `ValueError` 的畸形 IPv6（`mongodb://[::1:27017`）。
帳密一律被換成 `***:***`，其餘部分原樣保留。

---

## 2026-08-12 圖片描述管線記憶體壓力改善（DGX GB10 統一記憶體）

### 背景
DGX 主機在圖片解析期間進入「ping 得到但 SSH 連不進、未重開機」的假死狀態，
核心 log 出現 `NVRM: ... Out of memory [NV_ERR_NO_MEMORY]`，且**全程無 `oom-kill` 紀錄**。

硬體為 **DGX Spark（GB10，aarch64）**，CPU 與 GPU 共用同一塊約 121GiB 統一記憶體，
`nvidia-smi` 回報 `memory.total [N/A]` 即為此架構特徵。vLLM 的
`--gpu-memory-utilization 0.60` 直接從作業系統的記憶體扣掉 72.6GB，且**多模態前處理
（解碼／resize／patch embedding）是 vLLM 行程內的一般 host 配置，不在該預算之內**。
餘裕耗盡後核心 thrash page cache，ping 走 softirq 照常回應、sshd 卻 fork 不出來。

完整分析見 [NewFeaturesPlan_ImagePipelineMemoryPlan.md](NewFeaturesPlan_ImagePipelineMemoryPlan.md)。
與 [NewFeaturesPlan_IngestImageCaptionTimeoutPlan.md](NewFeaturesPlan_IngestImageCaptionTimeoutPlan.md)
是同一條管線的不同瓶頸：後者處理時間（已砍圖片數量與輸出長度），本次處理**輸入端的像素量**。

### 變更內容
- `backend/requirements.txt`：補列 `pillow>=10.0.0`。環境中原本已有 Pillow 12.3.0，
  但屬**未宣告的傳遞相依**，核心管線用到就必須明確宣告。
- `backend/services/llm_service.py`：新增 `_downscale_image_for_caption()`，於
  `describe_image()` 的 base64 編碼**之前**把長邊超過上限的圖片等比例縮小。
  放在此處而非 PDF 抽取階段，是為了讓磁碟保留原始解析度，且 ingest 與
  `ImageCaptionRepairService` 兩條路徑自動共用同一套邏輯。
- `backend/config.py`：新增 `IMAGE_CAPTION_MAX_DIMENSION`(1536，設 0 可停用)；
  `IMAGE_CAPTION_CONCURRENCY` 預設由 3 改為 **1**。
- `docker-compose.yml`：`backend` 與 `worker` 各加 `mem_limit: 8g` 與
  `restart: unless-stopped`。

### 設計要點（後續修改請勿破壞）
縮圖函式的**處理順序本身就是規格**，三個陷阱皆已實測確認：

1. **先判斷尺寸**：長邊未超標直接回傳原始 bytes，不重新編碼。
2. **先正規化色彩模式，再 resize**：`P`/`PA` 調色盤模式若直接用 LANCZOS 縮放，
   插值會作用在**調色盤索引值**上——不會報錯，但輸出是亂色。
3. **PNG 保留 alpha，不可 `convert("RGB")`**：實測 `RGBA(0,0,0,0).convert("RGB")` → `(0,0,0)`
   純黑。PDF/Word 大量圖片是「透明底 + 黑色線條」的流程圖，轉了就變**黑底黑字**，
   送給模型等於送一張全黑圖，且不會有任何錯誤訊息。JPEG 因不支援 alpha，
   須用白底 `paste(img, mask=img.split()[-1])` 合成。
4. **輸出格式必須與輸入相同**，否則與呼叫端寫進 data URI 的 `mime_type` 不一致。
5. **任何失敗只記 warning 並沿用原圖**，不可讓縮圖問題升級成 `caption_failed`。

`mem_limit` 與 `restart` **必須成套**：compose 檔原本所有服務都沒有 restart policy，
單獨加上限只會把「主機假死」換成「容器 OOM-kill 後靜默不起」。

### 驗證
- `py_compile` 通過；`docker compose config` 語法通過。
- 縮圖規格與陷阱（7 項全過）：

  | # | 案例 | 結果 |
  |:---|:---|:---|
  | 1 | 4000×3000 PNG | → 1536×1152，比例與格式維持 |
  | 2 | 800×600 小圖 | 回傳 bytes **與輸入完全相同**（未重新編碼） |
  | 3 | 透明底 + 黑線 PNG | 背景仍為 `(0,0,0,0)` 透明、線條完好，**未變黑底** |
  | 4 | `P` 模式 2400×2400 | 中心像素 `(255,0,0)` 正確，未插值到索引值 |
  | 5 | CMYK JPEG | → RGB 並維持 JPEG |
  | 6 | 損壞圖片 bytes | 只記 warning，原樣回傳未拋例外 |
  | 7 | `MAX_DIMENSION=0` | 停用生效，大圖原樣回傳 |

- 記憶體削減實測（4000×3000 高頻雜訊 JPEG，接近真實掃描件最壞情況）：

  | | 像素量 | 檔案 | base64 | raw RGB |
  |:---|:---|:---|:---|:---|
  | 原圖 | 12.0M px | 8.7MB | 11.5MB | 34MB |
  | 縮圖後 | 1.77M px | 0.5MB | 0.7MB | 5.1MB |

  **像素量降為 1/6.8**，vLLM 端前處理的記憶體峰值同比例下降。

- ⚠️ 主機面行為（`free -h` 峰值、SSH 存活、不再出現 NVRM OOM）待使用者以實際 PDF 驗收，
  見規劃文件第 7 節。**vLLM 啟動參數的調整（第 5 節）不在本次程式改動範圍，仍需主機端配合。**

---


## 2026-08-12 大量內嵌圖片 PDF 同步逾時改善（批次一、批次二）

### 背景
`airag-worker` 處理一份含 100+ 張內嵌圖片的 PDF 時，在 3600s 被 arq 判定 `TimeoutError`，
整份文件同步失敗且知識庫內一個 chunk 都沒有。完整根因分析與決策依據見
[NewFeaturesPlan_IngestImageCaptionTimeoutPlan.md](NewFeaturesPlan_IngestImageCaptionTimeoutPlan.md)。

核心問題不是單一 bug，而是「圖片數量 × 單張成本」超出時間預算，且流程為全有全無：
`ceil(100/3) × 3 × 180 ≈ 5.2 小時`，`INGEST_JOB_TIMEOUT` 調到 7200 也擋不住。

### 變更內容

**批次一：數量與成本控制**
- `backend/config.py`：新增 `IMAGE_CAPTION_MAX_TOKENS`(4096)、`IMAGE_MIN_WIDTH`(100)、
  `IMAGE_MIN_HEIGHT`(100)、`IMAGE_MIN_BYTES`(8192)。並於 `IMAGE_CAPTION_TIMEOUT` 補上約束註解：
  此值必須小於 `describe_image()` 內 `chat_completion` 的 httpx timeout(300)，否則逾時會改以
  `httpx.ReadTimeout` 拋出，使「逾時不重試」分流靜默失效。
- `backend/services/document_parser.py`：`extract_images_from_pdf()` 新增四道過濾
  （xref 去重 → 尺寸門檻 → 大小門檻 → sha256 內容去重），跨頁重複的 logo/圖章與裝飾小圖直接捨棄。
  另加單張獨立 `try/except`（單張損壞不再中斷其後所有頁面）、`doc.close()` 移入 `finally`、
  輸出過濾統計 info log。**DOCX 路徑未動**（已有自己的 OLE 物件過濾）。
- `backend/services/llm_service.py`：`describe_image()` 的 `max_tokens` 由寫死 20480 改為
  `settings.IMAGE_CAPTION_MAX_TOKENS`；`describe_image_with_retry()` 新增
  `timeout: Optional[float] = None` 參數（預設 None 沿用 `IMAGE_CAPTION_TIMEOUT`，
  既有呼叫端不受影響），並加入例外分流：`asyncio.TimeoutError` 不重試直接拋出，
  其餘例外維持重試 `IMAGE_CAPTION_MAX_ATTEMPTS` 次。單張最壞成本 555s → 約 180s。

**批次二：預算與可靠性**
- `backend/config.py`：新增 `IMAGE_CAPTION_PHASE_BUDGET_RATIO`(0.6)、
  `INGEST_SOFT_DEADLINE_MARGIN`(120)、`ARQ_MAX_JOBS`(2)。
- `backend/services/ingest_service.py`：
  - 新增模組常數 `MIN_CAPTION_ATTEMPT_SECONDS = 10`（剩餘預算不足時不發必定逾時的請求）。
  - 圖片描述階段加入時間預算 `INGEST_JOB_TIMEOUT × RATIO`；預算內傳入
    `timeout=min(IMAGE_CAPTION_TIMEOUT, remaining)`，預算用盡則剩餘圖片降級為
    `caption_failed=True` 佔位描述，讓切分／embedding／upsert 照常完成。
  - 每完成 10% 輸出進度 info log，預算用盡時輸出 warning（已描述/降級張數）。
  - `import asyncio` 提到模組層（原本在圖片區塊內區域匯入）。
- `backend/worker.py`：`WorkerSettings` 新增 `max_jobs = settings.ARQ_MAX_JOBS`。

### 設計要點（後續修改請勿破壞）
- **圖片檔一律落地**：`open(target_path, "wb")` 必須在 caption 的 try/except **之外**。
  降級的圖片若沒存檔，`ImageCaptionRepairService._resolve_image_path()` 會拋
  `FileNotFoundError`，那些段落就永遠補不回描述。
- **降級而非失敗**：本次刻意複用既有的 `caption_failed` + `ImageCaptionRepairService` 管線，
  不新建 checkpoint 或任務拆分機制。
- **尺寸取值方向**：`base_image.get("width")` 取不到時視為「通過」尺寸關卡，
  不可預設 0，否則尺寸未知的圖片會被靜默丟棄。

### 驗證
- `py_compile` 全數通過；`config.py` 新參數在**未修改 `.env`** 的情況下皆取得預期預設值。
- 合成 PDF（4 頁，每頁重複 logo + 1 張大圖 + 內容重複圖 + 純色小圖）：抽出 7 張 →
  `xref 重複 -4、內容重複 -0、尺寸門檻 -1、大小門檻 -1`，實際送描述 **1 張**。
- 例外分流：模擬 hang → 只嘗試 1 次即拋 `TimeoutError`（0.31s，非 3 輪）；
  模擬前兩次 `RuntimeError` → 第 3 次成功回傳，重試行為維持不變。
- 圖片階段預算（stub 外部相依，實跑 `_process_upsert()`）：
  | 情境 | LLM 呼叫 | caption_failed_count | 文字/圖片 chunk | 圖檔落地 |
  |:---|:---|:---|:---|:---|
  | 預算 1s（耗盡） | 0 | 12 | 2 / 12 | 12 |
  | 預算 3600s（充足） | 12 | 0 | 2 / 12 | 12 |
  | 預算 12s（中途用盡） | 6 | 6 | 2 / 12 | 12 |
- 軟性 deadline：`_process_upsert` hang 時於 1.01s（軟性上限）主動放棄，回報
  `status='failed'`、`error_message='處理逾時：超過內部軟性上限 1 秒'`（非空字串）。
- ⚠️ 實際 PDF 端到端行為待使用者手動測試（見規劃文件第 6 節）。**部署時需重啟 worker**，
  arq 在行程啟動時才讀取 `WorkerSettings`。

---


## 2026-07-30 新增集團知識庫混合查詢法 (`KB_hybrid`) 後端支援

### 背景
配合 [NewFeaturesPlan_KBHybridPlan.md](NewFeaturesPlan_KBHybridPlan.md) 規劃，新增檢索模式
`KB_hybrid`：等同 `KB_semantic_hybrid` 移除語義查詢（Instruct LLM JSON 轉換）步驟。

### 變更內容
- `backend/routers/rag.py`（`rag_chat_stream()`）：
  - 雙階段檢索分支判斷加入 `"KB_hybrid"`：
    `if search_type in ("semantic_hybrid", "semantic_hybrid_feedback", "semantic_hybrid_attachment", "KB_semantic_hybrid", "KB_hybrid")`。
  - 上方語義解析分支的判斷 tuple **刻意不加**，讓 `KB_hybrid` 落入 else 分支執行
    `EmbeddingService.get_embedding(question)`、`search_query_text = question`。
  - else 分支新增 `sparse_keywords = None` 初始化（原本未定義，`KB_hybrid` 會第一個踩到）。
  - 權限過濾：`if search_type in ("KB_semantic_hybrid", "KB_hybrid")` 走
    `filter_results_kb_semantic_hybrid()`，否則走 `filter_results()`。
  - `semantic_hybrid_feedback` 的回饋加權與 `semantic_hybrid_attachment` 的附件查詢皆用 `==`
    精確比對，`KB_hybrid` 不會誤觸發，未修改。
- `backend/routers/retrieval.py`（`POST /api/retrieval/search`）：
  - `is_semantic_hybrid_family` tuple 加入 `"KB_hybrid"`。
  - 權限過濾分流改為 `in ("KB_semantic_hybrid", "KB_hybrid")`。
- `backend/services/permission_service.py`：
  - `filter_results_kb_semantic_hybrid()` docstring 補述同時服務 `KB_semantic_hybrid` 與
    `KB_hybrid`，**判斷邏輯完全未改**（方法名沿用，不重新命名以免波及既有呼叫點）。

### 未修改（刻意保留現況）
- `backend/services/qdrant_service.py`：`search_similar_two_step()` 內部仍依傳入的字面值
  `search_type="semantic_hybrid"` 決定要不要做 RRF 融合，與外層模式名稱無關，無須改動。
- `backend/routers/evaluation.py`：批次評估未特別串接 `KB_hybrid`，與 `KB_semantic_hybrid`
  現況一致（既有落差，本次不擴大範圍修正）。
- `rag.py` 內 `score_label` 的 RRF Score 清單未含 `KB_semantic_hybrid`（既有小瑕疵），
  本次維持一致行為未一併修正，避免範圍外變更。

### 驗證
- `python -m compileall backend/routers/rag.py backend/routers/retrieval.py backend/services/permission_service.py` 通過。
- ⚠️ 實際 API 行為待使用者手動測試。

---

## 2026-07-24 子部門權限比對（部門代號前三碼相符歸類）實作

### 背景
集團內部包含諸多課級與子部門（例如 `S1800` 資訊服務部、`S1810` 網路通訊課），為使同部門群組內之子部門能互相存取該部門限制的文件，新增部門代號前三碼相符即歸類為相同部門之比對邏輯。

### 變更內容
- `backend/services/permission_service.py`：
  - 新增 `PermissionService._match_dept(user, target_dept)` 類別方法：
    1. 首先進行部門名稱與代號之完全比對 (`user.department == target_str` 或 `user.department_code == target_str`)。
    2. 若未完全相同，檢查使用者 `department_code` 與限制部門 `target_str` 長度是否皆 >= 3，若前三碼不分大小寫相同（如 `S1810` 與 `S1800` 皆為 `S18`），即判定為部門相符放行。
  - 將 `filter_results()` 與 `filter_results_kb_semantic_hybrid()` 中的所有 `access_dept` 與 `confidential_departments` 比對點統一代換為 `_match_dept()` 呼叫。

### 驗證
- 執行 `scratch/test_kb_semantic_hybrid.py` 單元測試：
  - `S1810`（網路通訊課）使用者成功匹配存取限制為 `S1800`（資訊服務部）之文件。
  - `S1720`（生產二課）使用者成功匹配存取限制為 `S1700`（生產管理部）之文件，且跨部門 `S1800` 文件被正確排除。
- 後端容器編譯與重啟 (`docker-compose up --build -d backend worker`) 順利完成。

---

### 背景
配合 [NewFeaturesPlan_KBSemanticHybridPlan.md](NewFeaturesPlan_KBSemanticHybridPlan.md) 規劃，新增獨立檢索模式 `KB_semantic_hybrid`。針對 Qdrant Point Payload 中的 `is_public` 欄位進行獨立的部門與職級過濾。

### 變更內容
- `backend/services/permission_service.py`：
  - 新增 `PermissionService.filter_results_kb_semantic_hybrid(raw_results, user)` 類別方法。
  - 當 Point Payload 包含 `is_public` 時：
    - `is_public == true`：開放跨部門存取，但必須符合職級門檻 (`user.level <= access_level`)。
    - `is_public == false`：必須符合部門限制 (`user.department == access_dept` 或代號相符) **且** 符合職級門檻 (`user.level <= access_level`)。
    - 個人白名單 `access_members` 優先覆蓋放行。
- `backend/routers/rag.py`：
  - 在 `rag_chat_stream()` 的檢索條件與 `search_similar_two_step` 呼叫點加入 `KB_semantic_hybrid` 模式。
  - 於機密過濾處新增判斷：`search_type == "KB_semantic_hybrid"` 時呼叫 `filter_results_kb_semantic_hybrid`，其餘模式維持原 `filter_results`。
- `backend/routers/retrieval.py`：
  - 在 `/api/retrieval/search` 檢索測試端點的 `is_semantic_hybrid_family` 判斷與權限過濾處加入 `KB_semantic_hybrid` 分流。

### 驗證
- 執行 `scratch/test_kb_semantic_hybrid.py` 權限過濾邏輯單元測試，全數 Test Cases 通過。

---

### 背景
外部 Ingest API 與系統核心在呼叫 `QdrantService.upsert_chunks` 時，此前一次性傳送全部 points 給 Qdrant。當長文件產生大量 chunks 時，單次 HTTP Payload 可能太大導致連線失敗。

### 變更內容
- `backend/services/qdrant_service.py`：
  - `upsert_chunks()` 方法新增 `batch_size: int = 20` 參數，內部改採 `range(0, total_points, batch_size)` 迴圈。
  - 將向量點位分割為每批最多 20 筆（相容密集與稀疏雙向量，以及 fallback 單一密集向量模態），避免單次 Payload 過大。

### 驗證
- `python -m py_compile backend/services/qdrant_service.py` 語法檢驗通過。

---

## 2026-07-23 多應用 RAG 同步段落 Prompt 結構化文字前綴自動注入實作

### 背景
依據需求與手動切分慣例，外部應用同步傳入的文檔/文章在經過 Parent-Child 階層切分與圖片描述生成後，需於每個 chunk 的內文前自動注入 `[檔案名稱]`、`[段落編號]`、`[分類標籤]`、`[主要內容]` 結構化樣板前綴並同步向量化。

### 變更內容
- `backend/services/ingest_service.py`：
  - 在 `_process_upsert()` 產出文字與圖片 chunks 後，於組裝 Qdrant payload 階段為每個 chunk 自動注入結構化標頭前綴：
    ```
    [檔案名稱] {filename}
    [段落編號] 第 {chunk_index + 1} 段
    [分類標籤] {tags}
    [主要內容]
    {chunk_content}
    ```
  - 重新計算結構化內文的 `token_count` 與 `char_count`，並將包含結構化標頭的內文送入 `EmbeddingService.get_embeddings_batch()` 產生向量，確保向量空間與手動批量寫入完全一致。

### 驗證
- `python -m py_compile backend/services/ingest_service.py` 語法檢驗通過。

---

## 2026-07-23 Qdrant 結構化元資料快取 (Metadata Cache) 跨容器與無刷新問題修復

### 背景
外部 Ingest API 在 worker 容器寫入資料後，僅清除 worker 進程內的快取，backend 容器仍沿用高達 600 秒的舊記憶體快取，導致前端 `GET /api/knowledge-bases/{id}/metadata` 無法即時取得最新寫入的檔案名稱選單。

### 變更內容
- `backend/services/qdrant_service.py`：將 `_METADATA_CACHE_TTL` 由 `600` 秒調降為 `60` 秒保底，降低跨容器異動延遲。
- `backend/routers/knowledge_base.py`：`GET /api/knowledge-bases/{id}/metadata` 新增 `refresh: bool = False` 參數，傳入 `refresh=True` 時主動呼叫 `invalidate_metadata_cache()` 清除該 Collection 快取並重新從 Qdrant 掃描最新檔案名稱與標籤。

### 驗證
- `python -m py_compile backend/routers/knowledge_base.py backend/services/qdrant_service.py` 通過。

---

## 2026-07-23 多應用 RAG 同步服務（IngestService）預設 Parent-Child 大小雙層切分與 PDF/Word 圖片自動擷取描述實作

### 背景
依據 [`MULTI_APP_RAG_SYNC_PLAN.md`](MULTI_APP_RAG_SYNC_PLAN.md) 規劃與需求，外部應用（如 Knowledge Base, BPM, Meeting 等）透過 API 同步文件與附件至 AiRAG 時，切區段預設套用 Parent-Child 大小雙層結構，並自動針對 PDF 及 Word 檔擷取內嵌圖片透過 VLM/LLM 產生說明描述後獨立向量化。

### 變更內容
- `backend/services/ingest_service.py`：
  - 擴充 `_process_upsert()` 邏輯：
    1. **圖片擷取與描述**：當 `doc_type == "attachment_file"` 且副檔名為 `pdf`, `docx`, `dotx` 時，調用 `DocumentParser.extract_images_from_pdf` / `extract_images_from_docx` 提取圖片。
    2. 使用 `caption_semaphore` 非同步控制併發，呼叫 `LLMService.describe_image` 產生圖片描述，並將實體圖檔儲存於 `FILE_ATTACHMENTS_DIR/image`。
    3. **Parent-Child 雙層切分**：對傳入文字內容（支援 Markdown, Word, PDF, 4GL, 4FD）進行 Parent-Child 大小雙層結構切分，計算各 Parent Block 的 Child 索引範圍並設定 `parent_id` 與 `parent_chunk_index_range`。
    4. **組合圖片 Chunk 與寫入 Qdrant**：將圖片描述轉為 `chunk_type="image"` 的 Chunk，附加 `"圖片"` Tag（若 MongoDB 無此 Tag 則自動建置），連同文字片段取得向量後批次寫入 Qdrant。

### 驗證
- 執行 `python -m py_compile backend/services/ingest_service.py` 檢查語法無誤。

---

## 2026-07-17 外部 API 真實使用者身分、問答稽核紀錄、API Key 驗證機制後端實作

### 背景
依據 [`NewFeaturesPlan_ExternalApiTestPlan.md`](NewFeaturesPlan_ExternalApiTestPlan.md) 第 8～12 節實作，取代先前「外部端點暫不驗證」的決策。

### 變更內容
- `backend/models/department.py`：`Department` 新增 `code: Indexed(str, unique=True)`。
- `backend/models/user_profile.py`：`UserProfile` 新增 `department_code: Optional[str]`；新增 `ExternalUserInfo`（`employee_id`/`name`/`department_code`/`department_name`/`job_title_name`/`job_title_level`），定義在此檔以避免 `rag.py`↔`permission_service.py` 之間的循環引用。
- `backend/routers/users.py`：`DepartmentCreateRequest`/`DepartmentResponse` 新增 `code`（必填，重複檢查）；`create_department()` 增加代號空值/重複驗證；`UserResponse` 新增 `department_code`；`create_user()` 新增時以 `Department.find_one(name==dept_name)` 查代號連動帶入，找不到則為 `None`（此時 `PermissionService` 仍可退回名稱比對）。
- `backend/services/permission_service.py`：
  - `filter_results()` 部門比對邏輯改為雙軌相容：`user.department in dept_str_list or (user.department_code and user.department_code in dept_str_list)`，過渡期不需要遷移既有 Qdrant `confidential_departments` 資料。
  - 新增 `get_user_from_external_info(info: ExternalUserInfo) -> UserProfile` classmethod，將外部使用者資訊轉為與模擬使用者相同形狀的物件（不落地寫入 `users` collection）。
- `backend/routers/rag.py`：`ChatParams` 新增 `external_user: Optional[ExternalUserInfo]`；`rag_chat_stream()` 解析身分處新增分支——有 `external_user` 時優先呼叫 `get_user_from_external_info()`，否則才走原本 `simulated_user_id` 查詢路徑，其餘下游過濾/排除摘要邏輯不變。
- `backend/utils/security.py`：新增 `generate_external_api_key()`（`secrets.token_urlsafe(32)` 產生明碼，回傳明碼/前綴/bcrypt hash）與 `verify_external_api_key()`（`X-API-Key` 標頭依賴注入，先以前綴查候選再 bcrypt 核對，通過後更新 `last_used_at`），與既有 `get_current_user` JWT 各自獨立。
- `backend/models/external_api_key.py`（新檔）：`ExternalApiKey` Document（`name`/`key_prefix` unique indexed/`key_hash`/`is_active`/`created_at`/`last_used_at`）。
- `backend/routers/external_api_keys.py`（新檔）：`GET/POST /api/external-api-keys`、`DELETE /api/external-api-keys/{id}`，沿用 `get_current_user` JWT 保護；`POST` 回應內的 `api_key` 明碼僅回傳一次。
- `backend/models/external_chat_log.py`（新檔）：`SourceSummaryItem`（精簡來源中繼資料，不存全文）與 `ExternalChatLog`（稽核紀錄，含呼叫端身分六欄位、問答內容、`custom_system_prompt` 實際使用文字、`api_key_id`）。
- `backend/routers/external.py`：
  - `POST /chat` 新增 `Depends(verify_external_api_key)`，並要求 `request.params.external_user` 必填（缺少回傳 400）。
  - 新增 `_external_chat_with_logging()`：以 `try...finally` 包住 `async for evt in rag_chat_stream(request)` 的轉發迴圈，旁路解析累積回答內容與來源，於 `finally`（涵蓋正常結束、中途斷線、例外）寫入一筆 `ExternalChatLog`；寫入本身另包 `try/except`，失敗僅記警告 log，不影響已送達使用者的串流結果（比照既有 `RetrievalStatsService.record` 的 best-effort 慣例）。
- `backend/models/mongodb.py`：`init_beanie` 註冊 `ExternalApiKey`、`ExternalChatLog`。
- `backend/main.py`：註冊 `external_api_keys.router`。

### 驗證
- `python -m py_compile` 全數通過（`rag.py`/`users.py`/`permission_service.py`/`user_profile.py`/`department.py`/`external_api_key.py`/`external_chat_log.py`/`external.py`/`external_api_keys.py`/`utils/security.py`/`main.py`/`models/mongodb.py`）。
- 以 venv Python 實際 import 全部新增/修改模組並執行端到端 smoke test：確認 `ChatParams.external_user` 欄位存在、`external.py`/`external_api_keys.py` 路由正確註冊、`get_user_from_external_info()` 能正確轉換欄位、`generate_external_api_key()` 產生的金鑰可被 `verify_password()` 正確驗證且錯誤金鑰會被拒絕。

---

## 2026-07-17 外部 API 測試頁面 (External API Test) 後端實作

### 背景
依據 [`NewFeaturesPlan_ExternalApiTestPlan.md`](NewFeaturesPlan_ExternalApiTestPlan.md) 規劃實作。新增獨立於內部測試 API 的外部端點，供公司內網外部應用未來串接，並支援自訂總結提示詞。

### 變更內容
- `backend/routers/external.py`（新檔）：新增 `POST /api/external/chat`，`APIRouter(prefix="/external")` 未掛 `Depends(get_current_user)`（依規劃決策，暫不驗證，僅限公司內網存取把關）。直接 import 並重用 `routers.rag` 現有的 `ChatRequest` schema 與 `rag_chat_stream()` async generator，未複製檢索/摘要/串流管線邏輯。
- `backend/routers/rag.py`：
  - `ChatParams` 新增 `custom_system_prompt: Optional[str] = None`。
  - `rag_chat_stream()` 新增區域變數擷取（去除頭尾空白後為空字串視同未帶）。
  - 三處組裝 `system_prompt` 的分支（`semantic_db_query` 分支／一般 `context_str` 分支／無資料 `else` 分支）皆改為：有帶 `custom_system_prompt` 時完全取代預設的指示規則文字，檢索到的參考資料（或資料庫查詢結果）仍由後端接續附加在後方；`else` 分支（無知識庫／無檢索資料）額外處理為若有帶入則直接等於 `custom_system_prompt`，不再強制接上「知識庫沒有相關資訊」警語，可用於純 Prompt／LLM 行為測試。未帶此欄位時三處皆完全維持原本預設文字，`/api/rag/chat` 行為不受影響。
- `backend/main.py`：`routers` import 新增 `external`，並註冊 `app.include_router(external.router, prefix="/api")`。

### 驗證
- `python -m py_compile routers/rag.py routers/external.py main.py` 通過。
- 以 venv Python 執行 `import routers.external`／`routers.rag`，確認 `'custom_system_prompt' in rag.ChatParams.model_fields` 為 `True`，且 `external.router` 路由為 `POST /external/chat`。

---

## 2026-07-16 手動建立與選擇 Qdrant 知識庫 (Knowledge Base / Collections) 實作

### 背景
依據 [`NewFeaturesPlan_ManualKnowledgeBaseCollectionsPlan.md`](NewFeaturesPlan_ManualKnowledgeBaseCollectionsPlan.md) 規劃修訂後端路由與 Schema。

### 變更內容
- `backend/routers/evaluation.py`：移除 `["tech_specs", "hr_docs"]` 舊相容分支，簡化知識庫解析邏輯為直接依 `PydanticObjectId` 尋找 `KnowledgeBase` 模型（無效或查無時 fallback 第一個知識庫）。
- `backend/routers/feedback.py`：
  - 導入 `KnowledgeBase` 模型。
  - `FeedbackItem` schema 補上 `knowledge_base_id: Optional[str]` 與 `knowledge_base_name: Optional[str]`。
  - `create_feedback()` 新增單筆 KnowledgeBase 名稱查詢並回傳。
  - `list_feedbacks()` 實作批次 KnowledgeBase 查詢（`$in` 條件），並加入 `try: PydanticObjectId(raw_id) except: pass` 過濾，排除髒資料與避免 N+1 查詢崩潰。

---

## 2026-07-16 文件機密權限控管 (Confidential Document Access Control) 實作

### 背景
依據 [`NewFeaturesPlan_ConfidentialAccessControlPlan.md`](NewFeaturesPlan_ConfidentialAccessControlPlan.md) 規劃實作。建立部門與使用者名冊，實作數值與部門雙重過濾之 `PermissionService`，解決檢索點位與附件下載連結可能洩漏機密文件的資安風險。

### 變更內容
- `backend/models/department.py` / `user_profile.py`：建立 `Department` 與 `UserProfile` Beanie Documents，並定義 `JOB_TITLE_LEVELS` 對照表。
- `backend/models/mongodb.py`：在 `init_beanie` 註冊二模型。
- `backend/routers/users.py`：實作 `/api/users/departments` 與 `/api/users` 之 CRUD 端點與 HTTP 400 驗證防護（修正：APIRouter `prefix` 改為 `/users` 避免 404；`get_departments` 的 `response_model` 改為 `List[DepartmentResponse]` 回傳 id 與 name）。
- `backend/services/permission_service.py`：實作核心權限過濾 `filter_results` 與隱私防禦型排除摘要產生器 `build_exclusion_summary`（修正：`confidential_level` 改採 `int(c_level)` 寬容轉型；當帶入已刪除/無效之 `simulated_user_id` 時，`get_user` 改採 Fail-Closed 最嚴防護模式回傳預設 Level 10 客戶身分，避免無效 ID 靜默降級洩漏機密）。
- `backend/services/qdrant_service.py`：`get_unique_metadata` 補齊權限 metadata，實作 `update_permissions_by_filename` 批次寫入（**Critical 修正**：`search_similar()`／`search_similar_two_step()` 鄰居結果／`get_by_parent_id()` 這三處組裝檢索結果 `metadata` dict 的程式碼，原本是逐欄位手動列舉的白名單，未列入 `is_confidential`/`confidential_level`/`confidential_departments`，導致 `PermissionService.filter_results()` 永遠讀不到這三個欄位、對任何人一律判定為非機密放行——等同 `vector`/`hybrid`/`semantic_hybrid` 家族查詢法的機密權限過濾自實作以來從未真正生效。三處皆已補上 `payload.get(...)` 讀取，詳見 [`NewFeaturesPlan_ConfidentialAccessControlPlan.md` 第 15 節](NewFeaturesPlan_ConfidentialAccessControlPlan.md)）。
- `backend/schemas/retrieval.py`：新增 `simulated_user_id`、`is_confidential`、`confidential_level`、`confidential_departments`、`excluded_items` 與 `UpdatePermissionsRequest`。
- `backend/routers/retrieval.py`：`/search` 與 `/semantic-hybrid-search` 整合過濾，新增 POST `/files/update-permissions` 端點。
- `backend/routers/rag.py`：在雙階段附件收集前及單階段搜尋處插入權限過濾，並處理 `permission_blocked_all` Early Exit 事件。

---

## 2026-07-14 AI 總結門檻審查問題修正 (8.2 附件 Early Exit 誤殺 / 8.3 死碼清理 / 8.4 補回無 KB 步驟)

### 背景
依據 [`NewFeaturesPlan_SimilaritySummaryThresholdPlan.md`](NewFeaturesPlan_SimilaritySummaryThresholdPlan.md) 8.2 ~ 8.4 審查項修復。修正附件查詢法在主文 Chunk 低於分數門檻時被 Early Exit 誤殺的問題、清理未使用的死碼 Schema 欄位，並補齊無知識庫情境下遺漏的 step 提示。

### 變更內容
- `backend/routers/rag.py`：
  - **8.2 附件 Early Exit 誤殺修復**：計算 `has_attachments` 狀態，當勾選「AI 讀取附件內容」且含有關聯附件時，Early Exit 不會觸發；Map-Reduce 區塊判斷調整為 `if context_str or has_attachments:`，確保附件文字能正確被 Map-Reduce 合併或摘要後送入 LLM 生成總結。
  - **8.4 無知識庫步驟修復**：於 `request.knowledge_base_id` 不存在的分支補上 `else`，發送 `semantic_analysis` 與 `vector_search` 略過提示事件。
- `backend/schemas/retrieval.py`：
  - **8.3 死碼清理**：從 `SearchParams` 移除未於 `/api/retrieval/search` 說明的 `ai_summary_score_threshold` 欄位。

---

## 2026-07-13 AI 總結相似度門檻與拒絕生成機制實作

### 背景
依據 [`NewFeaturesPlan_SimilaritySummaryThresholdPlan.md`](NewFeaturesPlan_SimilaritySummaryThresholdPlan.md) 規劃實作。提供前端 `ai_summary_score_threshold`（預設 `0.60`）參數，當檢索到的片段相似度低於此分數時排除於 LLM Context 外；當全數片段皆低於門檻時，觸發 Early Exit 硬防護跳過 LLM 總結。

### 變更內容
- `backend/schemas/retrieval.py`：
  - `SearchParams` 新增 `ai_summary_score_threshold: Optional[float] = Field(default=0.60)`。
- `backend/routers/rag.py`：
  - `ChatParams` 新增 `ai_summary_score_threshold: Optional[float] = None`。
  - `rag_chat_stream()` 提取 `ai_summary_score_threshold`（預設 0.60）。
  - 於 `raw_results` Chunks 處理循環中，逐一比較 `semantic_score >= ai_summary_score_threshold`：
    - 符合門檻才放入 `context_parts` 送給 LLM 做總結與回答。
    - 在每個 `sources` 筆數中補上 `semantic_score` 與 `metadata.included_in_ai_context` 狀態。
  - **Early Exit 機制**：若 `context_parts` 為空（全數片段皆低於門檻）：
    - `vector_search` 步驟事件發送 warning 與提示。
    - 以 SSE 直接串流友善提醒訊息及 `sources`，並 `return` 結束流，不調用 vLLM 推論，達成 100% 杜絕幻覺與零算力消耗。

### 驗證
- 執行 `python -m py_compile backend/routers/rag.py backend/schemas/retrieval.py` 通過。

## 2026-07-13 Qdrant 檢索查詢優化（中文 Tokenizer 設定與既有索引自動升級）

### 背景
依優化規劃文件 [QdrantRetrievalOptimizationPlan.md](QdrantRetrievalOptimizationPlan.md) 實作建議優先順序第 3 項目（方向二：優化中文全文檢索分詞 Tokenizer）。原本的 `models.TokenizerType.WORD` 是針對英文空格切分，導致中文查詢時的 Exact Keyword Boost（`models.MatchText`）幾乎無法命中。

### 變更內容
- [qdrant_service.py](file:///d:/%E6%AA%94%E6%A1%88%E5%88%86%E4%BA%AB/%E7%A8%8B%E5%BC%8F%E7%A2%BC/AiRAG/backend/services/qdrant_service.py)：
  - 在 `create_collection()` 方法中，將 `content` Payload 欄位的 Text Index Tokenizer 從 `WORD` 調整為 `MULTILINGUAL`（多語言/中文分詞器）。
  - 新增 `ensure_all_collections_payload_index()` 方法，自動遍歷 Qdrant 中所有 Collection 並升級 `content` 欄位的 Text Index 至 `MULTILINGUAL`。
- [mongodb.py](file:///d:/%E6%AA%94%E6%A1%88%E5%88%86%E4%BA%AB/%E7%A8%8B%E5%BC%8F%E7%A2%BC/AiRAG/backend/models/mongodb.py)：
  - 在後端啟動初始化邏輯 `init_mongodb()` 中呼叫 `QdrantService.ensure_all_collections_payload_index()`，讓現存的舊 Collection 於系統啟動時自動在背景完成中文分詞索引升級重建，無須手動執行重建指令或重灌向量資料。

### 驗證
- 語法編譯檢查（`python -m py_compile backend/services/qdrant_service.py backend/models/mongodb.py`）通過。

## 2026-07-13 Qdrant 檢索查詢優化（併行 Sibling 檢索與元資料分頁滾動）

### 背景
依優化規劃文件 [QdrantRetrievalOptimizationPlan.md](QdrantRetrievalOptimizationPlan.md) 實作建議優先順序第 1 與 2 項目（方向三與方向四）。

### 變更內容
- [qdrant_service.py](file:///d:/%E6%AA%94%E6%A1%88%E5%88%86%E4%BA%AB/%E7%A8%8B%E5%BC%8F%E7%A2%BC/AiRAG/backend/services/qdrant_service.py)：
  - **方向三（併行 Sibling 檢索）**：在 `search_similar()` 與 `search_similar_two_step()` 的 Parent-Child 還原合併階段，將原本依序串行（Sequential）執行的 `await cls.get_siblings_and_merge()` / `await cls.get_image_siblings()` 改為使用 `asyncio.gather()` 非同步併行執行。消除 Head-of-Line Blocking，顯著降低 1st-hop 與 2nd-hop 的 I/O 響應時間。
  - **方向四（元資料分頁滾動）**：在 `get_unique_metadata()` 中將一次性截斷抓取 `limit=10000` 改為基於 Cursor Pagination 的 `while True` 滾動分頁（每頁 1000 筆，迭代至 `next_offset` 為空），解決大規模 Collection（超過 10,000 點位）時元資料選單漏失檔案與標籤的問題。

### 驗證
- 語法編譯檢查（`python -m py_compile backend/services/qdrant_service.py`）通過。
