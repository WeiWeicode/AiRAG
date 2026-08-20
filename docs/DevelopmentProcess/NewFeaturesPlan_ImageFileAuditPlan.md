# 功能規劃案：圖片檔案稽核頁面 (Image File Audit)

## 0. 文件資訊

* **對象**：AiRAG 開發團隊（前端 + 後端）。
* **建立日期**：2026-08-18。
* **關聯文件**：
  * [NewFeaturesPlan_DocumentImageEmbeddingPlan.md](Seizure/NewFeaturesPlan_DocumentImageEmbeddingPlan.md)（PDF/Word 內嵌圖片擷取與向量化）
  * [NewFeaturesPlan_ImageCaptionRepairExternalApiPlan.md](NewFeaturesPlan_ImageCaptionRepairExternalApiPlan.md)（圖片描述修復，依賴磁碟原圖存在）
  * [MULTI_APP_RAG_SYNC_PLAN.md](MULTI_APP_RAG_SYNC_PLAN.md)（外部應用同步 / 重新向量流程）

---

## 1. 背景與痛點

圖片段落的資料分散在兩個地方，兩者之間**沒有任何一致性保證機制**：

| 位置 | 內容 |
|---|---|
| Qdrant（各 KB 的 collection） | `chunk_type == "image"` 的 point，payload 帶 `image_filename` |
| 地端磁碟 `backend/FileAttachments/image/` | 抽取出來的原圖實體檔（`{uuid4().hex}.{ext}`） |

目前唯一的自動清理機制在 [`QdrantService._cleanup_orphaned_image_files()`](../../backend/services/qdrant_service.py:1227)，只在三個刪點路徑被呼叫：`delete_points()`、`delete_by_filename()`、`delete_by_app_source()`。**其餘情況都會讓兩邊對不上**：

### 1.1 已知會產生「孤兒檔」（磁碟有、Qdrant 無引用）

| # | 情境 | 位置 |
|---|---|---|
| 1 | 刪除整個知識庫 → `delete_collection()` 只刪 collection，完全沒接圖片清理 | [knowledge_base.py:110](../../backend/routers/knowledge_base.py:110) → [qdrant_service.py:200](../../backend/services/qdrant_service.py:200) |
| 2 | 重新向量（ingest upsert）中途失敗：流程是「先寫圖檔到磁碟 → 生描述 → 切分 → embedding → 刪舊點 → upsert」，任一步在 upsert 前 raise（切分無 chunk、embedding 失敗、job timeout），已落地的新圖檔沒有任何 point 引用，且無 rollback | [ingest_service.py:270](../../backend/services/ingest_service.py:270)、[ingest_service.py:609](../../backend/services/ingest_service.py:609) |
| 3 | `POST /api/embedding/upload?extract_images=true` 在解析階段就把圖片落地，使用者沒按向量化就離開 | [embedding.py:98](../../backend/routers/embedding.py:98) |

### 1.2 已知會產生「遺失檔」（Qdrant 有引用、磁碟無檔）

| # | 情境 | 影響 |
|---|---|---|
| 1 | `_cleanup_orphaned_image_files()` 的 scroll 只查**當前這一個 collection**；若同一 `image_filename` 被兩個 collection 引用，刪 A 會把實體檔刪掉、B 的圖變成死引用 | 前端縮圖 404 |
| 2 | 人工清理 / volume 重掛 / 主機搬遷造成檔案不見 | `ImageCaptionRepairService` 靠磁碟原圖重生描述，檔案不在就永遠修不好 |

**目前沒有任何介面可以看出這兩種不一致**，只能人工比對 uuid 檔名與 Qdrant payload。本案就是把這件事做成頁面。

---

## 2. 功能範圍

### 2.1 In Scope

1. 後端提供「全庫掃描比對」API：掃 Qdrant **所有 collection** 的圖片 point，對上磁碟檔案清單，回傳三分類結果與統計。
2. 後端提供「清理孤兒檔」API：依前端傳來的明確檔名清單刪除實體檔（刪前重新驗證仍為孤兒）。
3. 前端新增 `圖片檔案稽核` 頁面：統計卡 + 分頁表格 + 縮圖預覽 + 勾選批次清理 + 二次確認。

### 2.2 Out of Scope（本案不做，但列出後續建議）

* 不自動排程清理（不加 cron / arq 週期任務），一律人工在頁面上按。
* 不修 §1.1 的三個根因（刪 KB 未清圖、ingest 失敗未 rollback）；本案是「事後稽核工具」。**建議另開案處理**，尤其是刪 KB 那條，否則孤兒檔會持續累積。
* 不處理 `FileAttachments/` 根目錄的附件本體（那是 `Attachment` model 管的，與向量無關，刪除走 [attachment.py:188](../../backend/routers/attachment.py:188)）。

---

## 3. 名詞與判定規則

| 分類 | 英文 key | 判定 | 建議處置 |
|---|---|---|---|
| 正常 | `matched` | 磁碟有檔 ∧ 至少一個 point 引用 | 無 |
| 孤兒檔 | `orphan_file` | 磁碟有檔 ∧ **所有 collection** 都無 point 引用 | 可安全刪除（本頁提供） |
| 遺失檔 | `missing_file` | 有 point 引用 ∧ 磁碟無檔 | 重新向量該文件；或刪掉這些 point |

> **關鍵設計：一定要掃「所有 collection」才判定孤兒。** 只掃單一 KB 會把別的 KB 正在用的圖判成孤兒，一鍵清掉就是 §1.2 的災難放大版。

---

## 4. 後端實作

### 4.1 新增 `backend/services/image_audit_service.py`

```python
class ImageAuditService:
    @classmethod
    async def scan(cls) -> dict:
        """掃描所有 collection 的圖片 point 與磁碟檔案，回傳比對結果。"""

    @classmethod
    async def cleanup_orphans(cls, filenames: List[str]) -> dict:
        """刪除指定的孤兒檔；刪前逐一重新確認仍無 point 引用。"""
```

#### 4.1.1 Qdrant 端：新增 `QdrantService.iter_all_image_points()`

**不能複用** [`get_image_points()`](../../backend/services/qdrant_service.py:1545)：它 (a) 在只剩 `chunk_type` 條件時故意 `raise ValueError`，(b) `limit=10000` 寫死無分頁。新增一個專供稽核用的方法：

```python
    @classmethod
    async def iter_all_image_points(cls, collection_name: str, page_size: int = 1000):
        """
        分頁 scroll 出該 Collection 全部 chunk_type == "image" 的段落，只取稽核需要的 payload 欄位。
        與 get_image_points() 的差異：本方法刻意允許「無定位條件的全庫掃描」，因為稽核就是要掃全部；
        因此只回傳 payload 子集、且用 offset 分頁，避免一次把上萬筆 payload 拉進記憶體。
        """
        client = cls.get_client()
        offset = None
        while True:
            points, offset = await client.scroll(
                collection_name=collection_name,
                scroll_filter=models.Filter(must=[
                    models.FieldCondition(key="chunk_type", match=models.MatchValue(value="image"))
                ]),
                limit=page_size,
                offset=offset,
                with_payload=["image_filename", "filename", "app_id", "doc_type",
                              "source_id", "page", "caption_failed"],
                with_vectors=False
            )
            for p in points:
                yield str(p.id), (p.payload or {})
            if offset is None:
                break
```

#### 4.1.2 掃描流程

1. `client.get_collections()` 取得**全部** collection 名稱（不是只取 MongoDB 的 `KnowledgeBase.qdrant_collection_name` —— Mongo 記錄被刪、collection 還在的殘留也要看得到）。
2. 另外把 `KnowledgeBase` 全撈一次，做 `collection_name -> kb_name / kb_id` 對照表，UI 才顯示得出人看得懂的知識庫名稱；查不到的標「（無對應知識庫紀錄）」。
3. 逐 collection 跑 `iter_all_image_points()`，累積成
   `refs: dict[image_filename, list[{collection, kb_name, kb_id, point_id, filename, page, caption_failed}]]`。
   單一 collection 掃描失敗只記 warning 並在回應的 `errors[]` 中列出，不中斷整體掃描（比照 `_cleanup_orphaned_image_files` 的 best-effort 精神），但**掃描有錯時前端必須禁用清理按鈕**（見 §6 風險 3）。
4. 磁碟端：`os.listdir(image_dir)` 過濾 `os.path.isfile`，取得 `disk_files: set[str]`；同時 `os.path.getsize` / `getmtime` 供 UI 顯示。
   `image_dir = os.path.abspath(os.path.join(settings.FILE_ATTACHMENTS_DIR, settings.FILE_ATTACHMENTS_IMAGE_SUBDIR))`（與 [embedding.py:674](../../backend/routers/embedding.py:674)、[qdrant_service.py:1238](../../backend/services/qdrant_service.py:1238) 同一套解析方式）。
5. 集合運算產出三類；`orphan_file` 依 `mtime` 新→舊排序（剛失敗的 ingest 產物排最前面，最好判斷）。

#### 4.1.3 清理流程 `cleanup_orphans(filenames)`

對每個檔名依序：

1. **路徑安全**：`abspath(join(image_dir, fn))` 必須落在 `image_dir` 底下，否則跳過並記 warning（比照 [qdrant_service.py:1259](../../backend/services/qdrant_service.py:1259) 的既有寫法）。同時拒絕含路徑分隔字元的輸入。
2. **重新驗證**：對所有 collection 各做一次 `limit=1` 的 scroll（`image_filename == fn`）；**只要任一 collection 命中就跳過不刪**，理由記為 `still_referenced`。掃描結果到按下按鈕之間可能隔了很久，這一步是防誤刪的最後一道關卡，不可省略。
3. 通過才 `os.remove()`；單檔例外不中斷其餘檔案。
4. 回傳 `{"deleted": [...], "skipped": [{"filename": ..., "reason": ...}], "failed": [{"filename": ..., "error": ...}]}`。

### 4.2 新增 `backend/routers/image_audit.py`

掛在 `main.py`：`app.include_router(image_audit.router, prefix="/api")`，router 自身 `prefix="/image-audit"`、`dependencies=[Depends(get_current_user)]`（與其他 router 一致，只有 `auth` 例外）。

| Method | Path | 說明 |
|---|---|---|
| `GET` | `/api/image-audit/scan` | 執行比對。Query：`refresh: bool = False`（見 §4.4 快取） |
| `POST` | `/api/image-audit/cleanup` | Body: `{"filenames": ["<uuid>.png", ...]}`，刪除孤兒檔 |

#### `GET /scan` 回應（`schemas/image_audit.py`）

```json
{
  "scanned_at": "2026-08-18T09:12:33.412Z",
  "image_dir": "/app/FileAttachments/image",
  "summary": {
    "disk_file_count": 41,
    "referenced_filename_count": 38,
    "image_point_count": 52,
    "matched_count": 37,
    "orphan_file_count": 4,
    "missing_file_count": 1,
    "collection_count": 3
  },
  "orphan_files": [
    { "image_filename": "0d02...b765d.png", "size": 184320, "modified_at": "2026-08-14T02:11:05Z" }
  ],
  "missing_files": [
    { "image_filename": "9f11...aa02.jpeg",
      "references": [
        { "collection": "kb_6a38...440", "kb_name": "產品文件庫", "kb_id": "6a38...440",
          "point_id": "1f2e...", "filename": "EFGP-ReleaseNote.pdf", "page": 7, "caption_failed": false }
      ] }
  ],
  "matched_files": [
    { "image_filename": "12f2...da1b1.jpeg", "size": 90112, "modified_at": "...", "reference_count": 2,
      "references": [ ] }
  ],
  "errors": [
    { "collection": "kb_xxxx", "error": "..." }
  ]
}
```

> `image_point_count` 與 `referenced_filename_count` 會不一樣（同一張圖可被多個 point 引用）；UI 要標清楚，否則對數字會對不起來。

#### `POST /cleanup` 回應

```json
{
  "message": "清理完成：刪除 3 筆、略過 1 筆、失敗 0 筆",
  "deleted": ["a.png", "b.png", "c.png"],
  "skipped": [{ "filename": "d.png", "reason": "still_referenced" }],
  "failed": []
}
```

錯誤碼：`400`（`filenames` 空陣列）、`401`（未登入）、`500`（無法取得 Collection 清單等執行失敗）。

> **實作時的調整（2026-08-18）**：原訂「掃描 `errors[]` 非空時 `cleanup` 直接回 `409`」，實作改為
> **逐檔複驗，任一 Collection 查不動就跳過該檔（`reason: "verify_failed"`）**。同樣擋住「某個
> Collection 掛掉導致它的圖全被當孤兒」，但判斷依據是清理當下的即時狀態而非可能已過期的掃描結果，
> 粒度也更細（其他檔案照樣清得掉）。非法檔名同樣降級為 `skipped`（`invalid_filename`）而非整批 400。
> 前端仍維持「掃描有錯就停用刪除按鈕」。

### 4.3 效能與規模

現況約 41 個檔、資料量極小，同步執行毫無問題。但掃描是 `O(collection 數 × 圖片 point 數)` 的全庫 scroll：

* 目前 `chunk_type` **沒有 payload index**，Qdrant 走的是全 collection 掃描過濾。若之後圖片段落上萬筆，先加 `create_payload_index(field_name="chunk_type", field_schema=KEYWORD)`（可比照 [`ensure_all_collections_payload_index()`](../../backend/services/qdrant_service.py:78) 在啟動時建立）。
* **轉背景任務的門檻**：單次掃描超過 30 秒就該改走 arq（`worker.py` 已在跑），API 改回 `202 + taskId`、前端輪詢。本案先不做，但 service 的介面設計要能直接被 worker 呼叫（純函式、不依賴 Request）。

### 4.4 快取

`GET /scan` 加一層 module 級 in-memory 快取（TTL 60 秒，`refresh=true` 強制重掃），避免使用者連點重新整理就對 Qdrant 打全庫 scroll。快取只用於顯示；**`POST /cleanup` 一律走即時重新驗證，絕不讀快取**。

---

## 5. 前端實作

### 5.1 新增檔案

| 檔案 | 內容 |
|---|---|
| `frontend/src/services/imageAuditService.js` | `scan(refresh)` / `cleanup(filenames)`，比照 [knowledgeBaseService.js](../../frontend/src/services/knowledgeBaseService.js) 的極簡風格 |
| `frontend/src/views/ImageAuditView.vue` | 主頁面，Vue 3 `<script setup>` + Tailwind |

### 5.2 修改檔案

| 檔案 | 修改 |
|---|---|
| `frontend/src/router/index.js` | 新增 `/image-audit` route，`meta: { requiresAuth: true }` |
| `frontend/src/components/common/AppSidebar.vue` | `menuItems` 加一項 `{ path: '/image-audit', label: '圖片檔案稽核', icon: ... }`，位置放在「知識庫管理」之後 |

### 5.3 頁面結構

```
┌ 圖片檔案稽核 ──────────────────────────── [重新掃描] ┐
│ 比對 Qdrant 全部 collection 的圖片段落與地端 FileAttachments/image 資料夾  │
│ 掃描時間：2026-08-18 17:12:33 ・ 目錄：/app/FileAttachments/image          │
├───────────────────────────────────────────┤
│ [磁碟檔案 41] [向量引用 38 檔名 / 52 段落] [孤兒檔 4] [遺失檔 1]           │
├───────────────────────────────────────────┤
│ Tab: 孤兒檔(4) | 遺失檔(1) | 正常(37)                                      │
├───────────────────────────────────────────┤
│ 孤兒檔 tab：☐ 全選   已選 2 筆   [刪除選取的實體檔]                        │
│   ☐ [縮圖] 0d02…765d.png   180 KB   2026-08-14 10:11                       │
│ 遺失檔 tab（唯讀）：檔名 / 來源文件 / 知識庫 / 頁次 / point_id / 描述失敗？ │
│ 正常 tab（唯讀）：縮圖 / 檔名 / 引用數 / 來源文件（可展開看全部引用）       │
└───────────────────────────────────────────┘
```

* 統計卡的數字直接對應 `summary`，並在 hover tooltip 說明「38 個檔名 / 52 個段落」的差異。
* 遺失檔那列給一個「複製 point_id」按鈕，方便貼到向量搜尋測試頁去刪點或重轉。
* `errors[]` 非空時，頁面頂端顯示紅色警示，條列掃描失敗的 collection。

### 5.4 縮圖的坑（實作前務必看）

`GET /api/embedding/images/{stored_filename}` 掛在 `embedding` router 底下，**有 `Depends(get_current_user)`**，`<img src="/api/embedding/images/xxx">` 會直接 401 出不來（瀏覽器不會帶 Authorization header）。

必須用既有的 [`imageService.fetchImageBlobUrl()`](../../frontend/src/services/imageService.js)（走 axios 帶 token → blob URL）：

* 只對「當前 tab 可見的那一頁」做 lazy load，不要一次抓幾十張。
* `onUnmounted` 與換頁時 `URL.revokeObjectURL()`，否則長時間停留會吃記憶體。
* **孤兒檔的縮圖照樣載得出來**（檔案還在磁碟上，端點不查 Qdrant），這正是刪除前肉眼確認的價值所在。
* 遺失檔必然 404 → 顯示灰色佔位圖示，不要顯示破圖。

### 5.5 刪除的二次確認

* 刪除按鈕預設 disabled，需勾選 ≥ 1 筆才啟用。
* 點擊後跳 modal，列出即將刪除的檔名（超過 10 筆顯示前 10 筆 +「…等 N 筆」），並要求**手動輸入 `DELETE`** 才能送出（比照 [KnowledgeBaseSettingsView.vue](../../frontend/src/views/KnowledgeBaseSettingsView.vue) 刪除知識庫的 `confirmInput` 做法）。
* 刪除完成後自動 `scan(refresh=true)` 重新整理，並用 `skipped` 的內容明確提示「有 N 筆在你確認期間被重新引用，已跳過」。
* **不提供「一鍵刪除全部孤兒檔」的無確認捷徑。**

---

## 6. 風險與防呆

| # | 風險 | 對策 |
|---|---|---|
| 1 | 只掃部分 collection 就判孤兒 → 誤刪別的 KB 正在用的圖 | 掃描一律走 `get_collections()` 全量；掃描失敗的 collection 進 `errors[]` |
| 2 | 掃描結果過期，清理時已被重新引用 | `cleanup` 每個檔案刪前重新 scroll 驗證（§4.1.3 step 2） |
| 3 | 掃描有 collection 失敗，卻照樣清理 → 該 collection 的圖全被當孤兒 | 後端逐檔複驗，任一 Collection 查不動即跳過該檔（`verify_failed`）；前端在 `errors[]` 非空時禁用刪除按鈕並說明原因 |
| 4 | 路徑穿越（前端傳 `../../config.py`） | `abspath` + 前綴檢查 + 拒絕含分隔字元的檔名 |
| 5 | 掃描期間有 ingest 正在跑，新圖剛落地、point 還沒寫入 → 被判成孤兒 | 孤兒判定加 **mtime 保護期**：`mtime` 在最近 `INGEST_JOB_TIMEOUT` 秒內的檔案標為 `orphan_recent`，UI 顯示「可能是進行中的任務，建議稍後再確認」且**預設不可勾選**（需另開「顯示近期檔案」開關才放行）。少了這條，正在跑的同步任務會被這個頁面直接砍掉素材 |

---

## 7. 驗收條件

1. 手動在 `backend/FileAttachments/image/` 放一張沒人引用的 `test-orphan.png`（mtime 改成一天前）→ 掃描後出現在「孤兒檔」，勾選刪除後檔案從磁碟消失，重新掃描不再出現。
2. 手動刪掉一張仍被引用的圖 → 掃描後出現在「遺失檔」，且能看到正確的知識庫名稱 / 來源文件 / 頁次。
3. 同一張圖被兩個 KB 引用時，該檔**不會**出現在孤兒清單。
4. 建立 KB → 上傳含圖 PDF 並向量化 → 刪除該 KB → 掃描能列出這批孤兒檔（驗證 §1.1-1 的既有缺陷確實被這個頁面看得見）。
5. 剛完成的 ingest（mtime 在保護期內）產生的圖不會被誤列為可刪孤兒。
6. 前端縮圖在有 JWT 的情況下正常顯示，重新整理頁面不會 401。
7. 掃描期間某個 collection 不存在 / 連線失敗 → 頁面顯示警示、刪除按鈕禁用；直接呼叫 `POST /cleanup` 時該檔以 `verify_failed` 跳過而非被刪除。

---

## 9. 實作狀態（2026-08-18）

階段 1–4 全部完成。實際落地的檔案與設計決策見
[NewFeatures.md](NewFeatures.md)、[BackendCorrection.md](BackendCorrection.md)、
[FrontendCorrection.md](FrontendCorrection.md) 的 2026-08-18 條目，API 契約見 `docs/03_API_CONTRACT.md` §20。
自動化驗證：`tests/test_image_audit_service.py`（本機，git-ignored）7 個案例全過。
驗收條件 §7 各項需由使用者在實機手動確認。

---

## 8. 實作順序

| 階段 | 內容 | 產出 |
|---|---|---|
| 1 | `QdrantService.iter_all_image_points()` + `ImageAuditService.scan()` + `GET /scan` | 可用 curl 驗證比對結果正確 |
| 2 | `ImageAuditView.vue`（唯讀）+ service + route + sidebar | 頁面看得到三分類與縮圖 |
| 3 | `cleanup_orphans()` + `POST /cleanup` + 前端勾選與二次確認 | 完整功能 |
| 4 | 文件紀錄 | `NewFeatures.md`（功能）、`BackendCorrection.md`（新 service/router）、`FrontendCorrection.md`（新頁面與側欄），並在 `docs/03_API_CONTRACT.md` 補上兩個端點 |

> 階段 1、2 完成就已經有價值（看得見問題），階段 3 才動到刪檔。建議分兩次上線：先讓稽核結果被人眼看過幾天，確認判定沒有誤判，再開放清理功能。
