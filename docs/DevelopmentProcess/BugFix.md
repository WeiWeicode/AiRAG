<!-- BUG修正(最新紀錄放最前面) -->

## 2026-08-12 ingest 任務逾時後不回報 failed，來源應用同步狀態永久卡在 processing

### 背景
`airag-worker` 處理含 100+ 張圖片的 PDF 時被 arq 判定 `TimeoutError`，但 KB 端的
`rag_sync_status` 既沒有變成 `failed`，也沒有任何錯誤訊息，永遠停在 `processing`。

原因：arq 逾時是對整個 job task 呼叫 cancel，`IngestService.process()` 內收到的是
`asyncio.CancelledError`。該例外**繼承 `BaseException` 而非 `Exception`**，
`except Exception as e` 攔不到，因此 `IngestReportService.report(status="failed")` 從未被執行。

同時核對 arq 原始碼（`arq/worker.py:610-634`）確認：`asyncio.TimeoutError` 會落入 `else` 分支
`finish=True / jobs_failed+=1`，**不會**進入 line 625 的重試分支。也就是 `INGEST_JOB_MAX_TRIES=2`
在逾時情境下不生效，arq 不會自動重跑——任務直接死亡，且來源端毫不知情。

### 變更內容
- `backend/services/ingest_service.py`（`process()`）：以 `asyncio.wait_for()` 包住
  `_process_upsert()`，逾時上限為 `INGEST_JOB_TIMEOUT - INGEST_SOFT_DEADLINE_MARGIN`（預設 120s 餘裕）。
  比 arq 更早主動放棄，讓逾時以一般 `Exception` 形式落入既有的 `except Exception` 而能正常回報 `failed`，
  並保留餘裕給回報本身完成（webhook timeout 15s / pyodbc timeout 10s）。
- 攔到 `asyncio.TimeoutError` 後改拋帶訊息的 `TimeoutError`：**`asyncio.TimeoutError` 的 `str()`
  是空字串**，直接沿用會讓來源應用收到空的 `errorMessage`，等於知道失敗卻不知道原因。

### 未採用的作法
直接加 `except asyncio.CancelledError: 回報 failed; raise`。在已被 cancel 的 task 內再 await
（webhook httpx 或 `asyncio.to_thread` 寫 SQL Server）會被二次取消，必須用 `asyncio.shield` 包裹才安全，
易寫錯且難測試。改用「我們自己先逾時」則完全走既有正常路徑，零特殊處理。

### 驗證
- 將 `INGEST_JOB_TIMEOUT=121`、`INGEST_SOFT_DEADLINE_MARGIN=120`（軟性上限 1s），
  `_process_upsert` 替換為 hang 30s：
  - 於 **1.01s** 主動放棄（未等到 arq 的 121s）
  - 回報序列 `processing` → `failed`
  - `error_message='處理逾時：超過內部軟性上限 1 秒'`（確認非空字串）

---

## 2026-08-12 PDF 內嵌圖片無任何過濾，重複 logo 與裝飾小圖灌爆圖片描述階段

### 背景
`DocumentParser.extract_images_from_pdf()` 對每頁 `page.get_images(full=True)` 的每個 xref
無條件抽出，**沒有任何過濾或去重**：頁首/頁尾 logo、圖章、分隔裝飾線每頁各算一張，
跨頁重複引用的同一個 xref 也被重複抽出，內容完全相同卻各送一次 vLLM。
一份 40 頁的 PDF 光 logo 就貢獻 40 張，是「100 多張圖」的直接來源。

對照組：DOCX 路徑早在 2026-07-27 就已加入 OLE 物件圖示過濾，PDF 路徑始終沒有對應處理。

此外原本只有一層外包 `try/except`，`doc.extract_image(xref)` 遇到損壞圖層時，
**該頁之後的所有頁面完全不再處理**（靜默少圖，現場只看得到一行 error log），
且 `doc.close()` 被跳過造成資源未釋放。

### 變更內容
- `backend/services/document_parser.py`（`extract_images_from_pdf()`）：
  - 依序套用四道過濾：`xref` 去重 → 尺寸門檻(`IMAGE_MIN_WIDTH/HEIGHT`) →
    大小門檻(`IMAGE_MIN_BYTES`) → `sha256` 內容去重。
  - **重複者直接捨棄**，不採「共用描述但每頁各留 chunk」——後者會讓同一段描述文字在知識庫中
    出現數十次，在向量檢索時洗版擠掉真正相關的內容。
  - 單張圖片獨立 `try/except`，失敗只記 log 並 `continue`；`doc.close()` 移入 `finally`。
  - 取寬高改用 `.get()`，**取不到時視為「通過」尺寸關卡**交由大小門檻判斷，
    不可預設 0 而讓尺寸未知的圖片被靜默丟棄。
  - 輸出過濾統計 info log（調整 `IMAGE_MIN_*` 前務必先看它）。

### 已知取捨
重複圖片只保留第一次出現的頁碼，針對「第 30 頁那張圖」的提問可能引用到第 3 頁的來源。
判定為可接受，過濾統計 log 留有調整依據。

### 驗證
合成 PDF（4 頁：每頁重複同一 logo 40x40、第 1 頁一張 300x300 噪點大圖、第 2 頁重複嵌入同圖、
第 1 頁一張 200x200 純色小圖）：

```
[DocumentParser] PDF 共抽出 7 張圖片：xref 重複 -4、內容重複 -0、尺寸門檻 -1、大小門檻 -1、抽取失敗 -0，實際送描述 1 張
```

僅保留該張有效大圖（270KB），符合預期。

---


## 2026-07-27 Word 內嵌附件（PDF/Excel 等）的檔案圖示被誤判為文件圖片修正

### 背景
KB 全量校驗回報「`電子發票設定.docx` 有 1 個內嵌圖片段落的 AI 描述產生失敗」。檢視原始文件後發現，
該「圖片」其實是 Word 內插入的 **PDF 附件（OLE 內嵌物件）在版面上顯示的檔案圖示**
（一個 PDF 小圖示加檔名文字），並非文件內容圖片。

`DocumentParser.extract_images_from_docx()` 的 `extract_rids_from_element()` 以
`.//v:imagedata` / `.//a:blip` 無條件掃出段落內所有圖片關聯，因此把 `<w:object>` 底下的
圖示也一併抽出送去多模態模型描述。這類圖示沒有可描述的內容，必然得到無意義描述或直接失敗，
既浪費 vLLM 資源，也在向量庫留下無檢索價值的段落。

Word 插入檔案附件時的實際結構：

```xml
<w:object w:dxaOrig="1531" w:dyaOrig="994">
  <v:shape id="_x0000_i1025" type="#_x0000_t75">
    <v:imagedata r:id="rId10" o:title=""/>   <!-- ← 這是檔案圖示 -->
  </v:shape>
  <o:OLEObject Type="Embed" ProgID="AcroExch.Document.DC" DrawAspect="Icon" r:id="rId99"/>
</w:object>
```

### 變更內容
- `backend/services/document_parser.py`：`extract_images_from_docx()` 內新增
  `collect_embedded_object_rids()`，先掃出所有 `<w:object>` 底下的 `v:imagedata` / `a:blip` 關聯 ID，
  `extract_rids_from_element()` 再據此排除。不限定附件類型，PDF / Excel / 簡報等各種內嵌檔案的
  圖示一律略過；有略過時輸出 info log。
- 只排除 `<w:object>` 內的圖片，一般的 `<w:drawing>`（現代格式）與 `<w:pict>`（舊版 VML 圖片）
  不受影響。

### 驗證
- 以程式建構含內嵌 OLE 物件的測試 docx（一張真正的內容圖片 + 一個模擬 PDF 附件的
  `<w:object>` 圖示，ProgID `AcroExch.Document.DC`）：
  - 抽取到的圖片數 = 1（預期 1）
  - 包含真正內容圖片 = True ✅
  - 包含附件圖示 = False ✅
- 回歸驗證 `ERP Tiptop災難實境演練.docx`：仍為 **19** 張，與修正前一致，未誤刪正常圖片。

### 後續處理
- 已寫入向量庫的失敗段落不會自動消失，需重新觸發一次該附件的同步；
  或在 AiRAG「向量資料管理」頁直接刪除該圖片段落。

---

## 2026-07-27 vLLM 400（max_tokens 超出上下文）與外部對話稽核紀錄驗證失敗修正

### 背景
外部 API 對話出現兩個互不相關的錯誤：

```text
[ERROR] airag.rag_router: Failed to stream from vLLM: Client error '400 Bad Request' ...
[WARNING] airag.external_router: [ExternalChatLog] 稽核紀錄寫入失敗: 1 validation error for SourceSummaryItem
chunk_index
  Input should be a valid integer, unable to parse string as an integer [input_value='0~2']
```

**問題 1（稽核紀錄）**：啟用 Parent-Child 合併時，`qdrant_service.py` 會刻意把
`item["metadata"]["chunk_index"]` 覆寫為父區塊範圍字串（例如 `"0~2"`），但
`SourceSummaryItem.chunk_index` 宣告為 `Optional[int]`，導致每次命中合併後的父區塊，
稽核紀錄就寫入失敗（有 try/except 保護，不影響對話本身）。

**問題 2（vLLM 400）**：原本的錯誤處理拿不到 vLLM 回應內容——串流模式下 `raise_for_status()`
只會產生「Client error '400 Bad Request'」，body 從未被讀取，現場無從判斷原因。補上 body
記錄後取得真正原因：

```text
This model's maximum context length is 92160 tokens. However, you requested 60000 output
tokens and your prompt contains at least 32161 input tokens, for a total of at least 92161 tokens.
```

超出上限僅 1 個 token。prompt 只有 32k，遠低於分批摘要門檻（50000），摘要未觸發是正確的；
真正原因是呼叫端帶入的 `max_tokens=60000`（來源為 KB 前端
`frontend/src/services/AiRAGApi.js` 的 `params.max_tokens || 60000`）。

### 變更內容
1. `backend/models/external_chat_log.py`：`SourceSummaryItem.chunk_index` 由 `Optional[int]`
   改為 `Optional[Any]`，與 `schemas/retrieval.py` 的 `RetrievalMetadata.chunk_index` 型別一致
   （該處早已因相同原因使用 `Any`）。
2. `backend/services/llm_service.py`：
   - `chat_completion()` 串流與非串流路徑在 `status_code >= 400` 時先讀取並記錄回應 body，
     連同 `model` / `max_tokens` / `messages_chars` 一起寫入 log。
   - 新增 `_clamp_max_tokens()`：送出前依 `VLLM_MAX_MODEL_LEN` 自動裁切 `max_tokens`，
     避免任何呼叫端帶入過大的值造成 400。多模態訊息只計文字部分（base64 圖片不納入估算）。
   - 新增 `_estimate_prompt_tokens()`：**刻意不使用 `utils.token_counter.count_tokens`
     （tiktoken cl100k_base）**。實測同一段 75,778 字元中文脈絡，vLLM 回報實際 32,161 tokens，
     cl100k 卻估成 124,002（高估 3.85 倍），會把 `max_tokens` 裁到 256 造成答案被截斷。
     改以字元類型估算：CJK 1 token/字（Qwen 實測約 0.42，保留約 2.4 倍餘裕）、其餘 0.3 token/字，
     方向上刻意保守（高估只會縮短輸出上限，低估會直接 400）。
   - 上下文額度不足時保留 `_MIN_OUTPUT_TOKENS = 2048` 的最小輸出額度，而非壓成 0/負數。
3. `backend/routers/rag.py`：`Failed to stream from vLLM` 的 log 補上例外類別名稱與 `repr`。
4. `backend/config.py`、`.env.example`、`.env`：新增 `VLLM_MAX_MODEL_LEN`（程式預設 0 = 停用裁切，
   本部署 `.env` 依 vLLM 回報值設為 **92160**）與 `VLLM_CONTEXT_SAFETY_MARGIN`（預設 1024）。

### 驗證
- `SourceSummaryItem` 以 `'0~2'` / `5` / `None` 三種輸入實測皆通過。
- `_clamp_max_tokens()` 以本次 400 的實際數值回歸驗證：
  - 75,779 字元中文 prompt + `max_tokens=60000` → 裁切為 **15,348**；
    以 vLLM 回報的實際 32,161 input tokens 計算，總量 47,509 < 92,160 ✅
    （輸出額度 15,348 tokens 對一般問答仍充足）
  - 短 prompt 的 `max_tokens` 1024 / 60000 皆不被裁切（不影響既有行為）
  - 多模態訊息（含 200KB base64 圖片）`max_tokens=20480` 不被裁切，確認 base64 未納入估算
- `main.py` import 成功。

### 已知限制與後續建議
- `_estimate_prompt_tokens()` 是以單一實測資料點（75,778 字元 ↔ 32,161 tokens）校準的啟發式估算，
  非精確計算。若日後更換模型（tokenizer 不同）需重新檢視比例，或改為呼叫 vLLM 的 `/tokenize` 取得精確值。
- KB 前端 `AiRAGApi.js` 的 `max_tokens || 60000` 未更動：有了後端裁切後已不會造成 400，
  但該預設值本身偏大，建議日後調整為 8192 之類的合理值。
- `DEFAULT_CONTEXT_SUMMARIZE_THRESHOLD_TOKENS`（預設 50000）是以 tiktoken 為單位計算的，
  同樣存在中文高估問題，實際觸發時機會比預期早，本次未更動。

---

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

