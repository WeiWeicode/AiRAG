<!-- 新功能紀錄(最新紀錄放最前面) -->
## 2026-07-07 刪除向量資料時一併清除本地圖片檔案

### 功能描述
當在「已向量化資料管理」頁面進行單筆/多選段落刪除，或整批刪除某檔案時，系統會自動清理落地存放在 `backend/FileAttachments/image/` 目錄下的實體圖片檔案。為了避免在「圖片描述過長切分」情境下，誤刪仍被同一圖片其他片段引用的實體檔案，實作了「最後引用檢查」機制——僅在 Qdrant 中已無任何 point 引用該圖片檔案時，才真正執行實體檔案刪除。

### 實作內容
1. `backend/services/qdrant_service.py`：
   - 新增 `_get_image_filenames_from_payloads()` 靜態方法，從批次點位的 payload 中過濾提取所有 chunk_type 為 "image" 的 `image_filename` 並進行去重。
   - 新增 `_cleanup_orphaned_image_files()` 類別方法，接受待清理的圖片檔名集合，對每個檔名在 Qdrant 中執行一次 scroll 查詢，確認是否仍有剩餘的點引用此檔名。若無引用，比照 `embedding.py` 的路徑安全驗證（防止路徑穿越），確認路徑安全後，以 `os.remove` 刪除本地實體檔案。
   - 修改 `delete_points()`：在呼叫 `client.delete()` 前，先使用 `client.retrieve(..., with_payload=True)` 撈取即將被刪除點位的 payload，萃取出所有關聯的 `image_filename`。Qdrant 點位刪除成功後，呼叫 `_cleanup_orphaned_image_files()` 執行實體清理。
   - 修改 `delete_by_filename()`：將原本 scroll 撈取點位時的 `with_payload=False` 改為 `with_payload=True`，在 `delete` 之前萃取出所有 `image_filename`，於 Qdrant 點位刪除成功後同樣呼叫 `_cleanup_orphaned_image_files()`。
2. 檔案刪除採 best-effort 方式，單一檔案清理失敗（例如已被手動刪除）會記錄 warning log，不影響已經成功的 Qdrant 點位刪除結果，符合 AGENT.md「fail loudly」原則。

### 影響範圍
修改完全封裝在 `QdrantService` 既有的兩個刪除方法內部，不改變對外回傳型別，對既有呼叫端（如 `database_indexing.py` 與 `delete_db_query_profile_point` 等）零影響，且不影響前端與 RAG 對話流程。

### 修改檔案
- `backend/services/qdrant_service.py`
- `tests/test_image_cleanup_on_delete.py`（新增單元測試）

## 2026-07-07 圖片描述過長時加入切分，向量檢索命中時重組回完整描述

### 功能描述
使用者提出：圖片的 AI 描述（`describe_image()` 產生的文字）不論多長都只變成一個 Qdrant chunk；自 `max_tokens` 提高到 20480 後，複雜表格/BOM 截圖的描述可能非常長，塞進單一個 embedding 向量會稀釋語意精準度。改為比照一般文字切分邏輯，把過長的圖片描述也切成多個 chunk 分別向量化，並在向量搜尋命中任一片段時，於檢索階段把同一張圖片的所有片段重新組合回完整描述。完全複用既有「`parent_id` + child chunk 同段落合併」架構，未新增其他機制。詳細規劃見 `docs/DevelopmentProcess/DocumentImageEmbeddingPlan.md` 第 11 節。

### 實作內容
1. `backend/routers/embedding.py`：新增 `_build_image_chunk_items()`，把每張圖片的描述呼叫既有 `ChunkingService.split_text()`（沿用該次 `/chunk` 請求同一份 `chunk_size`/`chunk_overlap`/`separator`）切分；短描述天然只產生 1 個 chunk（行為不變）。同一張圖片切出的所有片段共用同一個 `parent_id`（Word/Markdown 沿用跟旁邊文字相同的 `parent_id`；其餘情況給每張圖片自己的合成 `parent_id`，鍵值改用圖片自身序號 `img_idx` 而非片段序號，確保同一張圖的多個片段能共用同一個 `parent_id`——這也讓原本完全不掛 `parent_id` 的 PDF 圖片，第一次能支援「同一張圖片多片段」的重組）。`/chunk` 端點的 `parent_child` 與標準兩個分支皆改呼叫此共用函式。
2. `backend/services/qdrant_service.py`：新增共用方法 `_merge_overlap_texts()`（原本 `get_siblings_and_merge()` 內部的巢狀去重合併函式提升為共用 staticmethod）與 `_group_and_merge_image_siblings()`（依 `image_filename` 分組、組內依 `chunk_index` 排序、逐片段清除結構化樣板前綴後合併回完整描述）。`get_siblings_and_merge()`／`get_image_siblings()` 皆改用此共用方法組成 `image_chunks`，確保每個 `image_filename` 只對應一筆內容完整的項目（不再是「每個片段各自一筆」）。
3. `search_similar()`／`search_similar_two_step()`：圖片 chunk 本身被命中時，改成用同一張圖片的完整重組內容取代 `item["content"]`（原本是保留命中的單一片段內容不被覆蓋），確保 AI 與畫面看到的一定是完整描述，不會只看到命中的那一小段。

### 影響範圍
前端 `SourceChunks.vue`/`MessageBubble.vue` 與 `backend/routers/rag.py` 的 `sources` 組裝均不需修改——消費的資料形狀（每個 `image_filename` 對應一筆完整內容的 `image_chunks` 項目）維持不變，只是內容現在保證完整。已用獨立腳本驗證：短描述行為不變、長描述正確切分並共用 `parent_id`、依 `chunk_index` 重組不受輸入順序影響、同一 `parent_id` 下的不同圖片不會被誤合併；並重跑 `backend/tests/test_word_chunker.py`、`tests/test_two_step_search.py` 確認既有測試皆通過。

### 修改檔案
- `backend/routers/embedding.py`
- `backend/services/qdrant_service.py`
- `docs/DevelopmentProcess/DocumentImageEmbeddingPlan.md`（記錄規劃與實作結果）

## 2026-07-07 圖片描述改為並行處理（預設同時 3 張），縮短多圖文件的上傳等待時間

### 功能描述
使用者觀察到「資料切分與向量化寫入」上傳含多張圖片的文件時，是逐張依序送給 vLLM 做多模態描述、等前一張完成才處理下一張，整份文件的圖片辨識總耗時會隨圖片數量線性增加。改為併發處理，預設同時最多 3 張圖片一起送給 vLLM，縮短整體等待時間。詳細規劃見 `docs/DevelopmentProcess/DocumentImageEmbeddingPlan.md` 第 10 節。

### 實作內容
1. `backend/config.py`：新增 `IMAGE_CAPTION_CONCURRENCY`（預設 `3`，可透過環境變數調整），控制同時對 vLLM 發送多少個圖片描述請求。
2. `backend/routers/embedding.py`：`/upload` 端點原本序列處理圖片的 `for` 迴圈，重構為內部 async 函式 `process_one_image()` + `asyncio.Semaphore(settings.IMAGE_CAPTION_CONCURRENCY)` + `asyncio.gather()`，寫法比照既有 `EmbeddingService.get_embeddings_batch()` 的併發慣例；單張圖片描述失敗仍只影響該張（不中斷整批），且不論成功與否都照樣落地存檔；`asyncio.gather` 保證回傳順序與原始擷取順序一致，不影響後續 `image_index`／`parent_chunk_index_range` 的指派邏輯。

### 影響範圍
只影響 `/api/embedding/upload` 內部處理方式，對外的 request/response 格式不變；「資料切分與向量化寫入」與「自動分批寫入」兩個分頁皆共用此端點，自動一併受益，無需個別調整前端。若目標 vLLM 部署的顯存/運算資源吃緊，可將 `IMAGE_CAPTION_CONCURRENCY` 環境變數調低，不需要改動程式碼。

### 修改檔案
- `backend/config.py`
- `backend/routers/embedding.py`
- `docs/DevelopmentProcess/DocumentImageEmbeddingPlan.md`（記錄規劃與實作結果）

## 2026-07-07 向量化寫入圖片段落時自動加上「圖片」分類標籤

### 功能描述
當上傳並解析 Word/PDF 文件時，如果擷取到內嵌圖片並生成描述，在寫入向量資料庫 Qdrant 時，系統現在會自動為這些圖片段落的 `tags` 陣列加上 `"圖片"` 標籤。同時，若該標籤在 MongoDB 的分類標籤（Tag）清單中不存在，會自動於後端建立，確保前端的標籤選單中能正確顯示與篩選該標籤。

### 實作內容
1. `backend/routers/embedding.py`：在 `/vectorize` 路由中，判斷請求的所有 chunks 中若存在 `chunk_type == "image"` 的圖片點位：
   - 自動在 MongoDB `Tag` 集合中搜尋 `"圖片"` 標籤，若不存在則將其新增進資料庫，方便前端即時取得並在分類標籤篩選器中顯示。
   - 遍歷 chunks，當遇到圖片段落時（`chunk.metadata.get("chunk_type") == "image"`），自動將 `"圖片"` 字串附加至其 `tags` 列表（會自動進行去重與類型轉換安全檢查），確保點位最終被 upsert 寫入 Qdrant 時帶有此 tag。

### 修改檔案
- `backend/routers/embedding.py`
- `docs/DevelopmentProcess/NewFeatures.md`

## 2026-07-06 修正「AI 讀取附件內容」實際讀取的是使用者填寫的備註而非檔案本身內容

### 問題描述
使用者實測「擷取附件內容」步驟後回報：畫面上顯示的是上傳附件時手動填寫的「檔案描述」欄位（一段簡短備註），並非附件檔案本身的實際文字內容——這不符合預期，使用者要的是 AI 真正讀取檔案（PDF/DOCX 等）解析出來的內容，不是使用者自己打的一段話。

### 修改內容
1. **上傳時自動解析檔案實際內容**：`backend/routers/attachment.py` 的 `upload_attachment()` 新增呼叫既有的 `services/document_parser.py` 的 `DocumentParser.parse_file()`（與 `/api/embedding/upload` 共用同一套解析器，支援 PDF/DOCX/DOC/DOTX/TXT/MD/4GL/4FD），解析成功則存入 `Attachment.extracted_content`；解析失敗（例如上傳了目前不支援的格式，如 xlsx/pptx/圖片）則記錄 `extraction_error`，**不會**中斷上傳流程，附件仍可正常儲存與下載。
2. `backend/models/attachment.py`：新增 `extracted_content`（自動解析出的實際文字內容）與 `extraction_error`（解析失敗原因）兩個欄位；原本的 `description` 欄位保留，但重新定位為「使用者填寫的備註」，僅在無法自動解析時作為備援內容來源。
3. `backend/routers/rag.py`：新增共用函式 `_get_attachment_effective_text(att)`——優先回傳 `extracted_content`；解析失敗或不支援格式時退回 `description`（並在內容旁註明原因）；兩者皆無則明確回報「無可讀取的內容」，不假裝有內容。`attachment_extraction` 步驟與 Map-Reduce 分批摘要的附件區塊皆改用此函式取得的實際內容，而非直接讀 `description`。
4. `backend/schemas/attachment.py`：`AttachmentResponse` 新增 `has_extracted_content`（布林值，避免整份附件清單回應夾帶大量文字內容）與 `extraction_error`。
5. **前端**：`frontend/src/components/embedding/AttachmentManagerTab.vue` 附件清單每筆新增「✓ 已擷取實際內容」或「⚠ 無法自動擷取內容」徽章（滑鼠移入可看到失敗原因），並將「檔案描述 / AI 讀取內容」欄位標籤與提示文字改為「檔案描述（備註）」，清楚說明此欄位僅供顯示參考、AI 讀取附件內容時會優先使用自動擷取的檔案實際內容。

### 已知限制
本次修正前上傳的既有附件（尚未存有 `extracted_content`）不會被回溯解析，AI 讀取附件內容時會自動退回使用其 `description` 備註；若要讓既有附件也改用實際檔案內容，需重新上傳該檔案。

### 修改檔案
- `backend/models/attachment.py`
- `backend/schemas/attachment.py`
- `backend/routers/attachment.py`
- `backend/routers/rag.py`
- `frontend/src/components/embedding/AttachmentManagerTab.vue`

### 對應規劃文件
`docs/DevelopmentProcess/AttachmentSemanticHybridSearchPlan.md`。

## 2026-07-06 語義混合附件查詢法新增獨立的「擷取附件內容」步驟，讓使用者能親眼確認 AI 實際讀取了哪些附件

### 功能描述
使用者實測後回報：勾選「AI 讀取附件內容」後，附件描述內容會被併入回答的上下文摘要，但畫面上完全沒有任何步驟顯示「AI 真的讀取了哪些附件、讀到什麼內容」，無法確認這個功能是否真的生效。新增獨立的 SSE 步驟 `attachment_extraction`（擷取附件內容），在「向量資料查詢」步驟成功之後、進入分批摘要判斷之前送出，列出本次找到的每一個關聯附件的檔名、Token 數與完整內容說明文字，讓使用者展開此步驟即可親眼確認。

### 實作內容
1. `backend/routers/rag.py`：`rag_chat_stream()` 在 `vector_search` 的 `success` 事件送出之後，新增判斷——當 `search_type == "semantic_hybrid_attachment"` 且 `read_attachment_content` 為 `true` 且確實找到關聯附件（`attachments_data` 非空）時，依序送出 `attachment_extraction` 的 `running`／`success` 兩個 `event: step`，`success` 內容逐一列出每個附件的檔名、`count_tokens(description)` 計算的 Token 數與內容說明全文。未勾選、或沒有關聯附件時完全不會送出此步驟，不影響既有行為。
2. **前端零改動**：`frontend/src/stores/chatStore.js` 既有的 SSE 未知 step key 動態插入機制（與 Map-Reduce 分批摘要步驟共用同一套邏輯，見 2026-07-06「Map-Reduce 分批摘要」條目）會自動在 `vector_search` 之後、`llm_thinking` 之前插入這個新步驟並可展開查看，因此本次不需要修改任何前端程式碼。
3. 附件內容過長時的分批摘要門檻、以及一次讀取多個關聯附件內容，皆沿用既有機制（附件描述在 Map-Reduce 階段被當作額外 block 併入 `ContextSummarizerService.maybe_summarize`；`attachments_data` 本身即為清單，天然支援多檔案），未新增額外機制。

### 修改檔案
- `backend/routers/rag.py`

### 對應規劃文件
`docs/DevelopmentProcess/AttachmentSemanticHybridSearchPlan.md`。

## 2026-07-06 語義混合附件查詢法 (Semantic Hybrid Search + Attachment) 實作

### 功能描述
實作「語義混合附件查詢法 (Semantic Hybrid Search + Attachment)」，此查詢法能在 RAG 檢索時自動關聯預先上傳的實體附件：
1. **關聯附件管理與上傳**：在前端「向量切分與寫入」頁面中，新增一個「關聯附件管理與上傳」分頁。使用者可選定知識庫，上傳相關參考檔案（例如 xlsx, pdf 檔案），並可附帶該檔案的詳細功能用途描述（可用於對話摘要）、標籤 (Tags) 與類別 (Classes)。上傳的檔案存儲於本地磁碟，並記錄元資料於 MongoDB 中。
2. **多重關聯設定**：在「已向量化資料管理與刪除」分頁中，使用者在選擇主檔案後，除了原有的「設定關聯檔案 (Links To)」外，新增「設定關聯附件 (Linked Attachments)」區塊，列出目前知識庫所有上傳過的附件並以多選 checkbox 供使用者設定與更新。設定結果會批次寫入該主要檔案所有向量段落的 `linked_attachments` 欄位中。
3. **雙階段附件檢索**：語義混合附件查詢模式下，系統會將檢索命中片段的 `linked_attachments` 收集，若勾選「AI 讀取附件內容」，會自動將所涉附件的「描述與說明文字」併入上下文摘要（Map-Reduce 機制會將此附件內容妥善進行 Bin-Packing 與分批摘要），避免超出模型上下文長度。
4. **附件呈現與下載引用**：在對話泡泡內文下方，新增「相關參考附件」區塊，顯示附件的「原始檔名」與「描述說明」，點選時可直接從後端端點下載實體附件。

### 實作內容
1. **後端設定與資料模型**：
   - `backend/config.py`：新增 `FILE_ATTACHMENTS_DIR` 設定項。
   - `backend/models/attachment.py` (新設)：建立 `Attachment` Beanie 模型。
   - `backend/models/mongodb.py`：註冊 `Attachment` 文件模型。
   - `backend/schemas/attachment.py` (新設)：定義附件上傳、下載及列表回傳 Schema。
   - `backend/routers/attachment.py` (新設)：實作附件上傳、清單列出、單筆刪除與檔案安全下載端點。
   - `backend/main.py`：掛載附件 Router。
2. **後端檢索與 RAG 整合**：
   - `backend/services/qdrant_service.py`：新增 `update_attachments_by_filename` 用於批次更新 Qdrant 向量點位 payload 欄位；更新 `get_unique_metadata` 同步讀取 `linked_attachments` 與 `links_to`。
   - `backend/schemas/retrieval.py`：在 `RetrievalMetadata` 中加入 `linked_attachments` 欄位；新增 `UpdateAttachmentsRequest` 用於接收更新附件請求。
   - `backend/routers/retrieval.py`：新增 `update-attachments` POST 端點。
   - `backend/routers/rag.py`：在 `ChatParams` 新增 `read_attachment_content`；在 `rag_chat_stream()` 內，若採用語義混合附件查詢模式且包含關聯附件，自動拉取元資料；若勾選 `read_attachment_content` 則將附件描述合併至上下文；最終隨 `sources` 事件送出附件清單。
3. **前端 API 與 Store 整合**：
   - `frontend/src/services/attachmentService.js` (新設)：實作對附件 API 的呼叫。
   - `frontend/src/services/retrievalService.js`：擴充 `updateAttachments` 介面。
   - `frontend/src/stores/paramsStore.js`：狀態加入 `readAttachmentContent` 預設 false。
   - `frontend/src/stores/chatStore.js`：串流發送 payload 新增參數； sources 事件處理中將 `data.attachments` 存入 `msg.attachments`。
4. **前端 UI 與交互設計**：
   - `frontend/src/views/EmbeddingTestView.vue`：掛載「關聯附件管理與上傳」分頁。
   - `frontend/src/components/embedding/AttachmentManagerTab.vue` (新設)：上傳與列出/刪除/下載附件檔案之管理卡片。
   - `frontend/src/components/embedding/VectorManagementTab.vue`：加入「設定關聯附件」UI 區塊，並在 Chunks 清單中為關聯附件點位繪製綠色 📎 徽章。
   - `frontend/src/components/params/RagParamsPanel.vue`：搜尋模式下拉選單新增新模式選項，並在切換至新模式時動態顯示 `AI 讀取附件內容` 開關。
   - `frontend/src/components/chat/MessageBubble.vue`：在對話泡泡底部新增「相關參考附件」卡片，支援點選呼叫 URL 以新分頁下載。

### 修改檔案
- `backend/config.py`
- `backend/models/attachment.py` (新設)
- `backend/models/mongodb.py`
- `backend/schemas/attachment.py` (新設)
- `backend/routers/attachment.py` (新設)
- `backend/main.py`
- `backend/services/qdrant_service.py`
- `backend/schemas/retrieval.py`
- `backend/routers/retrieval.py`
- `backend/routers/rag.py`
- `frontend/src/services/attachmentService.js` (新設)
- `frontend/src/services/retrievalService.js`
- `frontend/src/stores/paramsStore.js`
- `frontend/src/stores/chatStore.js`
- `frontend/src/components/embedding/AttachmentManagerTab.vue` (新設)
- `frontend/src/components/embedding/VectorManagementTab.vue`
- `frontend/src/components/params/RagParamsPanel.vue`
- `frontend/src/components/chat/MessageBubble.vue`

## 2026-07-06 RAG 對話「參考文檔引用」面板新增每個 Chunk 的 Token 數與總計/分批次數顯示

### 功能描述
在既有的 Map-Reduce 分批摘要機制（見下一則紀錄）基礎上，讓使用者可以在前端直接看到本次檢索的 token 使用狀況：
1. 每個 chunk 卡片新增 `Tokens: N` 徽章，顯示該段落原始內容的 token 數。
2. 清單最上方新增統計列：顯示所有 chunk 的 Token 總計，以及是否觸發了分批摘要——觸發時顯示「切分 N 次整理 / M 輪思考」，未觸發則顯示「未超過門檻，未進行分批摘要」。

### 實作內容
1. `backend/routers/rag.py`：一般檢索與 `semantic_db_query` 兩種來源的 `sources.append(...)` 都新增 `token_count`（`utils.token_counter.count_tokens`）；新增 `context_summary` dict（`total_tokens`/`batch_count`/`rounds`/`was_summarized`/`threshold_tokens`），隨最終 `event: sources` 事件一併送出。
2. `backend/services/context_summarizer_service.py`：`maybe_summarize()` 記錄 `result["rounds"]`（遞迴中最後到達的輪數）與累加 `result["batch_count"]`（各輪 Map 分組數總和）。
3. `frontend/src/stores/chatStore.js`：`sources` 事件同時存入 `msg.contextSummary`。
4. `frontend/src/components/chat/MessageBubble.vue` / `SourceChunks.vue`：新增 `contextSummary` prop 並在 Chunks 清單上方顯示統計列，每個 chunk 項目新增 Token 數徽章。

### 對應規劃文件
對應 `docs/DevelopmentProcess/ContextMapReduceSummaryPlan.md` 第 11 節。

## 2026-07-06 實作 Map-Reduce 檢索上下文分批摘要機制，防止超長檢索內容造成 LLM 呼叫失敗

### 功能描述
當 RAG 檢索召回的參考資料總 Token 數過長時，直接送入主模型容易超出上下文長度限制（或觸發 HTTP 400 錯誤）。本功能實作了 Map-Reduce 分批摘要機制：
1. **觸發與門檻**：使用者可在前端檢索設定面板手動調整「分批摘要門檻 (Context Summarize Threshold, tokens)」（預設為 50,000 tokens）。
2. **Bin-Packing 分組**：使用不拆散任何檢索片段的 Bin-Packing 演算法，將檢索區塊依序累加分組。
3. **Map 階段（分批整理）**：依區塊類型套用專屬的摘要提示詞（文件段落保留來源檔名/段落編號標記；資料庫查詢結果則保留表格/欄位上下文），呼叫 LLM 對各分組進行重點整理。
4. **Reduce 階段（遞迴合併）**：當分批摘要結果仍大於門檻時，遞迴再次進入 Map 處理；當低於門檻且多於 1 份時，呼叫 LLM 進行最終合併，直至合一。設有最大輪數限制（預設 3 輪）避免無窮遞迴。
5. **動態 SSE 顯示**：整個 Map-Reduce 過程的每一步驟都會動態向前端推送 SSE `event: step` 狀態（例如 `context_summarize_r1_batch_1`），並支援展開查看原始內容與整理結果。

### 實作內容
1. **環境與 Docker 準備**：`backend/requirements.txt` 新增 `tiktoken`，並在 `backend/Dockerfile` 中配置 `TIKTOKEN_CACHE_DIR` 以在 Docker 建置時預載 `cl100k_base` 模型的編碼快取，實現離線環境下的精準 Token 計算。
2. **Token 計算工具**：新增 `backend/utils/token_counter.py`，封裝 `count_tokens` 以獲取精確的 tiktoken token 數。
3. **後端設定變更**：`backend/config.py` 增加 `DEFAULT_CONTEXT_SUMMARIZE_THRESHOLD_TOKENS` (50,000) 與 `CONTEXT_SUMMARIZE_MAX_ROUNDS` (3) 全域設定值。
4. **核心摘要服務**：建立 `backend/services/context_summarizer_service.py` 核心類別，提供 Bin-Packing 分組、Map/Reduce 專屬 Prompt 構建、串流進度 `yield` 輸出與遞迴 maybe_summarize 控制。
5. **RAG 路由整合**：修改 `backend/routers/rag.py` 的 `ChatParams` 模型，加入可覆寫的 `context_summarize_trigger_tokens` 欄位；在 `rag_chat_stream()` 內，於檢索完成後、主模型推理思考前，調用 `ContextSummarizerService.maybe_summarize` 執行分批摘要並將進度 SSE 串流推送給前端。
6. **前端 Store 擴充**：
   - 修改 `frontend/src/stores/paramsStore.js` 新增 `contextSummarizeThreshold` 參數。
   - 修改 `frontend/src/stores/chatStore.js`，將 `steps` 的建立改為所有查詢模式下無條件初始化；發送 API 請求時夾帶 `context_summarize_trigger_tokens`；SSE 接收步驟事件時支援動態插入未知 step 項目，確保摘要步驟能被流暢展開與更新。
7. **前端 UI 更新**：修改 `frontend/src/components/params/RagParamsPanel.vue`，在檢索設定區域中新增門檻自訂欄位與引導說明。

### 修改檔案
- `backend/requirements.txt`
- `backend/Dockerfile`
- `backend/utils/token_counter.py` (新設)
- `backend/config.py`
- `backend/services/context_summarizer_service.py` (新設)
- `backend/routers/rag.py`
- `frontend/src/stores/paramsStore.js`
- `frontend/src/stores/chatStore.js`
- `frontend/src/components/params/RagParamsPanel.vue`

## 2026-07-03 語義資料庫查詢法新增「必定查詢」設定檔標記，作為問題語意不明確時的兜底機制

### 功能描述
實測發現：當使用者問題與任何查詢設定檔都無明顯語意關聯時（例如問「Tiptop相關資訊」，但目前設定檔都是知識庫文章/附件用途），AI 依語意判斷會回傳「與任何設定檔都無關」，導致直接查無設定檔而不查詢。但某些設定檔（例如通用文章庫）用途夠廣泛，即使 AI 判斷不出明確關聯，仍值得嘗試查詢一次。新增「必定查詢」標記：使用者可在建立/編輯查詢設定檔時勾選此選項，勾選後不論 AI 的語意選擇結果為何，此設定檔都會被強制加入候選查詢清單。

### 實作內容
1. `backend/models/db_query_profile.py`：`DBQueryProfile` 新增 `is_default: bool = False` 欄位。
2. `backend/schemas/ai_db_query.py`：`DBQueryProfileCreate`/`DBQueryProfileResponse` 新增 `is_default` 欄位。
3. `backend/services/qdrant_service.py`：`upsert_db_query_profile()` 新增 `is_default` 參數，寫入 Qdrant payload（新增 `is_default` key）。
4. `backend/routers/ai_db_query.py`：建立/更新設定檔時讀取並傳遞 `is_default` 至 MongoDB 與 Qdrant。
5. `backend/services/ai_db_query_service.py`：`match_profiles()` 於取得 AI 選擇結果後，額外將目錄中標記 `is_default=True` 且未被選中的設定檔強制加入候選清單最前面，並於 `selection_reason` 註明是被強制加入；即使 AI 判斷「與任何設定檔都無關」，只要有設定檔標記為必定查詢，仍會產生候選並繼續執行查詢，不會直接判定查無設定檔。
6. `frontend/src/components/embedding/DBQueryProfileManager.vue`：新增「設為必定查詢設定檔」checkbox（建立/編輯表單），已建立的設定檔清單於標記為必定查詢者旁顯示「必定查詢」徽章。

### 修改檔案
- `backend/models/db_query_profile.py`
- `backend/schemas/ai_db_query.py`
- `backend/services/qdrant_service.py`
- `backend/routers/ai_db_query.py`
- `backend/services/ai_db_query_service.py`
- `frontend/src/components/embedding/DBQueryProfileManager.vue`

## 2026-07-03 語義資料庫查詢法改為「先提供完整設定檔清單，由 AI 直接判斷選用哪幾個」取代向量相似度門檻篩選

### 功能描述
延續同日「不限定知識庫」多設定檔合併查詢的調整，使用者實測後回報：即使已支援多設定檔合併，實際結果仍只選到 1 個設定檔（例如問題同時涉及「附件」與「文章」，卻只查了附件表），原因是向量相似度門檻/排序本質上是個粗略的量化篩選機制，容易讓語意上明顯相關但分數略低的設定檔被排除。使用者建議「在使用語義 AI 之前，先提供目前有的設定檔給語義 AI，讓語義 AI 自己判斷使用哪幾個」。
本次採納此建議，將設定檔選擇機制從「向量相似度門檻/Top-K 排序」改為「先列出目前所有查詢設定檔的完整清單（名稱/表格/用途），交給地端 Instruct AI 直接依問題語意判斷需要用到哪幾個設定檔（可複選、可 0 個）」，從根本上避免量化門檻造成的漏選問題。

### 實作內容
1. `backend/services/ai_db_query_service.py`：
   - 移除 `_rewrite_question_for_profile_match()`（向量檢索用的問題重寫，不再需要）。
   - 新增 `_select_relevant_profiles_from_catalog()`：把候選範圍內（指定知識庫或全部知識庫）的 `DBQueryProfile` 完整清單提供給 Instruct AI，要求以 JSON 回傳 `selected_profile_ids`（可複選）與 `reason`（選擇理由），防幻想規則要求只能選清單中確實存在的 id。
   - `match_profiles()` 改為直接從 MongoDB 撈取候選範圍內的 `DBQueryProfile` 清單（不再呼叫 `QdrantService.search_db_query_profiles()`），依 AI 選擇結果組裝候選清單（`score` 欄位改為依 AI 回傳順序的遞減示意分數，非向量相似度）。
2. `backend/schemas/ai_db_query.py`、`backend/routers/ai_db_query.py`：`MatchProfilesResponse.embeddings_input` 更名為 `selection_reason`（欄位語意已改變，不再是向量檢索輸入文字，而是 AI 的選擇理由）。
3. `backend/routers/rag.py`：語義分析步驟顯示的結構化 JSON 改為 `{"original_question", "scope", "selected_profiles", "selection_reason"}`，取代原本的 `embeddings_input`。
4. Profile 向量寫入機制（`QdrantService.upsert_db_query_profile()`／建立與更新設定檔時寫入 Qdrant）維持不變（仍可供向量管理頁面檢視、未來可能的擴充使用），僅選擇邏輯不再讀取這些向量；`QdrantService.search_db_query_profiles()` 暫時保留但未被呼叫。

### 修改檔案
- `backend/services/ai_db_query_service.py`
- `backend/schemas/ai_db_query.py`
- `backend/routers/ai_db_query.py`
- `backend/routers/rag.py`
- `docs/DevelopmentProcess/SemanticDatabaseQueryPlan.md`（補充架構異動說明）

## 2026-07-03 語義資料庫查詢法「不限定知識庫」模式支援自動執行多個候選設定檔並合併結果

### 功能描述
實測發現「不限定知識庫」模式原本只會自動選擇分數最高的**單一**候選設定檔執行查詢，當使用者問題同時橫跨多張表格/設定檔時（例如同時問到「附件」與「文章」，分屬 attachments/articles 兩個查詢設定檔），只查了其中一個表格，導致漏答。改為依分數排序依序執行前 N 個（預設 3 個，`AI_DB_QUERY_MAX_PROFILES_PER_QUERY`）候選設定檔，各自產生 SQL 並查詢後合併結果再交給主模型總結；僅有 1 個候選時行為不變。此變更僅影響「不限定知識庫」的自動選取路徑，指定知識庫時使用者手動選擇單一候選的既有兩段式流程不受影響。

### 實作內容
1. `backend/config.py`：新增 `AI_DB_QUERY_MAX_PROFILES_PER_QUERY`（預設 3）。
2. `backend/routers/rag.py`：`_run_execute()` 改為累加 `context_str`/`sources`（而非覆寫），使其可被呼叫多次；`_run_semantic_db_query()` 的 `global_scan` 分支改為依序對前 N 個候選呼叫 `_run_execute()`。
3. `frontend/src/views/RetrievalTestView.vue`：`dbQueryResult`（單一物件）改為 `dbQueryResults`（陣列），「不限定知識庫」時對前 3 個候選依序呼叫執行並合併顯示每個設定檔各自的 SQL 與查詢結果。

### 修改檔案
- `backend/config.py`
- `backend/routers/rag.py`
- `frontend/src/views/RetrievalTestView.vue`

## 2026-07-03 語義資料庫查詢法新增「不限定知識庫」跨知識庫自動掃描模式

### 功能描述
延續同日新增的「語義資料庫查詢法」，補上使用者的追加需求：允許不預先指定目標知識庫，改由 AI 掃描**所有**知識庫的查詢設定檔並自動判斷要用哪一個。因為此模式沒有預設範圍可供使用者判斷取捨，決定採「直接自動選分數最高的候選」而非列出候選讓使用者選（與指定知識庫時的既有兩段式選取流程並存，兩者依是否指定知識庫自動切換，互不影響）。

### 實作內容
1. **後端**：
   - `backend/services/ai_db_query_service.py`：`AIDBQueryService.match_profiles()` 的 `knowledge_base_id` 改為選填；未提供時改為列舉所有 `KnowledgeBase`，逐一呼叫 `QdrantService.search_db_query_profiles()` 後合併排序，取全域分數最高的候選清單。
   - `backend/schemas/ai_db_query.py`：`MatchProfilesRequest.knowledge_base_id` 改為 `Optional[str]`。
   - `backend/routers/rag.py`：`_run_semantic_db_query()` 移除「必須指定知識庫」的硬性檢查；新增 `global_scan` 判斷，若未指定知識庫且找到候選，直接自動選分數最高者並繼續執行 SQL（不送出 `profile_candidates` 事件、不中斷等待選擇），語義分析的 JSON 內容一併標註 `scope`（"所有知識庫（不限定）" 或 "指定知識庫"）供使用者辨識目前是哪種模式。
2. **前端**：
   - `frontend/src/stores/paramsStore.js`：新增 `dbQueryAutoKb` 狀態。
   - `frontend/src/components/params/RagParamsPanel.vue`、`frontend/src/views/RetrievalTestView.vue`：語義資料庫查詢法參數區新增「不限定知識庫」checkbox。
   - `frontend/src/stores/chatStore.js`：勾選後對話請求改送 `knowledge_base_id: null`。
   - `frontend/src/views/RetrievalTestView.vue` 的 `handleSemanticDbQuerySearch()`：勾選後不顯示候選選取 UI，取得候選清單後直接呼叫 `handleSelectDbProfile()` 自動執行分數最高者。

### 修改檔案
- `backend/services/ai_db_query_service.py`
- `backend/schemas/ai_db_query.py`
- `backend/routers/rag.py`
- `frontend/src/stores/paramsStore.js`
- `frontend/src/components/params/RagParamsPanel.vue`
- `frontend/src/views/RetrievalTestView.vue`
- `frontend/src/stores/chatStore.js`

## 2026-07-03 新增「語義資料庫查詢法」，讓 AI 自動判斷資料庫查詢設定檔、產生 SQL 並查詢既有關聯式資料庫

### 功能描述
新增一種全新的檢索模式 `semantic_db_query`（語義資料庫查詢法），使用者可先在「資料庫匯入向量化」頁面建立「查詢設定檔」（描述某個資料庫連線下某張表格與各欄位的用途），系統會將設定檔組成自然語言描述並向量化。之後在 RAG 對話測試、向量搜尋測試、準確度評估中選擇此查詢法時，AI 會先語義理解問題、比對出候選查詢設定檔（列出讓使用者選取，而非自動猜測），使用者選定後才由地端 Instruct AI 產生唯讀 SQL、執行查詢（套用筆數/字數上限與逐欄位截斷），最後把查詢結果交給主模型（vLLM）統整成答案。全程完全新增，不修改既有 `vector`/`hybrid`/`semantic_hybrid`/`semantic_hybrid_feedback` 四種查詢法與既有「資料庫匯入向量化」（DB → 向量長期存放）功能的任何行為。詳細規劃見 `docs/DevelopmentProcess/SemanticDatabaseQueryPlan.md`。

### 實作內容
1. **查詢設定檔資料模型與向量儲存**：
   - 新增 `backend/models/db_query_profile.py`：`DBQueryProfile` Document（含 `database_config_id`/`knowledge_base_id`/`table_name`/`columns`（每欄位可選填 `max_length` 截斷長度）/`composed_description`/`qdrant_point_id`），已註冊進 `backend/models/mongodb.py` 的 `document_models`。
   - Profile 向量依使用者需求存進**選定 KnowledgeBase 的既有 Qdrant collection**（而非獨立 collection），payload 新增 `source: "db_query_profile"`。為避免混入既有文件檢索結果，修改 `backend/services/qdrant_service.py` 的 `search_similar()`/`search_similar_two_step()`，加上一條**加法式** `must_not: source == "db_query_profile"` 過濾條件——既有資料從未出現此值，對既有四種查詢法零行為影響。另新增獨立方法 `upsert_db_query_profile()`/`delete_db_query_profile_point()`/`search_db_query_profiles()`，不共用、不修改既有 `upsert_chunks`/`search_similar` 方法本體。
2. **核心查詢流程 Service**：
   - 新增 `backend/services/ai_db_query_service.py`：`AIDBQueryService.match_profiles()`（語義理解 + Profile 向量比對，回傳候選清單供使用者選取，找不到候選時明確回報而非亂猜）、`AIDBQueryService.execute()`（依選定設定檔讓 Instruct AI 產生唯讀 SQL、重用 `database_indexing.py` 既有的 `validate_sql_query()`/`get_db_connection()`、套用筆數/字數上限與逐欄位自訂截斷、將結果文字化）。任一階段失敗皆拋出 `AIDBQueryError` 附明確原因，不靜默降級。
3. **新 API Router**：
   - 新增 `backend/routers/ai_db_query.py`（`/api/ai-db-query`）：查詢設定檔 CRUD、`list-tables`/`list-columns`（純 schema 探索，供前端下拉選單）、兩段式查詢執行 `match-profiles`/`execute`。已掛載至 `backend/main.py`。
   - 新增 `backend/schemas/ai_db_query.py`。
4. **設定值**：
   - 修改 `backend/config.py`：新增 `AI_DB_QUERY_MAX_ROWS`（預設 50）、`AI_DB_QUERY_MAX_CHARS`（預設 4000）、`AI_DB_QUERY_PROFILE_SCORE_THRESHOLD`（預設 0.5）。
5. **三處測試頁面整合（加法式，不改既有分支邏輯）**：
   - 修改 `backend/routers/rag.py`：新增 `_run_semantic_db_query()` 分支，`search_type == "semantic_db_query"` 時走此流程。採兩階段 SSE 串流——第一次請求僅回傳候選設定檔清單（新增 SSE `step: "profile_candidates"`）後即結束串流；使用者選定後帶 `selected_db_profile_id` 重新呼叫同一端點才繼續產生 SQL、查詢、交給主模型總結。
   - 修改 `backend/routers/evaluation.py` 與 `backend/models/eval_report.py`：批次評估流程無真人可選候選，自動取分數最高候選（Top-1）執行，新增 `EvalDetail.db_query_note` 欄位標記「自動選取、非人工確認」或失敗原因。
   - 檢索測試頁不經過 `/api/retrieval/search`，前端直接呼叫 `ai_db_query` router 的 `match-profiles`/`execute`（回應格式與一般 chunk 檢索不同）。
6. **前端：新增查詢設定檔管理 UI**：
   - 新增 `frontend/src/services/aiDbQueryService.js`。
   - 新增 `frontend/src/components/embedding/DBQueryProfileManager.vue`：可選取資料庫連線設定檔、表格（呼叫 `list-tables`）、欄位（呼叫 `list-columns`，可設定啟用/意義/截斷長度），即時預覽自動組合的自然語言描述，並列出/編輯/刪除現有設定檔。
   - 修改 `frontend/src/components/embedding/DatabaseIndexingTab.vue`：新增子模式切換（① 將資料庫內容轉向量【既有功能不動】／② AI 查詢設定檔【新增】），既有向量化流程完整保留於 `v-else` 區塊。
7. **前端：三處測試頁面新增查詢法選項**：
   - 修改 `frontend/src/components/params/RagParamsPanel.vue`、`frontend/src/views/RetrievalTestView.vue`、`frontend/src/components/eval/TestSetManager.vue`：新增「語義資料庫查詢法 (Semantic DB Query)」選項，並提供筆數/字數上限輸入框（`frontend/src/stores/paramsStore.js` 新增 `dbQueryMaxRows`/`dbQueryMaxChars`）。
   - `RetrievalTestView.vue` 新增候選設定檔選取 UI 與 SQL/查詢結果顯示區塊（`handleSemanticDbQuerySearch()`/`handleSelectDbProfile()`）。
   - 修改 `frontend/src/stores/chatStore.js`：抽出共用的 `_streamChat()`，新增 `selectDbQueryProfile()` action 供使用者選定候選後沿用同一則 assistant 訊息繼續串流；`step` 事件新增對 `profile_candidates` 的處理。
   - 修改 `frontend/src/components/chat/MessageBubble.vue`/`ChatWindow.vue`：新增候選查詢設定檔選取區塊與 `select-db-profile` 事件轉發。
   - 修改 `frontend/src/views/EvaluationView.vue`：評估明細列表新增 `db_query_note` 顯示。
8. **文件同步**：更新 `docs/03_API_CONTRACT.md`（新增第 13 節）、`docs/04_DB_SCHEMA.md`（新增 `db_query_profiles` collection 與 `source` 欄位新值說明）。

### 修改檔案
- `backend/models/db_query_profile.py`（新增）
- `backend/models/mongodb.py`
- `backend/models/eval_report.py`
- `backend/schemas/ai_db_query.py`（新增）
- `backend/services/ai_db_query_service.py`（新增）
- `backend/services/qdrant_service.py`
- `backend/routers/ai_db_query.py`（新增）
- `backend/routers/rag.py`
- `backend/routers/evaluation.py`
- `backend/config.py`
- `backend/main.py`
- `frontend/src/services/aiDbQueryService.js`（新增）
- `frontend/src/components/embedding/DBQueryProfileManager.vue`（新增）
- `frontend/src/components/embedding/DatabaseIndexingTab.vue`
- `frontend/src/components/params/RagParamsPanel.vue`
- `frontend/src/views/RetrievalTestView.vue`
- `frontend/src/components/eval/TestSetManager.vue`
- `frontend/src/stores/paramsStore.js`
- `frontend/src/stores/chatStore.js`
- `frontend/src/components/chat/MessageBubble.vue`
- `frontend/src/components/chat/ChatWindow.vue`
- `frontend/src/views/EvaluationView.vue`
- `docs/03_API_CONTRACT.md`
- `docs/04_DB_SCHEMA.md`
- `docs/DevelopmentProcess/SemanticDatabaseQueryPlan.md`（規劃文件，先前新增）

## 2026-07-02 新增可切換的本地 Embedding API 風格，支援居家 Ollama / LM Studio 取代地端部署

### 功能描述
為了讓使用者能在家用 Ollama、llama.cpp、LM Studio 三套本地引擎取代公司地端的 vLLM / llama.cpp 部署，補上環境變數範本，並讓 Embedding 服務可依設定切換呼叫端點與 payload 格式。對話（`VLLM_BASE_URL` + `/chat/completions`）與 Instruct 語義解析（`DenseVector_LLAMACPP_BASE_URL` + `/v1/chat/completions`）原本就已是 OpenAI 相容格式，Ollama／LM Studio 皆相容，僅需調整 `.env`；只有 Embedding 因為原本寫死呼叫 llama.cpp 原生 `/embedding` 端點，需要新增可切換的 API 風格。

### 實作內容
1. **Embedding API 風格切換**：
   - 修改 `backend/config.py`：新增 `EMBEDDING_API_STYLE`（預設 `llamacpp`，可選 `ollama`／`openai`）。
   - 修改 `backend/services/embedding_service.py`：抽出共用私有方法 `_fetch_embedding()`，依 `EMBEDDING_API_STYLE` 決定端點路徑（`/embedding` vs `/api/embeddings` vs `/v1/embeddings`）與 payload key（`content` vs `prompt` vs `input`），回應解析沿用既有的多格式彈性解析邏輯；`get_embedding()` 與 `get_semantic_embedding()` 改為呼叫共用方法，公開簽章不變，既有呼叫端零影響。
2. **環境變數範本**：
   - 新增 `backend/.env.example`：涵蓋公司地端（vLLM/llama.cpp）與居家（Ollama/LM Studio）的對話、Instruct 語義解析、Embedding 三組設定範例（後兩者以註解形式提供替代方案），並註明 docker-compose 容器需用 `host.docker.internal` 連到宿主機上執行的本地引擎。

### 修改檔案
- `backend/config.py`
- `backend/services/embedding_service.py`
- `backend/.env.example`（新增）

## 2026-07-02 新增「語義混合回饋查詢法」並補上人工回饋→檢索來源的資料鏈路

### 功能描述
補完 RPD 4.6「人工回饋與標註歷史」的資料閉環：過去 `Feedback` 只記錄問答文字，並未記錄該次回答引用了哪些檢索片段，導致回饋資料無法回頭影響檢索排序。本次新增後，標註時會一併儲存來源片段（`filename` + `chunk_index`），並新增一種檢索模式 `semantic_hybrid_feedback`（語義混合回饋查詢法），在既有語義混合（Two-Step Hybrid + Instruct 語義分析 + RRF + LLM Rerank）流程最後，依歷史人工回饋對命中片段做分數加權重排。

### 實作內容
1. **回饋資料模型擴充**：
   - 修改 `backend/models/feedback.py`：新增內嵌模型 `FeedbackSourceChunk`（`filename`/`chunk_index`），`Feedback` 新增 `source_chunks`、`knowledge_base_id` 欄位，並新增 `source_chunks.filename` 索引。
   - 修改 `backend/routers/feedback.py`：`FeedbackCreate` 新增對應欄位，`create_feedback()` 寫入時一併儲存。
2. **前端送出回饋時夾帶來源片段**：
   - 修改 `frontend/src/components/chat/ChatWindow.vue`：`openFeedbackModal()` 額外取出當次回答的 `sources`，傳給 `FeedbackPanel`。
   - 修改 `frontend/src/components/chat/FeedbackPanel.vue`：新增 `sources` prop，送出回饋時組出 `source_chunks` 與 `knowledge_base_id`（取自 `paramsStore.knowledgeBaseId`）。
3. **回饋加權服務**：
   - 新增 `backend/services/feedback_boost_service.py`：`FeedbackBoostService.apply_feedback_boost()`，依 `(filename, chunk_index)` 統計歷史回饋正確/不正確次數，`boost = (正確-不正確)/(正確+不正確)`，套用 `final_score = score × (1 + FEEDBACK_BOOST_WEIGHT × boost)` 後重新排序；任何錯誤皆優雅降級為保留原排序，比照 `RerankService` 的寫法。
   - 修改 `backend/config.py`：新增可調參數 `FEEDBACK_BOOST_WEIGHT`（預設 `0.2`）。
4. **三處檢索路由接上新 search_type**：
   - 修改 `backend/routers/retrieval.py`（`search()`、`semantic_hybrid_search()`）、`backend/routers/rag.py`（`rag_chat_stream()`）、`backend/routers/evaluation.py`（評估執行迴圈）：`search_type in ("semantic_hybrid", "semantic_hybrid_feedback")` 時走既有語義混合流程，呼叫 Qdrant 服務時固定傳字面值 `"semantic_hybrid"`（Qdrant 層完全不修改），rerank 後若為 `semantic_hybrid_feedback` 則多套用一次 `FeedbackBoostService`。`rag.py` 額外在 SSE `vector_search` step 內容附註「已套用歷史回饋加權」。
5. **前端新增檢索模式選項**：
   - 修改 `frontend/src/components/params/RagParamsPanel.vue`、`frontend/src/views/RetrievalTestView.vue`、`frontend/src/components/eval/TestSetManager.vue`：新增「語義混合回饋查詢法 (Semantic Hybrid + Feedback)」選項；`RetrievalTestView.vue` 的 `handleSearch()` 路由判斷（打哪個端點、是否顯示語義分析步驟 UI）一併涵蓋新選項。

### 修改檔案
- `backend/models/feedback.py`
- `backend/routers/feedback.py`
- `backend/services/feedback_boost_service.py`（新增）
- `backend/config.py`
- `backend/routers/retrieval.py`
- `backend/routers/rag.py`
- `backend/routers/evaluation.py`
- `frontend/src/components/chat/ChatWindow.vue`
- `frontend/src/components/chat/FeedbackPanel.vue`
- `frontend/src/components/params/RagParamsPanel.vue`
- `frontend/src/views/RetrievalTestView.vue`
- `frontend/src/components/eval/TestSetManager.vue`

## 2026-07-01 向量管理頁面新增關聯檔案 (links_to) 管理與顯示功能

### 功能描述
在向量管理頁面中，點選主要檔案後可額外選取多個關聯檔案，並批次寫入對應點位的 `links_to` 欄位中，以便支援雙階段檢索（Two-Step Hybrid Retrieval），同時在段落列表上顯示關聯檔案徽章。

### 實作內容
1. **後端 Qdrant 批次更新**：
   - 修改 `backend/services/qdrant_service.py`：新增 `update_links_to_by_filename` 類別方法，利用 Scroll API 拉取該檔案所有 Chunks 的 Point ID，再呼叫 `set_payload` API 批次更新這些點位的 `links_to` 欄位。
2. **後端 API 路由與 Schema**：
   - 修改 `backend/schemas/retrieval.py`：新增 `UpdateLinksRequest` 模型。
   - 修改 `backend/routers/retrieval.py`：新增 `/knowledge-bases/{knowledge_base_id}/files/update-links` POST 端點。
3. **前端 API 與 UI 串接**：
   - 修改 `frontend/src/services/retrievalService.js`：新增 `updateLinks` 方法調用。
   - 修改 `frontend/src/components/embedding/VectorManagementTab.vue`：
     - 新增多選關聯檔案編輯區（Links To），自動從 Metadata 中讀取並同步既有之關聯檔案關係。
     - 在 Chunks 列表上為具備 `links_to` 的 Chunk 繪製藍色關聯徽章。

### 修改檔案
- `backend/services/qdrant_service.py`
- `backend/schemas/retrieval.py`
- `backend/routers/retrieval.py`
- `frontend/src/services/retrievalService.js`
- `frontend/src/components/embedding/VectorManagementTab.vue`

## 2026-07-01 新增雙階段關聯檢索與防幻想語意分析層系統

### 功能描述
實作具備 Graph RAG 概念的「雙階段關聯檢索」與「防幻想語意分析層」系統，優化語意混合檢索的上下文命中率與抗幻想能力。

### 實作內容
1. **語意分析層 (Query Rewriter) Prompt 優化**：
   - 修改 `backend/services/embedding_service.py`：在 `query_to_semantic_json` 的 System Prompt 中加入嚴格的反幻想限制宣告，並提供對比鮮明的 3 個 Few-Shot 範例（Good/Bad），使重寫後的 `embeddings_input` 與 `sparse_keywords` 專注於核心實體檢索特徵，避免模型擅自腦補背景。
2. **Qdrant Indexing / Payload 關聯欄位擴充**：
   - 修改 `backend/services/qdrant_service.py` (`upsert_semantic_json_chunks`) 與 `backend/routers/embedding.py` (`/vectorize` 路由)：寫入 Qdrant 點位時，手動在 Payload 中寫入 `links_to` (關聯檔案名稱或自訂 Point ID) 與 `class` 清單。
3. **雙階段檢索機制 (Two-Step Hybrid Retrieval) 實作**：
   - 修改 `backend/services/qdrant_service.py`：新增 `search_similar_two_step` 類別方法。第一階段呼叫 `search_similar` 取得 core point；第二階段提取點位的 `links_to` 陣列，使用 Qdrant Scroll API 拉取這些關聯的一階鄰居點位 (2nd-hop Search)。最後對鄰居點位執行 parent_id 合併還原，並與 core points 合併進行嚴格的內容 `.strip()` 去重後回傳。
4. **API 與 RAG 流程整合**：
   - 修改 `backend/schemas/retrieval.py`：在 `RetrievalMetadata` 中新增 `links_to` 欄位。
   - 修改 `backend/routers/rag.py` 的對話串流與 `backend/routers/retrieval.py` 的 `/search`、`/semantic-hybrid-search` 路由，當啟用語義混合查詢 (`search_type == "semantic_hybrid"`) 時，調用 `search_similar_two_step` 取代原本的一階段 hybrid 檢索，並將關聯欄位輸出。
5. **單元測試建立**：
   - 新增 `tests/test_two_step_search.py` 測試檔案，對雙階段檢索進行 Mock 測試，模擬無 link、有 link 及重複內容去重的各種檢索情境，確保功能完整性。

### 修改檔案
- `backend/services/embedding_service.py`
- `backend/services/qdrant_service.py`
- `backend/routers/embedding.py`
- `backend/routers/rag.py`
- `backend/routers/retrieval.py`
- `backend/schemas/retrieval.py`
- `tests/test_two_step_search.py` (新設)

## 2026-07-07 新增文件內嵌圖片擷取、多模態描述生成與向量檢索功能

### 功能描述
實作 Word (docx/dotx) 與 PDF 文件上傳時自動擷取內嵌圖片、呼叫 vLLM 主模型（`Qwen3.6-35B-A3B-FP8`，非地端 llama.cpp Instruct 模型，因其目前已換成無視覺能力的 `qwen2.5-coder-7b-instruct-q8_0.gguf`）生成圖片語意描述，並將其轉化為圖片 Chunk 寫入向量庫 Qdrant。在對話檢索與引用中，若命中圖片 Chunk，前端能直接呈現圖片縮圖並提供下載功能。詳細規劃與 2026-07-07 程式碼複查發現的問題見 `docs/DevelopmentProcess/DocumentImageEmbeddingPlan.md`。

### 實作內容
1. **圖片子目錄與配置擴充**：
   - 修改 `backend/config.py`：新增 `FILE_ATTACHMENTS_IMAGE_SUBDIR`（預設 `"image"`），實際圖片目錄為 `FILE_ATTACHMENTS_DIR`（`backend/FileAttachments/`）下的 `image/` 子目錄，即 `backend/FileAttachments/image/`。
2. **圖片抽取與描述生成服務**：
   - 修改 `backend/services/document_parser.py`：新增靜態方法 `extract_images_from_pdf`（基於 `PyMuPDF` 的 `page.get_images`/`extract_image`）與 `extract_images_from_docx`（基於 `python-docx` 走訪段落中的 `w:drawing`/VML `v:imagedata`，透過 `doc.part.related_parts` 取出圖片二進位資料，非直接讀取 ZIP 檔）。
   - 修改 `backend/services/llm_service.py`：新增 `describe_image` 方法，將圖片轉為 Base64 後以 OpenAI 相容的多模態訊息格式呼叫 vLLM `chat_completion`（`settings.VLLM_MODEL`）進行語意分析與中文描述生成。
3. **API 路由器與 Schema 實作**：
   - 修改 `backend/schemas/embedding.py`：定義 `ExtractedImageItem`，擴充 `UploadResponse` 與 `ChunkRequest` 欄位以傳遞圖片資訊。
   - 修改 `backend/routers/embedding.py`：
     - 擴充 `/upload` 路由，支援 `extract_images` 參數。
     - 擴充 `/chunk` 路由，支援接收 `images` 並將其轉化為 `chunk_type: "image"` 的 Chunk 點位。
     - 新增 `/images/{stored_filename}` 路由，將擷取的圖片傳送給前端顯示。
   - 修改 `backend/routers/rag.py`：擴充檢索結果來源 Chunks 的 metadata，向前端透傳 `chunk_type` 與 `image_filename`。
4. **前端 API 與 UI 整合**：
   - 新增 `frontend/src/services/imageService.js`：提供圖片下載輔助方法。
   - 修改 `frontend/src/services/embeddingService.js`：擴充 `uploadFile` 新增 `extractImages` 參數。
   - 修改 `frontend/src/components/embedding/FileUploader.vue`：接受並透傳 `extractImages` 屬性。
   - 修改 `frontend/src/components/embedding/SingleIndexingTab.vue`：新增自動擷取勾選項目與已擷取圖片的預覽/下載 Grid 畫廊。
   - 修改 `frontend/src/components/embedding/BatchIndexingTab.vue`：在 PDF/Word 分流設定區塊下新增自動擷取勾選框，並於批次佇列上傳時透傳。
   - 修改 `frontend/src/components/chat/SourceChunks.vue`：在引用列表中為圖片加上 🖼 標記，並在 Hover 提示框中顯示縮圖與下載按鈕。
   - 修改 `frontend/src/components/chat/MessageBubble.vue`：在 AI 訊息框下方新增「相關參考圖片」畫廊，直接顯示所有命中的圖片與描述。

### 修改檔案
- `backend/config.py`
- `backend/services/document_parser.py`
- `backend/services/llm_service.py`
- `backend/schemas/embedding.py`
- `backend/routers/embedding.py`
- `backend/routers/rag.py`
- `frontend/src/services/imageService.js` (新增)
- `frontend/src/services/embeddingService.js`
- `frontend/src/components/embedding/FileUploader.vue`
- `frontend/src/components/embedding/SingleIndexingTab.vue`
- `frontend/src/components/embedding/BatchIndexingTab.vue`
- `frontend/src/components/chat/SourceChunks.vue`
- `frontend/src/components/chat/MessageBubble.vue`



## 2026-07-01 新增雙階段關聯檢索與防幻想語意分析層系統

### 功能描述
實作具備 Graph RAG 概念的「雙階段關聯檢索」與「防幻想語意分析層」系統，優化語意混合檢索的上下文命中率與抗幻想能力。

### 實作內容
1. **語意分析層 (Query Rewriter) Prompt 優化**：
   - 修改 `backend/services/embedding_service.py`：在 `query_to_semantic_json` 的 System Prompt 中加入嚴格的反幻想限制宣告，並提供對比鮮明的 3 個 Few-Shot 範例（Good/Bad），使重寫後的 `embeddings_input` 與 `sparse_keywords` 專注於核心實體檢索特徵，避免模型擅自腦補背景。
2. **Qdrant Indexing / Payload 關聯欄位擴充**：
   - 修改 `backend/services/qdrant_service.py` (`upsert_semantic_json_chunks`) 與 `backend/routers/embedding.py` (`/vectorize` 路由)：寫入 Qdrant 點位時，手動在 Payload 中寫入 `links_to` (關聯檔案名稱或自訂 Point ID) 與 `class` 清單。
3. **雙階段檢索機制 (Two-Step Hybrid Retrieval) 實作**：
   - 修改 `backend/services/qdrant_service.py`：新增 `search_similar_two_step` 類別方法。第一階段呼叫 `search_similar` 取得 core point；第二階段提取點位的 `links_to` 陣列，使用 Qdrant Scroll API 拉取這些關聯的一階鄰居點位 (2nd-hop Search)。最後對鄰居點位執行 parent_id 合併還原，並與 core points 合併進行嚴格的內容 `.strip()` 去重後回傳。
4. **API 與 RAG 流程整合**：
   - 修改 `backend/schemas/retrieval.py`：在 `RetrievalMetadata` 中新增 `links_to` 欄位。
   - 修改 `backend/routers/rag.py` 的對話串流與 `backend/routers/retrieval.py` 的 `/search`、`/semantic-hybrid-search` 路由，當啟用語義混合查詢 (`search_type == "semantic_hybrid"`) 時，調用 `search_similar_two_step` 取代原本的一階段 hybrid 檢索，並將關聯欄位輸出。
5. **單元測試建立**：
   - 新增 `tests/test_two_step_search.py` 測試檔案，對雙階段檢索進行 Mock 測試，模擬無 link、有 link 及重複內容去重的各種檢索情境，確保功能完整性。

### 修改檔案
- `backend/services/embedding_service.py`
- `backend/services/qdrant_service.py`
- `backend/routers/embedding.py`
- `backend/routers/rag.py`
- `backend/routers/retrieval.py`
- `backend/schemas/retrieval.py`
- `tests/test_two_step_search.py` (新設)

## 2026-06-30 新增語義混合查詢（Semantic Hybrid Search）提問先轉 JSON 與前端按鈕整合

### 功能描述
實作了當執行「語義混合查詢（semantic_hybrid）」時，將原始提問先發送給 Instruct 語義化 AI（Qwen3VL-8B-Instruct）轉換為語義結構化 JSON，再提取其 embeddings_input 與 sparse_keywords 生成密集/稀疏向量，並與前端對話視窗上方的「語義混合查詢」按鈕整合。

### 實作內容
1. **後端問答語義分析轉 JSON 方法**：
   - 於 `backend/services/embedding_service.py` 實作 `query_to_semantic_json` 類別方法，傳送 `question` 至地端 AI 服務的 `/v1/chat/completions`，格式化為包含 `embeddings_input` 與 `sparse_keywords` 的 JSON。
2. **後端 RAG 串流檢索語義化**：
   - 於 `backend/routers/rag.py` 中，當 `search_type` 為 `"semantic_hybrid"` 時，發送 `semantic_analysis` SSE 進度，調用 `query_to_semantic_json` 取得結構化 JSON，並於 UI 中以代碼區塊顯式渲染該 JSON。
   - 將轉換後的 `embeddings_input` 用於 `get_semantic_embedding` 密集向量生成，將 `sparse_keywords` 拼接成文字用於 `FastEmbed` 稀疏向量生成與檢索。
3. **前端查詢模式切換按鈕**：
   - 於 `frontend/src/components/chat/ChatWindow.vue` 對話頂部 Header 新增「語義混合查詢」按鈕，使使用者能快速在 `vector`、`hybrid` 與 `semantic_hybrid` 之間切換。

### 修改檔案
- `backend/services/embedding_service.py` (修改)
- `backend/routers/rag.py` (修改)
- `frontend/src/components/chat/ChatWindow.vue` (修改)

## 2026-06-30 新增地端多模態 AI 語義擷取與向量資料庫語義混合查詢 (Semantic Hybrid Search) 功能
### 功能描述
規劃並實作了地端多模態 AI 語義處理管線與混合檢索系統。可解析由地端多模態 AI（Qwen3VL-8B-Instruct）生成之結構化 JSON，自動呼叫專門的語義化 AI 模組生成密集向量（Dense Vector），同時結合關鍵字稀疏向量（Sparse Vector），寫入具有自動向量維度偵測之 Qdrant Collection，並於前後端實現語義混合搜尋（Semantic Hybrid Search）與 RRF 分數融合檢索。在 RAG 功能測試對話框中加入語義混合查詢模式，以即時步驟折疊面板（語義分析、向量資料查詢、思考中、結論）動態呈現資料管線的呼叫內容與處理詳情。

### 實作內容
1. **後端環境變數配置與語義化 AI 模組串接**：
   - 於 `backend/config.py` 中新增 `DENSE_VECTOR_LLAMACPP_BASE_URL` 與 `DENSE_VECTOR_INSTRUCT_MODEL` 設定，自訂環境變數載入。
   - 於 `backend/services/embedding_service.py` 實作 `get_semantic_embedding` 與批次取得方法 `get_semantic_embeddings_batch`，當專用服務尚未啟動時，預設回傳符合 4096 維度之模擬零向量作為降級與測試防線。
2. **Qdrant 資料庫服務維度自適應與批次寫入**：
   - 於 `backend/services/qdrant_service.py` 修改 `create_collection` 方法支援 `vector_size` 參數；實作 `upsert_semantic_json_chunks`，將 structured JSON 的 `embeddings_input` 用於密集向量生成、將 `sparse_keywords` 串接文本用於 `fastembed` 稀疏向量生成，連同 metadata 與自訂識別碼安全寫入向量資料庫，並提供稀疏向量配置降級支援。
3. **語義資料匯入與語義混合檢索端點**：
   - 於 `backend/schemas/embedding.py` 新增 `SemanticJSONItem`、`SemanticJSONIngestRequest` 與 `SemanticJSONIngestResponse` API Schema。
   - 於 `backend/routers/embedding.py` 新增 `POST /api/embedding/vectorize-json` 語義資料向量化寫入端點。
   - 於 `backend/routers/retrieval.py` 新增 `POST /api/retrieval/semantic-hybrid-search` 獨立端點，執行語義混合查詢，回傳 `text_content` 作為原始文本欄位。
4. **前端 JS 服務與語義混合檢索介面整合**：
   - 於 `frontend/src/services/embeddingService.js` 與 `retrievalService.js` 新增對應 API 端點呼叫。
   - 於 `frontend/src/views/RetrievalTestView.vue` 檢索下拉選單新增 `語義混合搜尋` 選項並連結對應 endpoint，對 RRF 分數和距離顯示進行自適應相容處理。
5. **前端 AI 語義 JSON 檔案匯入頁面**：
   - 新增 `frontend/src/components/embedding/SemanticJSONTab.vue` 提供使用者貼上 JSON 或上傳 JSON 檔案功能，提供即時格式驗證與解析欄位預覽（含 ID、語義輸入、原始內容與關鍵字氣泡），並可選擇知識庫一鍵匯入。
   - 於 `frontend/src/views/EmbeddingTestView.vue` 中將該 Tab 元件掛載並命名為「地端 AI 語義 JSON 匯入」。
6. **E2E RAG 功能測試對話框步驟視覺化**：
   - 於 `backend/routers/rag.py` 的對話串流 `/chat` 增加 SSE 狀態事件 `event: step`，在語義嵌入計算完畢、向量資料庫檢索完畢等管線節點向前端回傳處理細節（如產生之密集向量預覽、召回之文件來源及對應 RRF 相似度分數）。
   - 於 `frontend/src/components/params/RagParamsPanel.vue` 的檢索模式中加入 `語義混合查詢`。
   - 於 `frontend/src/stores/chatStore.js` 中新增 SSE step 解析與狀態跟蹤。
   - 於 `frontend/src/components/chat/MessageBubble.vue` 設計玻璃擬物化的折疊手風琴步驟元件，展示各分析與檢索步驟的即時狀態並支援點擊展開查看內容詳情。

### 修改檔案
- `backend/config.py` (修改)
- `backend/services/embedding_service.py` (修改)
- `backend/services/qdrant_service.py` (修改)
- `backend/schemas/embedding.py` (修改)
- `backend/routers/embedding.py` (修改)
- `backend/routers/retrieval.py` (修改)
- `backend/routers/rag.py` (修改)
- `frontend/src/services/embeddingService.js` (修改)
- `frontend/src/services/retrievalService.js` (修改)
- `frontend/src/components/embedding/SemanticJSONTab.vue` (新增)
- `frontend/src/views/EmbeddingTestView.vue` (修改)
- `frontend/src/components/params/RagParamsPanel.vue` (修改)
- `frontend/src/stores/chatStore.js` (修改)
- `frontend/src/components/chat/MessageBubble.vue` (修改)
- `docs/DevelopmentProcess/NewFeatures.md` (修改)��選單新增 `語義混合搜尋` 選項並連結對應 endpoint，對 RRF 分數和距離顯示進行自適應相容處理。
5. **前端 AI 語義 JSON 檔案匯入頁面**：
   - 新增 `frontend/src/components/embedding/SemanticJSONTab.vue` 提供使用者貼上 JSON 或上傳 JSON 檔案功能，提供即時格式驗證與解析欄位預覽（含 ID、語義輸入、原始內容與關鍵字氣泡），並可選擇知識庫一鍵匯入。
   - 於 `frontend/src/views/EmbeddingTestView.vue` 中將該 Tab 元件掛載並命名為「地端 AI 語義 JSON 匯入」。

### 修改檔案
- `backend/config.py` (修改)
- `backend/services/embedding_service.py` (修改)
- `backend/services/qdrant_service.py` (修改)
- `backend/schemas/embedding.py` (修改)
- `backend/routers/embedding.py` (修改)
- `backend/routers/retrieval.py` (修改)
- `frontend/src/services/embeddingService.js` (修改)
- `frontend/src/services/retrievalService.js` (修改)
- `frontend/src/components/embedding/SemanticJSONTab.vue` (新增)
- `frontend/src/views/EmbeddingTestView.vue` (修改)
- `docs/DevelopmentProcess/NewFeatures.md` (修改)

## 2026-06-30 新增 Word 文件大小雙層檢索 (Parent-Child Retriever) 語意切分與多檔批次上傳支援

### 功能描述
規劃並實作了針對 Word 文件（包含 `.docx`, `.doc`, `.dotx` 副檔名）的大小雙層（Parent-Child Retriever）語意切分策略。先將 Word 結構化轉換為 Markdown，精準提取多層級 Heading 樣式作為結構邊界，且支援清單與表格的 Markdown 格式轉換；再呼叫 Markdown 切分器生成子區塊並前置注入標題路徑進行語意增強，最後將此能力與前端多 Word 檔案佇列及後端 API 完成深度整合。

### 實作內容
1. **後端 Word 結構化解析與 Parent-Child 切分服務**：
   - 於 `backend/services/word_parent_child_chunker.py` 實作全新的 Word 區塊解析與切分服務。
   - 使用 `python-docx` 遍歷段落和表格，將 `Heading 1` ~ `Heading 3` 或帶有 outline_level 的段落映射為 `#`、`##`、`###` 標題。
   - 處理清單樣式前置 `* ` 或 `1. ` 符號，並將 Word 表格格式化為標準 Markdown 表格。
   - 針對 `.doc` 舊版 Word 檔案建立具高容錯度的轉換路徑，結合 `textract`、`pypandoc`、`comtypes`（Windows）及備用的 ASCII/非 ASCII 純文字提取器。
   - 將 Word 轉換出的 Markdown 文本丟入 `chunk_markdown_content` 進行大小雙層切分，並自動為 Child Chunks 加上標題階層前綴（例如 `[第一章 > 1.1 功能]`）與綁定 `parent_id`。
2. **後端 API /chunk 端點與分流擴充**：
   - 於 `backend/services/document_parser.py` 將 `.docx`, `.doc`, `.dotx` 解碼分流整合至 `parse_file` 中，使上傳預覽階段直接輸出 Markdown 內容。
   - 於 `backend/routers/embedding.py` 的 `/chunk` 端點中，將 `is_word` 副檔名納入雙層結構處理範圍，自動計算並在 Child Chunks Metadata 注入 `parent_chunk_index_range` 索引範圍與 `file_type`。
3. **前端批次寫入支援多 Word 檔案**：
   - 於 `frontend/src/components/embedding/BatchIndexingTab.vue` 中，將 Word 的下拉選項改為 `Word (.docx, .doc, .dotx)`。
   - 支援多 Word 副檔名上傳過濾、拖曳驗證與 MIME 類型過濾。
   - 當選取 Word 類型時，透過 watch 自動啟用 `parent_child` 切分模式，並預設帶入 `250` 字元 size 與 `50` 字元 overlap。
4. **單元測試與容器編譯驗證**：
   - 於 `backend/tests/test_word_chunker.py` 建立完整的自動化測試，模擬包含標題、內文、清單、表格的 `.docx` 文件，驗證其 Markdown 標題、清單、表格轉換、Child 標題路徑注入及 Metadata 欄位完整性，測試成功通過。
   - 完成 Docker 後端容器重建編譯並通過前端 `npm run build` 打包校正。

### 修改檔案
- `backend/services/word_parent_child_chunker.py` (新增)
- `backend/services/document_parser.py` (修改)
- `backend/routers/embedding.py` (修改)
- `frontend/src/components/embedding/BatchIndexingTab.vue` (修改)
- `backend/tests/test_word_chunker.py` (新增)

## 2026-06-30 新增 Markdown 大小雙層檢索 (Parent-Child Retriever) 語意切分工具

### 功能描述
規劃並實作了針對 Markdown (.md) 檔案的大小雙層切分（Parent-Child Retriever）檢索優化腳本。第一步精準依據 Markdown 的多層級標題（如 `#`, `##`, `###`）切分出 Parent Chunks，第二步將其內容依據字元長度切分出 Child Chunks，並自動加上該區塊所屬的完整標題路徑作為前綴以進行語意增強，方便寫入 Qdrant 或 Chroma 向量資料庫。

### 實作內容
1. **後端大小雙層切分腳本新增**：
   - 於 `backend/services/markdown_parent_child_chunker.py` 實作 Markdown 大小雙層切分工具。
   - 呼叫 `langchain_text_splitters.MarkdownHeaderTextSplitter` 與 `RecursiveCharacterTextSplitter` 進行邏輯與字元重疊切分。
   - 實作標題路徑重建與字串拼接，為 Child Chunks 前置注入 `[標題1 > 標題2]` 前綴，並妥善綁定 `parent_id`、`source_file` 與 `header_path` 等 rich metadata。
   - 在腳本的 `if __name__ == "__main__":` 區塊提供完整的單機模擬與測試功能。

### 修改檔案
- `backend/services/markdown_parent_child_chunker.py` (新增)


## 2026-06-29 新增 Genero .4fd 畫面定義檔大小雙層檢索 (Parent-Child Retriever) 解析與批次寫入支援

### 功能描述
為 Genero Studio 的 `.4fd` 畫面定義檔實作專屬的大小雙層切分（Parent-Child Retriever）檢索策略。利用 Python 內建的 `ElementTree` 函式庫以無感命名空間（Namespace-Insensitive）方式精準解析 XML 樹狀結構，將核心區塊（Layout、FormItems、BindFiles、ScreenRecords）切分為 Parent Chunks，並將其內部的元件或欄位切分為 Child Chunks，保留完整的 XML 片段與 rich metadata，並將此能力整合至前端與後端批次寫入流程中。

### 實作內容
1. **後端大小雙層切分服務擴展**：
   - 於 `backend/services/parent_child_chunker.py` 實作 `parse_4fd_to_parents` 解析 `.4fd` XML 結構，提取 `Layout`、`FormItems`、`BindFiles` 及 `ScreenRecords` 節點做為 Parent Chunks。
   - 實作 `slice_4fd_to_children` 依區塊類別遍歷內部的 `FormItem`、`Grid`、`Table` 節點或直接子節點（例如 `BindRow`、`RecordField`）作為 Child Chunks。
   - 實作 `extract_4fd_metadata` 提取子節點的所有屬性（如 `id`、`name` 等）並標準化主要識別欄位注入 rich metadata 中。
2. **API 路由相容與副檔名分流**：
   - 於 `backend/routers/embedding.py` 的 `/chunk` 路由中，將原先大小雙層判斷擴充為支援 `.4fd` 及 `.4gl` 檔案，並在執行時根據副檔名進行解析分流。
3. **CLI 單機測試腳本同步更新**：
   - 於 `scripts/parent_child_chunker.py` 整合上述 `.4fd` 切分與解析邏輯，並更新 CLI 命令列引數解析與 `process_file` 統一入口，支援直接於命令行切分 `.4fd` 檔案並導出 JSON。
4. **前端批次寫入介面支援**：
   - 於 `frontend/src/components/embedding/BatchIndexingTab.vue` 的批次寫入副檔名限制下拉選單中加入 `Genero Form (.4fd)` 選項。
   - 配置 watch 監聽，當選取 `.4fd` 時自動關聯 `parent_child` 切分模式，並代入推薦的切分參數。
5. **單元測試建立與驗證**：
   - 新增 `tests/test_parent_child_chunker_4fd.py` 單元測試檔，模擬標準 `.4fd` XML 資料，驗證 Parent Chunks 與 Child Chunks 切分之正確性、命名空間無感解析及豐富 metadata 的提取，並執行測試通過。

### 修改檔案
- `backend/services/parent_child_chunker.py` (修改)
- `backend/routers/embedding.py` (修改)
- `scripts/parent_child_chunker.py` (修改)
- `frontend/src/components/embedding/BatchIndexingTab.vue` (修改)
- `tests/test_parent_child_chunker_4fd.py` (新增)

## 2026-06-29 新增資料庫自訂資料向量化 (Embedding & Indexing) 匯入功能

### 功能描述
實作了自訂資料向量化 (Embedding & Indexing) 的「資料庫匯入向量化」Tab 與對應介面，支援：
1. **連線設定 & 快速選取**：可自行輸入 IP、Port、資料庫、帳號、密碼進行連線測試，並可將連線設定檔儲存至 MongoDB 中以便後續快速選取使用。
2. **安全過濾機制**：提供前後端 SQL 查詢語句驗證，強制限制僅執行 `SELECT` 或 `WITH` 開頭的唯讀語句，防止 SQL 注入與資料修改 (INSERT/UPDATE/DELETE/DROP 等)。
3. **三階段配置流程**：
   - 第一階段：查詢與取得欄位/樣品資料。
   - 第二階段：自訂欄意轉換，並可隨時變更為自然語言敘述或 Structured JSON 轉換模式。
   - 第三階段：即時樣品轉換成果預覽。
4. **批次向量化匯入**：支援一筆資料獨立為一向量段落，自動分批 (每批 20 筆) 進行向量化計算，並以 `DB_IMPORT_{tableName}` 檔名覆蓋寫入 Qdrant 向量資料庫與更新知識庫計數。

### 實作內容
1. **資料庫模型與 Schema**：
   - 新增 `backend/models/database_config.py`，定義 `DatabaseConfig` Beanie 集合，存儲 DB 設定。
   - 於 `backend/models/mongodb.py` 中註冊 `DatabaseConfig` 文件模型。
   - 新增 `backend/schemas/database_indexing.py`，包含設定 CRUD、連線測試、中介資料與向量化寫入之 Pydantic 傳輸 Schema。
2. **後端 Router 與驅動配置**：
   - 在 `backend/requirements.txt` 中追加 `oracledb>=2.0.0` 依賴。
   - 新增 `backend/routers/database_indexing.py`，內部實作 SQL 安全語法過濾器 `validate_sql_query`、SQL Server 的 `pyodbc` 多驅動程式自適應解析、Oracle Database 的 `oracledb` Thin 模式無驅動連線與資料提取、段落文字轉換公式、Qdrant 向量批次寫入與自動覆蓋刪除同名資料功能。
   - 在 `backend/main.py` 中註冊 `database_indexing` router。
3. **前端 API 與 UI 整合**：
   - 新增 `frontend/src/services/databaseIndexingService.js` 封裝所有資料庫 API 方法。
   - 於 `frontend/src/views/EmbeddingTestView.vue` 引入該服務，並在 script 中加入相關的狀態、連線測試、SQL 檢驗、中介資料取得、即時計算預覽文字 `dbPreviewText` 及匯入 API 呼叫。
   - 在 template 中新增「資料庫匯入向量化」按鈕，並編寫精美流暢的 Glassmorphic 連線設定表單、SQL 編輯器、欄位配置表格、樣品轉換預覽區與匯入執行按鈕與狀態回報。

### 修改檔案
- `backend/requirements.txt` (修改)
- `backend/models/database_config.py` (新增)
- `backend/models/mongodb.py` (修改)
- `backend/schemas/database_indexing.py` (新增)
- `backend/routers/database_indexing.py` (新增)
- `backend/main.py` (修改)
- `frontend/src/services/databaseIndexingService.js` (新增)
- `frontend/src/views/EmbeddingTestView.vue` (修改)

## 2026-06-26 新增客製化副檔名批次上傳限制、MongoDB 分類標籤與自訂類別選項管理

### 功能描述
優化自訂資料向量化 (Embedding & Indexing) 中的批次文件上傳流程：
1. **限制單一副檔名上傳與客製化切分**：限制批次上傳檔案必須符合選定的單一副檔名格式，並依選取的副檔名載入預設的客製化切分設定 (如切分大小、重疊大小、分隔符號與切分模式)。
2. **MongoDB 分類標籤管理**：分類標籤改為從 MongoDB 動態載入，使用者可一鍵勾選或在介面即時建立新標籤存入資料庫。
3. **自訂類別選項 (Class Array) 持久化與 Qdrant 寫入**：新增「類別選項 (Class)」管理，使用者可自行建立類別選項（儲存於 MongoDB），並在資料向量化時將選取之類別陣列寫入 Qdrant 向量點資料的 `"class"` 欄位中，且支援於 RAG 與向量搜尋結果中解析並回傳。

### 實作內容
1. **單一副檔名上傳限制**：
   - 於 `EmbeddingTestView.vue` 新增 `selectedExtension` 下拉式選單與預設切分參數對照表。
   - 修改 `addFilesToQueue` 邏輯，非指定副檔名檔案拒絕加入佇列。
   - 調整 Dropzone 的 `:accept` 屬性動態綁定 `selectedExtension`。
2. **分類標籤 (Tags) 與類別選項 (Classes) 管理**：
   - 實作 MongoDB / Beanie `Tag` 與 `ClassOption` 資料模型，並新增 API 端點提供查詢與建立功能。
   - 於前端 `embeddingService` 整合 `getTags()`, `createTag(name)`, `getClasses()`, `createClass(name)` API 方法。
   - 於 `EmbeddingTestView.vue` 中重構單筆編輯 (Tab 1) 與批次編輯 (Tab 2) 的 UI，移除原自由文字輸入框，替換為動態載入的 Checkbox 標籤/類別氣泡按鈕及即時建立新標籤/類別之輸入框。
3. **Qdrant `"class"` 欄位寫入與檢索回傳**：
   - 在後端向量化 API `/api/embedding/vectorize` 中，提取 `classes` 欄位並以 `"class"` 鍵值存入 Qdrant Metadata payload。
   - 修改後端 `RetrievalMetadata` 結構，加入 `class_list` 欄位並將其 alias 設為 `"class"`，實現對 Qdrant payload `"class"` 欄位的自動解析。
   - 於後端檢索與 RAG 端點中將 `"class"` 屬性對照回傳給前端。

### 修改檔案
- `backend/models/tag.py` (新增)
- `backend/models/class_option.py` (新增)
- `backend/models/mongodb.py` (修改)
- `backend/schemas/embedding.py` (修改)
- `backend/schemas/retrieval.py` (修改)
- `backend/routers/embedding.py` (修改)
- `backend/routers/retrieval.py` (修改)
- `frontend/src/services/embeddingService.js` (修改)
- `frontend/src/views/EmbeddingTestView.vue` (修改)

## 2026-06-25 新增 Genero 4GL 大小雙層檢索 (Parent-Child Retriever) 語法切分與前端自動分批寫入整合

### 功能描述
為了改善傳統字元切分容易將 4GL 程式碼截斷、導致語意上下文丟失的問題，實作了專屬的 4GL 大小雙層檢索切分與處理腳本。並將此切分能力整合至「自動分批寫入 (Batch Indexing)」功能中，允許使用者在批次處理時選用大小雙層結構切分，自動於向量庫點資料中寫入父子區塊關聯元資料。

### 實作內容
1. **父區塊語法結構解析 (Parent Chunks)**：
   - 提取 `MAIN ... END MAIN` 區塊。
   - 提取 `FUNCTION 函數名(...) ... END FUNCTION` 區塊。
   - 提取 `REPORT 報表名(...) ... END REPORT` 區塊。
   - 收集所有在上述結構之外的全域宣告（如 `DATABASE`, `GLOBALS`, `DEFINE`），合併切分為一個名為 `Global_Declarations` 的父區塊。
   - 透過正則與注釋過濾機制（排除 `#`, `--` 及 `{ ... }` 的偽關鍵字干擾），產出具備唯一 `parent_id`、`type`、`name` 與完整原始碼內容的 Parent Chunk 字典。
2. **子區塊滑動窗口切分 (Child Chunks)**：
   - 針對每個 Parent Chunk 的內容，使用固定的字元大小 `child_size`（預設 250 字元）進行切分。
   - 配置 `child_overlap`（預設 20% 重疊區間，即 50 字元），以防關鍵語句或條件判斷在切分邊界被截斷。
   - 自動將父節點元資料（`parent_id`, `source_file`, `type`, `function_name`）綁定至每個 Child Chunk 中，便於寫入向量資料庫。
3. **前端與後端批次寫入整合**：
   - **後端擴充**：在 `/api/embedding/chunk` 與 `/api/embedding/vectorize` 接口中，支援傳入 `chunk_mode` 與 `filename` 參數。若為 `parent_child` 模式或 `.4gl` 檔案，則自動調用 `parent_child_chunker` 產生帶有父區塊關聯 Metadata 的子區塊，並在寫入向量庫時將 `parent_id` 等欄位合併存入 Payload。
   - **前端擴充**：於 `EmbeddingTestView.vue` 之「自動分批寫入設定」面板新增「切分模式」下拉選單（包含「標準字元切分」與「大小雙層結構切分」）。批次發送時自動將選定模式發送給後端，並將後端回傳的父區塊 Metadata 完美合併至向量化 Request 中。

### 修改檔案
- `scripts/parent_child_chunker.py` (新增)
- `tests/test_parent_child_chunker.py` (新增)
- `backend/schemas/embedding.py` (修改)
- `backend/routers/embedding.py` (修改)
- `frontend/src/views/EmbeddingTestView.vue` (修改)

## 2026-06-25 新增自動分批寫入之重複檔案處理設定 (覆蓋與略過選項)

### 功能描述
為「自動分批寫入」新增重複檔案處理選項設定，允許使用者選擇「刪除重新上傳(覆蓋)」或「舊檔案略過不覆蓋（跳過）」。在批次處理開始前自動向後端獲取現有檔案清單，並依此判斷是否需略過已存在的檔案。

### 實作內容
1. **前端狀態擴充**：
   - 於 `frontend/src/views/EmbeddingTestView.vue` 新增 `batchDuplicateMode` 狀態（預設為 `overwrite`）。
2. **批次略過處理邏輯**：
   - 修改 `startBatchProcessing`：執行前呼叫 `/api/knowledge-bases/{kb_id}/metadata` API 取得最新庫內檔案名稱列表。
   - 迭代佇列時，若偵測到重複檔名且設定為 `skip`，則將進度設為 100%、狀態設為已完成，並顯示「檔案已存在於向量庫中，已自動略過不覆蓋」，直接進入下一個檔案處理。
   - 當寫入成功時，動態更新已存在檔案清單，以避免同批次或後續執行之檔案發生重複寫入。
3. **介面 UI 整合**：
   - 於「批次寫入設定」面板中加入「重複檔案處理」下拉選單，並將網格配置由雙欄調整為三欄。

### 修改檔案
- `frontend/src/views/EmbeddingTestView.vue`

## 2026-06-25 新增自訂資料分批寫入功能 (含批次上傳、4GL 格式支援與自動重複清理)

### 功能描述
於自訂資料向量化 (Embedding & Indexing) 頁面中，新增一個分頁「自動分批寫入」。使用者可一次性拖放或選取多個檔案（包含 `.4gl` 原始碼檔案）進行批次處理，系統將自動分批切分並將 Chunks 批次寫入 Qdrant 與 MongoDB 資料庫。若檢測到與資料庫內檔案名稱重複，則會先自動刪除該檔案先前之所有向量資料再重新寫入，並在前端提供直觀的整體進度條與檔案佇列詳細狀態指示。

### 實作內容
1. **後端支援與檔案相容性擴充**：
   - 修改 `backend/services/document_parser.py`：在 `parse_file` 中將 `.4gl` 副檔名加入文字解析分流中，使其能以純文字格式進行解碼與提取。
   - 修改 `backend/services/qdrant_service.py`：新增 `delete_by_filename` 類別方法，使用 Qdrant Scroll API 查找指定檔名的所有點 ID，並呼叫 `AsyncQdrantClient.delete` 進行刪除，回傳刪除的點數量。
   - 修改 `backend/schemas/retrieval.py`：新增 `DeleteByFilenameRequest` 結構體。
   - 修改 `backend/routers/retrieval.py`：新增 `POST /api/retrieval/knowledge-bases/{knowledge_base_id}/files/delete-by-filename` 端點。呼叫 `delete_by_filename` 刪除同名資料，並更新 MongoDB 知識庫的 `chunk_count` 總數。
2. **前端服務對接**：
   - 修改 `frontend/src/services/retrievalService.js`：新增 `deleteFileByFilename` API 方法。
3. **前端 UI 與批次佇列引擎開發**：
   - 修改 `frontend/src/views/EmbeddingTestView.vue`：
     - **新分頁整合**：新增 `activeTab = 'batch_indexing'` 分頁。
     - **批次檔案管理**：設計支援拖拽與多檔案選取的 Dropzone 介面，可載入多個檔案至佇列。
     - **分批配置設定**：提供分類標籤 (Tags) 輸入，以及「向量寫入批次大小」配置 (Chunk/Batch)，預設為每次 20 段，用以降低連線或 Payload 過大之錯誤率。
     - **全域與個別進度條**：使用 computed 計算總體進度百分比，並透過 `Parsing`, `Chunking`, `Deleting`, `Vectorizing (Batch X/Y)`, `Success`, `Failed` 等狀態更新各檔案微型進度條與狀態訊息。
     - **依序非同步佇列處理**：以迴圈依序執行各檔案之：上傳解析、文本切分、庫內重複資料刪除、分批向量化寫入 Qdrant 與 Beanie 流程。

### 修改檔案
- `backend/services/document_parser.py`
- `backend/services/qdrant_service.py`
- `backend/schemas/retrieval.py`
- `backend/routers/retrieval.py`
- `frontend/src/services/retrievalService.js`
- `frontend/src/views/EmbeddingTestView.vue`

## 2026-06-24 新增自訂資料向量化文字結構化 (Structured Chunks) 功能

### 功能描述
於「自訂資料向量化 (Embedding & Indexing)」頁面之切分預覽功能中，新增文字結構化設定。啟用此功能後，文字切分時將自動結合檔案名稱、段落編號與分類標籤資訊，整合成結構化格式再進行向量化寫入 Qdrant 向量資料庫，以強化後續 RAG 檢索的語意關聯與元資料提取品質。

### 實作內容
1. **全域參數擴充**：
   - 修改 `frontend/src/stores/paramsStore.js`，於 Pinia store 中新增 `enableStructuring` 狀態開關，預設為 `true`。
2. **參數控制面板整合**：
   - 修改 `frontend/src/components/params/ChunkingParams.vue`，在切分參數邊欄的切分符號下方新增「啟用文字結構化 (Structure Text)」的 checkbox 開關，支援全域狀態雙向綁定。
3. **前端切分邏輯整合與精確估算**：
   - 修改 `frontend/src/views/EmbeddingTestView.vue`，當執行「開始文本切分」時，若啟用文字結構化，則自動將各個 chunk 依據格式範本（含檔名、段落、標籤與主要內容）進行字串重新格式化。
   - 實作前端的 CJK 字元/英文 token 精確估算器 `estimateTokens`，動態更新結構化段落的 tokens 數與字元數以提供最真實的切分預覽，並確保寫入資料庫的內容完全與預覽一致。

### 修改檔案
- `frontend/src/stores/paramsStore.js`
- `frontend/src/components/params/ChunkingParams.vue`
- `frontend/src/views/EmbeddingTestView.vue`

## 2026-06-23 新增 Qdrant 雙路召回與 RRF 混合檢索 (Hybrid Search) 功能

### 功能描述
實作結合「密集語意向量 (Dense Vector) 檢索」與「稀疏關鍵字向量 (Sparse Vector / SPLADE) 檢索」的雙路融合檢索（Hybrid Search）。以 Qdrant 的 Reciprocal Rank Fusion (RRF) 整合兩路檢索結果，顯著提升專有名詞與精確型號、關鍵字的查詢準確度。

### 實作內容
1. **依賴管理**：
   - 於 `backend/requirements.txt` 中新增 `fastembed>=0.3.0` 套件依賴，以高效地生成語意與詞頻稀疏向量。
2. **稀疏向量產生模組**：
   - 新建 `backend/services/sparse_embedding_service.py`，封裝 `fastembed.SparseTextEmbedding` (預設為 SPLADE) 生成器，支援單筆與批次文字的稀疏向量生成。
3. **向量庫 Schema 與寫入更新**：
   - 修改 `backend/services/qdrant_service.py`：
     - `create_collection`：在建立 Collection 時定義命名空間 `"sparse-text"` 及其對應的稀疏索引。
     - `upsert_chunks`：變更資料寫入的 Vector 結構，呼叫 `SparseEmbeddingService` 自動批次計算並儲存對應的稀疏向量。
4. **雙路檢索與安全降級 (Fallback)**：
   - 修改 `search_similar` 介面：支援 `search_type` 與原始 `query_text` 參數。
   - 當 `search_type` 為 `"hybrid"` 時，同時預檢索 Dense 與 Sparse 兩路，再利用 Qdrant `FusionQuery(fusion=models.Fusion.RRF)` 計算最佳綜合排序。
   - 增加安全降級防線：若因舊 Collection 不支援或其他未知異常，會自動捕捉例外並降級為常規純向量搜尋，保障高可用性。
5. **RAG 對話與檢索 API 銜接**：
   - 修改 `backend/routers/retrieval.py` 與 `backend/routers/rag.py` 路由，將前端發送的 `search_type`（混合/向量）參數穿透傳遞給底層檢索引擎，使對話串流與獨立檢索都支援 Hybrid 模式。

### 修改檔案
- `backend/requirements.txt`
- `backend/services/sparse_embedding_service.py` (新設)
- `backend/services/qdrant_service.py`
- `backend/routers/retrieval.py`
- `backend/routers/rag.py`

## 2026-06-23 新增人工回饋紀錄單筆刪除與批次刪除功能

### 功能描述
為「人工回饋與標註歷史」頁面擴充紀錄清理與刪除功能，支援單筆回饋紀錄刪除，以及多選核取方塊後的批次刪除，以便於管理與整理匯入測試集前的標註數據。

### 實作內容
1. **後端刪除 API 實作**：
   - 實作 `DELETE /api/feedback/{feedback_id}` 端點，用於刪除指定的單一回饋紀錄。
   - 實作 `POST /api/feedback/batch-delete` 端點，以接收包含多個 ID 的 payload，進行安全的 MongoDB 批次刪除。
2. **前端 Store 狀態對接**：
   - 在 Pinia Store (`feedbackStore.js`) 中新增 `deleteFeedback` 與 `batchDeleteFeedbacks` Actions 以連接後端刪除端點。
3. **前端 UI 與操作交互**：
   - 在 `FeedbackView.vue` 列表的標題操作列新增「刪除選取」按鈕，並於多選 checkbox 有勾選時啟用，點擊後會彈出確認視窗，執行完成後清空選取狀態並重新載入列表。
   - 在表格每行末尾新增一個「操作」欄位，擺放紅色的垃圾桶按鈕以支援單筆刪除。

### 修改檔案
- `backend/routers/feedback.py`
- `frontend/src/stores/feedbackStore.js`
- `frontend/src/views/FeedbackView.vue`

## 2026-06-23 新增 Prompt 測試多源引用與 A/B 測試結果歷史存檔系統

### 功能描述
為「Prompt 測試」頁面擴充四項大幅提升調優效率之進階功能，支援範本與測試結果的 MongoDB 歷史存檔、引導載入預設 RAG 範本、針對 Qdrant 知識庫執行即時向量檢索多選注入、以及引用評估集問題（並能聯動載入標準答案與相關上下文）。

### 實作內容
1. **測試歷史與範本存檔**：
   - 後端新增 `PromptTestRecord` MongoDB 資料模型，紀錄 System Prompt、User Template、Context、Question 與 A/B 測試 Variant 的生成 answer、elapsed_ms 與 parameters。
   - 提供 `GET /api/prompt/records`、`POST /api/prompt/records`、`DELETE /api/prompt/records/{id}` 對應 API。
   - 前端點擊「儲存本次測試與結果」可為本次結果命名存檔；點擊「檢視歷史紀錄」彈出暗色玻璃擬物 Modal，顯示歷史列表，並提供「還原參數」與「刪除」功能。
2. **預設/自訂範本引用機制**：
   - 後端在 `mongodb.py` 初始化中實作 `seed_default_prompt_templates()`，若資料庫為空則自動載入「預設 RAG 助手」與「嚴格知識問答」兩款內建範本。
   - 提供 `GET /api/prompt/templates`、`POST /api/prompt/templates`、`DELETE /api/prompt/templates/{id}` 等範本 API。
   - 前端 System Prompt 設定上方新增「載入範本」與「儲存為範本」按鈕。點選載入可彈出視窗並套用範本，非預設範本可執行刪除。
3. **Qdrant 知識庫 Chunk 段落多選引用**：
   - 前端 Context 上方新增「檢索並引用 Qdrant Chunks」按鈕。
   - 點選彈出 Modal 視窗，使用者可選擇系統內現有 Knowledge Base，輸入關鍵字後呼叫後端 `/api/retrieval/search` 進行真實向量檢索。
   - 以相似度排序顯示 Chunks，支援多選 Checkbox，確認後自動將所選段落附帶檔名與頁碼以 `\n---\n` 串接注入 Context 輸入框。
4. **評估集問題引用**：
   - 前端 User Query 上方新增「引用評估集問題」按鈕。
   - 點選彈出 Modal 視窗，使用者可選擇測試集並自動加載問答清單。
   - 點擊特定項目即填入問題，並提示是否一併將該問答對應的標準答案 (Ground Truth) 與 relevant contexts 追加載入 Context 輸入框。

### 修改檔案
- `backend/models/prompt_test_record.py` (新設)
- `backend/models/mongodb.py`
- `backend/routers/prompt.py`
- `frontend/src/views/PromptTestView.vue`

## 2026-06-24 新增刪除向量資料的 Points 功能 (含檔案名稱過濾與批次刪除)

### 功能描述
於向量檢索測試頁面中新增 Qdrant 向量 Points 的管理與刪除功能，免去手動登入 Qdrant 後台的操作。功能包含：透過知識庫元資料（Metadata）動態取得唯一檔案清單並進行前端下拉式檔案名稱過濾篩選、檢索結果的單筆與 checkbox 多選核取，以及批次永久刪除 Qdrant 向量 Points 並連帶更新 MongoDB 知識庫的 chunk 總數。

### 實作內容
1. **後端 Qdrant 服務與 API 端點實作**：
   - 修改 `backend/services/qdrant_service.py`：新增 `delete_points` 類別方法，封裝 `AsyncQdrantClient.delete` 並使用 `PointIdsList` 進行 Qdrant 點的刪除。
   - 修改 `backend/schemas/retrieval.py`：新增 `BatchDeleteRequest` 結構，包含要刪除的點 ID 列表 (`point_ids: List[str]`)。
   - 修改 `backend/routers/retrieval.py`：新增 `POST /api/retrieval/knowledge-bases/{knowledge_base_id}/points/batch-delete` 路由端點。刪除 Qdrant 對應 Point 後，自動將 MongoDB 中該知識庫紀錄的 `chunk_count` 扣除對應刪除數量並保存。
2. **前端服務對接**：
   - 修改 `frontend/src/services/retrievalService.js`：新增 `batchDeletePoints(knowledgeBaseId, pointIds)` 方法對接後端批次刪除 API。
3. **前端 UI 與交互優化**：
   - 修改 `frontend/src/views/RetrievalTestView.vue`：
     - **檔案名稱過濾**：新增 `watch` 監聽知識庫 ID，當切換時自動向 `/api/knowledge-bases/{id}/metadata` 請求元資料，並提供 `檔案名稱過濾` 下拉選單供使用者限制檢索範圍。
     - **單筆刪除與批次刪除**：在檢索結果列表的每一筆資料右上角放置紅色垃圾桶圖示，點擊可單獨刪除該點；列表左上方新增全選與「刪除所選」按鈕，配合每筆資料左側 Checkbox 供多選與批次刪除。
     - **即時響應**：點擊刪除並確認後，直接在前端結果陣列中剔除已刪除的資料，不需重新發起搜尋即可即時更新。

### 修改檔案
- `backend/services/qdrant_service.py`
- `backend/schemas/retrieval.py`
- `backend/routers/retrieval.py`
- `frontend/src/services/retrievalService.js`
- `frontend/src/views/RetrievalTestView.vue`
