# 圖片描述管線記憶體壓力改善規劃文件（GB10 統一記憶體）

> 狀態：**程式端四項已實作完成 / 待使用者以實際 PDF 驗收主機面行為**（2026-08-12，
> 變更明細見 [BackendCorrection.md](BackendCorrection.md)）
> ⚠️ **第 5 節的 vLLM 啟動參數調整不在程式改動範圍，仍需主機端配合，那才是記憶體超賣的主因。**
> 觸發事件：2026-08-12 執行圖片解析期間，DGX 主機進入「ping 得到但 SSH 連不進、未重開機」的假死狀態。
> 影響範圍：**中** —— 改動 [llm_service.py](../../backend/services/llm_service.py)（送模型前縮圖）、
> [config.py](../../backend/config.py)（新增縮圖上限、調整併發預設）、[docker-compose.yml](../../docker-compose.yml)（worker 記憶體上限）、
> `backend/requirements.txt`（補列 Pillow）。
> 核心目標：**讓圖片描述階段的記憶體用量可預測且有上界，撐爆時死的是容器而不是整台主機**。
>
> 關聯文件：[NewFeaturesPlan_IngestImageCaptionTimeoutPlan.md](NewFeaturesPlan_IngestImageCaptionTimeoutPlan.md)
> 處理的是同一條圖片管線的**時間**瓶頸（arq 逾時），本文處理的是**記憶體**瓶頸。兩者根因不同、
> 互不取代：前者已實作完成，但它只砍了輸出端（`max_tokens` 20480→4096）與圖片數量，
> **完全沒有觸及輸入端的記憶體成本**。

---

## 1. 問題現象

圖片解析過程中或接近結束時，DGX 主機出現：

- ping 正常回應
- SSH 完全連不進去
- 主機沒有自動重開機，服務仍在運作
- 事後無 process 被 OOM killer 終止的紀錄

## 2. 證據

### 2.1 核心 log

```
8月 12 06:12:41 kernel: NVRM: nvCheckOkFailedNoLog: Check failed: Out of memory
  [NV_ERR_NO_MEMORY] (0x00000051) returned from _memdescAllocInternal(pMemDesc) @ mem_desc.c:1359
8月 12 06:12:42 kernel: (同上，第二次)
```

- 全期間**沒有** `oom-kill` / `Killed process` 紀錄 —— Linux OOM killer 從未觸發，
  是 NVIDIA driver 自己的配置先失敗並回傳錯誤，因此不會有行程被殺、不會重開機。
- `06:05:56` 為 NVIDIA 模組載入時間（開機）。查詢 `02:00–03:00` 回報 `No entries`，
  代表當時 journal **未持久化、只保留當次開機**，最初那次事故的現場已遺失。
  已於 2026-08-12 建立 `/var/log/journal` 並重啟 `systemd-journald` 修正，後續事故才有完整紀錄。

### 2.2 硬體與記憶體現況

```
$ nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv
NVIDIA GB10, [N/A], [N/A]          ← 無獨立 VRAM 可回報，統一記憶體的特徵

$ free -h
               total   used   free   shared  buff/cache  available
Mem:           121Gi   88Gi   2.3Gi  6.0Gi   37Gi        32Gi
置換：          15Gi   418Mi  15Gi
```

`uname` 架構為 `aarch64`。硬體為 **DGX Spark（GB10 Grace-Blackwell）**，
CPU 與 GPU 共用同一個約 121GiB 可用的 LPDDR5X 記憶體池，**沒有獨立 VRAM**。

### 2.3 vLLM 啟動參數

```
vllm serve /home/giga/models/Qwen3.6-35B-A3B-FP8 --port 8080
  --quantization fp8 --max-model-len 92160 --max-num-seqs 7
  --gpu-memory-utilization 0.60 --reasoning-parser qwen3 --trust-remote-code
```

---

## 3. 根因分析

### 3.1 在統一記憶體架構下，「GPU 記憶體不足」與「主機記憶體不足」是同一件事

一般獨立顯卡機器上，`--gpu-memory-utilization` 佔用的是 VRAM，與系統 RAM 井水不犯河水；
GPU 爆掉不會影響 SSH。**GB10 沒有這條分界線**，vLLM 預留的每一 byte 都直接從作業系統可用的
121GiB 裡扣除。

### 3.2 記憶體帳本身就是超賣的

| 項目 | 用量 |
|:---|:---|
| `--gpu-memory-utilization 0.60` × 121GB | **72.6GB** |
| └ Qwen3.6-35B-A3B FP8 權重 | ≈ 35GB |
| └ KV cache 池 | ≈ 37GB |
| **剩給作業系統 + 6 個 Docker 容器 + llama.cpp** | **≈ 48GB** |

而 `free -h` 顯示在系統幾乎閒置時就已經 `used 88Gi`、`free 2.3Gi`。
88 − 72.6 ≈ **15GB** 才是圖片描述階段真正能動用的餘裕。

### 3.3 多模態前處理不在 `gpu-memory-utilization` 的預算之內

這是最關鍵的一點。`--gpu-memory-utilization` 只框住權重與 KV cache；
**圖片的解碼、resize、patch embedding 都是 vLLM 行程內的一般 host 配置**，走的是上述那 15GB。

一張 4000×3000 的掃描圖解成 raw RGB array 就是 36MB，前處理過程中會有數份副本，
再乘上兩層併發：

- 我方 `IMAGE_CAPTION_CONCURRENCY = 3`
- vLLM 端 `--max-num-seqs 7`

同時還要加上 worker 行程自己持有的成本：`extract_images_from_pdf()` 會把**整份 PDF
所有圖片的 bytes 同時留在記憶體**，`describe_image()` 再做 base64 編碼（1.33 倍）、
組 JSON 字串（再一份）、httpx 序列化（再一份）。

### 3.4 為什麼症狀是「SSH 死掉但 ping 活著」

餘裕耗盡後，核心開始瘋狂回收那 37GiB 的 page cache（swap 僅 15GiB 且幾乎未使用，
核心選擇 thrash cache 而非 swap）：

- **ping**：由核心在 softirq 情境直接回應，不需配置記憶體、不需磁碟 I/O → 照常運作
- **SSH**：需要 fork sshd、跑 PAM、寫 utmp、開 pty，每一步都要配置記憶體與 I/O → 全部卡住

因此表現為「機器還活著但進不去」。這不是網路問題，是記憶體問題。

### 3.5 與逾時問題（另一份規劃）的關係

同一條圖片管線的兩個不同瓶頸：

| | 逾時規劃 | 本規劃 |
|:---|:---|:---|
| 瓶頸 | 時間（arq job_timeout） | 記憶體（統一記憶體池） |
| 已處理 | 圖片**數量**（PDF 四道過濾）、**輸出**長度（`max_tokens` 20480→4096） | — |
| 未處理 | **輸入端的像素量** | 本規劃處理 |

逾時規劃的過濾會減少圖片張數，間接減輕記憶體壓力，但**單張高解析度圖的前處理成本完全沒動**。
一份只有 10 張圖但每張都是 6000×4000 的掃描件，仍然會打爆這台機器。

---

## 4. 定案設計（程式端三項）

### 4.1 送 vLLM 前把圖片長邊縮到 1536px

**這是三項中效益最大的一項**，因為它砍的正是第 3.3 節那塊「預算外」的前處理記憶體，
同時也減少 vision token 數量而降低 KV cache 用量。

#### 4.1.1 實作位置：`LLMService.describe_image()` 內，base64 編碼之前

| | |
|:---|:---|
| **決議** | 在 `describe_image()` 內縮圖，不在 `DocumentParser.extract_images_from_pdf()` 抽取時縮。 |
| **理由** | ① 磁碟保留**原始解析度**圖檔，前端顯示與日後需要更高解析度時仍可用；② `ingest_service` 與 [ImageCaptionRepairService](../../backend/services/image_caption_repair_service.py:125) 兩條路徑都經過 `describe_image_with_retry()` → `describe_image()`，在此處實作可讓兩者自動共用，不必各寫一次也不會漏。 |
| **代價** | 每次重新產生描述都會重複縮圖一次（CPU 成本，數十毫秒等級，可忽略）。 |

#### 4.1.2 實作細節

新增 `IMAGE_CAPTION_MAX_DIMENSION`（預設 **1536**）。**處理順序本身就是規格的一部分**，
不可調換（理由見 4.1.2.1）：

| # | 步驟 | 規則 |
|:---|:---|:---|
| 1 | 開圖 | `Image.open(BytesIO(image_bytes))` |
| 2 | **先判斷尺寸** | 長邊 ≤ 上限 → **直接回傳原始 bytes，完全不碰**。避免無謂 CPU 消耗與重新壓縮的畫質損失 |
| 3 | **再正規化色彩模式** | 見下表。**必須在 resize 之前** |
| 4 | 縮放 | 等比例縮至長邊 = 上限，`Image.Resampling.LANCZOS` |
| 5 | 編碼輸出 | **維持與輸入相同的格式**（PNG 進 PNG 出、JPEG 進 JPEG 出） |
| — | 全程例外 | **只記 warning 並沿用原圖繼續**，絕不可讓縮圖失敗變成「圖片描述失敗」 |

輸出格式必須維持不變：呼叫端傳入的 `mime_type` 會被寫進 data URI，擅自改變編碼格式
會造成 mime 與實際內容不一致。

##### 4.1.2.1 色彩模式：三個已實測確認的陷阱

**陷阱一：`RGBA` 直接 `convert("RGB")` 會把透明背景變成純黑。**

實測（Pillow 12.3.0）：

```python
Image.new('RGBA', (2, 2), (0, 0, 0, 0)).convert('RGB').getpixel((0, 0))
# -> (0, 0, 0)   全透明像素變成純黑
```

PDF/Word 抽出的流程圖、架構圖大量是「透明底 + 黑色線條文字」，一旦轉成黑底就是
**黑底黑字**，送給 vLLM 等於送一張全黑圖，描述必然失敗或胡謅。這比不縮圖還糟。

**陷阱二：`P`（調色盤）模式用 LANCZOS 縮放不會報錯，但結果是錯的。**

實測確認 `P` 模式圖片呼叫 `resize(..., LANCZOS)` 不拋例外，但插值運算作用在
**調色盤索引值**而非實際顏色上，輸出是亂的。因此模式正規化必須排在 resize **之前**。

**陷阱三：JPEG 不支援 alpha**，含透明度的圖直接存成 JPEG 會拋例外。

綜合以上，正規化規則：

| 原始模式 | 處理 | 理由 |
|:---|:---|:---|
| `P` / `PA` | 有透明資訊 → `RGBA`，否則 → `RGB` | 陷阱二：不可帶著調色盤進 resize |
| `LA` | → `RGBA` | 同上，且保留 alpha |
| `CMYK` | → `RGB` | 無 alpha，無黑底問題 |
| `RGBA` / `RGB` / `L` | 維持不變 | 可直接 resize |

輸出階段：

| 輸出格式 | 處理 |
|:---|:---|
| **PNG** | **保留 `RGBA`，不要轉 `RGB`** —— PNG 原生支援 alpha，轉了才會踩陷阱一 |
| **JPEG** | 若含 alpha，先建白底再合成：`Image.new("RGB", size, (255,255,255))` + `paste(img, mask=img.split()[-1])`。**不可**直接 `convert("RGB")` |

> **重採樣常數**：使用 `Image.Resampling.LANCZOS`（標準 Enum）。實測 Pillow 12.3.0 中
> 舊別名 `Image.LANCZOS` 仍存在且值相同（皆為 `1`），不會壞，但用 Enum 可避免日後棄用警告。

> 1536px 對「供語意檢索的描述」而言綽綽有餘 —— 足以辨識圖表結構、流程圖與大部分表格文字。
> 若日後發現密集表格的辨識率下降，此值可調高，但每提高一倍長邊、像素量就是四倍。

#### 4.1.3 相依性：Pillow 必須補進 `requirements.txt`

環境中已有 **Pillow 12.3.0**，但它目前是**傳遞相依（未列在 `backend/requirements.txt`）**。
直接使用而不補列，等於讓核心管線依賴一個沒有宣告的套件 —— 上游相依一改動就會 `ImportError`。

實作時必須同步在 `requirements.txt` 加入 `pillow>=10.0.0`。

### 4.2 `IMAGE_CAPTION_CONCURRENCY` 預設 3 → 1

第 3.3 節的兩層併發（我方 3 × vLLM `--max-num-seqs 7`）在僅 15GB 餘裕的機器上過於激進。

| | |
|:---|:---|
| **決議** | [config.py](../../backend/config.py) 的預設值由 `3` 改為 **`1`**。 |
| **理由** | 地端單台 vLLM 的吞吐量本來就固定，提高併發不會變快（見逾時規劃 2.7 節）；在統一記憶體機器上它還會**同時**放大前處理的記憶體峰值。降為 1 讓峰值成為單張成本而非三張疊加。 |
| **注意** | 這**只改預設值**，`.env` 若已明確設定 `IMAGE_CAPTION_CONCURRENCY=3` 會覆蓋它，需一併確認部署環境的 `.env`。 |
| **副作用** | 圖片描述總時間會拉長（約 3 倍）。逾時規劃已實作的「階段預算 + 降級」機制正是為此準備的：預算用盡的圖片會標記 `caption_failed` 而非讓整份文件失敗，事後再補。**兩份規劃在此處產生正向互補**。 |

### 4.3 docker-compose 的 `worker` 加上 `mem_limit`

目前 [docker-compose.yml](../../docker-compose.yml) 所有服務**都沒有任何記憶體限制**，
worker 可以一路吃到把 host 拖垮。

| | |
|:---|:---|
| **決議** | `worker` **與 `backend`** 服務各加上 `mem_limit: 8g`。 |
| **效果** | 撐爆時由核心 OOM-kill **容器內的行程**，任務失敗但**主機存活、SSH 進得去**。從「整台假死要靠 BMC 救」降級為「一個容器重啟」。 |
| **為何是 8g** | worker 需容納整份 PDF 的所有圖片 bytes + base64 副本 + chunk/向量。以 100 張圖估算約數百 MB 到 2GB，8g 留有充裕餘裕。若日後出現**正常文件**被 OOM-kill，應調高而非移除。 |
| **語法** | 本專案的 compose 檔無 `version:` 鍵，屬 Compose Spec，服務層級的 `mem_limit` 直接支援。 |

#### 4.3.1 `backend` 也要加（原列為未決事項 9.2，本次決議納入）

[ImageCaptionRepairService](../../backend/services/image_caption_repair_service.py:110) 在
**`airag-backend` 容器內**以同樣的 `IMAGE_CAPTION_CONCURRENCY` 併發呼叫
`describe_image_with_retry()`，具備與 worker 完全相同的記憶體風險。使用者一次觸發大批
「重新產生圖片描述」時，撐爆的會是 backend。

> **但 backend 的取捨方向與 worker 相反，值不可設得比 worker 低**：worker 被 OOM-kill
> 只是一個 ingest 任務失敗，backend 被 OOM-kill 則是**全體使用者的 API 與 RAG 對話同時中斷**。
> 因此採與 worker 相同的 `8g`，不採更嚴格的值。

#### 4.3.2 ⚠️ 必須同時補上 `restart` policy，否則是把問題換一種形式

現行 [docker-compose.yml](../../docker-compose.yml) 的**所有服務都沒有 `restart:` 設定**。

在這個前提下單獨加 `mem_limit` 會產生新的故障模式：容器被 OOM-kill 後**不會自動起來**，
服務就這樣安靜地掛著直到有人發現。對 backend 而言，這等於把「主機假死（至少會被立刻察覺）」
換成「API 靜默全掛」，不見得比較好。

**決議**：`backend` 與 `worker` 在加 `mem_limit` 的同時，一併加上
`restart: unless-stopped`。兩者必須成套，不可只做其一。

> 其餘服務（redis / mongodb / qdrant / frontend）同樣沒有 restart policy，屬既有問題，
> 本次不擴大範圍處理，另見第 9 節。

---

## 5. vLLM 端建議（記錄在案，不屬本 repo 範圍）

程式端三項改動能降低我方造成的壓力，但**記憶體超賣的主因在 vLLM 的啟動參數**，
這部分需由主機管理者調整：

| 參數 | 現值 | 建議 | 理由 |
|:---|:---|:---|:---|
| `--gpu-memory-utilization` | 0.60 | **0.45** | 歸還約 18GB 給作業系統。權重 35GB 不變，KV 池仍有約 19GB |
| `--max-model-len` | 92160 | **32768** | 應用端實際送不到 9 萬 token，過大只是讓單一請求能預約掉整個 KV 池 |
| `--max-num-seqs` | 7 | **4** | 直接壓低同時進行的多模態前處理數量 |
| `--limit-mm-per-prompt` | 未設 | **`image=1`** | 我方每次只送一張，設上限可擋掉異常情況 |

> 若調整 `--max-model-len`，需同步確認 [config.py](../../backend/config.py) 的 `VLLM_MAX_MODEL_LEN`
> （`chat_completion()` 用它自動裁切 `max_tokens`，避免超出模型上限被回 400）。

---

## 6. 參數定案表

| 參數 | 現值 | 定案值 | 位置 | 說明 |
|:---|:---|:---|:---|:---|
| `IMAGE_CAPTION_MAX_DIMENSION` | 無 | **1536** | `config.py` | 新增，送模型前的長邊上限（像素） |
| `IMAGE_CAPTION_CONCURRENCY` | 預設 3 | **1** | `config.py` | 改預設值。已確認 `backend/.env` 現為 `1`，兩者一致 |
| `worker.mem_limit` | 無 | **8g** | `docker-compose.yml` | 新增 |
| `backend.mem_limit` | 無 | **8g** | `docker-compose.yml` | 新增，見 4.3.1。**不可低於 worker** |
| `worker.restart` | 無 | **`unless-stopped`** | `docker-compose.yml` | 新增，見 4.3.2。與 `mem_limit` 成套 |
| `backend.restart` | 無 | **`unless-stopped`** | `docker-compose.yml` | 同上 |
| `pillow` | 未宣告 | **`>=10.0.0`** | `requirements.txt` | 補列現有的傳遞相依 |

---

## 7. 驗收方式

沿用專案慣例（使用者手動測試，AI 不自行開瀏覽器驗證）。

### 程式面

1. **縮圖正確性**：以合成大圖（例如 4000×3000 PNG）呼叫縮圖函式，確認
   長邊 = 1536、比例維持、格式未改變；再以 800×600 小圖確認**原樣回傳未重新編碼**
   （回傳的 bytes 應與輸入完全相同）。
2. **透明背景不變黑（4.1.2.1 陷阱一）**：以「透明底 + 黑色線條」的大尺寸 PNG 測試，
   縮圖後取樣背景像素，確認**不是 `(0,0,0)`**——PNG 應保留 alpha，若走 JPEG 路徑應為白色。
   這項不驗，問題會以「模型描述亂寫」的形式出現，很難回頭追到縮圖。
3. **調色盤模式（陷阱二）**：以 `P` 模式大圖測試，確認縮圖後顏色正常而非亂色。
4. **失敗不影響主流程**：餵入損壞的圖片 bytes，確認只有 warning、仍以原圖繼續送出描述，
   不會變成 `caption_failed`。
5. **相依宣告**：`pip install -r requirements.txt` 於乾淨環境可安裝並成功 import。

### 主機面（最關鍵）

6. **記憶體峰值**：以同一份 100+ 張圖的 PDF 重跑，期間於 DGX 上持續觀察，
   確認 `available` 的最低點明顯高於改動前，且**不再出現 `NVRM ... NV_ERR_NO_MEMORY`**：

   ```bash
   watch -n 2 free -h
   ```

   ```bash
   docker stats airag-worker airag-backend
   ```

7. **SSH 存活**：整個解析期間維持另一條 SSH 連線，確認不再斷線或卡死。
8. **mem_limit 與 restart 同時生效**（兩者成套，見 4.3.2）：

   ```bash
   docker inspect airag-worker airag-backend --format '{{.Name}} mem={{.HostConfig.Memory}} restart={{.HostConfig.RestartPolicy.Name}}'
   ```

9. **事故可追溯**：journal 已於 2026-08-12 持久化，若仍重現，
   `sudo journalctl -k --since "<事發時間>"` 這次要能撈到完整紀錄。

---

## 8. 明確不做的事

- **不把縮圖後的結果存回磁碟取代原圖**。原始解析度對前端顯示與日後重新描述仍有價值，
  且覆蓋原圖是不可逆操作。
- **不在 `extract_images_from_pdf()` 抽取階段縮圖**，理由見 4.1.1。
- **不調整 `IMAGE_CAPTION_TIMEOUT` / `IMAGE_CAPTION_MAX_TOKENS`**。它們屬逾時規劃的範圍且已定案，
  本次不重複改動。
- **不自行修改 vLLM 啟動參數**。屬主機管理範圍，僅在第 5 節記錄建議值。
- **不增加 swap**。swap 目前 15GiB 幾乎未使用，核心在此情境選擇 thrash cache 而非 swap，
  加大 swap 無助於解決根因，只會讓假死持續更久。
- **不對 `backend` / `worker` 以外的容器加 `mem_limit` 或 `restart`**
  （redis / mongodb / qdrant / frontend），屬既有問題，本次不擴大範圍。

---

## 9. 未決事項

1. **llama.cpp 的記憶體佔用尚未確認。** `.env` 指向 8081（embedding）與 8082（instruct）
   兩個 llama.cpp 服務，它們同樣吃這塊統一記憶體，但先前的 `ps` 只 grep 了 vllm。
   待補查後才能確定第 5 節的 `--gpu-memory-utilization 0.45` 是否足夠、或需壓得更低：

   ```bash
   ps -eo pid,rss,comm,args --sort=-rss | head -12
   ```

2. **部署機（DGX）上的 `.env` 內容仍無法直接確認。** 本機 `backend/.env` 已核對為
   `IMAGE_CAPTION_CONCURRENCY=1`，與本次的新預設值一致；但 `.env` 為 git-ignored，
   DGX 上是否為同一份取決於部署方式。套用後建議實地確認：

   ```bash
   docker exec airag-worker python -c "from config import settings; print(settings.IMAGE_CAPTION_CONCURRENCY, settings.IMAGE_CAPTION_MAX_DIMENSION)"
   ```

   > ⚠️ **不可用 `docker exec airag-worker env | grep IMAGE_CAPTION` 驗證。**
   > `.env` 是由 `config.py` 的 `load_dotenv()` 在 **Python 行程內**載入 `os.environ`，
   > 不是容器層級的環境變數；`docker exec ... env` 另開一個行程，看不到這些值，
   > 會誤判成「設定沒生效」。必須實際 import `settings` 才是應用真正讀到的值。

---

## 10. 覆核紀錄（2026-08-12）

針對實作細節與邊界條件的第二輪覆核，逐條核對程式碼與實機行為後：

| 提議 | 判定 | 說明 |
|:---|:---|:---|
| RGBA→RGB 透明背景變黑 | ✅ **採納** | 實測確認 `(0,0,0,0)` → `(0,0,0)`。已改寫 4.1.2.1，PNG 保留 alpha、JPEG 合成白底 |
| `Image.Resampling.LANCZOS` | ✅ 採納 | 實測 Pillow 12.3.0 舊別名仍可用且值相同（皆為 `1`），不會壞；改用 Enum 純為前瞻性 |
| `.env` 已是 `1` | ✅ 採納（修正 9.3） | 核對本機 `backend/.env` 確為 `1`。原未決事項改寫為「DGX 上的 `.env` 仍待實地確認」 |
| `backend` 也加 `mem_limit` | ✅ **採納**（4.3.1） | 但**值不可低於 worker**：backend 被 OOM-kill 是全體使用者的 API 中斷，比一個 ingest 任務失敗嚴重得多，因此不採「4g」而與 worker 同為 8g |

**覆核過程中另外發現兩項提議未涵蓋的問題，一併納入：**

1. **`P`（調色盤）模式用 LANCZOS 縮放不報錯但結果錯亂**（4.1.2.1 陷阱二）。
   實測確認插值作用在調色盤索引值上。這決定了「模式正規化必須排在 resize 之前」，
   也就是 4.1.2 的處理順序本身即為規格。
2. **compose 檔完全沒有 `restart` policy**（4.3.2）。單獨加 `mem_limit` 會把
   「主機假死」換成「容器被 OOM-kill 後靜默不起」，對 backend 而言不見得比較好。
   `mem_limit` 與 `restart: unless-stopped` 必須成套。

---

## 11. 建議實作順序

```
① requirements.txt 補 pillow  →  ② llm_service.py 縮圖  →  ③ config.py 兩項參數
                                                              ↓
                                          ④ docker-compose.yml mem_limit + restart
                                                              ↓
                                          重建並重啟 backend / worker 容器後，以同一份 PDF 驗收
```

四項皆為低風險獨立改動，可一次提交。實作完成後依 AGENT.md 規範記錄於
`docs/DevelopmentProcess/BackendCorrection.md`。
