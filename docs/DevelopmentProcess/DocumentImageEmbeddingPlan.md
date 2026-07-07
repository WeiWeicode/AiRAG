# 文件內嵌圖片語意向量化規劃文件（Document Image Embedding & Indexing）

> 狀態：**已實作，2026-07-07 完成程式碼複查並修正全部發現的問題（9.1-9.11）**。實作與修正異動請對照 `docs/DevelopmentProcess/NewFeatures.md`／`BugFix.md`／`FrontendCorrection.md` 2026-07-07 條目。複查過程與各項問題的修正結果見文末「第 9 節：程式碼複查發現的問題」。本文件規劃「自訂資料向量化 (Embedding & Indexing)」頁面下「資料切分與向量化寫入」（`SingleIndexingTab.vue`）、「自動分批寫入」（`BatchIndexingTab.vue`）兩個既有分頁的新功能：讓上傳的 Word/PDF 檔案中的內嵌圖片，能被轉成文字敘述後一併向量化寫入 Qdrant，並在 RAG 對話的「同段落查看」「附件查詢」與來源引用區塊提供縮圖懸浮預覽與下載。
>
> **關鍵架構決策（已與使用者確認 2026-07-07）**：圖片轉文字敘述呼叫 **vLLM `Qwen3.6-35B-A3B-FP8`**（`LLMService`，非地端 llama.cpp Instruct 模型）。原因：使用者目前把地端 Instruct 模型（`DENSE_VECTOR_INSTRUCT_MODEL`，供語義混合檢索的問題結構化解析與 rerank 使用）換成了 `qwen2.5-coder-7b-instruct-q8_0.gguf`，**沒有視覺（看圖）能力**，因此圖片說明只能交給有多模態能力、且已知會載入視覺權重的 vLLM 主模型處理。
>
> **外部部署前提（本規劃無法從程式碼保證，需使用者自行確認）**：vLLM 服務啟動時需支援 OpenAI 相容的多模態輸入（`messages[].content` 陣列中含 `{"type": "image_url", "image_url": {"url": "data:image/...;base64,..."}}`），也就是啟動參數需正確掛載 `Qwen3.6-35B-A3B-FP8` 對應的視覺 tower/processor（例如 `--limit-mm-per-prompt` 等 vLLM 參數）。若目前部署的 vLLM 服務未開啟視覺功能，此功能會在呼叫階段直接以 4xx/5xx 失敗，需先確認部署面再進行前端串接測試。

## 1. 目標與範圍

新增能力：
1. 使用者在「資料切分與向量化寫入」或「自動分批寫入」上傳 Word（`.docx`/`.doc`/`.dotx`）或 PDF 檔案時，系統自動抽取檔案內嵌的圖片（不含純文字檔 `.txt`/`.md`/`.4gl`/`.4fd`，這些格式不含內嵌二進位圖片，維持現狀不動）。
2. 每張圖片呼叫 vLLM（`Qwen3.6-35B-A3B-FP8`）產生文字敘述（例如：「這是一張系統架構圖，包含 Web 服務、MQTT 代理與 SQL 伺服器...」）。
3. 圖片原始檔落地存放於 `backend/FileAttachments/image/`（重新編碼檔名，做法比照既有 `backend/routers/attachment.py` 的附件存檔慣例）。
4. 圖片敘述文字視為一個新的 **image chunk**，與同一份文件的一般文字 chunk 用同一套 `/api/embedding/vectorize` 流程一起向量化、寫入同一個 Qdrant collection，並盡量掛上跟鄰近文字段落相同的 `parent_id`（Word/Markdown 結構化切分時）或 `page`（PDF），使其能自然融入既有「同段落查看」（`get_siblings_and_merge`）與既有「語義混合兩階段檢索」（`links_to`/`get_unique_metadata`）機制，**不需要新增檢索邏輯分支**。
5. RAG 測試頁的來源引用區塊（`SourceChunks.vue`）與訊息底部，圖片類型的來源提供「滑鼠懸浮顯示圖片縮圖」與「下載原圖」功能。
6. 驗收範例：RAG 對話輸入「架構圖」或「數據圖表」，AI 能透過語義檢索命中該圖片轉出的文字敘述 chunk，直接說明圖片內容並在來源引用中提供縮圖與下載。

**明確不動的部分**（比照既有加法式開發慣例）：
- 既有 `vector`/`hybrid`/`semantic_hybrid`/`semantic_hybrid_feedback`/`semantic_hybrid_attachment`/`semantic_db_query` 查詢法的程式路徑、Prompt **完全不修改**——圖片 chunk 只是多一種 chunk 內容來源，用既有檢索邏輯就能查到。
- `docs/DevelopmentProcess/Seizure/AttachmentSemanticHybridSearchPlan.md` 的「附件 (Attachment)」概念（`backend/FileAttachments/` 根目錄、MongoDB `attachments` collection、`linked_attachments`）**不受影響、不重用**。本功能的「圖片」是文件內嵌圖片，直接向量化進 Qdrant 供語義檢索命中；「附件」則是使用者另外上傳、以檔案關聯方式帶出下載點、不寫入 Qdrant 的獨立機制。兩者都存在 `backend/FileAttachments/` 下，但用不同子目錄區隔（`image/` vs 附件現行的扁平結構），彼此不共用程式碼路徑。
- 現有「資料庫匯入」「地端 AI 語義 JSON」「已向量化資料管理」「關聯附件管理」四個分頁**不修改**（本次僅涉及「資料切分與向量化寫入」「自動分批寫入」兩分頁）。
- 圖片抽取與說明生成維持與現有流程一致的**同步處理**（無 Celery/背景佇列），比照目前上傳/切分/向量化皆為同步阻塞請求的慣例，透過既有分批進度 UI 呈現處理中狀態。

## 2. 名詞定義

| 名詞 | 說明 |
|---|---|
| Image Chunk | **新概念**：文件內嵌圖片經 vLLM 轉換出的文字敘述，包裝成與一般文字 chunk 同構的 chunk 物件（`content` 為敘述文字），額外帶 `chunk_type: "image"` 與 `image_filename`（實體檔名）等 metadata，寫入 Qdrant 的方式與一般文字 chunk 完全相同（同一個 `/api/embedding/vectorize` 呼叫、同一批次）。 |
| 圖片實體檔案 | 從 Word/PDF 抽取出的原始圖片二進位資料，重新編碼檔名後存於 `backend/FileAttachments/image/`，供前端下載/縮圖預覽使用。與 `qdrant_service.py` 的 Qdrant payload 是分離的兩份資料（比照文字 chunk 內容存在 Qdrant、原始上傳檔案不留存的既有模式，只是圖片額外落地存檔以供顯示/下載）。 |

## 3. 資料模型設計

### 3.1 圖片抽取（Word / PDF 解析擴充）

**PDF**（`backend/services/document_parser.py:11-25` `parse_pdf`）：
- PyMuPDF（`fitz`）本身就支援圖片抽取，新增輔助函式 `extract_images_from_pdf(file_bytes) -> List[{image_bytes, ext, page_number, image_index}]`：對每一頁呼叫 `page.get_images(full=True)`，用 `doc.extract_image(xref)` 取出 `{"image": bytes, "ext": "png"/"jpeg"}`。
- 只有 `page_number` 可作為關聯依據（PDF 走標準字元切分，非 parent-child 結構，見第 6 節限制說明）。

**DOCX/DOTX**（`backend/services/word_parent_child_chunker.py:134-157` `parse_docx_to_markdown`，及其呼叫的 `iter_block_items`）：
- python-docx 的內嵌圖片以 `w:drawing` XML 節點存在於 run 中，關聯的圖片二進位資料透過 `document.part.related_parts`（`r:embed` 對應的 relationship id）取得。
- 擴充 `iter_block_items` 走訪邏輯（或新增平行函式 `extract_images_from_docx(docx_bytes) -> List[{image_bytes, ext, paragraph_index, nearest_heading_path}]`）：在既有逐段落走訪迴圈中，偵測該段落的 run 是否含 `w:drawing`（`paragraph._element.findall('.//' + qn('w:blip'))` 取得 `r:embed` id），並記錄「當時最近一次遇到的標題階層路徑」（`get_heading_level` 已有的偵測邏輯可直接沿用），讓圖片能歸屬到跟周圍文字相同的章節（供第 3.4 節掛上相同 `parent_id`）。
- `.doc`（走 `parse_doc_to_markdown` 的 textract/pypandoc/comtypes/binary fallback 鏈）**不處理圖片**——舊版二進位格式沒有可靠的統一抽取方式，且現有轉換鏈本身就是多層 fallback，圖片抽取失敗時直接略過即可（只影響圖片功能，不影響既有文字解析）。

### 3.2 圖片說明生成

`backend/services/llm_service.py` 新增 `LLMService.describe_image(image_bytes: bytes, mime_type: str, context_hint: str = "") -> str`：
- 將圖片 base64 編碼後組成 OpenAI 相容的多模態訊息：
  ```python
  messages = [
      {"role": "system", "content": "你是一個文件圖片內容描述助手。請詳細描述這張圖片的內容、類型（例如：系統架構圖、流程圖、數據圖表、截圖、照片等）與其中可辨識的文字/數值，供後續語意檢索使用。只輸出描述文字，不要有前導詞。"},
      {"role": "user", "content": [
          {"type": "text", "text": f"這張圖片位於文件段落：{context_hint}" if context_hint else "請描述這張圖片。"},
          {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64_str}"}}
      ]}
  ]
  ```
- 呼叫既有 `cls.chat_completion(messages, temperature=0.3, max_tokens=512)`（`llm_service.py:10-69` 本身不限制 `content` 必須是字串，型別提示 `List[Dict[str, str]]` 需放寬為 `List[Dict[str, Any]]` 以容納陣列型 `content`，這是本功能唯一需要修改既有函式簽名型別提示之處，行為不變）。
- 失敗（vLLM 未開視覺功能、逾時等）時記錄 log 並讓該圖片的 image chunk 標記 `caption_failed: true`、內容退回一段固定文字（例如「[圖片描述產生失敗：{filename}]」），該圖片仍會存檔、仍可下載，只是不會被寫入有意義的語意向量內容——不靜默吞掉例外，前端會顯示這張圖片處理失敗的訊息（對應 AGENT.md「fail loudly」原則）。

### 3.3 圖片實體檔案儲存

- `backend/config.py` 新增 `FILE_ATTACHMENTS_IMAGE_SUBDIR: str = os.getenv("FILE_ATTACHMENTS_IMAGE_SUBDIR", "image")`，實際目錄為 `os.path.join(settings.FILE_ATTACHMENTS_DIR, settings.FILE_ATTACHMENTS_IMAGE_SUBDIR)`（即 `backend/FileAttachments/image/`，符合需求指定路徑，並重用既有 `FILE_ATTACHMENTS_DIR` 設定值）。
- 存檔時重新編碼檔名：`stored_filename = f"{uuid4().hex}.{ext}"`，避免檔名衝突與路徑穿越風險（比照 `docs/DevelopmentProcess/Seizure/AttachmentSemanticHybridSearchPlan.md` 3.2 節的既有慣例）。
- 目錄需在啟動或首次使用時 `os.makedirs(..., exist_ok=True)`（比照 `routers/attachment.py:51-52`）。

### 3.4 Chunk / Qdrant Payload 設計

Image chunk 沿用既有 `qdrant_service.py:107-125` 的 payload 結構，`content` 欄位放圖片敘述文字，並在 `metadata`（`vectorize_chunks` 既有的「額外合併」迴圈 `embedding.py:262-265` 本身就會把 `metadata` 裡不在白名單的自訂欄位原樣寫入 payload，**不需要修改 `VectorizeChunkItem`/`vectorize_chunks` 的程式碼**）中新增：

| 欄位 | 說明 |
|---|---|
| `chunk_type` | `"image"`（一般文字 chunk 不帶此欄位或帶 `"text"`，前端用來判斷是否顯示圖片縮圖/下載按鈕） |
| `image_filename` | 存於 `backend/FileAttachments/image/` 的 `stored_filename`，供下載端點查找 |
| `image_original_ref` | 除錯用途，記錄原始檔案內第幾張圖（如 `"page3_img1"` 或 `"docx_img5"`） |
| `parent_id` / `parent_chunk_index_range` | Word/Markdown 檔案：沿用第 3.1 節取得的「最近標題路徑」算出跟周圍文字相同的 `parent_id`（與 `markdown_parent_child_chunker.chunk_markdown_content` 產生的 `parent_id` 算法必須一致，才能被 `get_by_parent_id`/`get_siblings_and_merge` 撈到同一組），使圖片說明真的能被同段落的文字檢索一起帶出 |
| `page` | PDF 檔案：圖片所在頁碼，比照一般 chunk 既有的 `page` 欄位 |

因為 `get_siblings_and_merge`（`qdrant_service.py:1196-1249`）只是把 `content` 文字做 overlap 去重拼接，image chunk 只要 `content`/`parent_id`/`chunk_index` 符合既有慣例，**完全不需要修改這個函式**就能自動把圖片敘述併入同段落合併結果。

## 4. 後端 API 設計

### 4.1 `/api/embedding/upload`（`backend/routers/embedding.py:26-50`）擴充

- `UploadRequest` 維持不變（仍是 `UploadFile`），新增可選 Form 欄位 `extract_images: bool = Form(False)`（預設關閉，避免每次上傳都觸發額外的 vLLM 呼叫拖慢速度與增加成本；使用者需在前端勾選才啟用，見第 5 節）。
- `extract_images=True` 且副檔名為 pdf/docx/doc/dotx 時：呼叫第 3.1 節的抽取函式取得圖片清單 → 對每張圖依序呼叫 `LLMService.describe_image`（同步迴圈，非平行呼叫，避免同時對 vLLM 發送過多請求；比照現有 `EmbeddingService.get_embeddings_batch` 的 `semaphore` 節流精神，但這裡圖片數量通常遠少於文字 chunk 數，簡單序列處理即可）→ 每張圖呼叫第 3.3 節存檔邏輯。
- `UploadResponse`（`schemas/embedding.py:4-9`）新增：
  ```python
  class ExtractedImageItem(BaseModel):
      image_filename: str          # stored_filename
      description: str
      page: Optional[int] = None
      parent_id: Optional[str] = None
      caption_failed: bool = False

  class UploadResponse(BaseModel):
      ...既有欄位...
      images: List[ExtractedImageItem] = Field(default_factory=list)
  ```

### 4.2 `/api/embedding/chunk`（`backend/routers/embedding.py:52-201`）擴充

- `ChunkRequest` 新增可選欄位 `images: List[ExtractedImageItem] = []`（前端把 `/upload` 回傳的 `images` 原樣轉呈給 `/chunk`，因為切分是純文字操作，圖片清單只是「跟著走」，不參與切分演算法本身）。
- 在既有回傳 `all_children`/`items`（一般文字 chunk 清單）之後，追加把每個 `ExtractedImageItem` 轉成一個 `ChunkItem`：
  - `content` = `description`
  - `index` = 接續文字 chunk 之後的流水號
  - `metadata` = `{"chunk_type": "image", "image_filename": ..., "page": ..., "parent_id": ..., "parent_chunk_index_range": str(index), "filename": request.filename}`（Word 檔案的 `parent_id` 若第 3.1 節有成功關聯到章節則帶入，取不到則退回用自己的 `index` 當獨立 `parent_id`，不強行掛靠不相關的段落）
- `ChunkResponse.total_chunks`/`avg_token_count` 一併納入計算（圖片描述文字通常不長，token 數比照一般文字用 `ChunkingService.estimate_tokens` 估算）。

### 4.3 `/api/embedding/vectorize`

不需修改程式碼（見第 3.4 節說明，`metadata` 額外欄位會自動合併進 payload）。前端把 `/chunk` 回傳的完整 chunk 清單（含圖片 chunk）一起送進 `/vectorize`，向量化流程對圖片 chunk 與文字 chunk一視同仁（都是對 `content` 文字呼叫 `EmbeddingService.get_embeddings_batch`）。

### 4.4 新增圖片下載/預覽端點

`backend/routers/embedding.py` 新增（掛在既有 `router`，沿用 router 層級的 `Depends(get_current_user)`）：
```python
@router.get("/images/{stored_filename}")
async def get_image(stored_filename: str):
    """回傳圖片實體檔案，供前端縮圖預覽與下載使用。"""
```
- 使用 `Path(...).resolve()` 並檢查結果仍在 `FILE_ATTACHMENTS_DIR/image` 目錄底下（防止路徑穿越），找不到回 404，成功回傳 `FileResponse(path, media_type=guess_type(...))`。
- 前端不可直接用 `<img src="/api/embedding/images/xxx">`（此端點需要 JWT，瀏覽器原生 `<img>` 不會帶 `Authorization` 標頭），必須比照 `attachmentService.download()`（`frontend/src/services/attachmentService.js:58-68`）的作法，用帶 Authorization 攔截器的 axios 取得 blob 後轉成 `URL.createObjectURL` 給 `<img>`/下載連結使用（見第 5.4 節）。

### 4.5 檢索/RAG 流程

**不需修改** `qdrant_service.py`（`search_similar`/`search_similar_two_step`/`get_unique_metadata`/`get_siblings_and_merge`）與 `routers/rag.py` 既有邏輯——圖片 chunk 就是一筆內容為敘述文字的普通向量點，會自然被既有語義混合檢索找到並塞進 `sources`。唯一新增的是 `backend/routers/rag.py:433-445` 組 `sources` 陣列時，把 `meta.get("chunk_type")`、`meta.get("image_filename")` 一併帶進每筆 `source.metadata`，供前端判斷是否顯示圖片縮圖/下載按鈕（`SourceChunks.vue` 現有的 `source.metadata` 已是白名單挑選欄位的 dict，只需要在這個既有 dict literal 裡加兩個 key）。

## 5. 前端設計

### 5.1 `frontend/src/services/imageService.js`（新增）

```js
export default {
  getImageUrl(filename) { return `/api/embedding/images/${filename}` },
  async fetchImageBlobUrl(filename) {
    const response = await api.get(this.getImageUrl(filename), { responseType: 'blob' })
    return window.URL.createObjectURL(new Blob([response.data]))
  },
  async download(filename, displayName) { /* 比照 attachmentService.download() 的 blob + <a download> 手法 */ }
}
```

### 5.2 `SingleIndexingTab.vue`（資料切分與向量化寫入）

- 上傳區塊新增一個 checkbox「同時擷取圖片並生成描述（呼叫 vLLM，會增加處理時間）」，僅在偵測到副檔名為 pdf/docx/doc/dotx 時顯示；勾選時 `/upload` 呼叫帶上 `extract_images: true`（`FormData.append`）。
- 呼叫 `/upload` 後，若回傳 `images` 非空，於畫面上列出「偵測到 N 張圖片」＋逐張縮圖與描述文字預覽（縮圖用 `imageService.fetchImageBlobUrl` 取得），讓使用者在切分/向量化前就能確認描述是否合理（比照現有純文字內容預覽 `ChunkPreview.vue` 的呈現精神）。
- `/chunk` 呼叫時把 `images` 原樣帶入 `ChunkRequest.images`；`/vectorize` 呼叫時，圖片轉出的 chunk 與一般文字 chunk 合併在同一個 `chunks` 陣列送出（沿用現有一次性送出全部 chunk 的呼叫方式，不需要新的批次呼叫）。

### 5.3 `BatchIndexingTab.vue`（自動分批寫入）

- 「批次寫入設定」卡片新增與 5.2 相同的 checkbox（僅在 `selectedExtension === '.pdf'` 或 `'.docx'` 時顯示）。
- `startBatchProcessing()`（`BatchIndexingTab.vue:225-389`）現有流程 `上傳解析 → 切分 → 刪除舊資料 → 分批向量化` 的第一步 `embeddingService.uploadFile(fileItem.fileObject)`（`:274`）改為視 checkbox 狀態傳遞 `extract_images` 參數；`fileItem.status` 新增中繼狀態 `'captioning'`（對應訊息「正在辨識圖片並生成描述 (X/Y)...」），因為圖片描述生成是這次新增流程中最耗時的步驟，需要讓使用者在批次表格的「訊息與結果」欄位看到進度，比照現有 `parsing`/`chunking`/`deleting`/`vectorizing` 狀態的呈現方式（`:748-778` 的狀態文字/顏色/spinner 對照表新增一筆 `captioning: '辨識圖片中'`）。
- `chunkPayload`（`:283-293`）比照 5.2 節帶入 `images` 欄位；後續分批向量化迴圈（`:334-365`）不需特別處理，因為圖片 chunk 已經和文字 chunk 合併在同一個 `chunks` 陣列，會自然分批送進 `/vectorize`。

### 5.4 RAG 對話來源引用區塊：`SourceChunks.vue` + `MessageBubble.vue`

- `SourceChunks.vue`（`:40-76`）目前每筆 `source` 用 `group`+`group-hover` 的方式在 hover 時彈出文字內容 tooltip（`:61-75`）。新增判斷 `source.metadata?.chunk_type === 'image'` 時：
  - 該筆來源列前綴加一個 🖼 圖示徽章，取代/補充原本的「段落: #N」文字。
  - hover tooltip 內容從純文字改成「圖片縮圖 + 描述文字」：縮圖用 `imageService.fetchImageBlobUrl(source.metadata.image_filename)`，因為是 hover 才觸發、非常駐請求，用 `onMouseenter` 觸發抓取並快取到本地 `ref`（同一個 `image_filename` 只抓取一次，避免重複發請求），避免一次載入畫面上所有圖片來源造成沒必要的網路開銷。
  - tooltip 下方加「下載原圖」按鈕，呼叫 `imageService.download(...)`（同樣是 blob 手法，因為下載端點掛 JWT，不能用原生 `<a href>`）。
- 訊息底部（`MessageBubble.vue`，比照既有 `message.attachments` 區塊 `:188-210` 的畫法）：若本次回答的 `sources` 中含 `chunk_type === 'image'` 的項目，額外渲染一個「相關圖片」區塊，逐張顯示縮圖 + 下載按鈕（與附件下載區塊視覺上並列但邏輯獨立，不合併成同一個陣列，因為圖片來自 Qdrant `sources`、附件來自獨立的 `message.attachments` SSE 欄位，資料來源不同）。

## 6. PDF 與 Word「同段落查看」的差異與因應（設計限制，需知悉）

- Word/Markdown 檔案走 parent-child 結構化切分（`chunk_mode=parent_child`），每個 chunk 都有 `parent_id`，「同段落查看」靠 `get_siblings_and_merge` 用 `parent_id` 撈出同一組兄弟 chunk 合併還原完整段落——圖片只要正確掛上跟周圍文字相同的 `parent_id`（第 3.1、4.2 節），就能自然參與這個既有機制，使用者問「這張架構圖旁邊在說什麼」時，AI 引用的段落內容會自動包含圖片描述。
- PDF 檔案目前預設走**標準字元切分**（無 `parent_id`/parent-child 結構），本來就沒有「同段落查看」的還原機制（這是現狀既有限制，非本次新增問題）。因此 PDF 圖片 chunk 只掛 `page` 欄位，**不會**有「同段落」合併效果，只能靠語義檢索直接命中圖片描述本身。若之後需要 PDF 也支援「同段落查看」，需要先讓 PDF 走 parent-child 切分模式（屬於更大範圍的既有限制改動，不在本次規劃範圍內，先如實記錄此限制）。

## 7. 實作順序

1. 後端：`config.py` 新增 `FILE_ATTACHMENTS_IMAGE_SUBDIR` → `document_parser.py`/`word_parent_child_chunker.py` 新增圖片抽取函式 → `llm_service.py` 新增 `describe_image`。
2. 後端：`schemas/embedding.py` 新增 `ExtractedImageItem`、`UploadResponse.images`、`ChunkRequest.images` → `routers/embedding.py` 的 `/upload` 擴充抽取+存檔+描述邏輯、`/chunk` 擴充圖片轉 `ChunkItem` 邏輯、新增 `/images/{stored_filename}` 端點。
3. 後端：`routers/rag.py` 的 `sources` 組裝加上 `chunk_type`/`image_filename` 欄位。
4. 前端：新增 `imageService.js` → `SingleIndexingTab.vue` 加勾選項與圖片預覽 → `BatchIndexingTab.vue` 加勾選項、`captioning` 狀態與進度文字。
5. 前端：`SourceChunks.vue` 圖片縮圖 hover 預覽/下載 → `MessageBubble.vue` 訊息底部「相關圖片」下載區塊。
6. 文件同步：更新 `docs/03_API_CONTRACT.md`（`/api/embedding/upload`/`/chunk`/新增 `/images/{stored_filename}` 端點、`sources` 新增欄位）、`docs/04_DB_SCHEMA.md`（Qdrant payload 新增 `chunk_type`/`image_filename`/`image_original_ref` 欄位）、`docs/DevelopmentProcess/NewFeatures.md`/`BackendCorrection.md`/`FrontendCorrection.md`。

## 8. 驗證方式

使用者自行手動測試（依專案慣例不需開瀏覽器驗證）。建議驗證步驟：

1. 確認 vLLM 服務已可接受多模態 `image_url` 請求（可先用簡單 curl 測試一張圖片，確認不是純文字部署）。
2. 啟動後端 `uvicorn main:app --reload --port 53020`、前端 `npm run dev`。
3. 「資料切分與向量化寫入」上傳一份含架構圖/圖表的 Word 或 PDF，勾選「同時擷取圖片並生成描述」，確認：
   - `backend/FileAttachments/image/` 出現對應圖片檔。
   - 上傳後畫面列出偵測到的圖片與生成的描述文字，描述內容合理（例如正確辨識出是架構圖並列出圖中主要元件）。
   - 切分結果的 chunk 清單中出現對應的 image chunk，向量化後 `已向量化資料管理` 頁能看到該筆資料。
4. 「自動分批寫入」勾選同一個選項，批次上傳多份含圖片的檔案，確認佇列表格能正確顯示「辨識圖片中」的中繼狀態與進度，且不會因為某張圖片描述失敗而中斷整批處理（失敗只影響單張圖片，不影響檔案其餘文字 chunk 正常寫入）。
5. RAG 測試頁提問「請問架構圖裡有哪些元件」或「這份文件有沒有數據圖表」，確認：
   - AI 能命中圖片描述並在回答中說明圖片內容。
   - 來源引用區塊該筆圖片來源有 🖼 標示，滑鼠懸浮能看到縮圖預覽，點擊下載能正確存下原始圖片檔。
   - 若圖片是 Word 檔案內嵌，確認同段落的文字內容有一併被檢索/摘要引用（驗證 `parent_id` 掛靠正確）。

## 9. 程式碼複查發現的問題（2026-07-07，尚待修正）

比對實際實作（`backend/services/qdrant_service.py`、`backend/services/document_parser.py`、`backend/routers/embedding.py`、前端 `SourceChunks.vue`/`MessageBubble.vue`/`ChunkPreview.vue` 等）與本規劃文件、以及既有 `get_siblings_and_merge` 原始行為，發現以下問題：

### 9.1【高，已修正 2026-07-07】圖片 Chunk 本身被命中時，其內容會被 `parent_id` 合併邏輯用純文字覆蓋，導致 AI 看不到圖片描述

`backend/services/qdrant_service.py` 的 `get_siblings_and_merge()`（約 1216-1288 行）為了不讓圖片描述污染文字段落，把撈到的兄弟節點依 `chunk_type == "image"` 分成 `text_siblings`／`image_siblings`，只用 `text_siblings` 做去重合併，回傳的 `display_content` 完全不含圖片描述文字，圖片部分改包成獨立的 `image_chunks` 清單另外回傳。

問題在於：呼叫端（`search_similar` 約 461-498 行、`search_similar_two_step` 的鄰居合併約 712-745 行）對**每一筆帶 `parent_id` 的檢索結果**（不分該結果本身是文字還是圖片 chunk）都執行同一段邏輯：
```python
if not parent_content:
    parent_content, parent_range, image_chunks = await cls.get_siblings_and_merge(...)
...
if parent_content:
    item["content"] = parent_content   # <-- 直接覆蓋
```
當**圖片 Chunk 自己就是最相關的命中結果**時（例如使用者問「架構圖」，語意檢索命中的正是那張圖的 AI 描述），因為它是 Word 文件內嵌圖片、依規劃設計必然帶有 `parent_id`，這段邏輯會把它自己的 `item["content"]`（也就是圖片描述本身）整個換成「同段落的純文字兄弟合併結果」——而這份純文字合併結果依上面的新邏輯**刻意排除了圖片自己**。也就是說，圖片之所以被命中，是因為它的描述語意符合查詢，但送進 LLM context（`routers/rag.py` 的 `context_parts`／`sources[].content`）與呈現在畫面上的內容，卻變成了旁邊的文字段落，圖片描述反而消失不見。

**影響**：直接打破本功能最核心的驗收情境——使用者問「架構圖」或「數據圖表」時，AI 有極高機率因為看不到圖片描述本身而無法正確說明圖片內容，等於功能名存實亡。純文字 chunk 不受影響（`text_siblings` 包含自己，合併結果仍含自身內容）；PDF 圖片因為沒有 `parent_id` 也不受影響（不會進入這段 if 分支）；只有「Word/DOCX 文件、且圖片被正確掛上 `parent_id`」這個本功能最主要的情境會觸發此 bug。

**建議修正方向**：`item` 若自己就是圖片 chunk（`meta.get("chunk_type") == "image"`），不應該用 `parent_content` 覆蓋 `item["content"]`，只需要補上 `image_chunks`／同段文字（可放進 metadata 供前端顯示同段文意，不動 `content` 本體）；只有「文字 chunk 命中、順便帶出旁邊圖片」的情境才適合用現在的覆蓋寫法。

**修正結果**：`backend/services/qdrant_service.py` 的 `search_similar()`（461-508 行）與 `search_similar_two_step()` 的鄰居合併（712-750 行附近）皆新增 `is_image_chunk = meta.get("chunk_type") == "image"` 判斷；套用合併結果時改為 `if parent_content and not is_image_chunk: item["content"] = parent_content`，圖片 chunk 命中時保留自己原本的描述文字不被覆蓋。文字 chunk 命中的既有行為（用同段文字合併結果取代單一 child 片段）完全不受影響。順便修正圖片 chunk 的 `image_chunks` 清單會把自己也列進去的小瑕疵：新增排除邏輯 `image_chunks = [ic for ic in image_chunks if ic.get("metadata", {}).get("image_filename") != self_image_filename]`，避免圖片在自己的「同段落圖片」清單中出現自己。兩處呼叫端（`search_similar` 核心結果、`search_similar_two_step` 鄰居結果）皆已同步套用相同修正。

### 9.2【高，已修正 2026-07-07】開發紀錄文件與 04_DB_SCHEMA.md 內容與實際程式碼不符

`docs/DevelopmentProcess/NewFeatures.md`（2026-07-07 條目）與 `docs/04_DB_SCHEMA.md` 新增的說明寫著：
- 圖片描述由「地端多模態 AI (MiniCPM-V)」產生；
- 圖片存放於 `EXTRACTED_IMAGES_DIR` 設定、預設路徑 `ExtractedImages/`。

但實際程式碼：
- `backend/services/llm_service.py` 的 `describe_image()` 呼叫的是 `cls.chat_completion(...)`，也就是 `settings.VLLM_BASE_URL`／`settings.VLLM_MODEL`（vLLM 主模型 `Qwen3.6-35B-A3B-FP8`），與地端 llama.cpp Instruct 模型無關，程式碼裡完全沒有 `MiniCPM` 字樣。
- `backend/config.py` 新增的設定是 `FILE_ATTACHMENTS_IMAGE_SUBDIR`（預設 `"image"`），圖片實際存於 `backend/FileAttachments/image/`；全專案 grep 不到 `EXTRACTED_IMAGES_DIR`／`ExtractedImages` 字樣。

**建議修正**：更新 `NewFeatures.md` 該條目與 `04_DB_SCHEMA.md` 的 `image_filename` 欄位說明，改成實際的模型（vLLM `Qwen3.6-35B-A3B-FP8`）與實際目錄設定（`FILE_ATTACHMENTS_DIR` + `FILE_ATTACHMENTS_IMAGE_SUBDIR` → `backend/FileAttachments/image/`），避免之後只看文件的人被誤導（對應 CLAUDE.md「Known doc/code drift」的既有要求）。

**修正結果**：`docs/DevelopmentProcess/NewFeatures.md` 2026-07-07 條目改為正確描述「呼叫 vLLM 主模型 `Qwen3.6-35B-A3B-FP8`」，並補充說明地端 llama.cpp Instruct 模型目前已換成無視覺能力的 `qwen2.5-coder-7b-instruct-q8_0.gguf`、故無法承擔此任務的背景；設定項目說明改為實際的 `FILE_ATTACHMENTS_IMAGE_SUBDIR`（`backend/FileAttachments/image/`）；`extract_images_from_docx` 的說明也改為「透過 `doc.part.related_parts` 取出圖片二進位資料」，不再誤寫成「讀取 ZIP 檔」。`docs/04_DB_SCHEMA.md` 的 `image_filename` 欄位說明同步改為 `backend/FileAttachments/image/` 與對應的 `GET /api/embedding/images/{stored_filename}` 讀取端點。

### 9.3【中，已修正 2026-07-07】對話畫面圖片來源重複顯示兩次

`frontend/src/components/chat/SourceChunks.vue`（新增的「🖼️ 參考圖片引用」區塊）與 `frontend/src/components/chat/MessageBubble.vue`（新增的「相關參考圖片」畫廊）各自獨立算了一份幾乎相同的 `imageSources`（直接圖片來源 + 從文字來源 `metadata.image_chunks` 拉出的巢狀圖片，並依 `image_filename` 去重），但 `MessageBubble.vue` 版面上 `<SourceChunks ... />` 與新的「相關參考圖片」區塊是前後相鄰渲染、並非互斥，導致同一張圖片會在對話訊息中被畫兩次（一次在 Chunk 引用列表的 hover tooltip 內、一次在下方的圖片畫廊格狀顯示）。

**建議修正**：兩者擇一顯示，例如 `SourceChunks.vue` 移除自己的「🖼️ 參考圖片引用」小節、只保留文字 chunk 列表，圖片統一交給 `MessageBubble.vue` 的「相關參考圖片」畫廊呈現；或反過來只保留 `SourceChunks.vue` 內的呈現、拿掉 `MessageBubble.vue` 新增的畫廊區塊。

**修正結果**：採用第一種方案。`frontend/src/components/chat/SourceChunks.vue` 移除了 `imageSources`/`imageUrls`/`loadSourceImages`/`downloadImage` 與整個「🖼️ 參考圖片引用」樣板區塊，只保留 `textSources`（過濾掉 `chunk_type === 'image'`）與既有的文字 Chunk hover tooltip 列表；圖片統一由 `MessageBubble.vue` 既有的「相關參考圖片」畫廊呈現（含縮圖、hover 下載按鈕），不再重複顯示。

**後續更新（2026-07-07，使用者實測回饋）**：使用者實際測試後回饋，`MessageBubble.vue` 的小縮圖網格式畫廊（一次召回 9 張圖片時，每張縮圖只有約 140px 高）圖片太小、看不清楚內容，且多張圖片時排版占用大量對話畫面空間。改採第二種方案：圖片改回在 `SourceChunks.vue` 呈現，但樣式**比照「參考文檔引用」文字 Chunk 的緊湊列表列**（單行：檔名＋段落編號＋Tokens／Similarity 徽章），只在列表右側新增一個下載圖片 icon 按鈕；原本網格縮圖的「太小看不清楚」問題改用 Hover 提示框解決——比照文字 Chunk 的 hover tooltip 機制，滑鼠移到圖片來源列上會彈出放大的圖片預覽（`h-56`，約 224px 高，比原本 112px 網格縮圖大一倍）與完整描述文字。`MessageBubble.vue` 移除整個「相關參考圖片」網格畫廊區塊與相關的 `imageSources`/`imageUrls`/`imageLoadFailed`/`loadMessageImages`/`downloadImage`/`watch`/`computed` 程式碼（改由 `SourceChunks.vue` 內部管理）。已用 `npm run build` 驗證編譯正常。

### 9.4【中，已修正 2026-07-07】DOCX 表格儲存格內的圖片不會被擷取

`backend/services/document_parser.py` 的 `extract_images_from_docx()` 走訪 `iter_block_items(doc)` 時，只在 `isinstance(item, docx.text.paragraph.Paragraph)` 分支中尋找圖片（`w:drawing`/VML `v:imagedata`），沒有像既有 `parse_docx_to_markdown()` 一樣額外處理 `docx.table.Table` 項目。若架構圖/截圖是放在表格儲存格裡（常見的圖文並排排版方式），會被完全跳過、不會出現在 `images` 清單中，且不會有任何錯誤或警告訊息提示使用者。

**建議修正**：在 `extract_images_from_docx()` 補上對 `Table` 項目的走訪（比照 `parse_docx_to_markdown()` 的 `for table in doc.tables` 或走訪 `item.rows[].cells[].paragraphs`），把儲存格內段落一併納入圖片偵測邏輯。

**修正結果**：`extract_images_from_docx()` 重構為共用的 `extract_rids_from_element(element)`／`append_images_for_rids(rids, header_path)` 兩個內部函式，`iter_block_items` 走訪迴圈新增 `elif isinstance(item, docx.table.Table):` 分支，走訪 `for row in item.rows: for cell in row.cells: for para in cell.paragraphs:`，對每個儲存格段落套用相同的圖片偵測邏輯，並沿用當時累積到的標題階層（`current_headers`）供 `parent_id` 關聯。

### 9.5【中，已修正 2026-07-07】啟用「結構化 Prompt 強化」時，圖片描述的懸浮預覽/畫廊會多出樣板文字

`SingleIndexingTab.vue`／`BatchIndexingTab.vue` 的「結構化」選項會把**所有** chunk（含圖片 chunk）的 `content` 包成 `[檔案名稱] ...\n[段落編號] ...\n[分類標籤] ...\n[主要內容]\n{原內容}` 樣板再送去向量化。`get_siblings_and_merge()` 只對 `text_siblings` 呼叫 `clean_and_extract_content()` 去除這層樣板，`image_siblings` 收集進 `image_chunks` 時直接使用原始 `sib.get("content")`，未經清洗。前端 `SourceChunks.vue`/`MessageBubble.vue` 的 `nestedImages` 直接顯示 `img.content`，會連同樣板前綴一起顯示，讓圖片描述的預覽多出一段重複的檔名/段落編號/標籤資訊。

**建議修正**：`get_siblings_and_merge()` 收集 `image_chunks` 時，比照 `text_siblings` 一樣呼叫 `clean_and_extract_content()` 清洗 `content` 欄位。

**修正結果**：`clean_and_extract_content()` 提升為 `QdrantService._strip_structured_content_prefix()` 共用靜態方法（見 9.6 修正說明），`get_siblings_and_merge()` 收集 `image_chunks` 時已改為呼叫 `cls._strip_structured_content_prefix(sib.get("content") or "")`，與 `text_siblings` 使用同一套清洗邏輯，圖片描述預覽不會再夾帶結構化樣板前綴。

### 9.6【低，部分優化 2026-07-07】每筆帶 `parent_id` 的檢索結果都多一次 Qdrant 查詢，即使文件完全沒有圖片

`search_similar`／`search_similar_two_step` 在 `parent_content` 已從 metadata 快取取得的分支（`else` 分支）中，仍會為了取得 `image_chunks` 而**再呼叫一次** `get_siblings_and_merge()`（等於再一次 `get_by_parent_id` 的 Qdrant scroll）。這對每一筆有 `parent_id` 的檢索結果都會發生，即便對應文件根本沒有任何圖片 chunk，屬於不必要的效能開銷；`semantic_hybrid` 兩階段檢索召回筆數較多時，額外的 DB 往返會被放大。

**建議修正**：可以讓 `get_by_parent_id` 一次撈回的 siblings 結果被兩個呼叫共用（例如把「情況 B」也改成呼叫同一個 `get_siblings_and_merge()` 取得 `image_chunks` 而不必重覆 scroll），或改成只在偵測到快取的 `parent_content` 缺少圖片資訊時才查詢。

**修正結果（部分）**：新增 `QdrantService.get_image_siblings(collection_name, parent_id)` 輕量方法，只做 `get_by_parent_id` 掃描 + 篩選圖片型兄弟節點，不執行完整的文字去重合併運算（`merge_two_strings_with_overlap` 等）；`search_similar`／`search_similar_two_step` 的「情況 B」（快取 `parent_content` 分支）改呼叫這個輕量方法取代原本完整的 `get_siblings_and_merge()`，省下不必要的 CPU 運算。**誠實說明未完全解決之處**：Qdrant 的網路往返次數本身沒有減少——「情況 B」分支每筆結果仍然需要 1 次 `get_by_parent_id` scroll 才能知道是否有圖片兄弟節點，這是無法在不改變快取資料結構（例如把「是否有圖片」也一併快取進 `parent_content` 旁邊）的前提下避免的。另外，經查目前程式碼中**沒有任何寫入路徑會設定 `parent_content` 這個 payload 欄位**（`vectorize_chunks` 等既有寫入端都不會寫入它），所以「情況 B」分支在現有資料下實際上是無法被觸發的死路徑，此問題目前對正式環境沒有實質效能影響；若未來真的有寫入端開始填入 `parent_content`，此輕量化仍會生效降低 CPU 成本。

### 9.7【低，已修正 2026-07-07】圖片 `<img>` 的 fallback 網址一定會 401，起不到 fallback 作用

`ChunkPreview.vue`、`SingleIndexingTab.vue`、`SourceChunks.vue`、`MessageBubble.vue`、`VectorManagementTab.vue` 皆寫成：
```html
<img :src="imageUrls[filename] || `/api/embedding/images/${filename}`" ... />
```
但 `backend/routers/embedding.py` 的 `router` 掛了全域 `Depends(get_current_user)`，瀏覽器原生 `<img src>` 不會帶 `Authorization` 標頭，這個 fallback 網址必定回 401，無法真正顯示圖片，只會在 blob 尚未載入完成的瞬間、或 `fetchImageBlobUrl` 失敗時顯示一個必定失敗的圖片（等同破圖圖示），沒有實際的降級效果。

**建議修正**：拿掉這個 fallback，改成明確的載入中/載入失敗佔位圖（例如一個灰底 SVG 圖示），避免顯示一個看似合理實則必定失敗的網址。

**修正結果**：`ChunkPreview.vue`、`SingleIndexingTab.vue`、`MessageBubble.vue`、`VectorManagementTab.vue`（`SourceChunks.vue` 已在 9.3 移除圖片顯示邏輯，不再適用）皆改為三態渲染：新增 `imageLoadFailed` 狀態，`fetchImageBlobUrl()` 失敗時記錄該檔名為載入失敗（不再設定會 401 的 fallback URL）；樣板改成 `v-if="imageUrls[...]"` 顯示圖片、`v-else-if="imageLoadFailed[...]"` 顯示明確的「圖片載入失敗」灰階佔位圖示、否則顯示轉動中的 spinner（表示正在載入 blob）。下載按鈕僅在圖片成功載入時顯示。已用 `npm run build` 驗證所有修改過的 Vue 元件皆可正常編譯。

### 9.8【高，已修正 2026-07-07，使用者實測發現】圖片描述常在複雜表格/BOM 圖片上被硬性截斷，且系統無法察覺截斷已發生

使用者實際上傳含表格/BOM（物料清單）截圖的 Word 文件測試後，在 Qdrant 內檢視寫入的 point payload，發現 `content`（AI 產生的圖片描述）明顯被腰斬：模型原本逐行列舉表格內容（「**第1行 (10)**：...」「**第2行 (20)**：...」「**第3行 (30)**：...」），卻在描述到第 3 行時嘎然而止，沒有收尾句，後面該有的其餘行數與總結說明完全消失。

**根本原因**：`backend/services/llm_service.py:141` 的 `describe_image()` 呼叫 `chat_completion(messages, temperature=0.3, max_tokens=512)`，把 vLLM 產生描述的長度硬性限制在 512 tokens。系統提示詞（`llm_service.py:126-130`）要求「詳細描述」「其中可辨識的文字/數值」，對內容複雜、行數多的表格類截圖（BOM、系統畫面等），模型逐行描述很容易在描述完的一半就把 512 tokens 用完，被 vLLM 依 `max_tokens` 強制中斷。

**且無法自我偵測**：`chat_completion()`（`llm_service.py:56-66`）從回應中只取 `data["choices"][0]["message"]["content"]`，從未讀取 `finish_reason` 欄位；vLLM 在被 `max_tokens` 截斷時會回傳 `finish_reason: "length"`，但這個資訊完全被丟棄。導致 `describe_image()` 呼叫「成功」（不會拋例外），截斷後的半截文字被視為正常描述直接寫入 `ExtractedImageItem.description`／Qdrant `content`，`caption_failed` 仍是 `false`——使用者與系統都不會被告知這筆圖片描述其實不完整，只能像本次一樣事後人工翻 Qdrant payload才能發現。

**影響**：被截斷的描述會直接進入向量化與 RAG context，語意檢索與 AI 回答時只能看到殘缺的表格內容（例如只看到前 3 行 BOM 資料），對「數據圖表」「BOM 表」類文件的問答品質影響很大，且目前的 UI（`caption_failed` 紅色徽章）完全無法呈現這種「有描述但描述不完整」的狀態。

**建議修正方向**：
1. 提高 `describe_image()` 的 `max_tokens`（例如 1500~2000，視 vLLM 部署的 context window 上限調整），讓表格類圖片有足夠空間逐行描述完。
2. `chat_completion()` 增加回傳（或至少讓 `describe_image()` 能取得）`finish_reason`；當 `finish_reason == "length"` 時，把該圖片標記為某種「描述可能不完整」狀態（例如複用/擴充 `caption_failed`，或新增 `caption_truncated` 欄位），讓前端能顯示對應提示，而非誤判為正常完成。
3. 對表格/清單類密集圖片，可考慮讓系統提示詞改成「摘要重點欄位與代表性資料列」而非逐行鉅細靡遺列出，降低長內容被截斷的機率（表格完整原始資料使用者仍可下載原圖查看）。

**修正結果**：
1. `backend/services/llm_service.py` 的 `chat_completion()` 新增可選參數 `return_finish_reason: bool = False`（預設不影響既有 7 處呼叫端 `query_rewrite`/`hyde_generation`/`evaluation.py`/`prompt.py`/`rag.py`/`context_summarizer_service.py` 的既有行為），為 `True` 時額外回傳 `finish_reason`。
2. `describe_image()` 改為呼叫 `chat_completion(messages, temperature=0.3, max_tokens=20480, return_finish_reason=True)`（`max_tokens` 由 512 提高到 20480），並依 `finish_reason == "length"` 判斷是否被截斷，回傳值由原本的 `str` 改為 `tuple[str, bool]`（`description, truncated`），截斷時會記錄 `logger.warning`（不再靜默吞掉這個訊號）。
3. `backend/schemas/embedding.py` 的 `ExtractedImageItem` 新增 `caption_truncated: bool = False` 欄位；`backend/routers/embedding.py` 的 `/upload` 呼叫端同步改用新的 tuple 回傳值並填入該欄位。
4. `frontend/src/components/embedding/SingleIndexingTab.vue` 的已擷取圖片畫廊新增橘色「描述可能被截斷」徽章（`img.caption_truncated`，與既有紅色「描述失敗」徽章互斥顯示），讓使用者在上傳當下就能看到警示，不需要再自行翻 Qdrant payload 才能發現。
5. 未採納建議方向 3（改寫系統提示詞為摘要模式）：優先用提高 `max_tokens` + 截斷偵測解決，避免同時改變既有描述詳細度的行為；若之後仍持續遇到截斷，可再評估調整提示詞。
6. 此修正只涵蓋「資料切分與向量化寫入」（`SingleIndexingTab.vue`）上傳流程的即時預覽提示；「自動分批寫入」（`BatchIndexingTab.vue`）目前設計上沒有逐張圖片的預覽畫廊，`caption_truncated` 欄位雖然一樣會由後端正確產生並存在回傳的 `images` 陣列中，但批次流程不會將其顯示出來，使用者仍需之後自行查看向量化結果才能得知（此為既有批次流程 UI 範圍限制，非本次修正目標，如需要可另外規劃）。

### 9.9【中，已修正 2026-07-07，使用者提出】「資料切分與向量化寫入」上傳時若正在解析圖片，前端沒有對應的等待動畫/提示，容易誤以為沒有執行

**問題描述**：在「自訂資料向量化 → 資料切分與向量化寫入」分頁勾選「上傳時自動擷取文件內嵌圖片並呼叫多模態 AI 自動描述圖片內容」後，上傳流程會在單一 `/api/embedding/upload` 請求內完成「文字解析 + 逐張圖片抽取 + 依序呼叫 vLLM 產生描述 + 落地存檔」，若文件內嵌圖片數量較多、或圖片內容複雜（例如 9.8 提到的 BOM 表格圖），單張圖片的 vLLM 描述生成本身就可能耗時數秒到數十秒，且目前是序列處理（見規劃文件 4.1 節），整體請求時間會被線性放大。

但 `frontend/src/components/embedding/FileUploader.vue`（53-64、107-110 行）目前唯一的處理中提示，只是把 dropzone 的文字從「拖曳文件至此或點擊上傳」換成靜態文字「正在上傳並解析文件...」，並把整個區塊降低透明度（`opacity-50`）——**沒有任何轉動的 spinner／動畫效果**，而且不論是否勾選「擷取圖片」都顯示同一句話，看不出目前卡在「解析文字」還是「正在辨識圖片（可能要等很久）」。使用者反映：因為畫面長時間停在同一句靜態文字沒有任何動態變化，會誤以為前端卡住／沒有真的在執行。

**建議實作方向**：
1. `FileUploader.vue` 的 dropzone 處理中狀態（`isUploading`）比照專案內既有慣例（例如 `BatchIndexingTab.vue` 的 `animate-spin` SVG spinner 寫法）加上一個轉動中的 loading 圖示，讓使用者一眼就能分辨「畫面沒有卡住、正在跑」。
2. 當 `props.extractImages` 為 `true` 時，提示文字改成明確告知「正在解析文件並辨識圖片中，圖片數量較多時可能需要較長時間，請耐心等候...」之類的字樣，與未勾選圖片擷取時的「正在上傳並解析文件...」做區隔，讓使用者對耗時有心理預期。
3. 若要更精確呈現進度（例如「正在辨識第 3/7 張圖片」），需要後端把目前同步阻塞的 `/api/embedding/upload` 改成能回報中間進度的機制（例如 SSE 或輪詢式的 job 狀態端點），這會是較大幅度的改動，超出單純加提示動畫的範圍，可視情況於後續獨立規劃，本次先以「靜態提示文字＋spinner 動畫」處理最直接的「以為沒在執行」問題。
4. 「自動分批寫入」（`BatchIndexingTab.vue`）本身已有 spinner 動畫與逐檔狀態訊息（`parsing`/`chunking`/`deleting`/`vectorizing`），但目前的 `parsing` 訊息只在勾選圖片擷取時整段改成「正在上傳、解析並辨識/描述內嵌圖片...」（見 `BatchIndexingTab.vue` 約 271 行），沒有進一步依圖片數量細分進度，可視需要一併補強，但非本次使用者回報的主要情境（使用者是在「資料切分與向量化寫入」單筆上傳頁面遇到）。

**修正結果**：`frontend/src/components/embedding/FileUploader.vue` 新增 `uploadingText` computed（依 `props.extractImages` 顯示不同文字：勾選圖片擷取時顯示「正在解析文件並辨識圖片中，圖片數量較多或內容複雜時可能需要較長時間，請耐心等候...」，否則維持原本的「正在上傳並解析文件...」），並在 `isUploading` 為 `true` 時，把原本靜態的上傳雲朵圖示換成轉動中的 spinner（比照 `BatchIndexingTab.vue` 既有的 `animate-spin` SVG 寫法），讓使用者能明確看到畫面正在執行中。第 3 點提到的「精確逐張圖片進度」（需要後端改造成可回報中間進度的機制）維持規劃階段，未在本次一併實作，屬於較大範圍的後續項目；第 4 點的批次頁面補強亦維持待辦，非本次使用者回報的情境。已用 `npm run build` 驗證編譯正常。

### 9.10【高，已修正 2026-07-07，修正 9.6 時複查發現】`get_by_parent_id()` 從未把 `chunk_type`／`image_filename` 投影出來，導致圖片／文字兄弟節點分離邏輯實際上完全沒有作用

**問題描述**：`get_siblings_and_merge()`（9.1、9.5 節的核心修正對象）依賴 `sib["metadata"].get("chunk_type") == "image"` 來把撈到的兄弟節點分成 `text_siblings`／`image_siblings` 兩組，藉此避免圖片描述被硬塞進文字合併結果。但這些兄弟節點是透過 `QdrantService.get_by_parent_id()`（`qdrant_service.py` 約 1185-1231 行）撈取的，而這個函式回傳的 `metadata` dict 只投影了 `filename`/`page`/`section`/`chunk_index`/`tags`/`parent_id`/`parent_content`/`parent_chunk_index_range`/`function_name`/`type` 十個欄位，**完全沒有 `chunk_type` 與 `image_filename`**。

這代表 `sib["metadata"].get("chunk_type")` 對每一個兄弟節點（不管它在 Qdrant payload 裡實際是不是圖片）永遠回傳 `None`，於是：
1. `image_siblings = [sib for sib in siblings if sib["metadata"].get("chunk_type") == "image"]` 永遠是空清單——`image_chunks` 永遠回傳 `[]`，代表「同段落圖片」（`metadata.image_chunks`，供前端 `MessageBubble.vue` 巢狀顯示同段圖片）這個子功能實際上從未真正運作過。
2. `text_siblings = [sib for sib in siblings if sib["metadata"].get("chunk_type") != "image"]` 永遠等於全部的 `siblings`（包含真正的圖片兄弟節點）——代表圖片兄弟節點的描述文字仍然會被送進 `clean_and_extract_content`/`merge_two_strings_with_overlap` 跟文字段落一起去重合併，**這正是本功能最初（BugFix.md 2026-07-07 第一筆條目）想要解決的「圖片語意描述被硬塞進檢索文字段落中」問題，但因為這個欄位缺漏，該修正實際上從未生效過**。

也就是說，9.1 的修正（`item` 自己是圖片 chunk 時不覆蓋自己的 `content`）因為讀取的是 `search_similar` 自己組出的、有正確投影 `chunk_type` 的 `meta`，所以仍然有效；但 9.1／9.5 想額外解決的「siblings 分離、不要把圖片文字混進合併結果」這個更根本的機制，因為 `get_by_parent_id()` 缺少欄位投影，實際上完全沒有作用。

**建議修正／修正結果**：`get_by_parent_id()` 的 `metadata` dict 補上 `"chunk_type": payload.get("chunk_type")` 與 `"image_filename": payload.get("image_filename")` 兩個欄位投影，與 `search_similar`／`search_similar_two_step` 自己組 `metadata` 時的欄位集合一致。修正後 `get_siblings_and_merge()`／`get_image_siblings()` 才能真正依 `chunk_type` 正確分離文字與圖片兄弟節點，9.1/9.5/9.6 的修正才具備實際效果。

### 9.11【高，已修正 2026-07-07，使用者實測發現】自架 vLLM 描述複雜圖片時因固定 60 秒逾時而失敗，且錯誤訊息是空字串導致無法診斷

**問題描述**：使用者實測上傳含密集文字/表格截圖的 Word 文件（見附圖：一張 ERP 系統畫面截圖，內含大量小字表格），圖片描述產生失敗，畫面顯示紅色「描述失敗」徽章與內容「[圖片描述產生失敗：圖片測試.docx_img1]」。Docker 後端日誌顯示：
```
[ERROR] airag.llm: Failed to call vLLM chat_completion: 
[ERROR] airag.llm: Failed to generate description for image: 
[ERROR] airag.embedding_router: Image captioning failed for b90dc797f5aa4edfa8cc9ad800e1f7d0.png:
```
三行錯誤訊息冒號後面**完全是空字串**，無法從 log 判斷真正的失敗原因；但同一張圖片使用者確認在 OpenWebUI 是可以正常讀取內容的，代表模型本身具備視覺能力，問題出在這個專案呼叫 vLLM 的方式上。

**根本原因**：`backend/services/llm_service.py` 的 `chat_completion()` 固定用 `httpx.AsyncClient(timeout=60.0)`，所有呼叫端（含 `describe_image()`）共用這個 60 秒上限。9.8 修正時已把 `describe_image()` 的 `max_tokens` 大幅提高（目前為 8192，需求方後續又自行調整過數次），對內容複雜、文字/表格密集的圖片，vLLM 在自架環境（非雲端專用推論服務）上要產生這麼長的描述，生成時間很容易超過 60 秒，導致 httpx 在請求尚未完成時就主動判定逾時中斷連線。而 Python 的逾時類例外（`httpx.ReadTimeout`／`asyncio.TimeoutError` 等）建立時通常不帶訊息文字，`str(e)` 會是空字串，原本的 `logger.error(f"...: {e}")` 因此完全印不出任何有意義的診斷資訊，讓人誤以為是圖片本身有問題（例如「文字太多」），實際上是「還沒生成完就先被本地逾時設定切斷」。

**建議修正／修正結果**：
1. `chat_completion()` 新增可選參數 `timeout: float = 60.0`，改用 `httpx.AsyncClient(timeout=timeout)`；其餘既有呼叫端（`query_rewrite`/`hyde_generation`/`evaluation.py`/`prompt.py`/`rag.py`/`context_summarizer_service.py`）未傳入此參數，行為不變，仍是 60 秒。
2. `describe_image()` 呼叫 `chat_completion(...)` 時改傳入 `timeout=300.0`（5 分鐘），讓內容複雜、`max_tokens` 設得較大的圖片有足夠時間完整生成描述，不會被過早判定逾時。
3. `chat_completion()`、`describe_image()`、`routers/embedding.py` 三處的例外 log 訊息，全部從 `f"...: {e}"` 改成 `f"...: {type(e).__name__}: {e!r}"`——即使例外本身字串化是空字串，也一定會印出例外類別名稱（例如 `ReadTimeout`）與 `repr()`，未來若再發生類似失敗能直接從 log 判斷是逾時、連線失敗還是其他原因，不需要再靠使用者事後回報猜測。
4. 若提高到 300 秒後仍然逾時（例如 vLLM 硬體資源嚴重不足），現象會從「訊息空白」變成 log 明確印出 `ReadTimeout`/`ConnectTimeout` 等字樣，此時才需要考慮進一步降低 `max_tokens`、簡化提示詞或提升 vLLM 部署的運算資源，本次先解決「診斷不出原因」與「常見情境下 60 秒明顯不夠」兩個問題。
