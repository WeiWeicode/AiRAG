# 專用 Cross-Encoder Rerank（Local FastEmbed TextCrossEncoder）規劃文件

> 狀態：規劃中，待使用者確認後執行
> 影響範圍：`backend/services/rerank_service.py`（內部新增策略分支，對外簽章不變）、新檔案 `backend/services/cross_encoder_rerank_service.py`、`backend/config.py`（新增 `RERANK_STRATEGY`/`RERANKER_MODEL`）、`requirements.txt`。**呼叫端（`rag.py`/`retrieval.py`/`evaluation.py`）零修改**——`RerankService.rerank()` 對外簽章與行為契約完全不變，只是內部依設定值切換兩種實作策略。

## 1. 目標與範圍

### 目標
現行 `RerankService.rerank(query, candidates, top_k)`（[rerank_service.py:9-81](../../backend/services/rerank_service.py)）依賴地端 Instruct LLM（`DENSE_VECTOR_INSTRUCT_MODEL`）輸出 listwise JSON 排序，穩定性依賴 LLM 對 JSON Schema 的遵循度，且每次 rerank 都是一次完整的 LLM 呼叫（有網路/推論延遲）。新增一個**本地 in-process** 的 fastembed `TextCrossEncoder` 作為第二種可選策略，透過設定值切換，不需要額外部署外部服務。

**已確認的技術方向（使用者決策，非待討論項）**：採用 **local fastembed TextCrossEncoder**，不使用外部 reranker 服務（例如另外部署一個 bge-reranker HTTP API）。

### 明確不動的部分
- `RerankService.rerank()` 的**對外簽章與回傳格式完全不變**（`(query: str, candidates: List[Dict], top_k: int) -> List[Dict]`），三個既有呼叫點——[rag.py:393-395](../../backend/routers/rag.py)（限定 `semantic_hybrid*` 家族才呼叫）、[retrieval.py:200-202](../../backend/routers/retrieval.py)（`if has_query and raw_results`，不限查詢法）、[evaluation.py:300,313-315](../../backend/routers/evaluation.py)（`is_semantic_hybrid_family` 判斷 + `fetch_k = max(top_k, RerankService.MAX_CANDIDATES)` 過取）——**全部零修改**，因為策略切換完全封裝在 `RerankService` 內部。
- `MAX_CANDIDATES = 20`／`CONTENT_PREVIEW_LEN = 500`（[rerank_service.py:14-15](../../backend/services/rerank_service.py)）兩個既有類別常數維持不變，`evaluation.py:301` 依賴 `RerankService.MAX_CANDIDATES` 做過取（over-fetch）的邏輯不受影響。
- 既有 LLM-based rerank 邏輯（[rerank_service.py:17-81](../../backend/services/rerank_service.py)）**完全保留**，`RERANK_STRATEGY` 預設值為 `"llm"`，代表**不改變預設行為**，只有使用者主動切換設定值才會啟用 cross-encoder 路徑。
- 既有「任何失敗優雅降級為 `candidates[:top_k]`」的行為契約（[rerank_service.py:79-81](../../backend/services/rerank_service.py)）在兩種策略下都必須保留。

## 2. 名詞定義

| 名詞 | 說明 |
|---|---|
| Cross-Encoder | 一種同時輸入 (query, document) 對，直接輸出相關性分數的模型架構，相較雙塔（bi-encoder）向量比對通常精準度更高，但計算成本也更高（每個候選都要單獨跑一次前向傳播）。 |
| `fastembed.TextCrossEncoder` | fastembed 套件提供的本地 cross-encoder 推論介面，`requirements.txt` 已有 `fastembed>=0.3.0`（目前用於 `SparseEmbeddingService` 的 SPLADE 稀疏向量，[sparse_embedding_service.py:3](../../backend/services/sparse_embedding_service.py)），本功能延伸使用同一套件的另一個模型類別，不新增額外重量級依賴。 |
| `RERANK_STRATEGY` | 新增設定值，`"llm"`（現行 Instruct LLM listwise 排序，預設值/零行為改變）或 `"cross_encoder"`（本地 fastembed cross-encoder 評分排序）。 |

## 3. 架構設計

### 3.1 依賴確認事項（實作前必須驗證）

`requirements.txt` 已有 `fastembed>=0.3.0`，但 `fastembed.rerank.cross_encoder.TextCrossEncoder`（或視安裝版本可能是 `fastembed.TextCrossEncoder`）需要在實作前先確認：
1. 目前容器內實際安裝的 `fastembed` 版本是否包含 `TextCrossEncoder` 類別（低於某版本可能沒有此 API，需要升級 `fastembed` 版本號）。
2. 執行 `TextCrossEncoder.list_supported_models()` 取得目前套件版本實際支援的模型清單，確認規劃中提議的模型名稱（見第 7 節）確實存在於清單中，避免程式寫死一個不存在的模型名稱導致啟動時下載失敗。

此驗證步驟需列入 Batch 0 的第一個 Checklist 項目，作為後續開發的前置條件。

### 3.2 新 Service：`backend/services/cross_encoder_rerank_service.py`

比照 `SparseEmbeddingService`（[sparse_embedding_service.py:8-18](../../backend/services/sparse_embedding_service.py)）的 lazy-load 單例模式：

```python
import logging
from typing import List, Dict, Any
from fastembed.rerank.cross_encoder import TextCrossEncoder  # 實際 import 路徑需依安裝版本驗證（見第 3.1 節）
from config import settings

logger = logging.getLogger("airag.cross_encoder_rerank")

class CrossEncoderRerankService:
    _model = None

    @classmethod
    def get_model(cls) -> TextCrossEncoder:
        if cls._model is None:
            logger.info(f"Initializing fastembed TextCrossEncoder model: {settings.RERANKER_MODEL} ...")
            cls._model = TextCrossEncoder(model_name=settings.RERANKER_MODEL)
            logger.info("fastembed TextCrossEncoder model initialized successfully.")
        return cls._model

    @classmethod
    def rerank_sync(cls, query: str, pool: List[Dict[str, Any]], top_k: int) -> List[Dict[str, Any]]:
        """
        同步 CPU-bound 推論，供 RerankService 以 asyncio.to_thread 包裝呼叫，
        避免阻塞事件迴圈（比照既有 SparseEmbeddingService.get_sparse_vector() 也是同步方法、
        由呼叫端自行決定是否需要 executor 包裝的既有慣例）。
        """
        model = cls.get_model()
        documents = [(item.get("content") or "")[:CONTENT_PREVIEW_LEN] for item in pool]
        scores = list(model.rerank(query, documents))
        scored_pool = list(zip(pool, scores))
        scored_pool.sort(key=lambda x: x[1], reverse=True)
        return [item for item, _ in scored_pool[:top_k]]
```

- 單例（class-level `_model`）比照 `SparseEmbeddingService._model`（[sparse_embedding_service.py:9](../../backend/services/sparse_embedding_service.py)）模式，整個進程生命週期只載入一次模型。
- `rerank()` 本身是 CPU-bound 同步呼叫（fastembed 底層是 ONNX Runtime 推論，非 async I/O），需要在 `RerankService` 呼叫處用 `asyncio.to_thread()` 包裝，避免阻塞 FastAPI 的事件迴圈（這是與現行 LLM-based 路徑用 `httpx.AsyncClient` 天生 async 的關鍵差異，需要特別處理，否則會拖慢同進程內其他並行請求）。

### 3.3 `RerankService.rerank()` 內部策略分支

`backend/services/rerank_service.py:18-81`，對外簽章不變，內部依 `settings.RERANK_STRATEGY` 分派：

```python
@classmethod
async def rerank(cls, query: str, candidates: List[Dict[str, Any]], top_k: int) -> List[Dict[str, Any]]:
    if not candidates or len(candidates) <= top_k:
        return candidates

    pool = candidates[:cls.MAX_CANDIDATES]

    if settings.RERANK_STRATEGY == "cross_encoder":
        return await cls._rerank_cross_encoder(query, pool, top_k, candidates)
    return await cls._rerank_llm(query, pool, top_k, candidates)

@classmethod
async def _rerank_cross_encoder(cls, query, pool, top_k, candidates):
    import asyncio
    from services.cross_encoder_rerank_service import CrossEncoderRerankService
    try:
        result = await asyncio.to_thread(CrossEncoderRerankService.rerank_sync, query, pool, top_k)
        logger.info(f"Cross-Encoder rerank 完成：候選 {len(pool)} 筆重排序後取前 {top_k} 筆。")
        return result
    except Exception as e:
        logger.warning(f"Cross-Encoder rerank 失敗，降級為保留原始順序: {e}")
        return candidates[:top_k]

@classmethod
async def _rerank_llm(cls, query, pool, top_k, candidates):
    # 既有 [rerank_service.py:24-81] 的完整邏輯原封不動搬移到這個私有方法內
    ...
```

- 原本 `rerank()` 方法體（[rerank_service.py:19-81](../../backend/services/rerank_service.py)）整段搬進 `_rerank_llm()`，`rerank()` 本身變成一個薄的策略分派層，**新增檔案行數但不改動既有邏輯的任何一行程式碼內容**，符合本專案「加法式」慣例（用新分支取代直接改寫既有邏輯）。
- 兩種策略共用同一個 `pool = candidates[:cls.MAX_CANDIDATES]` 過取邏輯與同一個「失敗降級為 `candidates[:top_k]`」的契約，確保 `evaluation.py` 依賴的過取行為（[evaluation.py:301](../../backend/routers/evaluation.py)）在兩種策略下一致。

## 4. API 設計

本功能**不新增/修改任何對外 API 欄位**——策略切換是全域 `config.py` 設定值，非每次請求可帶入的參數（除非使用者要求做成 per-request 可覆寫，見第 8 節待確認事項），對前端與 API 契約零影響。

## 5. 前端設計

本次不需要前端 UI 修改（策略是後端全域設定值，透過環境變數/`config.py` 切換，非使用者可在對話介面即時調整的參數）。若未來需要在管理介面（例如系統設定頁）暴露此開關，屬於後續擴充，非本次規劃範圍。

## 6. 執行流程設計

```
呼叫端（rag.py / retrieval.py / evaluation.py）呼叫 RerankService.rerank(query, candidates, top_k)
  （三處呼叫程式碼完全不變）
  │
  ▼
RerankService.rerank() 內部依 settings.RERANK_STRATEGY 分派
  │
  ├─ RERANK_STRATEGY == "llm"（預設值）
  │     → 走既有 _rerank_llm()，即目前 [rerank_service.py:17-81] 逐字元相同的邏輯
  │     → 呼叫地端 Instruct LLM 輸出 JSON ranking → 失敗降級為原始順序
  │
  └─ RERANK_STRATEGY == "cross_encoder"
        → 走新的 _rerank_cross_encoder()
        → asyncio.to_thread(CrossEncoderRerankService.rerank_sync, ...)
              → 單例載入 fastembed TextCrossEncoder 模型（僅第一次呼叫時載入）
              → model.rerank(query, documents) 對每個候選給出相關性分數
              → 依分數由高到低排序，取前 top_k
        → 任一環節失敗（模型載入失敗/推論例外）→ 降級為 candidates[:top_k]，log warning
  │
  ▼
回傳值格式（List[Dict] 且保留原始 candidates 的完整欄位結構）在兩種策略下完全一致
  → 下游 rag.py 組 context_parts / evaluation.py 組評估結果的程式碼無需區分策略來源
```

## 7. 新增設定值（`backend/config.py`）

| 變數 | 預設值 | 用途 |
|---|---|---|
| `RERANK_STRATEGY` | `"llm"` | Rerank 策略切換：`"llm"`（現行 Instruct LLM listwise，零行為改變）或 `"cross_encoder"`（本地 fastembed TextCrossEncoder） |
| `RERANKER_MODEL` | 待第 3.1 節驗證後定案（暫定候選 `"Xenova/ms-marco-MiniLM-L-6-v2"` 或 BAAI 系列多語模型，需對照實際安裝的 `fastembed` 版本 `TextCrossEncoder.list_supported_models()` 清單確認存在後才能定案） | fastembed cross-encoder 模型名稱 |

> `RERANKER_MODEL` 的預設值**不可在本文件直接定案**——必須先完成第 3.1 節「依賴確認事項」，實際查詢已安裝 `fastembed` 版本支援的模型清單後，選一個支援中文/多語（因知識庫內容含中文文件）且體積合理的模型，才能寫入 `config.py` 的預設值與 `.env.example`。

## 8. 決策紀錄／待確認事項

**已確認（本次規劃前提，使用者決策）**：
- **採用 local fastembed TextCrossEncoder**，不使用外部 reranker 服務（不新增額外部署的 HTTP 微服務），推論在後端進程內完成。
- `RerankService.rerank()` 對外簽章與三個既有呼叫點（`rag.py`/`retrieval.py`/`evaluation.py`）完全零修改，策略切換封裝在 Service 內部。
- 預設 `RERANK_STRATEGY="llm"`，即功能上線後預設行為不變，需要使用者主動切換設定值才會啟用新策略。

**待使用者確認的開放問題**：
1. **`RERANKER_MODEL` 確切模型名稱**（第 3.1／7 節已標註）：需要先在實際部署環境驗證 `fastembed` 版本與 `TextCrossEncoder.list_supported_models()` 回傳清單後才能定案，本文件先以「待驗證」標記，不假設一個可能不存在的模型名稱。
2. **`fastembed.rerank.cross_encoder.TextCrossEncoder` 的確切 import 路徑與 `rerank()` 方法簽章**：不同 fastembed 版本 API 可能有差異（例如 `model.rerank(query, docs)` 回傳值是 iterator 還是 list、是否需要先呼叫某個 `predict`），需要在 Batch 1 對照實際安裝版本的原始碼/官方文件確認後再定案介面呼叫方式。
3. **是否需要支援 per-request 覆寫**（例如 `ChatParams` 新增 `rerank_strategy` 讓使用者在對話測試頁臨時切換做 A/B 比較）：本文件預設不支援（全域設定值），若使用者需要在測試階段快速比較兩種策略效果，建議之後另外評估是否值得新增這個可調參數，屬於錦上添花，非必要功能。
4. **是否需要為兩種策略的排序結果新增可觀測性欄位**（例如在 SSE `step` 事件內容中標註本次 rerank 用的是哪種策略/耗時），方便使用者在 UI 上比較差異，待確認是否需要。

## 9. 分階段實作 Checklist

### Batch 0：依賴驗證（阻塞性前置步驟）
- [ ] 確認容器內 `fastembed` 實際安裝版本是否具備 `TextCrossEncoder`（或對應類別），必要時升級 `requirements.txt` 版本號
- [ ] 執行 `TextCrossEncoder.list_supported_models()` 取得目前版本支援的模型清單，選定一個支援中文/多語的模型，定案 `RERANKER_MODEL` 預設值（依第 8 節待確認事項 1）
- [ ] 確認 `TextCrossEncoder` 的 import 路徑與 `.rerank()` 方法實際簽章（依第 8 節待確認事項 2）

### Batch 1：後端核心邏輯
- [ ] `backend/config.py` 新增 `RERANK_STRATEGY`（預設 `"llm"`）／`RERANKER_MODEL`（依 Batch 0 驗證結果定案）
- [ ] `backend/services/cross_encoder_rerank_service.py`（新檔，`CrossEncoderRerankService` 單例模型載入 + `rerank_sync()`）
- [ ] `backend/services/rerank_service.py`：既有 `rerank()` 方法體搬移至新的 `_rerank_llm()` 私有方法（邏輯逐字元不變），`rerank()` 改為依 `RERANK_STRATEGY` 分派的薄封裝層，新增 `_rerank_cross_encoder()`（含 `asyncio.to_thread` 包裝與失敗降級）

### Batch 2：驗證與回歸測試
- [ ] 確認預設設定（`RERANK_STRATEGY="llm"`）下，`rag.py`/`retrieval.py`/`evaluation.py` 三處呼叫行為與功能上線前完全一致（回歸測試重點）
- [ ] 切換 `RERANK_STRATEGY="cross_encoder"` 後人工測試：確認模型僅在首次呼叫時載入（觀察日誌）、rerank 結果排序合理、模型載入失敗時能正確降級為原始順序不中斷對話

### Batch 3：文件更新
- [ ] `docs/03_API_CONTRACT.md`：本功能為後端全域設定值，通常無需修改 API 契約文件；若採納第 8 節待確認事項 3（per-request 覆寫）才需要補充
- [ ] `docs/DevelopmentProcess/NewFeatures.md`：實作完成後記錄本次新增（含最終定案的 `RERANKER_MODEL` 模型名稱與驗證過程摘要）
