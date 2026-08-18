<!-- BUG修正(最新紀錄放最前面) -->

## 2026-08-18 PDF 的圖片描述永遠進不了文字脈絡；非通用格式圖片的 MIME 一律無效

### 背景
兩個缺陷同在 `IngestService._process_upsert` 的圖片處理流程，都只影響 PDF：

**(1) 圖片段落掛在孤兒 `parent_id` 上。**
`process_one_image()` 的 PDF 分支只取得 `page_val`，`parent_id_val` 始終保持 `None`
（`ingest_service.py:297`），最後落到 `img_item.parent_id or f"{filename}_img_fallback_{img_idx}"`。
這個 `parent_id` 底下**只有這張圖自己**，沒有任何文字兄弟。
而 `QdrantService.get_siblings_and_merge()` 是靠「`parent_id` 相同」才撈得到同段落圖片，
因此 PDF 的圖片描述永遠不會隨著文字命中被帶進 LLM 脈絡——只有圖片段落自己被向量命中時才看得到。
Word 走 `header_path` 算 `parent_id`（`ingest_service.py:305`），一直是正常的，只有 PDF 缺這一段。

**(2) 非通用格式圖片的 MIME 是憑空拼出來的。**
`mime_type = f"image/{img_ext}"` 直接把 `fitz.extract_image()` 回傳的 `ext` 拼進 MIME。
PDF 內嵌圖片可能是 `jpx`（JPEG 2000）、`jb2`（JBIG2）等格式，組出 `image/jpx` 這種
多模態模型不接受的型別，描述必定失敗。事後的 `ImageCaptionRepairService` 也是依存檔的副檔名
回推 MIME（`image_caption_repair_service.py:131`），不在寫入階段轉檔就永遠補不回來。

### 變更內容
1. `backend/services/pdf_parent_child_chunker.py`：
   - `_parents_to_children()` 的 child metadata 新增 `end_page`。父段落可能橫跨數頁
     （`PDF_PARENT_MAX_PAGES` 預設 3），只留 `start_page` 的話，落在中間頁的圖片反查不到父段落。
   - `chunk_pdf_text()`（無頁面結構的退化路徑）一併把 `end_page` 釘成 1，與既有的 `page = 1` 一致，
     不讓偽頁碼流進反查表。
   - payload 組裝是白名單取欄位，多這個 metadata key 不會影響寫入 Qdrant 的內容。
2. `backend/services/document_parser.py`：新增 `DocumentParser.normalize_image_format(image_bytes, ext, filename)`：
   副檔名不在 `SUPPORTED_IMAGE_EXTS`（png/jpg/jpeg/gif/webp）時以 Pillow 轉成 PNG，回傳
   `(bytes, ext, mime_type)`。轉檔失敗**只記錄並沿用原始格式**，讓描述階段自己失敗並留下
   `caption_failed`，不為了一張圖中斷整份文件的處理。存檔與送描述用的是同一份 bytes，
   副檔名與實際內容不會對不上。放在 `DocumentParser` 是因為 `(bytes, ext)` 本來就由它產出，
   兩條圖片流程（ingest worker 與 `/api/embedding/upload`）也才共用得到。
3. `backend/services/ingest_service.py`：
   - `process_one_image()` 改由 `DocumentParser.normalize_image_format()` 取得
     `(img_bytes, img_ext, mime_type)`，移除原本手動拼 MIME 的那一行。
   - 圖片 chunk 迴圈前，用已切好的文字 chunks 建 `page_to_parent`（展開 `page`~`end_page` 區間，
     先到先佔），圖片的 `parent_id` 改為
     `img_item.parent_id or page_to_parent.get(img_item.page) or f"{filename}_img_fallback_{idx}"`。
     Word 走第一項不受影響；PDF 走頁碼對應；兩者都取不到才退回舊的孤兒 ID。
4. `backend/routers/embedding.py`：`/api/embedding/upload` 的 `process_one_image()` 有一模一樣的
   MIME 缺陷，同樣改用 `DocumentParser.normalize_image_format()`。

### 驗證
- `chunk_pdf_pages()` 對 4 頁輸入切出 2 個父段落（第 1-3 頁、第 4 頁），
  以 ingest 相同邏輯建出的 `page_to_parent` 為 `{1:A, 2:A, 3:A, 4:B}`
  ——**跨頁父段落中間的第 2、3 頁確實對應得到 A**，這正是本次要修的關鍵。
- `normalize_image_format()`：TIFF → 轉出的 bytes 以 `PNG` 開頭、回報 `png` / `image/png`；
  `png`/`jpg` 直通且 jpg 正確回報 `image/jpeg`；無法解碼的位元組退回原副檔名並記錄錯誤，不拋例外。

### 未一併修改（刻意）
`/api/embedding/chunk` 的 PDF 分支走 `chunk_pdf_text()`，該端點只收得到解析後的純文字、
拿不到頁面結構，所有 chunk 的 `page` 一律是 1（見 2026-08-17 紀錄）。
那裡沒有可靠的頁碼可以拿來做圖文對應，硬做只會把所有圖片都掛到第一個父段落上，
因此該路徑的圖片仍維持 `_img_fallback_`。真實頁碼只有握有原始 bytes 的 ingest 流程才有。

### 注意事項
- **需重跑 ingest 才生效**：既有資料的圖片段落仍掛在 `_img_fallback_` 上。
- 圖片型兄弟節點不受 `PARENT_SIBLING_WINDOW` 限制（見 2026-08-17 紀錄），
  圖片接回文字父段落後，該父段落底下的圖會全數帶入脈絡。以頁為父時單頁圖數有限，
  但重切後仍須實測脈絡長度有沒有被圖片描述灌大。


## 2026-08-17 PDF 走錯切分器，整份文件被歸成單一父段落，每次查詢都把全文丟給 LLM

### 背景
使用者從 Qdrant 後台發現 `BPM-ReLeaseNote-58.pdf` 的 point 帶著
`parent_chunk_index_range: "0~555"`、`total_chunks: 559`——**整份 559 段共用同一個 `parent_id`**。
Parent-Child 還原時會把該 parent 的兄弟節點全部拼回去，等於每命中一段就把整份 PDF 送進 LLM。

根因在 `backend/services/ingest_service.py:408` 的 `else` 分支：除了 `.4fd`/`.4gl` 之外的所有檔案
（含 PDF）都丟給 `chunk_markdown_content()`，而該切分器的父段落**只由 markdown `#` 標題決定**
（`markdown_parent_child_chunker.py:166`）。PDF 經 `fitz.page.get_text()` 出來是純文字、一個 `#` 都沒有，
`MarkdownHeaderTextSplitter` 回傳單一 doc 且 metadata 為空 → `generate_parent_id()` 對全檔算出同一個 ID。

同源缺陷：`document_parser.parse_pdf()` 把所有頁面 `"\n".join()` 成一整串、只回傳 `page_count`，
頁碼在解析階段就被丟掉，payload 的 `page` 永遠是預設值 `1`，來源引用標不到頁。

同日稍早加入的 `PARENT_MERGE_MAX_TOKENS`（見下一則紀錄）只是事後截斷：
562 筆 payload 仍然整批傳回、字串仍然整份合併，九成工作白做，且截斷視窗的語意邊界是斷的。

### 變更內容（第一批：檢索端鄰居視窗，不需重跑 ingest 即可對既有資料生效）
1. `backend/services/qdrant_service.py`：
   - `get_by_parent_id()` 新增 `center_index` / `window` / `image_only` 參數。傳入 `center_index`
     且視窗 > 0 時，在 **Qdrant 查詢階段**就以 `chunk_index` 範圍過濾，不再撈回整個父段落。
   - 圖片型兄弟節點**刻意不受視窗限制**：切分時圖片段落統一附加在文字段落之後
     （`IngestService._process_upsert`），`chunk_index` 天生遠離命中位置，
     套用視窗會讓「同段落圖片」永遠撈不到。過濾條件因此是
     `parent_id = X AND (chunk_index ∈ [lo, hi] OR chunk_type = "image")`（巢狀 Filter）。
   - `get_siblings_and_merge()` 改帶入命中點的 `chunk_index` 作為視窗中心；
     取不到（非整數）時退回舊行為撈取整個父段落。
   - `get_image_siblings()` 改用 `image_only=True` 直接在查詢端過濾，
     不再撈回全部兄弟節點後於記憶體丟棄九成。
2. `backend/config.py`、`.env.example`：新增 `PARENT_SIBLING_WINDOW=8`（單側兄弟節點數，0 = 不限制）。
   以 `DEFAULT_CHUNK_SIZE=512`／`OVERLAP=50` 計，±8 約 7,800 字元，與 `PARENT_MERGE_MAX_TOKENS=6000` 相當。

### 驗證（第一批）
以假 Qdrant client（實作與 Qdrant 相同的 must／巢狀 should 語義）模擬截圖那份 PDF
（559 個文字段落 + 3 個圖片段落共用一個 `parent_id`）：

- 命中第 392 段 → 撈回 **20 筆（17 文字 + 3 圖片），原為 562 筆**；文字 `chunk_index` 為 384~400。
- 命中第 0 段 → `chunk_index` 0~8，視窗下界不會越界。
- 未帶 `center_index`、或 `window=0` → 撈回 562 筆，**舊行為完全保留**。
- `image_only=True` → 只撈回 3 筆圖片。
- 小型父段落（5 個子段落，正常 Word/Markdown 情境）→ 撈回 5 筆，**行為不變**。
- `get_siblings_and_merge()` 端到端 → `parent_range` 由 `0~555` 變成 `384~400`，
  合併後內容由整份全文縮為 186 字元，`image_chunks` 仍為 3 筆。

### 變更內容（第二批：PDF 頁面感知切分 + 父段落 token 上限，需重跑 ingest 才生效）
1. `backend/services/document_parser.py`：新增 `parse_pdf_pages()` 回傳**逐頁**純文字。
   `parse_pdf()` 改為呼叫它再 `"\n".join()`，對外輸出與修改前逐字相同（`attachment.py`
   等既有呼叫端不受影響）。
2. **新檔** `backend/services/pdf_parent_child_chunker.py`：
   - `build_pdf_parents()`：以「頁」為父段落的自然邊界，連續頁面聚合到
     `PARENT_MAX_TOKENS` 或 `PDF_PARENT_MAX_PAGES` 先到者為止；單頁本身就超過預算時
     於行邊界切成多個父段落（同頁多段時 `part_key` 帶序號，避免 `parent_id` 相撞）。
   - `chunk_pdf_pages()`：回傳格式與 `chunk_markdown_content()` 一致（`child_content` + `metadata`），
     呼叫端不必為 PDF 另外分支；metadata 帶真實 `page` 與 `section`（如「第 4-6 頁」）。
   - `chunk_pdf_text()`：只拿得到純文字時的退化入口，仍保證父段落有界，但頁碼一律為 1
     ——寧可誠實標成第 1 頁，也不要編造頁碼。
   - `split_by_token_budget()`：以行為邊界打包，單行就超過預算時才退回 `split_text_by_tokens()` 硬切。
3. `backend/services/ingest_service.py`：PDF 改走 `parse_pdf_pages()` + PDF 專用切分器
   （**不再重複呼叫 `parse_file()`**，否則整份 PDF 會被解析兩次）。其餘副檔名維持原本的 markdown 切分器。
4. `backend/services/markdown_parent_child_chunker.py`（方案 2 的通用安全網）：
   - 新增 `split_oversized_parents()`，父段落超過 `PARENT_MAX_TOKENS` 時於行邊界再切開。
     「整份只有一個 `#` 標題」的 Word/Markdown 文件是同一類問題，不是 PDF 專屬。
   - `generate_parent_id()` 新增 `part_index` 參數；**`part_index=0` 的結果與修改前完全相同**，
     未超過上限的文件其 `parent_id` 不變，既有已建索引資料不受影響
     （`IngestService` 為 docx 圖片算 `parent_id` 的呼叫端也不必改）。
5. `backend/routers/embedding.py`：`/api/embedding/chunk` 新增 `is_pdf` 分支。
   先前 PDF 在 `parent_child` 模式下**落到 4GL 分支**（用 4GL 語法剖析器去剖 PDF 文字），
   改用 `chunk_pdf_text()`。此端點只收得到 `/upload` 解析後的純文字、拿不到頁面結構，
   因此頁碼一律為 1；**真實頁碼只有 ingest 流程（持有原始 bytes）才有**。
6. `backend/config.py`、`.env.example`：新增 `PARENT_MAX_TOKENS=1500`（切分階段的父段落上限，
   與事後截斷的 `PARENT_MERGE_MAX_TOKENS` 分工不同）、`PDF_PARENT_MAX_PAGES=3`。

### 驗證（第二批）
以 PyMuPDF 產生一份 120 頁、仿 BPM ReleaseNote 格式（每頁 18 筆 `V00-…` 條目）的 PDF：

| 項目 | 修改前 | 修改後 |
|:---|---:|---:|
| 父段落數 | **1** | **40** |
| 單一父段落最大 tokens | 46,000+（整份） | **1,152**（上限 1,500） |
| 單一父段落的子段落數 | 362 | 9~10 |
| `page` 相異值 | 1（永遠是預設值） | 40（範圍 1~118） |

其餘案例：

- 單頁 6,000 字的 PDF → 頁內再切成 8 個父段落，最大 1,500 tokens，`parent_id` 無重複。
- `chunk_pdf_text()`（無頁面結構）→ 31 個父段落、每個最多 12 個子段落，`page` 一律 1。
- 只有一個 `#` 標題的長 Markdown → 由 1 個父段落變成 60 個。
- **未超過上限的一般文件 → `parent_id` 與修改前逐字相同**，且
  `generate_parent_id(f, h) == generate_parent_id(f, h, 0)`。
- `parse_pdf()` 輸出與 `"\n".join(parse_pdf_pages())` 完全一致，既有呼叫端行為不變。
- 既有 `backend/tests/test_word_chunker.py` 仍全數通過。

### 變更內容（第三批：字級啟發式標題偵測，需重跑 ingest 才生效）
頁面邊界只是機械的切法，一個章節跨頁就會被切斷。PDF 沒有語意標記，唯一能還原標題階層的
線索是**排版本身**（字級、粗體）——`get_text("text")` 把這些線索全部丟掉了。

1. `backend/services/document_parser.py`：
   - 新增 `parse_pdf_lines()`，以 `page.get_text("dict")` 取出逐頁逐行的
     `{text, size, bold}`（粗體判定為 PyMuPDF span flags 的 bit 4）。
   - 新增 `lines_to_page_texts()`，讓呼叫端能從同一份解析結果還原純文字，
     **不必為了同時取得文字與排版而解析兩次 PDF**。
2. `backend/services/pdf_parent_child_chunker.py`：
   - `detect_body_size()`：以**字元數加權**找出內文字級。用行數加權會被大量短行
     （頁首頁尾、表格欄位）帶偏。
   - `detect_heading_levels()`：字級 ≥ 內文 × `PDF_HEADING_SIZE_RATIO`、
     或「與內文同級但粗體」的短行視為標題；字級由大到小對應 Header 1~6。
   - `build_pdf_parents_by_heading()`：以標題邊界切父段落並維護標題堆疊，
     仍套用 `PARENT_MAX_TOKENS`（只有一層標題的長章節不會因此逃過上限）。
     第一個標題出現前的封面／目次自成一段。
   - `chunk_pdf_lines()`：PDF 切分的主要入口，標題模式優先、失敗才退回頁面模式。
   - 有標題階層時，子段落比照 markdown 切分器加上 `[標題路徑] ` 語意前綴。
   - **三道退回頁面模式的護欄**（刻意不硬湊，寧可用可靠的頁面邊界）：
     偵測到的標題少於 3 個、標題佔全文行數超過 20%（判準失準，例如整份都是大字）、
     或完全沒有字級變化（掃描檔）。
3. `backend/services/ingest_service.py`：PDF 改走 `parse_pdf_lines()` + `chunk_pdf_lines()`。
4. `backend/config.py`、`.env.example`：新增 `PDF_HEADING_DETECTION=true`、`PDF_HEADING_SIZE_RATIO=1.15`。

### 驗證（第三批）
以 PyMuPDF 產生四種不同排版的 PDF：

| 情境 | 偵測結果 | 父段落數 |
|:---|:---|---:|
| 章(16pt粗)/節(12pt粗)/內文(8pt)，6 章 24 節 | `{16.0: Header 1, 12.0: Header 2}` | **30**（= 6 章 + 24 節） |
| 單一字級（仿掃描檔），12 頁 | `{}` → 退回頁面模式 | 4 |
| 整份皆為 14pt 粗體短行（判準失準） | `{}` → 退回頁面模式 | 2 |
| 只有 1 個標題 | `{}` → 退回頁面模式（少於 3 個不採信） | — |

其他檢查：

- 標題模式下 `section` 為完整標題路徑（如
  `1. Chapter 1 Release Notes > 1.1 Bug Fix Web`），子段落帶對應的 `[標題路徑] ` 前綴。
- 父段落最大 211 tokens，`parent_id` 無重複。
- 退回頁面模式時 `section` 為頁碼範圍（`第 1-3 頁`）且**不加**語意前綴。
- `PDF_HEADING_DETECTION=false` → 與第二批的頁面模式結果一致（6 個父段落）。
- 第一批、第二批的測試與 `backend/tests/test_word_chunker.py` 重跑仍全數通過；
  `main.py` 匯入正常。

### 尚未處理
- **既有已建索引的 PDF 需重新 ingest** 才會套用第二、三批的新切分結果；
  在那之前靠第一批的鄰居視窗控制脈絡大小。
- `/api/embedding/chunk` 手動上傳路徑仍拿不到頁面與排版資訊（`/upload` 只回傳純文字），
  因此只有 token 預算切分、頁碼一律為 1。若要讓手動路徑也享有頁碼與標題偵測，
  需要在 `UploadResponse`／`ChunkRequest` 之間傳遞頁面結構，會動到前端契約，本次未做。

## 2026-08-17 分批摘要自己撞上模型上下文上限，導致 RAG 對話一律回「[系統連線錯誤]」

### 背景
外部 KB 前端提問持續失敗，前端只看到「[系統連線錯誤] 無法從 vLLM 服務取得回覆：400 Bad Request」。
使用者回報「明明做了分批摘要功能，似乎沒有發揮作用」。實際 log 顯示摘要**有觸發**，
但每次都以同一個序列失敗：

```text
[ERROR] airag.llm: Prompt 估算約 152085 tokens，已接近或超過 VLLM_MAX_MODEL_LEN=92160，max_tokens 僅能給到 2048
[ERROR] airag.rag_router: Context summarization failed, falling back to original unsummarized context: 400 Bad Request
[ERROR] airag.llm: Prompt 估算約 152205 tokens，已接近或超過 VLLM_MAX_MODEL_LEN=92160，max_tokens 僅能給到 2048
```

四個獨立的問題疊在一起：

1. **Map 批次大小 = 觸發門檻**：`_bin_pack(blocks, threshold_tokens)` 把「整份脈絡多大才啟動摘要」
   直接當成「每批送多少進 LLM」。門檻 50,000 代表第一批就是 50,000 tokens，本身就接近模型上限。
2. **單一區塊永遠不切**：`_bin_pack` 對「第一個區塊」無條件放行（原註解：絕不拆散任何一個區塊）。
   Parent-Child 還原後的父段落是把該 parent 的**所有兄弟節點**拼回去（`get_siblings_and_merge()`），
   `top_k=15` 下單一區塊就可能有數萬 token —— 這種區塊獨佔一批且必定超過上限，摘要這條路徹底走不通。
3. **失敗後 fallback 回原始未摘要脈絡**：摘要之所以失敗正是因為脈絡過長，沿用原文等於保證正式回答再爆一次。
   且 Map 階段任一批失敗就 `raise`，其餘正常批次的成果全部丟棄。
4. **裁切估算低估**：另一筆 400 是 `32,161(input) + 60,000(max_tokens) = 92,161`，只超出 **1 個 token**。
   `_estimate_prompt_tokens()` 對該內容估出 ≤31,136（實際 32,161），低估 1,025 恰好吃光 1,024 的安全邊際。

### 變更內容
1. `backend/utils/token_counter.py`：新增 `split_text_by_tokens()`。只 encode 一次再對 token 序列
   切片 decode（避免對超長文字反覆 encode），並去除切點落在中文字中間產生的 U+FFFD。
2. `backend/services/context_summarizer_service.py`：
   - 新增 `_batch_limit()`：批次大小改用 `CONTEXT_SUMMARIZE_BATCH_TOKENS`（預設 8,000）與觸發門檻脫鉤；
     呼叫端把門檻設得比批次小時以門檻為準。
   - 新增 `_split_oversized_block()`：單一區塊超過批次上限時切分，並為每個子區塊補回
     `【來源文件：… | 段落編號：…】` 標頭，確保引用格式不斷。
   - Map 階段單一批次失敗**不再中止全部**，改為記錄 `result["failed_batches"]` 後續跑；
     只有在所有批次都失敗時才往外拋。
   - 新增 `truncate_blocks_to_budget()`：摘要全失敗時的保底截斷，預算取模型上下文的一半。
   - Map/Reduce 呼叫改帶 `timeout=120.0`（預設 60 秒對「長輸入 + 1500 tokens 輸出」偏緊，
     逾時會被當成該批失敗）。
3. `backend/routers/rag.py`：摘要失敗改用 `truncate_blocks_to_budget()` 的截斷結果，不再沿用原始全文；
   有批次失敗或段落被捨棄時，於 context 前面加上【系統提示】要求模型提醒使用者資料可能不完整。
4. `backend/services/llm_service.py`：
   - 新增 `_count_prompt_tokens_via_vllm()`：優先呼叫 vLLM `/tokenize` 取精確 prompt token 數
     （含 chat template 佔用），失敗／逾時才退回字元估算。**該端點掛在服務根路徑**，
     需從 `VLLM_BASE_URL` 去掉尾端 `/v1`（實測 `/v1/tokenize` 為 404）。
   - 新增 `effective_max_model_len()`：`VLLM_MAX_MODEL_LEN` 設定值優先，未設定時採用 `/tokenize`
     回應中的 `max_model_len`。原本只要部署忘了設這個環境變數，整套裁切保護就會靜默失效。
   - 多模態訊息不送 `/tokenize`（圖片會被展開成大量 patch token），維持只計文字的估算。
5. `backend/services/qdrant_service.py`：新增 `_limit_merged_parent_length()`，於
   `get_siblings_and_merge()` 合併後套用 `PARENT_MERGE_MAX_TOKENS`（預設 6,000）。
   刻意**不做截頭去尾**——命中的子段落可能在文件中段，改以命中內容為中心取窗，找不到時才取開頭。
6. `backend/config.py`、`.env.example`：新增 `CONTEXT_SUMMARIZE_BATCH_TOKENS=8000`、
   `PARENT_MERGE_MAX_TOKENS=6000`、`VLLM_USE_TOKENIZE_ENDPOINT=true`；
   `VLLM_CONTEXT_SAFETY_MARGIN` 預設由 1024 提高為 **4096**（1024 已被實測低估量吃光）。

### 驗證
以模擬 LLM（`chat_completion` 替換為 fake）與實機 vLLM 兩種方式驗證：

- `split_text_by_tokens`：4,992 tokens 切為 5 段（999/999/999/1000/992），無殘留 U+FFFD。
- `_bin_pack`：30,000 tokens 的**單一**區塊 → 4 批（8000/8037/8037/6067），且每個子區塊都保留來源標頭；
  一般區塊（5 × 2,976 tokens）仍照常打包成 3 批，不被切散。
- `truncate_blocks_to_budget`：10 × 20,000 tokens → 截到預算內並回報捨棄的段落數；
  單一 200,000 tokens 區塊也能取出開頭一段而非整個放棄。
- `maybe_summarize`：4 × 9,000 tokens → 8 批 / 2 輪 / 9 次 LLM 呼叫，最終脈絡 < 1,000 tokens；
  第 2 批失敗時 `failed_batches=1` 且其餘批次仍完成；全部失敗才拋出例外。
- `_limit_merged_parent_length`：24,023 tokens 的父段落 → 6,056 tokens，且**命中段落仍在窗內**；
  未超過上限時原樣回傳。
- `/tokenize` 實機：`POST http://10.10.130.45:8080/tokenize` 回 200
  `{"count":18,"max_model_len":92160,...}`；`/v1/tokenize` 為 404（確認路徑正確）。
- 實機端到端：以 72,150 字元中文 prompt + `max_tokens=60000`（即當初 400 的條件）呼叫 vLLM，
  精確計數 42,578 tokens → 自動裁切後**成功取得回覆**，不再 400；
  將 `VLLM_MAX_MODEL_LEN` 設為 0 時，能自 `/tokenize` 自動偵測到 92160 並照常裁切。

### 已知限制與後續建議
- 15 萬 token 的脈絡即使摘要成功，也要跑約 20 次 Map 呼叫（序列執行），延遲會很明顯。
  真正的解法是別讓檢索端產出這麼大的脈絡（本次已加 `PARENT_MERGE_MAX_TOKENS`），
  必要時可再考慮 Map 階段並行化。
- 分批摘要的觸發門檻仍以 tiktoken cl100k 計算，對中文高估、對英數低估；
  裁切則已改用精確 token。兩者單位不同這點未統一，但門檻方向偏保守（提早觸發）不影響正確性。
- `PARENT_MERGE_MAX_TOKENS=6000` 是依現行 chunk 設定推估的值，若日後調整 chunk size 需重新檢視。

---

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

