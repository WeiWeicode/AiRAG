# 大量內嵌圖片 PDF 同步逾時（arq TimeoutError）改善規劃文件

> 狀態：**批次一、批次二均已實作完成 / 待使用者以實際 PDF 驗收**（2026-08-12，變更明細見
> [BackendCorrection.md](BackendCorrection.md) 與 [BugFix.md](BugFix.md)）
> ⚠️ **部署提醒**：arq 在行程啟動時才讀取 `WorkerSettings`，套用後必須 `docker compose restart worker`。
>
> **2026-08-12 後續發現**：本規劃只處理了同一條圖片管線的**時間**瓶頸，實機執行時另外暴露出
> **記憶體**瓶頸（DGX GB10 統一記憶體耗盡導致主機假死），根因與解法皆不同，另立
> [NewFeaturesPlan_ImagePipelineMemoryPlan.md](NewFeaturesPlan_ImagePipelineMemoryPlan.md) 處理。
> 該規劃會把 `IMAGE_CAPTION_CONCURRENCY` 預設由 3 降為 1，圖片描述總時間將拉長約 3 倍——
> 本規劃第 4.2.1 節的「階段預算 + 降級」機制正是承接此副作用的安全網，兩者互補。
> 觸發事件：2026-08-12 `airag-worker` 處理一份含 100+ 張內嵌圖片的 PDF，在 3600.01s 時被 arq 判定 `TimeoutError`，整份文件同步失敗且無任何產出。
> 影響範圍：**中～高** —— 改動 [document_parser.py](../../backend/services/document_parser.py)、[llm_service.py](../../backend/services/llm_service.py)、[ingest_service.py](../../backend/services/ingest_service.py)、[worker.py](../../backend/worker.py)、[config.py](../../backend/config.py)。
> 核心目標：**讓「圖片很多的大文件」從「跑一小時後全滅」變成「一定會完成，部分圖片描述可事後補」**。
>
> **2026-08-12 決策**：已就 7 項開放取捨完成決議（見第 3 節），方案定案為**兩個實作批次**（批次一：數量與成本控制；批次二：預算與可靠性）。原草案中標記為「選配」的內容雜湊去重**改為納入批次一**；原方案 G（進度回報）**決議不做**，理由見第 3.7 節。
>
> **2026-08-12 第二輪覆核**：針對例外處理、介面簽名與邊界條件再次逐條核對程式碼，採納 3 項補正、否決 1 項提議（見第 3.9 節）。其中「`describe_image_with_retry()` 缺少 `timeout` 參數」是原計劃的**實作缺口**——批次二寫了要傳入動態逾時，但該函式簽名根本沒有這個參數。

---

## 1. 問題現象

```
02:39:09: 3600.01s ! d674cfd1e0c04719a526995a391fa371:process_ingest_task failed, TimeoutError:
  File "/app/services/ingest_service.py", line 235, in _process_upsert
    extracted_images = list(await asyncio.gather(*[process_one_image(img) for img in raw_images]))
  File "/app/services/ingest_service.py", line 209, in process_one_image
    async with caption_semaphore:
asyncio.exceptions.CancelledError
```

**traceback 的位置是假象。** arq 在 job_timeout 到期時 cancel 整個 job task，`asyncio.gather` 內所有尚未完成的 coroutine 同時收到 `CancelledError`；停在 [ingest_service.py:209](../../backend/services/ingest_service.py:209) 的 `async with caption_semaphore` 只代表「那幾十張還在排隊等號誌的圖片」被砍掉的位置，**不是 semaphore 有 bug**。真正耗掉一小時的是前面已經跑完的幾十批 vLLM 圖片描述請求。

---

## 2. 根因分析

### 2.1 設定沒有生效：實際 timeout 是 3600，但設定檔寫 7200

| 來源 | 值 |
|:---|:---|
| `backend/.env:64` | `INGEST_JOB_TIMEOUT=7200` |
| [config.py:84](../../backend/config.py:84) 預設 | `7200` |
| **實際 log** | **3600.01s** |

[worker.py:40](../../backend/worker.py:40) 的 `WorkerSettings.job_timeout` 在 arq 行程啟動時讀取一次。docker-compose 雖把 `./backend` 掛進 `/app`（改檔即生效），但**已啟動的 worker 行程不會重讀 `.env`**。

須確認兩件事：
1. 目前的 `airag-worker` 容器是否在 `.env` 改成 7200 **之前**啟動的 → 需 `docker compose restart worker`。
2. 容器環境變數是否另有 `INGEST_JOB_TIMEOUT=3600` 覆蓋（`load_dotenv()` 不會覆寫已存在的 OS 環境變數）。docker-compose.yml 的 `worker.environment` 沒有這一項，但仍應實測確認。

### 2.2 但改成 7200 也不夠：時間預算本來就是負的

以本次檔案（100+ 張圖）代入 [config.py:70-78](../../backend/config.py:70)：

| 參數 | 值 | 推導 |
|:---|:---|:---|
| `IMAGE_CAPTION_CONCURRENCY` | 3 | 100 張 → **34 批** |
| `IMAGE_CAPTION_TIMEOUT` | 180s | 單張單次牆鐘上限 |
| `IMAGE_CAPTION_MAX_ATTEMPTS` | 3 | 退避 5s / 10s |
| **單張最壞成本** | **555s** | 180×3 + 5 + 10 |

| 情境 | 總時間 | 結果 |
|:---|:---|:---|
| 每張 60s、零重試 | 34 × 60 ≈ 2040s | 過 |
| 每張 100s、零重試 | 34 × 100 ≈ 3400s | **卡在 3600 邊緣（=本次現象）** |
| 最壞（全部走滿重試） | 34 × 555 ≈ 18,870s ≈ 5.2 小時 | 7200 也擋不住 |

[config.py:82](../../backend/config.py:82) 的註解自己已經寫出這條最壞估算公式，代表現行參數組合在「圖片數量大」時**數學上就不可能保證完成**。單純調大 `INGEST_JOB_TIMEOUT` 只是把失敗時間往後延，不是解法。

此外，圖片描述**不是**唯一耗時項：切分後的 embedding 走 [get_embeddings_batch()](../../backend/services/embedding_service.py:73)，併發僅 5，數百個 chunk 也需要可觀時間。任何時間預算設計都必須替 embedding 與 Qdrant upsert 保留餘裕。

### 2.3 單張圖片的成本上限失控

[llm_service.py:286](../../backend/services/llm_service.py:286) 圖片描述使用 `max_tokens=20480`，而外層 [describe_image_with_retry](../../backend/services/llm_service.py:350) 用 `asyncio.wait_for(..., 180)` 硬砍。兩者不匹配：

- 一張複雜表格/BOM 圖若真的需要 200s 才生成完 → **永遠不可能成功**，而且每次都是「跑滿 180s 被砍 → 等 5s → 再 180s → 等 10s → 再 180s」＝**單張燒掉 555 秒仍然失敗**。
- 逾時是「這張圖本來就慢」的訊號，原封不動重試兩次幾乎必然再逾時，屬於純浪費。
- 20480 tokens 的描述對檢索也無意義（後續還要被 `DEFAULT_CHUNK_SIZE` 切碎），且過大的上限讓 `_is_repeating_tail` 偵測到重複前能空轉很久。

### 2.4 PDF 圖片完全沒有過濾，數量被無謂放大

[document_parser.py:11-35](../../backend/services/document_parser.py:11) 的 `extract_images_from_pdf()` 對每頁 `page.get_images(full=True)` 的每個 xref 無條件抽出，**沒有任何過濾或去重**：

- 頁首/頁尾 logo、公司圖章、分隔裝飾線、簽名檔 → 每頁各算一張，一份 40 頁的 PDF 光 logo 就貢獻 40 張。
- 跨頁重複引用的**同一個 xref** 會被重複抽出成多筆，內容完全相同卻各送一次 vLLM。
- 對照組：DOCX 路徑反而有做過濾（[document_parser.py:60-76](../../backend/services/document_parser.py:60) 的 `collect_embedded_object_rids()` 會排除 OLE 物件圖示），PDF 路徑沒有對應處理。

**這是投報率最高的一項** —— 「100 多張圖」很可能有一半以上是重複或裝飾圖，砍掉即等於直接砍掉一半以上的處理時間，且不損失任何檢索價值。

### 2.5 全有全無（all-or-nothing），沒有任何 checkpoint

[_process_upsert()](../../backend/services/ingest_service.py:101) 內「圖片描述 → 切分 → embedding → Qdrant upsert」是一整段不可中斷的流程。逾時被砍時：

- 已成功產生的 90 張描述**完全不保存**，重跑要從第 1 張重來。
- 已寫入 `FileAttachments/image/` 的圖檔（[ingest_service.py:223](../../backend/services/ingest_service.py:223)）因為 Qdrant 從未 upsert，成為孤兒檔；每次重跑再產生一批新的 uuid 檔。
- 這份文件在知識庫中**一個 chunk 都沒有**，連純文字部分都檢索不到 —— 明明文字切分只需要幾秒鐘。

### 2.6 逾時後不會回報 failed，來源應用狀態永久卡住

`asyncio.CancelledError` 繼承 `BaseException` 而非 `Exception`，[ingest_service.py:86](../../backend/services/ingest_service.py:86) 的 `except Exception as e` **攔不到**，因此 `IngestReportService.report(status="failed")` 不會送出。KB 端 `rag_sync_status` 會永遠停在 `processing`，既不會告警也不會被重排。

> **更正（相對於先前口頭分析）**：已核對 [arq/worker.py:610-634](../../backend/.venv/Lib/site-packages/arq/worker.py:610)，`asyncio.TimeoutError`（Python 3.11 下等同內建 `TimeoutError`，屬 `Exception`）會落入 line 628 的 `else` 分支 → `finish = True`、`jobs_failed += 1`，**不會**進入 line 625 的重試分支。也就是 `INGEST_JOB_MAX_TRIES=2` 在逾時情境下不生效，arq 不會自動重跑。先前說「會再燒一小時重跑一次」是錯的。實際後果更差：**任務直接死亡，且來源端毫不知情**。

### 2.7 worker 併發未設限，多文件同步時互相拖垮

`caption_semaphore` 是**每個 job 各自建立**的（[ingest_service.py:182](../../backend/services/ingest_service.py:182)），而 [worker.py:33-41](../../backend/worker.py:33) 的 `WorkerSettings` 沒有設定 `max_jobs`（arq 預設 **10**，見 [arq/worker.py:203](../../backend/.venv/Lib/site-packages/arq/worker.py:203)）。

若同時有多份文件在同步，最壞情況 **10 job × 3 併發 = 30 個多模態請求**同時打同一台地端 vLLM → 每張變慢數倍 → 更容易撞上 180s 單張上限 → 觸發重試 → 更多併發 → 惡性循環。單機 vLLM 的吞吐量是固定的，提高併發不會變快，只會讓每個請求都逾時。

---

## 3. 決策紀錄（2026-08-12）

### 3.1 重複圖片處理：同一 xref／同一內容只保留第一次出現，其餘**直接捨棄**

| | |
|:---|:---|
| **決議** | 以 `xref` 為第一層鍵、`sha256(image_bytes)` 為第二層鍵去重；重複者**完全不產生圖片 chunk**，不只是共用描述。 |
| **被否決的替代方案** | 「共用同一份描述，但每頁仍各產生一個 chunk 以保留頁碼」。 |
| **理由** | 跨頁重複出現的圖片本質上是版面元素（logo/浮水印/頁尾圖章）。若每頁各留一個 chunk，同一段描述文字會在知識庫中出現數十次，在向量檢索時**洗版擠掉真正相關的內容**——這正是 [NewFeaturesPlan_QdrantGroupByOptimizationPlan.md](NewFeaturesPlan_QdrantGroupByOptimizationPlan.md) 要解決的多樣性問題，不應在此處自己製造。即使少數情況下是真正的內容圖被重複引用，保留一份仍可被檢索到。 |
| **承擔的風險** | 該圖只會帶第一次出現的頁碼；針對「第 30 頁那張圖」的提問可能引用到第 3 頁的來源。判定為可接受，且會在過濾統計 log 中留痕以便日後調整。 |

### 3.2 內容雜湊去重：從「選配」提升為**批次一必做**

`hashlib.sha256` 對數十至數百張圖僅毫秒級成本，卻能處理「同一張 logo 以不同 xref 重複嵌入」的常見情況（不同工具產生的 PDF 極常見）。成本與收益不對稱，沒有理由延後。

### 3.3 圖片過濾門檻：採 `100×100` 像素 + `8192` bytes，且**必須輸出統計 log**

門檻值先採保守值上線，實測後再依 log 調整。**強制要求**輸出如下格式的統計行，沒有它就無法判斷門檻設得對不對：

```
[DocumentParser] PDF 共抽出 137 張圖片：xref 重複 -58、內容重複 -6、尺寸門檻 -31、大小門檻 -12，實際送描述 30 張
```

### 3.4 單張成本：`max_tokens` 定為 **4096**，逾時類例外**完全不重試**

| | |
|:---|:---|
| **決議** | 新增 `IMAGE_CAPTION_MAX_TOKENS`（預設 4096）取代寫死的 20480；`describe_image_with_retry` 對 `asyncio.TimeoutError` **不重試**（非「重試 1 次」），其餘例外維持 3 次。 |
| **理由** | 180s 逾時代表這張圖的生成量遠超預期，原封不動重試只會再逾時一次，每次都是完整的 180s 純浪費。直接判失敗、交由既有的修復端點事後處理，是成本低得多的路徑。`RuntimeError`（無限思考迴圈）與連線錯誤屬偶發性，重試確實有效，維持不變。 |
| **效益** | 單張最壞成本 **555s → 約 180s**；最壞總時間由 5.2 小時降至約 1.7 小時，再疊加 3.1～3.3 的數量削減即可落入 3600s 內。 |
| **副作用** | `finish_reason=length`（`truncated=True`）的比例會上升。此為既有且已正確處理的機制（[llm_service.py:328-334](../../backend/services/llm_service.py:328)），截斷的描述仍是可用內容、不視為失敗。 |

### 3.5 階段預算：採**比例參數**而非絕對秒數

| | |
|:---|:---|
| **決議** | 新增 `IMAGE_CAPTION_PHASE_BUDGET_RATIO`（預設 **0.6**），實際預算 = `INGEST_JOB_TIMEOUT × ratio`。 |
| **被否決的替代方案** | 草案原本的絕對值 `IMAGE_CAPTION_PHASE_BUDGET=4320`。 |
| **理由** | 兩個絕對值參數必然會不同步——有人調大 `INGEST_JOB_TIMEOUT` 卻忘了同步調整預算，圖片階段就會提早降級；反之則預算超過 job 上限，整個設計失效。用比例可讓兩者永遠自洽。 |
| **為何是 0.6** | 剩下的 40% 要留給切分、embedding（[get_embeddings_batch()](../../backend/services/embedding_service.py:73) 併發僅 5，數百 chunk 需數分鐘）、Qdrant upsert，以及第 3.6 節的回報餘裕。 |

### 3.6 逾時回報：採**內部軟性 deadline**，不攔截 `CancelledError`

| | |
|:---|:---|
| **決議** | 在 `IngestService.process()` 內用 `asyncio.wait_for()` 包住 `_process_upsert()`，預算 = `INGEST_JOB_TIMEOUT - INGEST_SOFT_DEADLINE_MARGIN`（新增參數，預設 **120**）。 |
| **被否決的替代方案** | 直接加 `except asyncio.CancelledError: 回報 failed; raise`。 |
| **理由** | 在已被 cancel 的 task 內再 await（webhook httpx 或 `asyncio.to_thread` 寫 SQL Server）會被二次取消，必須用 `asyncio.shield` 包裹才安全，易寫錯且難測試。改成「我們自己先丟 `TimeoutError`」則落入既有的 `except Exception` 正常路徑，零特殊處理。120s 餘裕足夠回報本身完成（webhook timeout 15s、pyodbc timeout 10s）。 |

### 3.7 方案 G（圖片階段回報 progress）：**決議不做**

原草案的 P2 方案，決議移除，理由：

- 需要跨系統改動——[_report_direct_db()](../../backend/services/ingest_report_service.py:122) 的 `processing` 分支目前只 UPDATE status 不寫 progress，要落實得先確認 KB 端 `rag_sync_status.progress` 欄位存在並補寫入。
- 3.1～3.5 落地後，單份文件的處理時間本身就會大幅縮短且變得可預期，長跑觀測的價值下降。
- 改以**成本為零的替代方案**：在圖片描述迴圈中每完成 10% 輸出一行 `logger.info` 進度。需要觀測時查 worker log 即可，不動任何跨系統契約。

### 3.8 其他確認事項

| 項目 | 決議 |
|:---|:---|
| `INGEST_JOB_TIMEOUT` | 維持 **7200**，不再往上加。批次一落地後應遠低於此值。 |
| `IMAGE_CAPTION_CONCURRENCY` | 維持 **3**。瓶頸是單台 vLLM 吞吐，調高只會讓每張都變慢並觸發逾時。 |
| `IMAGE_CAPTION_TIMEOUT` | 維持 **180**。`max_tokens` 降到 4096 後，180s 相對寬鬆。 |
| `ARQ_MAX_JOBS` | 定為 **2**（非 1）。設 1 會讓一份大圖文件完全阻塞後面所有純文字文件（後者只需數秒）；設 2 可讓小文件穿插消化，最壞 6 併發對 vLLM 仍在合理範圍。 |
| `INGEST_JOB_MAX_TRIES` | 維持 **2**。逾時情境下不生效（見 2.6 節），但對 worker 重啟造成的 `CancelledError` 仍有意義。 |

### 3.9 第二輪覆核補正

#### 3.9.1 採納：PDF 單張圖片獨立 `try/except`（批次一）

現行 [extract_images_from_pdf()](../../backend/services/document_parser.py:11) 只有一層外包 `try/except`。`doc.extract_image(xref)` 對損壞圖層或特殊 inline image 可能拋 `ValueError` / `fitz.FileDataError`。

> **後果修正**：由於 `images = []` 宣告在 `try` 之外、`return images` 在 `except` 之後，**已抽出的圖片不會被拋棄**。真正的後果是：異常之後的所有頁面**完全不再處理**（靜默少圖，現場只看得到一行 error log），且 `doc.close()` 被跳過造成資源未釋放。後果比「全部丟失」輕，但仍應修。

決議：在 `for img_idx, img in enumerate(image_list)` 迴圈內加獨立 `try/except`，單張失敗只記 log 並 `continue`；`doc.close()` 改放 `finally`。

> **`.get()` 預設值方向必須相反**：取寬高改用 `base_image.get("width")`，但**取不到時視為「通過尺寸關卡」**，交由 bytes 關卡判斷 —— 不可如提議所述預設為 `0`，那會讓尺寸未知的圖片被門檻**靜默丟棄**。不確定的東西不該預設刪除。

#### 3.9.2 採納：`describe_image_with_retry()` 新增 `timeout` 參數（介面缺口，批次一）

原計劃 4.2.1 節寫「傳入 `min(IMAGE_CAPTION_TIMEOUT, remaining)`」，但現行簽名為 `(cls, image_bytes, mime_type, context_hint="")`，內部寫死 `settings.IMAGE_CAPTION_TIMEOUT`，**根本無法傳入**。

決議：`describe_image_with_retry()` 增加 `timeout: Optional[float] = None`，為 `None` 時沿用 `settings.IMAGE_CAPTION_TIMEOUT`。

- 排入**批次一**（與 4.1.3 節同檔同函式一併改），批次二才使用，可讓批次二只動 `ingest_service.py` / `worker.py` / `config.py`。
- 預設值 `None` 確保 [ImageCaptionRepairService](../../backend/services/image_caption_repair_service.py:125) 的既有呼叫完全不受影響。
- `describe_image()` 內部的 `chat_completion(timeout=300.0)` **維持不變**，理由見 3.9.4。

#### 3.9.3 採納：剩餘預算最小門檻（批次二）

`remaining` 只剩 2 秒時仍呼叫 LLM，必定在 2 秒內被打斷，白白發起一次無效 HTTP 連線並佔用 `caption_semaphore` 名額。

決議：`remaining < MIN_CAPTION_ATTEMPT_SECONDS`（**10 秒**）時直接降級為 `caption_failed = True`，不發請求。

> **寫成 `ingest_service.py` 的模組常數，不新增 `.env` 參數。** 本次已新增 7 個設定項，這種不需要現場調整的邊界值再外露只會增加維運負擔。

#### 3.9.4 否決：把 `httpx.TimeoutException` 併入「不重試」分流

提議認為 3.4 節只捕捉 `asyncio.TimeoutError` 會漏掉 HTTP 層逾時。經核對**兩個前提都不成立**：

1. **該例外在此路徑不可達。** [llm_service.py:286](../../backend/services/llm_service.py:286) 傳入 `chat_completion(timeout=300.0)`，而 [describe_image_with_retry](../../backend/services/llm_service.py:350) 外層是 `asyncio.wait_for(..., 180)`。180 < 300，`wait_for` 永遠先觸發；批次二改為 `min(180, remaining)` 只會更小，httpx 的 read/connect timeout 更不可能先到。
2. **即使可達，這樣分流是退步。** `httpx.ConnectTimeout` 代表 vLLM 未啟動或網路瞬斷，**正是重試最有效的偶發情境**。將整個 `httpx.TimeoutException`（含 ConnectTimeout）歸入「不重試」，等於把可自癒的錯誤變成永久失敗，與 3.4 節「依例外性質分流」的原則相反。

**但由此衍生一條必須寫入的護欄**：

> ⚠️ **`IMAGE_CAPTION_TIMEOUT` 必須恆小於 `describe_image()` 內 `chat_completion` 的 httpx timeout（現為 300）。** 一旦被調到 ≥ 300，逾時例外的型態會從 `asyncio.TimeoutError` 變成 `httpx.ReadTimeout`，3.4 節的「逾時不重試」分流會**靜默失效**、退回重試 3 次的舊行為。實作 4.1.3 時應在 `config.py` 或該函式加註此約束。

#### 3.9.5 否決：進度 log 計數器的「併發安全」處理

asyncio 為單執行緒事件迴圈，closure 變數的 `completed_count += 1` 不會在 await 點之間被打斷，**不存在競態條件**。以 `nonlocal` 計數器實作即可，屬實作細節，不需寫入計劃。

#### 3.9.6 否決：另立「`config.py` 預設值完備性」條目

第 5 節結尾已載明「`os.getenv` 預設值必須是可直接上線的安全值，讓不補 `.env` 也能正常運作」，重複列出無新增資訊。

---

## 4. 定案設計

### 批次一：數量與成本控制（低風險，效益立即可見）

#### 4.1.1 前置：確認 `INGEST_JOB_TIMEOUT` 生效（無程式碼）

```bash
docker exec airag-worker env | grep -i ingest
```

若顯示 3600 或未設定：

```bash
docker compose restart worker
```

#### 4.1.2 `document_parser.py`：PDF 圖片過濾與去重

於 `extract_images_from_pdf()` 的 `images.append()` 前，依序套用四道關卡（由便宜到昂貴）：

| 順序 | 關卡 | 判定 | 參數 |
|:---|:---|:---|:---|
| 1 | xref 去重 | `xref in seen_xrefs` → 跳過 | 無 |
| 2 | 尺寸門檻 | `base_image["width"] < W or base_image["height"] < H` → 跳過 | `IMAGE_MIN_WIDTH` / `IMAGE_MIN_HEIGHT` |
| 3 | 大小門檻 | `len(image_bytes) < N` → 跳過 | `IMAGE_MIN_BYTES` |
| 4 | 內容去重 | `sha256(image_bytes) in seen_hashes` → 跳過 | 無 |

- 各關卡分別累計計數，最後輸出第 3.3 節格式的統計 log。
- 保留現行的回傳結構（`image_bytes` / `ext` / `page_number` / `image_index`），不改變呼叫端契約。
- **單張獨立 `try/except`（見 3.9.1）**：迴圈內每張圖各自防護，單張失敗只記 log 並 `continue`，不讓損壞圖層中斷其後所有頁面的處理；`doc.close()` 移入 `finally` 確保釋放。
- **尺寸以 `base_image.get("width")` 取值，取不到時視為「通過」尺寸關卡**（見 3.9.1），交由 bytes 關卡判斷，不得預設為 0 而靜默丟棄。
- **不動 DOCX 路徑** —— 它已有自己的 OLE 物件過濾邏輯，本次不觸碰。

#### 4.1.3 `llm_service.py`：單張成本控制與介面調整

1. `describe_image()` 的 `max_tokens=20480` 改為 `settings.IMAGE_CAPTION_MAX_TOKENS`。
2. `describe_image_with_retry()` 的重試迴圈加入例外分流：捕捉到 `asyncio.TimeoutError` 時**立即 raise，不進入下一輪重試**；其餘例外（`RuntimeError` 無限思考迴圈、連線/HTTP 錯誤）維持現行的 3 次重試。
   - **不併入 `httpx.TimeoutException`**，理由見 3.9.4。
   - 需加註 3.9.4 的護欄：`IMAGE_CAPTION_TIMEOUT` 必須恆小於 `describe_image()` 內 `chat_completion` 的 httpx timeout（現為 300），否則此分流靜默失效。
3. **`describe_image_with_retry()` 新增 `timeout: Optional[float] = None` 參數**（見 3.9.2）：為 `None` 時沿用 `settings.IMAGE_CAPTION_TIMEOUT`，供批次二傳入動態剩餘預算。此處僅開放介面，批次一不改變任何呼叫端行為。
4. 兩處的 warning log 需明確區分「逾時放棄」與「重試中」，便於驗收時統計。

### 批次二：預算與可靠性（結構性改善）

#### 4.2.1 `ingest_service.py`：圖片描述階段預算 + 超時降級

**設計目標**：無論圖片多少張、vLLM 多慢，`_process_upsert()` 都必須在預算內走完「切分 → embedding → upsert」，讓文件至少可被檢索到；沒來得及描述的圖片以既有的失敗佔位機制標記，事後補。

**關鍵前提（已具備，不需新建）**：專案已有完整的事後修復管線 ——

- 失敗佔位文字 `[圖片描述產生失敗：...]` 與 `caption_failed=True` payload（[ingest_service.py:220-221](../../backend/services/ingest_service.py:220)、[ingest_service.py:430](../../backend/services/ingest_service.py:430)）。
- [ImageCaptionRepairService.repair()](../../backend/services/image_caption_repair_service.py:70)：以磁碟原圖重新描述並用相同 point id 覆寫。
- 對外端點 [retrieval.py:664](../../backend/routers/retrieval.py:664)。
- 回報欄位 `caption_failed_count` 已一路傳到 KB 端的 `rag_sync_status`（[ingest_report_service.py:113-121](../../backend/services/ingest_report_service.py:113)）。

**「先降級、事後補」的基礎建設已經完成，本方案只是讓 ingest 階段主動使用它。**

實作要點：

1. 進入圖片迴圈前計算 deadline：
   `deadline = loop.time() + settings.INGEST_JOB_TIMEOUT * settings.IMAGE_CAPTION_PHASE_BUDGET_RATIO`
2. `process_one_image()` 取得號誌後、呼叫 LLM 前先檢查剩餘時間：
   - `remaining < MIN_CAPTION_ATTEMPT_SECONDS`（模組常數 **10**，見 3.9.3）→ **完全跳過 LLM 呼叫**，直接走既有的 `caption_failed = True` 佔位路徑。不對必定逾時的請求浪費連線與號誌名額。
   - 否則 → 以 3.9.2 新增的參數傳入 `timeout=min(IMAGE_CAPTION_TIMEOUT, remaining)`，避免最後一張仍能超支 180s。
3. **無論成功或降級，圖檔一律寫入磁碟**。現行 [ingest_service.py:223](../../backend/services/ingest_service.py:223) 的 `open(target_path, "wb")` 已在 `try/except` 之外，行為正確，**改動時務必保持** —— 否則 `ImageCaptionRepairService._resolve_image_path()` 會因 `FileNotFoundError` 而無法修復（[image_caption_repair_service.py:45](../../backend/services/image_caption_repair_service.py:45)）。
4. 預算耗盡時輸出 `logger.warning`，明確寫出「已描述 N 張／降級 M 張／預算 X 秒」，並確保這 M 張都計入既有的 `caption_failed_count` 回報。
5. 依第 3.7 節，於迴圈中每完成 10% 輸出一行 `logger.info` 進度（僅 log，不動回報契約）。

**結果對照**：

| | 現行 | 批次二後 |
|:---|:---|:---|
| 100 張圖、vLLM 很慢 | 1 小時後 `TimeoutError`，**0 個 chunk**，來源端卡 `processing` | 預算內描述完 N 張，其餘標記失敗，**文件完整寫入 Qdrant**，回報 `completed` + `captionFailedCount=M` |
| 事後處置 | 只能整份重跑 | 呼叫既有的「重新產生圖片描述」端點分批補 M 張 |

#### 4.2.2 `ingest_service.py`：內部軟性 deadline

依第 3.6 節，在 `process()` 中以 `asyncio.wait_for()` 包住 `_process_upsert()`。實作批次二的 4.2.1 後此路徑理論上不該被觸發，但它是「預算估算失準時」的最後一道防線，兩者互補而非擇一。

#### 4.2.3 `worker.py`：`max_jobs` 設限

`WorkerSettings` 新增 `max_jobs = settings.ARQ_MAX_JOBS`（預設 2），理由見 2.7 與 3.8 節。

---

## 5. 參數定案表

| 參數 | 現值 | **定案值** | 批次 | 說明 |
|:---|:---|:---|:---|:---|
| `INGEST_JOB_TIMEOUT` | 7200（實際生效 3600） | **7200** | 一 | 確認生效即可，不再往上加 |
| `IMAGE_MIN_WIDTH` | 無 | **100** | 一 | 新增，PDF 圖片尺寸門檻（像素） |
| `IMAGE_MIN_HEIGHT` | 無 | **100** | 一 | 新增 |
| `IMAGE_MIN_BYTES` | 無 | **8192** | 一 | 新增，PDF 圖片大小門檻 |
| `IMAGE_CAPTION_MAX_TOKENS` | 無（寫死 20480） | **4096** | 一 | 新增，取代寫死值 |
| `IMAGE_CAPTION_PHASE_BUDGET_RATIO` | 無 | **0.6** | 二 | 新增，比例而非絕對秒數 |
| `INGEST_SOFT_DEADLINE_MARGIN` | 無 | **120** | 二 | 新增，保留給 failed 回報 |
| `ARQ_MAX_JOBS` | 無（arq 預設 10） | **2** | 二 | 新增 |
| `IMAGE_CAPTION_CONCURRENCY` | 3 | **3（不動）** | — | 受限於單台 vLLM 吞吐 |
| `IMAGE_CAPTION_TIMEOUT` | 180 | **180（不動）** | — | 降 `max_tokens` 後相對寬鬆 |
| `IMAGE_CAPTION_MAX_ATTEMPTS` | 3 | **3（不動）** | — | 逾時類例外改為不適用 |
| `INGEST_JOB_MAX_TRIES` | 2 | **2（不動）** | — | 逾時不生效，但對 worker 重啟有意義 |

> `.env` 為 git-ignored 且無 `.env.example`，新增參數需另行通知部署者補上；[config.py](../../backend/config.py) 的 `os.getenv` 預設值必須是可直接上線的安全值，讓不補 `.env` 也能正常運作。
>
> **不外露為設定項**：`MIN_CAPTION_ATTEMPT_SECONDS = 10`（3.9.3）寫為 `ingest_service.py` 的模組常數。它是不需現場調整的邊界值，外露只會增加維運負擔。
>
> **約束**：`IMAGE_CAPTION_TIMEOUT` 必須恆小於 `describe_image()` 內 `chat_completion` 的 httpx timeout（現為 300），否則 3.4 節的逾時分流會靜默失效（見 3.9.4）。

---

## 6. 驗收方式

沿用專案慣例（由使用者手動測試，AI 不自行開瀏覽器驗證）。**重現素材：本次失敗的同一份 100+ 張圖 PDF。**

### 批次一

1. **過濾生效**：worker log 出現第 3.3 節格式的統計行，「實際送描述張數」顯著低於抽出張數；抽樣確認被濾掉的確實是 logo/裝飾/重複圖。
2. **成本下降**：`Image captioning attempt X/3 failed` 的出現次數大幅下降；`finish_reason=length` 的 warning 可能增加，屬預期。
3. **端到端**：同一份 PDF 能在 3600s 內跑完並回報 `completed`。
3a. **單張防護（選做）**：若手邊有含損壞圖層的 PDF，確認 log 出現單張抽取失敗訊息，但其後頁面的圖片仍被正常抽出（驗證 3.9.1 的 `continue` 行為）。無此素材時可略過，改以 code review 確認迴圈內確有獨立 `try/except`。

### 批次二

4. **降級保證（最關鍵）**：刻意把 `IMAGE_CAPTION_PHASE_BUDGET_RATIO` 調到極小（例如 0.02），任務仍必須回報 **`completed`**，且：
   - Qdrant 內該檔案的**文字 chunks 完整存在**；
   - 未描述的圖片 chunks 帶 `caption_failed=true`；
   - KB 端收到 `captionFailedCount > 0`。
5. **修復管線可用**：對上述結果呼叫「重新產生圖片描述」端點，確認 `caption_failed` 段落能成功補上（即驗證圖檔確實有落地，未因降級而漏寫）。
6. **failed 回報**：暫時把 `INGEST_JOB_TIMEOUT` 調到極小使其必然逾時，確認 KB 端收到 `status=failed` 與明確 `errorMessage`，而非停在 `processing`。
7. **併發設限**：同時觸發 3 份含圖文件，確認 worker log 顯示最多 2 份同時執行。

---

## 7. 明確不做的事

- **不引入分散式任務拆分**（把每張圖拆成獨立 arq job）。會牽動回報彙總、部分失敗語意、Qdrant 寫入時機，複雜度遠超收益；4.2.1 的「預算內降級」已達成同樣的可用性目標。
- **不做斷點續傳／中繼狀態持久化**。需要新的儲存結構與清理機制；既有的 `caption_failed` + 修復端點是更輕量的等價方案。
- **不做跨系統的 progress 回報**（原方案 G），理由見 3.7 節，改以 log 替代。
- **不改用其他多模態模型或外部 API**。屬部署決策，不在本次程式改善範圍。
- **不動 `IMAGE_CAPTION_CONCURRENCY`**。瓶頸在單台 vLLM 吞吐，調高只會讓每張變慢並觸發逾時。
- **不動 DOCX 圖片抽取路徑**。它已有自己的過濾邏輯，本次問題來自 PDF。
- **不清理既有孤兒圖檔**。另開任務處理（`FileAttachments/image/` 中未被任何 Qdrant point 引用的檔案）。

---

## 8. 實作順序與提交粒度

```
批次一（一次 commit）
  前置：docker exec 確認 INGEST_JOB_TIMEOUT → 必要時 restart worker
  ├─ config.py           新增 IMAGE_MIN_WIDTH / HEIGHT / BYTES、IMAGE_CAPTION_MAX_TOKENS
  ├─ document_parser.py  PDF 四道過濾 + 單張 try/except + doc.close() 移入 finally + 統計 log
  └─ llm_service.py      max_tokens 參數化 + 逾時類例外不重試 + 新增 timeout 參數（僅開介面）
      ↓ 以同一份 PDF 驗收第 6 節 1～3 點
批次二（一次 commit）
  ├─ config.py           新增 IMAGE_CAPTION_PHASE_BUDGET_RATIO / INGEST_SOFT_DEADLINE_MARGIN / ARQ_MAX_JOBS
  ├─ ingest_service.py   階段預算降級（含 MIN_CAPTION_ATTEMPT_SECONDS 門檻）+ 內部軟性 deadline
  └─ worker.py           max_jobs
      ↓ 驗收第 6 節 4～7 點
```

批次一屬低風險且效益立即可見，建議先合併驗證後再進行批次二。

實作完成後依 AGENT.md 規範記錄：

- `docs/DevelopmentProcess/BackendCorrection.md` —— 參數新增與服務層改動（批次一、二）。
- `docs/DevelopmentProcess/BugFix.md` —— 逾時未回報 `failed`（2.6 節）與 PDF 圖片無過濾導致同步失敗（2.4 節）兩項缺陷修正。
