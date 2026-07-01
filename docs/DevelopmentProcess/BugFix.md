<!-- BUG修正(最新紀錄放最前面) -->

## 2026-07-01 修正雙階段檢索 (Two-Step Search) 關聯檔案全量載入與 context 稀釋問題

### 問題描述
原本的雙階段檢索在第一階段召回核心點位後，第二階段針對其 `links_to` 指定的關聯檔案，是採用無條件的 Qdrant Scroll API 直接把關聯檔案的所有向量點位（高達 50 筆 Chunks）全部抓取出來。這會導致關聯檔案中的大量無關點位（如非對應資料庫列/非對應段落）全部被塞入 RAG 上下文中，造成嚴重的 Context 稀釋與 Token 浪費。

### 解決方案
1. **二次檢索由 Scroll 改為語意/混合搜尋**：
   - 修改 `backend/services/qdrant_service.py` 中的 `search_similar_two_step` 方法。
   - 當召回關聯檔案 (`all_links`) 後，不再使用無差別的 `client.scroll`。
   - 改為對 Qdrant 進行過濾搜尋（以 `filename` 或 `custom_id` 匹配 `all_links` 作為 `should` 條件），並使用與使用者問題相同的 `query_vector`、`query_text` 進行密集與稀疏 Hybrid 檢索（支援 exact keyword boost 加速）。
   - 在密集向量 Prefetch 中套用 `score_threshold=score_threshold`，確保只有與查詢內容高度相關的鄰居片段才會被召回，完全隔絕無關點位。
2. **調降預設鄰居召回上限**：
   - 將 `neighbor_limit` 參數的預設值由 `50` 調降至 `10`，以防止過多邻居片段稀釋主要檢索脈絡，提升 LLM 回答的精準度。
3. **單元測試相容**：
   - 無查詢向量時，系統會自動安全降級為 Scroll，以確保原有單元測試程式碼及無向量檢索場景的運作正常。

### 修改檔案
- `backend/services/qdrant_service.py`


## 2026-06-30 修正 Oracle Instant Client CPU 架構不符（x86_64 zip 安裝於 ARM64 Ubuntu）

### 問題描述
Ubuntu 生產伺服器架構為 **ARM64（aarch64）**，但 backend/目錄放置的是 x86_64 版本的 Instant Client zip：
`instantclient-basic-linux.x64-19.31.0.0.0dbru.zip`

Docker build 成功（mv、ldconfig 均正常），`libclntsh.so` 也存在於容器的 `/opt/oracle/lib/` 中，
但 Python `oracledb.init_oracle_client()` 嘗試 `dlopen` 時，動態連結器因架構不符（ELF class mismatch）
無法載入，表現為 `No such file or directory`，導致退回 Thin Mode。

診斷指令確認：
```
/usr/lib/aarch64-linux-gnu/libaio.so.1  ← 系統為 ARM64
```

### 解決方案
1. **下載 ARM64 版本的 Oracle Instant Client**：
   前往 https://www.oracle.com/database/technologies/instant-client/linux-arm-aarch64-downloads.html
   下載 `instantclient-basic-linux.arm64-19.*.zip`，替換舊的 x64 zip。
2. **更新 Dockerfile COPY 的 glob pattern**：
   由 `instantclient-basic-linux.x64-19.*.zip` 改為 `instantclient-basic-linux.*.zip`，
   讓同一個 Dockerfile 能兼容 x64 和 arm64 兩種版本的 zip 檔。
3. **重新 build**：`docker compose build backend --no-cache && docker compose up -d backend`

### 修改檔案
- `backend/Dockerfile`



### 問題描述
第二次部署後 Oracle 連線仍失敗，錯誤與上次相同：
`DPI-1047: Cannot locate a 64-bit Oracle Client library: "/opt/oracle/lib/libclntsh.so"`
雖然 COPY 步驟成功（zip 已放入 backend/ 目錄且 Docker build 未報錯），但容器啟動時 `/opt/oracle/lib` 仍不存在。
根本原因：Dockerfile 中使用 `ln -s "$IC_DIR" /opt/oracle/lib 2>/dev/null || true` 建立 symlink，由於後面的 `|| true` 使得 `ln -s` 的失敗（可能因為路徑已存在或其他原因）被完全靜默忽略，`/opt/oracle/lib` 從未真正建立。

### 解決方案
1. **Dockerfile 改用 `mv` 直接重命名**：
   - 移除 `ln -s` 邏輯，改用 `mv /opt/oracle/instantclient_19_* /opt/oracle/lib` 直接將解壓出的目錄重命名，確保 `/opt/oracle/lib/libclntsh.so` 路徑必定存在。
   - 新增環境變數 `ORACLE_CLIENT_LIB_DIR=/opt/oracle/lib`。
2. **Python 明確傳入 `lib_dir`**：
   - 修改 `backend/routers/database_indexing.py`，加入 `import os`，讀取 `ORACLE_CLIENT_LIB_DIR` 環境變數，若存在則以 `oracledb.init_oracle_client(lib_dir=lib_dir)` 明確指定路徑；本地 Windows 開發環境無此環境變數時仍走自動偵測。

### 修改檔案
- `backend/Dockerfile`
- `backend/routers/database_indexing.py`





### 問題描述
當啟用 Thick Mode 連線時，`oracledb` 在 Linux 底下讀取 `ORACLE_HOME` 時，預設會從該路徑下的 `lib/` 子目錄中尋找 `libclntsh.so`。然而在原先的 `Dockerfile` 中，Oracle Instant Client 解壓後直接移到了 `/opt/oracle/instantclient` 下，沒有建立 `lib/` 目錄，導致在連線時拋出以下錯誤：
`Cannot locate a 64-bit Oracle Client library: "/opt/oracle/instantclient/lib/libclntsh.so: cannot open shared object file: No such file or directory"`

### 解決方案
修改 `backend/Dockerfile`，重構 Instant Client 的目錄放置結構：
1. 將 `ORACLE_HOME` 指向 `/opt/oracle`，並將 Instant Client 檔案解壓移至 `/opt/oracle/lib` 目錄中，使其完全匹配標準 Oracle 的 `/lib` 子資料夾結構。
2. 將動態連結器配置 `/etc/ld.so.conf.d/oracle-instantclient.conf` 與環境變數 `LD_LIBRARY_PATH` 調整為 `/opt/oracle/lib`，確保系統與 `python-oracledb` 能正確抓取到 `libclntsh.so`。

### 修改檔案
- `backend/Dockerfile`
