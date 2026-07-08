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

## 10. 圖片描述並行處理最佳化（已實作 2026-07-07）

> 狀態：**已實作 2026-07-07**。使用者觀察到目前一份文件內有多張圖片時，是「上傳一張、等 AI（vLLM）產生完整描述、再處理下一張」的序列式處理（9.11 的 log 也印證：三次 `POST /v1/chat/completions` 請求間隔約 35～40 秒，代表確實是逐張依序發送，而非同時發送），要求改成「一次送 3 張給 AI 平行處理」以縮短整份文件的圖片辨識總耗時。實作內容請對照 `docs/DevelopmentProcess/NewFeatures.md` 2026-07-07 條目。

### 10.1 現況

`backend/routers/embedding.py` 的 `/upload` 端點（約 59-114 行）用一個同步 `for raw_img in raw_images:` 迴圈依序處理每張圖片：組出 `context_hint`／`parent_id_val` → `await LLMService.describe_image(...)` → 寫入磁碟 → 組成 `ExtractedImageItem` 加進 `extracted_images` 清單。因為是 `for` 迴圈內逐一 `await`，第 2 張圖片的請求要等第 1 張完全處理完（含 vLLM 生成、寫檔）才會送出，N 張圖片的總耗時 ≈ N × 單張耗時。

### 10.2 設計方向

比照專案內已有的批次併發慣例——`backend/services/embedding_service.py` 的 `get_embeddings_batch()`／`get_semantic_embeddings_batch()`（73-102 行）：用 `asyncio.Semaphore(N)` 限制同時併發數量、包成一個內部 async 函式、最後用 `asyncio.gather(*tasks)` 一次送出並收集結果，本次沿用同一套寫法，只是併發數量依需求設為 3（而非既有的 5，因為影像多模態請求的算力/顯存成本比純文字 embedding 高很多，先用使用者要求的 3 張作為預設）。

具體改法：
1. 把迴圈內「組 context_hint/parent_id → 呼叫 describe_image → 寫檔 → 組 ExtractedImageItem」整段邏輯抽成一個內部 async 函式 `process_one_image(raw_img) -> ExtractedImageItem`，函式內部維持現有的 per-image `try/except`（不讓單張圖片失敗中斷整批，仍會標記 `caption_failed`），且維持「不論描述成功或失敗，圖片實體檔案都照樣落地存檔」的既有行為不變。
2. 建立 `semaphore = asyncio.Semaphore(settings.IMAGE_CAPTION_CONCURRENCY)`（新設定項，預設 `3`，見 10.3），每個 `process_one_image` 內用 `async with semaphore:` 包住「呼叫 vLLM」這段最耗時的部分（檔案讀取/寫入這種本地 I/O 不需要被信號量卡住，只需要限制同時打給 vLLM 的請求數）。
3. 用 `extracted_images = await asyncio.gather(*[process_one_image(img) for img in raw_images], return_exceptions=False)` 一次送出所有圖片的任務；因為每個 `process_one_image` 內部已經自行 `try/except` 並保證一定回傳 `ExtractedImageItem`（不會讓例外往外拋），`asyncio.gather` 不需要額外設 `return_exceptions=True` 就能安全收集全部結果，且**保證回傳順序與輸入的 `raw_images` 順序一致**（`asyncio.gather` 的既有保證），不影響後續 `/chunk` 端點依序給 `image_index`／`parent_chunk_index_range` 的邏輯。

### 10.3 新增設定項

`backend/config.py` 新增：
```python
# 圖片描述並行處理的併發數量上限（同時最多幾張圖片一起送給 vLLM 做多模態描述）
IMAGE_CAPTION_CONCURRENCY: int = int(os.getenv("IMAGE_CAPTION_CONCURRENCY", "3"))
```
做成可設定值（而非寫死 3），方便之後依 vLLM 實際承載能力調整，不需要改程式碼重新部署。

### 10.4 預期效益與風險（誠實評估，避免過度承諾）

- **樂觀情境**：vLLM 本身支援 continuous batching（多個請求可以在 GPU 上一起排程執行，非單純排隊），此時 3 張圖片同時送達，vLLM 內部能一定程度平行運算，總耗時可能明顯小於「3 張耗時總和」，效果接近使用者期待的「3 倍加速」。
- **保守情境**：若目前 vLLM 部署的瓶頸主要是單一 GPU 的運算資源已經被單一請求佔滿（例如 9.11 log 顯示的每張圖約 35-40 秒很大一部分是模型生成大量 token 的時間），那麼同時送 3 個請求，vLLM 端可能還是得排隊依序處理，此時併發送出本身不會讓總運算時間縮短，但至少不會比現在更慢——差別只在於「由這個專案的程式碼排隊」改成「由 vLLM 自己排隊」，網路請求的排程開銷會降低，且如果 vLLM 確實有任何併發處理能力，都能自動受益，不需要之後再改程式碼。
- **需要使用者評估的風險**：3 個並發的多模態請求，每個 base64 圖片本體 + 8192 max_tokens 的生成空間，會同時佔用 vLLM 的顯存/運算資源，如果目前的 vLLM 部署顯存或 `--max-num-seqs`／`--gpu-memory-utilization` 等啟動參數是抓得很緊繃的，同時 3 個請求有機會造成顯存不足（OOM）或請求被 vLLM 自己的排隊機制拒絕，需要使用者依實際部署資源決定 `IMAGE_CAPTION_CONCURRENCY` 設多少合適（有問題的話可以直接調低這個設定值，不需要改動程式碼）。

### 10.5 影響範圍

- 只影響 `backend/routers/embedding.py` 的 `/upload` 端點與新增的 `backend/config.py` 設定項，`/chunk`／`/vectorize` 與前端完全不需要改動——因為並行化只是讓同一個 `/upload` HTTP 請求內部處理圖片的方式改變，對外的 request/response 格式（`UploadResponse.images` 陣列的內容與順序）完全不變。
- 「資料切分與向量化寫入」與「自動分批寫入」兩個分頁都會自動受益（兩者都是呼叫同一個 `/api/embedding/upload` 端點），不需要個別調整前端。
- 9.9 已經處理的「上傳中 spinner + 提示文字」不受影響，仍然是同一個請求從送出到收到回應之間顯示同一組提示；此次優化只會讓這段等待時間變短，不會改變 UI 的顯示方式（若之後想在畫面上呈現「目前正在處理第幾批 / 第幾張」，仍然需要 9.9 規劃中提到的「後端改造成可回報中間進度的機制」，不在本次規劃範圍內）。

### 10.6 實作結果（2026-07-07）

1. `backend/config.py` 新增 `IMAGE_CAPTION_CONCURRENCY: int = int(os.getenv("IMAGE_CAPTION_CONCURRENCY", "3"))`。
2. `backend/routers/embedding.py` 的 `/upload` 端點：原本的 `for raw_img in raw_images:` 序列迴圈重構為內部 async 函式 `process_one_image(raw_img) -> ExtractedImageItem`（保留原有的 per-image try/except、失敗時仍照樣落地存檔的行為），搭配 `caption_semaphore = asyncio.Semaphore(settings.IMAGE_CAPTION_CONCURRENCY)` 與 `extracted_images = list(await asyncio.gather(*[process_one_image(img) for img in raw_images]))` 一次送出全部圖片的任務，寫法比照既有 `EmbeddingService.get_embeddings_batch()` 的 semaphore + gather 慣例。`asyncio.gather` 保證回傳順序與輸入的 `raw_images` 順序一致，`/chunk` 端點依序指派 `image_index`／`parent_chunk_index_range` 的邏輯不受影響。
3. 已用 `python -c "import ast; ast.parse(...)"` 驗證 `config.py`／`routers/embedding.py` 語法正確；`/chunk`、`/vectorize` 與所有前端元件皆未變動（如 10.5 節分析，並行化只影響 `/upload` 內部處理方式，對外的 request/response 格式不變）。
4. **待使用者實機驗證**：上傳一份含 3 張以上圖片的文件，比對總耗時是否有感縮短，並觀察 vLLM 服務端（或其所在主機）在同時處理 3 個請求時的顯存/資源使用狀況是否穩定；若觀察到 OOM 或請求被拒絕，可將 `IMAGE_CAPTION_CONCURRENCY` 環境變數調低（例如 2 或 1）而不需要改動程式碼。

## 11. 圖片描述加入切分、向量搜尋時重組（已實作，2026-07-07）

> 狀態：**已實作 2026-07-07**。實作異動請對照 `docs/DevelopmentProcess/NewFeatures.md` 2026-07-07 條目「圖片描述過長時加入切分，向量檢索命中時重組回完整描述」。使用者提出：圖片的 AI 描述（`describe_image()` 產生的文字）目前不論多長都只變成一個 Qdrant chunk；自 9.8 節把 `max_tokens` 大幅提高後，複雜表格/BOM 截圖的描述可能非常長，塞進單一個 embedding 向量會稀釋語意精準度（跟一開始要把長文件切成小 chunk 的理由相同）。使用者要求：比照一般文字切分邏輯，把過長的圖片描述也切成多個 chunk 分別向量化，並在向量搜尋命中任一片段時，於檢索階段把同一張圖片的所有片段重新組合回完整描述。

### 11.1 設計原則

完全複用現有「`parent_id` + child chunk」架構，把「一張圖片的描述」視為跟「一個 Word 段落」同構的可切分單位，不新增另一套機制：

1. **切分**：`/chunk` 端點（`backend/routers/embedding.py`）把每張圖片的 `description` 呼叫既有 `ChunkingService.split_text()`（`backend/services/chunking_service.py:20-141`，沿用一般文字同一份 `chunk_size`/`chunk_overlap`/`separator`，不新增設定項）。已驗證：文字長度未超過 `chunk_size` 時 `split_text()` 原樣回傳單一 chunk，因此不需要額外的「是否要切」判斷，直接無條件呼叫即可，短描述（多數情況）行為與現況完全一致，只有長描述才會真的產生多個片段。
2. **關聯**：同一張圖片切出的所有片段共用**同一個 `parent_id`**：
   - Word/Markdown 情境沿用現有「跟旁邊文字同一個 `parent_id`」的掛法（`img_item.parent_id`）。
   - PDF／無結構文件目前完全不掛 `parent_id`（`backend/routers/embedding.py:304-324` 標準分支），改成給每張圖片自己一個**以圖片本身為單位**的合成 `parent_id`（例如 `f"{filename}_img_fallback_{img_idx}"`，用圖片自身序號 `img_idx`，而不是切出來的 chunk 序號，否則同一張圖的多個片段會各自拿到不同 parent_id 而無法重組）。這只讓「同一張圖片的多片段」能重組，**不擴大**到「PDF 圖文同段落合併」——PDF 文字本身仍然沒有 `parent_id`，第 6 節既有限制不變。
3. **重組**：`backend/services/qdrant_service.py` 現有的 `get_siblings_and_merge()`（1262 行起）／`get_image_siblings()`（1240 行起）改成依 `image_filename` 分組、組內依 `chunk_index` 排序，用既有的 overlap 去重合併函式（`get_siblings_and_merge()` 內部現有的 `merge_two_strings_with_overlap`，計畫抽成共用 staticmethod）重新拼回完整描述；`search_similar()`／`search_similar_two_step()` 命中圖片本身時，把 `item["content"]` 換成「自己這張圖片的完整重組描述」，而不是像現在只保留命中的那一個片段。

前端（`SourceChunks.vue`/`MessageBubble.vue`）與 `routers/rag.py` 的 `sources` 組裝**預期不需要修改**——它們消費的資料形狀（每個 `image_filename` 對應一筆完整內容的 `image_chunks` 項目）維持不變，只是這筆內容現在會保證完整、不再受限於單一片段。

### 11.2 後端改動範圍

**`backend/routers/embedding.py` — `/chunk` 端點的圖片轉 chunk 邏輯**（`parent_child` 分支約 258-283 行、標準分支約 304-324 行，兩分支需套用同一段邏輯）：
- 拿掉現行「`p_id = img_item.parent_id`；`if not p_id and (is_word or is_md): p_id = ...`」的格式限制，讓**每張圖片一律**都會有 `parent_id`（PDF 圖片也是）。
- 對每張圖片的 `description` 呼叫 `ChunkingService.split_text()`，切出的每個片段各自成為一個 `ChunkItem`（沿用同一個 `parent_id`、依序遞增的全域 `index`），並計算該圖片自己片段範圍的 `parent_chunk_index_range`（`"start~end"`，供除錯／顯示用，非重組邏輯必要欄位）。
- `ChunkResponse.total_chunks`/`avg_token_count`（285-290、326-332 行）不需要另外調整，list 長度自然反映片段數增加。

**`backend/services/qdrant_service.py`**：
- 新增共用 staticmethod：`_merge_overlap_texts(pieces: List[str]) -> str`（把現有巢狀函式 `merge_two_strings_with_overlap` 提升出來共用）與 `_group_and_merge_image_siblings(image_siblings: List[Dict]) -> List[Dict]`（依 `image_filename` 分組 → 依 `chunk_index` 排序 → 逐片段先用既有 `_strip_structured_content_prefix()` 去除結構化樣板前綴 → 用 `_merge_overlap_texts()` 拼回完整描述 → 每組輸出一筆，回傳格狀維持現有 `image_chunks` 的 dict 結構）。
- `get_siblings_and_merge()`／`get_image_siblings()` 內組成 `image_chunks` 的地方改呼叫上述共用方法。
- `search_similar()`（456-503 行）與 `search_similar_two_step()`（同構鄰居合併段落，約 718-753 行）：圖片命中時（`is_image_chunk`），從 `image_chunks` 中找出自己 `image_filename` 對應的完整重組內容並賦值給 `item["content"]`（取代現行「保留自己原本片段內容不被覆蓋」的寫法），再把該筆從回傳的 `image_chunks` 中排除（維持「圖片自己不出現在自己的同段落圖片清單」的既有行為）。

**不需要改動**：`routers/rag.py` 的 `sources` 組裝、前端 `SourceChunks.vue`/`MessageBubble.vue`（皆已依 `image_filename` 去重、假設一個 filename 對應一筆完整內容，此假設在新設計下依然成立）、`/vectorize` 端點（`metadata` 白名單外欄位已自動合併進 payload，`chunk_index` 已確認由 `chunk.index` 寫入，`embedding.py:413`，足夠支撐片段排序需求）。

### 11.3 驗證方式

使用者手動測試（依專案慣例不開瀏覽器驗證）：
1. 上傳含複雜表格/BOM 截圖的 Word 文件並勾選擷取圖片，確認該圖片描述若很長，`/chunk` 回傳的 chunk 清單中出現同一 `image_filename`、相同 `parent_id`、不同 `chunk_index` 的多筆 `chunk_type: image` 項目。
2. 向量化後於「已向量化資料管理」頁確認 Qdrant 內確實寫入對應的多筆 point。
3. RAG 測試頁針對該圖片細節提問，確認命中來源在 `SourceChunks.vue` 呈現的內容/hover 預覽是**完整**描述（不是被切斷的片段），且同一張圖片不會重複列出多次。
4. 額外測試一張「短描述」圖片（原本不會被切分），確認行為與修改前完全一致（回歸測試）。
5. 上傳含圖片的 PDF，確認 PDF 圖片描述若被切分也能在檢索時正確重組，且 PDF 文字本身仍然沒有 `parent_id` 的既有行為不受影響。

### 11.4 實作結果（2026-07-07）

1. `backend/routers/embedding.py` 新增 `_build_image_chunk_items()`，`/chunk` 端點的 `parent_child` 分支（原 258-283 行）與標準分支（原 304-324 行）皆改呼叫此共用函式；`parent_id` 一律賦值（拿掉原本 `is_word or is_md` 的格式限制），合成 `parent_id` 鍵值改用圖片自身序號 `img_idx`。
2. `backend/services/qdrant_service.py` 新增 `_merge_overlap_texts()`（原 `get_siblings_and_merge()` 內部巢狀函式提升為共用 staticmethod）與 `_group_and_merge_image_siblings()`（依 `image_filename` 分組、依 `chunk_index` 排序後合併）；`get_siblings_and_merge()`／`get_image_siblings()` 改用共用方法組成 `image_chunks`；`search_similar()`／`search_similar_two_step()` 圖片命中時改為賦值「自己完整重組後的描述」而非保留原本命中的單一片段。
3. **驗證方式**：因本次改動不牽涉前端與需要真實 vLLM／Qdrant 服務的行為（純屬 chunk 切分與檢索時的資料重組邏輯），改用獨立 Python 腳本直接呼叫 `_build_image_chunk_items()`／`_group_and_merge_image_siblings()`／`_merge_overlap_texts()` 驗證以下情境皆符合預期：短描述維持 1 個 chunk 且內容/`parent_id`不變（回歸）；長描述正確切分成多個 chunk 並共用同一個 `parent_id`；用打亂順序的模擬 siblings 呼叫 `_group_and_merge_image_siblings()` 仍能正確依 `chunk_index` 排序重組回完整描述（驗證不依賴 Qdrant scroll 回傳順序）；不同圖片各自取得不同的合成 `parent_id`；同一個 `parent_id` 下的兩張不同圖片（Word 同段落內有多張圖）分組後仍保持各自獨立、不會被誤合併成一筆。另外重跑既有回歸測試 `backend/tests/test_word_chunker.py`、`tests/test_two_step_search.py`，確認未受影響、全數通過。
4. 依規劃，前端 `SourceChunks.vue`/`MessageBubble.vue` 與 `backend/routers/rag.py` 的 `sources` 組裝皆未修改。
5. **待使用者實機驗證**：上傳含複雜表格/BOM 截圖的 Word/PDF 文件，確認長描述確實被切分並在 RAG 對話中能看到完整重組後的描述內容（本次未使用真實 vLLM 服務驗證端到端行為，僅驗證切分/重組的邏輯正確性）。

## 12. 刪除向量資料時一併清除本地圖片檔案 (已完成，2026-07-07)

> 狀態：**已完成**。圖片內嵌向量化功能會把每張圖片的 AI 描述寫入 Qdrant，同時把圖片原始檔另外落地存放於 `backend/FileAttachments/image/`。但「已向量化資料管理」頁面目前的刪除功能（刪除單一/多筆段落，或整批刪除某個檔案）只會刪除 Qdrant 裡的向量點，完全不會清除對應的本地圖片檔案，導致圖片檔案只會不斷累積、永遠沒有機會被清掉。
>
> 於 2026-07-07 實作完成，在刪除區段或整批刪除時，一併刪除無其餘點位引用的本地圖片檔案，並透過 Mock 寫好單元測試，在 `tests/test_image_cleanup_on_delete.py` 驗證所有情境皆正常。

### 12.1 需特別注意的正確性問題

第 11 節剛完成的「圖片描述過長時切分」功能，代表**同一張圖片現在可能對應多個 Qdrant point，共用同一個 `image_filename`**。若使用者只刪除其中一個片段（例如管理頁面上單選某一小段刪除），不能直接刪除該圖片檔案，否則會讓同一張圖其餘還沒被刪除的片段變成「引用一個已經不存在的檔案」（縮圖/下載全部失效）。因此**刪除本地圖片檔案前，必須先確認 Qdrant 中已經沒有任何 point 還引用這個 `image_filename`**，才能真正刪除檔案。

### 12.2 現況調查

- 前端「已向量化資料管理」（`frontend/src/components/embedding/VectorManagementTab.vue`）有三種刪除動作，皆透過 `frontend/src/services/retrievalService.js` 呼叫後端：
  - 單筆刪除／多選批次刪除 → `POST /api/retrieval/knowledge-bases/{id}/points/batch-delete`（`backend/routers/retrieval.py` 的 `batch_delete_points()`，約 338-380 行）→ 呼叫 `QdrantService.delete_points()`。
  - 整批刪除某檔案 → `POST /api/retrieval/knowledge-bases/{id}/files/delete-by-filename`（`delete_file_by_filename()`，約 383-427 行）→ 呼叫 `QdrantService.delete_by_filename()`。
- `backend/services/qdrant_service.py` 的 `delete_points()`（912-928 行）與 `delete_by_filename()`（931-965 行）目前都是「盲刪」：`delete_points()` 直接用 `client.delete(points_selector=PointIdsList(...))`，從未讀取 payload；`delete_by_filename()` 雖然有 `scroll` 撈出所有點，但 `with_payload=False`（948 行），只取得 `p.id`，同樣拿不到 `image_filename`。
- 圖片檔案的路徑組法與路徑穿越防護，`backend/routers/embedding.py` 的 `GET /images/{stored_filename}` 端點（628-656 行）已有現成寫法可沿用：`os.path.abspath(os.path.join(settings.FILE_ATTACHMENTS_DIR, settings.FILE_ATTACHMENTS_IMAGE_SUBDIR))` 組出圖片目錄，並檢查目標路徑仍在此目錄底下才允許操作。
- 另外兩處既有呼叫端：`backend/services/qdrant_service.py:1112` 的 `delete_db_query_profile_point()`（刪除「資料庫查詢設定檔」point，與圖片無關）、`backend/routers/database_indexing.py:540`（刪除 `DB_IMPORT_{table_name}` 匯入資料，同樣與圖片無關）——這兩處都呼叫到 `delete_points()`/`delete_by_filename()`，新邏輯對它們是無害的空操作（它們刪除的 point 不會有 `chunk_type == "image"`）。

### 12.3 設計方向

改動集中在 `qdrant_service.py` 既有的兩個刪除方法內部，作為刪除成功後的「順便清理」步驟，**不改變這兩個方法對外的回傳型別**（`delete_points()` 仍回傳 `bool`，`delete_by_filename()` 仍回傳 `int`），因此不會影響其他既有呼叫端，`backend/routers/retrieval.py` 的兩個路由與前端都不需要修改：

1. **刪除前先取得即將被刪除的 points 的 payload**：`delete_points()` 在呼叫 `client.delete()` 之前，先用 `client.retrieve(collection_name=..., ids=point_ids, with_payload=True, with_vectors=False)` 取得 payload；`delete_by_filename()` 把既有 scroll 呼叫的 `with_payload=False` 改成 `with_payload=True`。兩者都從 payload 中挑出 `chunk_type == "image"` 的 `image_filename`（去重）。
2. **Qdrant 刪除成功後**，對每個蒐集到的 `image_filename`，用 `client.scroll(collection_name, scroll_filter=Filter(must=[FieldCondition(key="image_filename", match=MatchValue(value=filename))]), limit=1, with_payload=False)` 確認是否還有其他 point 仍引用這個檔名——沒有的話，比照 `embedding.py:628-656` 的路徑安全驗證寫法刪除實體檔案；還有的話跳過。
3. 檔案刪除是 best-effort：單一檔案刪除失敗只記錄 warning log，不影響已經成功的 Qdrant 刪除結果（Qdrant 刪除是主要操作，圖片檔案清理是附帶效果，兩者失敗不應互相拖累，符合 AGENT.md「fail loudly」——清楚記錄但不吞例外）。

新增共用 helper：
- `_get_image_filenames_from_payloads(payloads: List[dict]) -> Set[str]`：從一批 payload 中挑出圖片 chunk 的 `image_filename`，回傳去重集合。
- `_cleanup_orphaned_image_files(collection_name: str, image_filenames: Set[str]) -> None`：對每個檔名做「是否仍被引用」的 Qdrant 查詢，沒有才刪除實體檔案，單一檔案例外不中斷其餘檔案的清理。

### 12.4 驗證方式（規劃）

本地沒有可用的即時 Qdrant/Docker 服務可供端到端測試，比照既有 `tests/test_two_step_search.py` 的做法（`sys.modules['qdrant_client'] = MagicMock()`）撰寫驗證腳本／測試涵蓋：
1. `delete_points()`：mock `client.retrieve()` 回傳一筆 `chunk_type: "image"` 的 payload，且 mock 後續確認引用的 `client.scroll()` 回傳空清單 → 驗證有嘗試刪除本地檔案（`unittest.mock.patch("os.remove")` 驗證有被呼叫、路徑正確）。
2. 同上情境，但 `client.scroll()` 回傳非空（代表同一張圖還有其他片段存在）→ 驗證**不會**呼叫 `os.remove()`。
3. 刪除的 point 是純文字 chunk（無 `chunk_type` 或非 `"image"`）→ 驗證完全不會觸發任何檔案系統操作。
4. `delete_by_filename()` 同樣驗證上述 1、2 情境。
5. 確認兩個方法回傳值型別與既有行為一致，不影響 `database_indexing.py`、`delete_db_query_profile_point()` 既有呼叫端。

使用者待實機驗證：在「已向量化資料管理」頁面對一份含圖片的文件整批刪除，確認 `backend/FileAttachments/image/` 內對應的圖片檔案消失；再測試「圖片描述被切成多個片段」的情境，只單獨刪除其中一個片段但保留同一張圖的其他片段，確認圖片檔案不會被誤刪、其餘片段的縮圖/下載仍正常。

## 13. 圖片描述生成套用「重複輸出／無限思考」偵測與中斷（已實作，2026-07-07）

> 狀態：**已實作 2026-07-07**。實作異動請對照 `docs/DevelopmentProcess/BackendCorrection.md` 2026-07-07 條目。使用者要求：圖片解析（`describe_image()` 呼叫 vLLM 生成描述）時，若模型陷入「無限思考」（reasoning/thinking 階段不斷迴圈、遲遲不產生正式內容）或「輸出重複」（不斷重複同一段文字），要能直接偵測並中斷，並指出專案先前已針對 RAG 對話做過同類需求，套用同一套機制即可。

### 13.1 既有機制（可直接套用的原型）

專案在 2026-07-03 已針對 RAG 對話串流實作過「重複輸出偵測」，記錄於 `docs/DevelopmentProcess/BackendCorrection.md`「2026-07-03 RAG 對話新增 repetition/frequency penalty 與重複輸出偵測」條目，分兩層防禦：

1. **Layer 1：vLLM 生成參數層** — `backend/config.py:47-48` 的 `DEFAULT_REPETITION_PENALTY`（預設 `1.1`）、`DEFAULT_FREQUENCY_PENALTY`（預設 `0`）；`backend/services/llm_service.py` 的 `chat_completion()`（10-19 行參數、36-39 行）已支援 `repetition_penalty`/`frequency_penalty` 參數，未帶入時維持 `None`（不影響 `query_rewrite`/`hyde_generation` 等既有呼叫端）。
2. **Layer 2：串流層 n-gram 重複偵測** — `backend/routers/rag.py:609-634`：串流消費迴圈中持續累積 `content` 增量到 `accumulated_content`，一旦累積長度達到 `repeat_ngram_size(25) * repeat_trigger_count(4)`，取最後 25 字當作 `tail`，若 `tail` 在整個累積內容中出現次數 `>= 4` 次，判定為重複迴圈，記錄 warning log、附加系統提示文字、`break` 主動中斷串流。

**現況缺口**：這兩層目前只套用在 `backend/routers/rag.py` 的 RAG 對話串流，`backend/services/llm_service.py` 的 `describe_image()`（125-166 行）完全沒有套用——呼叫 `chat_completion()` 時未傳入 `repetition_penalty`/`frequency_penalty`（Layer 1 缺）；且目前是**非串流**呼叫（未傳 `stream=True`），必須等 vLLM 完全生成完畢（撞到 `max_tokens=20480` 或 300 秒 timeout）才能拿到結果，中途完全無法偵測或中斷重複/迴圈（Layer 2 缺，且非串流架構下無法套用）。另外，既有 Layer 2 只檢查 `content`（正式輸出）的重複，**沒有檢查 `reasoning_content`／`thought`／`reasoning`（思考內容）的重複**（`rag.py:621-623` 思考內容直接 yield 給前端顯示，未經任何重複檢查）——這正是使用者說的「無限思考」情境：具備推理能力的模型（Qwen3.6-35B-A3B-FP8）可能卡在思考階段不斷迴圈，遲遲不產生正式描述內容，而現有機制對此毫無防備。

### 13.2 設計方向

把 `describe_image()` 從「非串流、等待完整結果」改為「串流消費、邊收邊偵測」，完整套用既有兩層機制，並額外把 Layer 2 的重複偵測**同時套用在思考內容與正式內容兩條軌道**：

1. **Layer 1**：`describe_image()` 呼叫 `chat_completion()` 時補上 `repetition_penalty=settings.DEFAULT_REPETITION_PENALTY, frequency_penalty=settings.DEFAULT_FREQUENCY_PENALTY`（沿用既有全域設定，不新增設定項）。
2. **改為串流呼叫**：`chat_completion(messages, temperature=0.3, max_tokens=20480, timeout=300.0, stream=True, repetition_penalty=..., frequency_penalty=...)`，`describe_image()` 內部改成 `async for raw_chunk in stream:` 消費迴圈（比照 `rag.py:614-636` 的解析寫法：`json.loads` → 取 `choices[0]["delta"]` 的 `content`/`reasoning_content`(`thought`/`reasoning`) → 分別累積成 `accumulated_content`、`accumulated_reasoning`；`finish_reason` 從帶有該欄位的 chunk 中取得，供既有「`finish_reason == "length"` → `truncated=True`」判斷沿用）。
3. **Layer 2（思考與正式內容分別偵測）**：新增共用 staticmethod `LLMService._is_repeating_tail(accumulated: str, ngram_size: int = 25, trigger_count: int = 4) -> bool`（把 `rag.py:628-630` 的判斷式抽出來共用，數值不變，`rag.py` 既有的內嵌判斷式一併改為呼叫這個共用方法，避免同一組 magic number 在兩處各自維護、日後容易失準）。串流消費迴圈中，`accumulated_reasoning`／`accumulated_content` 各自累積後都呼叫 `_is_repeating_tail(...)` 檢查：
   - **思考內容（`accumulated_reasoning`）觸發重複** → 記錄 warning log（例如「Detected repeated reasoning loop while describing image」）、中斷串流消費（`break`）。此時 `accumulated_content` 必然是空字串（模型還沒開始正式輸出），視為**完全沒有產生可用描述**，直接 `raise RuntimeError(...)`，讓既有呼叫端 `backend/routers/embedding.py` 的 `process_one_image()`（現有 `try/except` 已存在，見 9.8 節）依既有邏輯自動標記 `caption_failed=True`、落地存檔但描述文字改為失敗提示——**不需要修改 `embedding.py` 或任何 schema**。
   - **正式內容（`accumulated_content`）觸發重複** → 記錄 warning log、中斷串流消費（`break`），視為「有部分內容但不完整」，回傳 `(accumulated_content.strip(), truncated=True)`——沿用既有 `caption_truncated` 語意（現有前端「描述可能被截斷」橘色徽章不需修改即可正確呈現這個情境）。
4. **不新增欄位／不新增設定項**：重複偵測的門檻數值沿用既有的 `25`/`4`；截斷語意沿用既有 `caption_truncated` 布林欄位；失敗語意沿用既有 `caption_failed` + 例外處理路徑。刻意不新增例如 `caption_repeated` 這類新欄位，避免為同一個「描述不可靠」的使用者情境（截斷 vs 迴圈中斷）製造兩套不同的 UI 判斷分支。

### 13.3 影響範圍

- 改動集中在 `backend/services/llm_service.py` 的 `describe_image()`（125-166 行，內部實作方式改變，對外簽章與回傳型別 `tuple[str, bool]` 或拋出例外的既有行為不變）與新增的 `_is_repeating_tail()` 共用方法。
- `backend/routers/rag.py` 只需把既有內嵌判斷式（628-630 行）換成呼叫新的共用方法，數值與行為不變，屬於零風險重構。
- `backend/routers/embedding.py`／`schemas/embedding.py`／前端皆**不需修改**：`describe_image()` 對外行為維持「回傳 `(description, truncated)`」或「拋出例外」兩種既有型態，呼叫端既有的 `caption_failed`/`caption_truncated` 處理邏輯直接適用。

### 13.4 驗證方式

本地沒有會真的無限迴圈/重複輸出的 vLLM 服務可供端到端測試，改用獨立腳本，比照既有 `tests/test_two_step_search.py` 的 mock 手法，直接 mock `LLMService.chat_completion` 回傳的串流生成器（模擬逐塊 `data: {...}` 字串），驗證以下情境：
1. 正常情境（無重複）：串流內容不觸發 `_is_repeating_tail`，最終回傳完整描述、`truncated=False`，行為與修改前一致（回歸測試）。
2. `finish_reason == "length"`（現有情境）：回傳 `truncated=True`，行為與修改前一致（回歸測試）。
3. 模擬 `reasoning_content` 不斷重複同一段文字達到門檻 → 驗證會 `raise` 例外（不會回傳任何 tuple），且不會誤把思考內容當作正式描述回傳。
4. 模擬 `content` 不斷重複同一段文字達到門檻 → 驗證回傳 `(已累積的部分內容, True)`，且串流有被提前中斷（mock 的生成器不會被完整消費到底）。
5. `_is_repeating_tail()` 本身用幾組固定字串（重複/不重複）驗證判斷邏輯正確。

使用者待實機驗證：待 vLLM 服務可實際觸發思考迴圈或重複輸出的情境出現時（或人為調整 prompt 誘發），觀察後端 log 是否正確印出對應的 warning 訊息、圖片是否正確標記 `caption_failed`/`caption_truncated`，且不會像現況一樣卡滿 300 秒 timeout 或 20480 個 token 才結束。

### 13.5 實作結果（2026-07-07）

1. `backend/services/llm_service.py`：新增 `LLMService._is_repeating_tail()` staticmethod（`rag.py` 原本的內嵌判斷式抽出來的共用版本，數值不變：`ngram_size=25`、`trigger_count=4`）。`describe_image()` 改為呼叫 `chat_completion(..., stream=True, repetition_penalty=settings.DEFAULT_REPETITION_PENALTY, frequency_penalty=settings.DEFAULT_FREQUENCY_PENALTY)`，內部改成 `async for raw_chunk in stream:` 消費迴圈，分別累積 `accumulated_reasoning`／`accumulated_content` 並各自呼叫 `_is_repeating_tail()`；思考內容觸發重複時 `raise RuntimeError(...)`，正式內容觸發重複時提前 `return (accumulated_content.strip(), True)`；`finish_reason` 從串流中帶有該欄位的 chunk 擷取，`finish_reason == "length"` 的既有截斷判斷邏輯不變。
2. `backend/routers/rag.py`：串流重複偵測的內嵌判斷式（原 628-630 行）改為呼叫 `LLMService._is_repeating_tail(accumulated_content)`，移除重複定義的 `repeat_ngram_size`/`repeat_trigger_count` 區域變數，行為與門檻數值完全不變。
3. **驗證方式**：因本地無可觸發真實無限迴圈的 vLLM 服務，改用獨立 Python 腳本 mock `LLMService.chat_completion` 回傳的串流生成器，驗證：正常情境完整回傳且 `truncated=False`（回歸）；`finish_reason=="length"` 情境 `truncated=True`（回歸）；`reasoning_content` 重複觸發 `RuntimeError` 且訊息含「無限思考」字樣；`content` 重複時回傳已累積的部分內容且 `truncated=True`，並確認串流生成器**沒有被完整消費到底**（實際只消費 6/20 個模擬 chunk，證明有提前中斷，而非等到生成器自然結束）；`_is_repeating_tail()` 的獨立字串判斷案例皆正確。另重跑既有回歸測試 `backend/tests/test_word_chunker.py`、`tests/test_two_step_search.py`，確認未受影響、全數通過。
4. 依規劃，`backend/routers/embedding.py`／`schemas/embedding.py`／前端皆未修改。

## 14. 圖片查詢語義解析降級、同段落多張圖片未進入 AI 摘要、段落編號顯示 #?（已實作，2026-07-07）

> 狀態：**已實作 2026-07-07**。實作異動請對照 `docs/DevelopmentProcess/BackendCorrection.md` 2026-07-07 條目。使用者實測「跟我說明 GP5.1建立備份營運中心.docx 圖片」這類查詢後回報三個相關問題：(1) 語義解析 AI 輸出 `is_fallback: true`，`embeddings_input`／`sparse_keywords` 直接退化成原始問句，完全沒有理解查詢意圖；(2) 畫面上「參考圖片引用」列出約 9 筆同一份文件、相似度皆為 0.75 的圖片，但 AI 的結論只總結了其中 1 張；(3) 這 9 筆圖片的段落編號都顯示「#?」而非實際數字。

### 14.1 問題一：語義解析降級為 fallback（`is_fallback: true`）

**根因**：`backend/services/embedding_service.py` 的 `query_to_semantic_json()`（108-276 行）系統提示詞（117-181 行）的「【嚴格核心規則】」與全部 3 個 Few-Shot 範例（143-179 行：`p_zta.4gl`／`gab_file`／`q_smy`）**清一色都是程式碼/資料庫欄位查詢情境**，核心教學重點是「積極剝除『說明』『用途』『功能』等通用語意詞，只留下精確檔名/識別碼」（規則 5，140-142 行）。這套規則套用在使用者對**一般 Word 文件**的查詢、且查詢中帶有「圖片」這種**內容型態限定詞**時並不合適：
- 規則 5 沒有排除「圖片」「圖表」「截圖」這類詞——這些詞恰好是本次「圖片內嵌向量化」功能命中圖片 chunk 的關鍵語意訊號（圖片描述文字本身會包含大量與「圖片」「畫面」「圖表」相關的詞彙），若被當成通用稀釋詞剝除，`embeddings_input`／`sparse_keywords` 就會遺漏這個檢索意圖。
- 3 個少樣本範例全部是「純檔名查詢」，完全沒有「一般文件檔名 + 內容型態限定詞（圖片/圖表/截圖）」這種查詢形狀的示範，地端 Instruct 模型（目前是 `qwen2.5-coder-7b-instruct-q8_0.gguf`，程式碼專用模型）缺乏可依循的模板，對這類非程式碼查詢容易產生不符合既有 3 個схема 認知的輸出格式，導致 `_call_and_parse()`（237-257 行）的 `json.loads()` 解析失敗或缺少 `embeddings_input` 欄位（255-256 行的 `ValueError`），兩次重試（`temperature=[0.1, 0.5]`）都失敗後降級為 `fallback_json`（223-235 行：直接把原始問句整句塞進 `embeddings_input`/`sparse_keywords`）。
- 本次修正**無法從程式碼層面重現或確認 llama.cpp 實際回傳了什麼**（沒有即時服務可測試），只能從 Prompt 設計面改善「讓模型更容易產生正確格式」與「不要誤刪關鍵檢索詞」，若之後仍持續 fallback，需要使用者提供當下的後端 log（`logger.warning`/`logger.error`，237-276 行已有記錄實際例外訊息）才能進一步精確診斷。

**修正方向**：`backend/services/embedding_service.py` 的 `query_to_semantic_json()` 系統提示詞：
1. 規則 5 明確加入排除清單：「圖片」「圖表」「截圖」「照片」「畫面」「介面」等**內容型態詞**不屬於稀釋用詞，必須保留在 `embeddings_input`／`sparse_keywords` 中（因為知識庫內確實存在圖片描述類型的 chunk，這些詞是有效的檢索訊號，與「說明」「用途」等純粹的提問客套語不同）。
2. 新增第 4 個 Few-Shot 範例（「一般文件 + 內容型態限定詞」情境），對齊使用者實際遇到的查詢形狀：
   - 輸入：`跟我說明 GP5.1建立備份營運中心.docx 圖片`
   - 良好輸出：`embeddings_input: "GP5.1建立備份營運中心.docx 圖片"`、`sparse_keywords: ["GP5.1建立備份營運中心.docx", "圖片"]`
   - 錯誤示範：把「圖片」也當通用詞一併剝除，變成只剩檔名（會導致檢索不到圖片說明類型的 chunk，只找到一般文字段落）。
3. 這兩處修改單純是 Prompt 文字調整，不改變 `query_to_semantic_json()` 的程式邏輯、重試機制或回傳格式。

### 14.2 問題二：同一區塊有多張圖片時，AI 只總結其中一張

**根因**：使用者的文件（多張截圖的教學文件）裡，這 9 張圖片實際上共用**同一個 `parent_id`**（Word 結構化切分時，同一段落/章節下的多張內嵌圖片，依第 3.1／11 節設計會沿用「跟旁邊文字相同的 `parent_id`」）。`backend/services/qdrant_service.py` 的 `search_similar_two_step()` 鄰居合併階段在依 `parent_id` 去重時（708-717 行 `seen_parents`／`deduped_neighbors`）**每個 `parent_id` 只保留一筆結果**，其餘 8 張圖片雖然各自都有 0.75 分的獨立相似度，仍會被去重掉、不會出現在最終的頂層 `raw_results`／`sources` 清單中——牠們只會透過「贏家」那一筆結果呼叫 `get_siblings_and_merge()`／`get_image_siblings()`（729-747 行）時，被當作「同段落圖片」附掛進贏家的 `metadata.image_chunks`（供前端顯示縮圖清單）。

問題在於 `backend/routers/rag.py` 組 `context_str` 送給 vLLM 的迴圈（428-461 行 `for idx, item in enumerate(raw_results):`）**只走訪頂層 `raw_results`**，完全沒有把每筆結果 `metadata.image_chunks`（447 行，目前只附掛給前端顯示用）攤平併入 `context_parts`。也就是說，這 8 張「陪榜」圖片的完整描述其實已經被正確撈出、正確重組（第 11-13 節的成果都有效運作），**卻從未真正送進 LLM 的 context**，AI 自然只看得到、只能總結那 1 張「贏家」圖片。

**修正方向**：`backend/routers/rag.py` 的 `context_parts` 組裝迴圈（428-461 行），在處理完每個頂層 `item` 之後，額外攤平 `meta.get("image_chunks", [])` 併入 `context_parts`（沿用既有「【來源文件：X | 段落編號：Y】\n內容：Z」格式，額外標註「（圖片描述）」以利 LLM 分辨），並用一個貫穿整個迴圈的 `seen_image_filenames` 集合（涵蓋頂層圖片 hit 自己的 `image_filename` 與攤平的巢狀圖片）避免同一張圖片經由不同「贏家」被重複塞進 context 兩次。這個設計呼應既有「同段落文字全部合併進 `parent_content`、不論個別分數」的既有邏輯——同段落圖片本來就該同等對待，不需要各自重新過門檻分數（它們本來就沒有獨立的查詢相似度分數，`get_by_parent_id` 只是單純的 scroll，UI 上顯示的 0.75 其實是繼承自贏家的分數，並非自己的分數）。若攤平後總 token 數變大，沿用既有 `ContextSummarizerService`（`docs/DevelopmentProcess/ContextMapReduceSummaryPlan.md`）Map-Reduce 分批摘要機制即可，不需要新增安全機制。

### 14.3 問題三：圖片段落編號顯示「#?」

**根因**：`backend/services/qdrant_service.py` 的 `_group_and_merge_image_siblings()`（1364-1395 行）組出的 `image_chunks` 項目 `metadata` 只有 `filename`／`page`／`chunk_type`／`image_filename` 四個欄位，**從未包含 `chunk_index`**。前端 `frontend/src/components/chat/SourceChunks.vue`（約 174-177 行）渲染「段落: #」時讀的是 `source.metadata.chunk_index`，讀不到就顯示預設值 `'?'`——這是前端行為完全正確、後端漏給欄位的問題。

**修正方向**：`_group_and_merge_image_siblings()` 組成每筆合併結果時，補上 `"chunk_index": first["metadata"].get("parent_chunk_index_range") or first["metadata"].get("chunk_index")`——直接沿用第 11 節既有已經在計算並存進 payload 的 `parent_chunk_index_range`（每張圖片自己切出的片段範圍，例如單片段圖片是 `"5"`、多片段是 `"5~11"`），不需要新增任何計算或欄位，純粹是「漏寫」的補齊。`get_image_siblings()`（呼叫同一個共用方法）自動一併修正。

### 14.4 影響範圍

- `backend/services/embedding_service.py`：只改系統提示詞文字，不動程式邏輯。
- `backend/routers/rag.py`：`context_parts` 組裝迴圈新增攤平 `image_chunks` 的邏輯；`sources` 陣列組成（`image_chunks` 欄位本身）不需修改，前端顯示邏輯不受影響（頂層 `sources` 清單筆數不變，只是被送進 LLM 的 `context_str` 內容變多）。
- `backend/services/qdrant_service.py`：`_group_and_merge_image_siblings()` 補一個既有欄位，`get_siblings_and_merge()`／`get_image_siblings()` 呼叫端不需修改。
- 前端不需修改：`SourceChunks.vue` 讀取 `metadata.chunk_index` 的邏輯已經正確，只是後端一直沒有給值。

### 14.5 驗證方式

1. Prompt 調整後，需要使用者在實際 vLLM/llama.cpp 環境重新測試「跟我說明 GP5.1建立備份營運中心.docx 圖片」這類查詢，確認 `is_fallback` 不再是 `true`，且 `embeddings_input`/`sparse_keywords` 保留「圖片」關鍵字（本地無法端到端驗證 Prompt 對地端 Instruct 模型實際輸出品質的影響，僅能靜態檢視 Prompt 文字修改是否合理）。
2. `_group_and_merge_image_siblings()` 補上 `chunk_index` 後，比照既有測試手法（mock siblings 資料）驗證回傳的 `metadata.chunk_index` 正確等於來源片段的 `parent_chunk_index_range`。
3. `rag.py` 的 `context_parts` 攤平邏輯，用 mock `raw_results`（其中一筆帶 `metadata.image_chunks` 有 3 張圖片）驗證：`context_str` 最終包含所有 3 張圖片的描述文字，且同一個 `image_filename` 不會因為被多個頂層結果引用而重複出現兩次。
4. 使用者待實機驗證：對含多張圖片的同一段落提問，確認 AI 回答中會提及/總結所有相關圖片（不再只總結 1 張），且畫面上的「參考圖片引用」段落編號不再顯示「#?」。

### 14.6 實作結果（2026-07-07）

1. `backend/services/embedding_service.py`：`query_to_semantic_json()` 系統提示詞規則 5 補上「圖片」「圖表」「截圖」「照片」「畫面」「介面」等內容型態詞的排除例外（不屬於要剝除的通用稀釋詞）；新增「範例 4」示範一般文件檔名 + 內容型態限定詞的正確/錯誤輸出對照，直接對齊使用者實測的查詢形狀。僅調整 Prompt 文字，`query_to_semantic_json()` 的重試/解析邏輯與回傳格式完全未變動。
2. `backend/services/qdrant_service.py`：`_group_and_merge_image_siblings()` 補上 `metadata.chunk_index`，值取自既有已在計算的 `parent_chunk_index_range`（單片段圖片顯示單一數字、多片段圖片顯示範圍如 `"5~7"`），未新增任何欄位或計算，`get_siblings_and_merge()`／`get_image_siblings()` 呼叫端自動一併受益。
3. `backend/routers/rag.py`：`context_parts` 組裝迴圈新增攤平 `meta.get("image_chunks", [])` 的邏輯，並用貫穿整個迴圈的 `seen_image_filenames` 集合去重（涵蓋頂層圖片 hit 自己的 `image_filename`，避免圖片自己也出現在自己的巢狀清單中被重複攤平；也避免同一張圖片透過不同「贏家」結果被塞入 context 兩次）。`sources` 陣列組成與 `retrieved_summary`（`vector_search` 步驟訊息）未變動，只有實際送進 LLM 的 `context_str` 內容變多。
4. **驗證方式**：因本地無可用的即時 llama.cpp 服務可驗證 Prompt 對模型輸出品質的實際影響，該部分僅靜態檢視文字修改。`_group_and_merge_image_siblings()`／`context_parts` 攤平邏輯則用獨立 Python 腳本驗證：單片段圖片正確帶出 `chunk_index`；多片段圖片正確帶出共用範圍；同一 `parent_id` 下的不同圖片各自保留自己的 `chunk_index`（不被誤合併，回歸 11 節既有邏輯）；一筆文字結果附帶 9 張同段落圖片時全部 9 張都會攤平進 context；同一張圖片透過兩筆不同「贏家」結果重複出現時只會被計入一次；圖片本身命中時，其巢狀 `image_chunks` 清單中的「自己」不會被重複攤平、但清單中的其他圖片仍會正確攤平。另重跑既有回歸測試 `backend/tests/test_word_chunker.py`、`tests/test_two_step_search.py`，確認未受影響、全數通過。
5. 前端 `SourceChunks.vue`／`sources` 回傳結構皆未修改，如規劃預期。

# 15. 圖片描述與 RAG 重複偵測演算法升級（2026-07-08 修正）

### 15.1 問題描述

使用者在實測解析圖片（`describe_image`）時，多張圖片頻繁觸發 `LLMService._is_repeating_tail` 導致圖片描述生成失敗（顯示為「描述失敗」或「描述可能被截斷」）。
根本原因為舊有的 `_is_repeating_tail` 採用全局字串出現次數統計（`accumulated.count(tail) >= 4`），當模型在正常長推理/描述過程中多次提及上下文提示或長技術名詞（如 `Createdb dbname 4 ---> 建立一個指定來源的資料庫(非DS資料庫 )`）時，極易將其誤判為生成無限迴圈。

### 15.2 解決方案與實作結果

1. **升級為連續週期性重複（Consecutive Loop）演算法**：
   重構 `backend/services/llm_service.py` 中的 `_is_repeating_tail()`。設定偵測週期 P 介於 3 到 250 之間。唯有當累積字串尾部最後長度為 P 的區塊，在局部滑動視窗（大小限制為 P * 5）內連續重覆出現達 `trigger_count` 次時，才判定為無限迴圈。
2. **加入 Alphanumeric 過濾機制**：
   在判斷週期時，要求重複區塊 `suffix` 中必須含有至少一個 `isalnum()` 字母或數字。藉此正確忽略 Markdown 表格線（如 `|---|---|---|`）、純空格、換行、點號 `...` 等排版性符號的連續重複，防範其被誤判為內容迴圈。
3. **影響與相容性**：
   - 封裝簽章與回傳型別完全不變，無須修改 RAG 路由（`rag.py`）或前端。
   - `rag.py` 因為同樣呼叫 `LLMService._is_repeating_tail`，因此自動繼承並受益於此升級，解決對話串流的重複誤判風險。
4. **驗證方式**：
   已透過獨立 Python 測試腳本，完整覆蓋並通過「正常分散提及關鍵字」、「寬 Markdown 表格線不誤觸」以及「真實連續重複精準攔截」等多情境驗證，成功排除所有 False Positive。原本創建的所有暫存測試檔案已全部刪除，保持環境衛生。
