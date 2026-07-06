# 部署疑難排解紀錄 (Deployment Troubleshooting)

> 本文件記錄 AiRAG 在生產環境部署時遇到的問題、診斷過程與解決方案，供未來維護參考。

---

## [2026-06-30] Oracle Instant Client 無法載入 — DPI-1047 / Thin Mode 降級

### 問題描述

在 Ubuntu 生產伺服器（ARM64 架構）以 Docker Compose 部署後端後，Oracle 資料庫連線失敗，錯誤訊息如下：

```
DPY-6005: cannot connect to database
DPY-3010: connections to this database server version are not supported by python-oracledb in thin mode
DPI-1047: Cannot locate a 64-bit Oracle Client library:
  "/opt/oracle/lib/libclntsh.so: cannot open shared object file: No such file or directory"
```

本地 Windows Docker Desktop 環境可以正常連線。

---

### 根本原因（分三個階段診斷）

#### 原因一：Oracle 官方下載需要授權，curl 無法直接取得 zip

原始 Dockerfile 使用 `curl -fL` 直接下載 Oracle 官方連結：

```dockerfile
curl -fL https://download.oracle.com/otn_software/linux/instantclient/1922000/instantclient-basic-linux.x64-19.22.0.0.0dbru.zip
```

Oracle 所有下載連結均需通過 OTN License Agreement 授權頁，`curl` 只會下載到 HTML 頁面，導致 `unzip` 失敗，`libclntsh.so` 從未真正安裝。

**修正**：改為手動下載 zip 後，用 `COPY` 將其放入容器。

---

#### 原因二：`ln -s` symlink 靜默失敗

改為 COPY zip 後，Dockerfile 使用以下邏輯建立 symlink：

```dockerfile
ln -s "$IC_DIR" /opt/oracle/lib 2>/dev/null || true
```

`|| true` 使 `ln -s` 的失敗被完全靜默忽略，`/opt/oracle/lib` 從未建立，`libclntsh.so` 無法被找到。

**修正**：改用 `mv` 直接重命名目錄，確保路徑必定存在：

```dockerfile
mv /opt/oracle/instantclient_19_* /opt/oracle/lib
```

---

#### 原因三：Ubuntu 主機為 ARM64，但使用了 x86_64 的 Instant Client

**關鍵診斷指令**：

```bash
# 確認容器內 libclntsh.so 的架構
docker exec airag-backend ldd /opt/oracle/lib/libclntsh.so
# 輸出: not a dynamic executable  ← ARM64 系統無法解析 x86_64 ELF

# 確認主機架構
docker exec airag-backend find /usr/lib -name "libaio*"
# 輸出: /usr/lib/aarch64-linux-gnu/libaio.so.1  ← 確認為 ARM64
```

`libclntsh.so` 確實存在，但為 x86_64 binary，在 ARM64 上無法被 `dlopen`，表現為 `No such file or directory`。

此外，backend/ 目錄同時存在 `arm64` 和 `x64` 兩個 zip：

```
instantclient-basic-linux.arm64-19.31.0.0.0dbru.zip
instantclient-basic-linux.x64-19.31.0.0.0dbru.zip
```

Dockerfile 的 glob `COPY instantclient-basic-linux.*.zip /tmp/instantclient.zip` 匹配兩個檔案時，**字母排序較後的 `x64` 覆蓋了 `arm64`**，最終使用的是 x86_64 版本。

**修正**：刪除 Ubuntu 伺服器上的 x64 zip，只保留 arm64 zip。

---

### 最終解決方案

#### 1. 下載正確架構的 Oracle Instant Client

| 主機架構 | 下載連結 |
|:---|:---|
| x86_64（一般 PC/Server） | https://www.oracle.com/database/technologies/instant-client/linux-x86-64-downloads.html |
| ARM64（aarch64） | https://www.oracle.com/database/technologies/instant-client/linux-arm-aarch64-downloads.html |

下載 **Basic Package** zip，放入 `backend/` 目錄（此路徑已加入 `.gitignore`，不會被 commit）。

#### 2. 確保 backend/ 只有一個 zip 檔

```bash
# 確認只有一個匹配的 zip
ls backend/*.zip
```

若有多個 zip，只保留對應伺服器架構的那一個，刪除其他的。

#### 3. Dockerfile（最終版本關鍵段落）

```dockerfile
# 安裝 Oracle Instant Client 19c（Thick Mode）
# 依照 Ubuntu 主機架構下載對應 zip 放至 backend/ 目錄（需接受 OTN 授權）：
# x86_64: https://www.oracle.com/database/technologies/instant-client/linux-x86-64-downloads.html
# ARM64:   https://www.oracle.com/database/technologies/instant-client/linux-arm-aarch64-downloads.html
ENV ORACLE_HOME=/opt/oracle
COPY instantclient-basic-linux.*.zip /tmp/instantclient.zip
RUN mkdir -p /opt/oracle \
    && unzip /tmp/instantclient.zip -d /opt/oracle \
    && mv /opt/oracle/instantclient_19_* /opt/oracle/lib \
    && echo "/opt/oracle/lib" > /etc/ld.so.conf.d/oracle-instantclient.conf \
    && ldconfig \
    && rm /tmp/instantclient.zip

ENV LD_LIBRARY_PATH=/opt/oracle/lib
ENV PATH=/opt/oracle/lib:$PATH
ENV ORACLE_CLIENT_LIB_DIR=/opt/oracle/lib
```

#### 4. Python 程式碼（`backend/routers/database_indexing.py`）

```python
import os

oracle_init_error = None
try:
    lib_dir = os.environ.get("ORACLE_CLIENT_LIB_DIR")
    if lib_dir:
        oracledb.init_oracle_client(lib_dir=lib_dir)
    else:
        oracledb.init_oracle_client()
    logger.info("Oracle Instant Client initialized successfully (Thick Mode enabled).")
except Exception as e:
    oracle_init_error = e
    logger.warning(f"Failed to initialize Oracle Instant Client: {e}. Falling back to Thin Mode.")
```

#### 5. 重新部署指令（Ubuntu）

```bash
# 確認只有一個 zip
ls ~/code/AiRAG/backend/*.zip

# 重新 build 並啟動
cd ~/code/AiRAG
docker compose build backend --no-cache
docker compose up -d backend

# 確認成功
docker logs airag-backend 2>&1 | grep -i oracle
# 預期輸出: Oracle Instant Client initialized successfully (Thick Mode enabled).
```

---

### 診斷指令速查

```bash
# 確認容器內 Oracle Client 是否存在
docker exec airag-backend find /opt/oracle -name "libclntsh*"

# 確認 libclntsh.so 是否可被系統載入（ARM64 載 x64 會顯示 "not a dynamic executable"）
docker exec airag-backend ldd /opt/oracle/lib/libclntsh.so

# 確認主機架構
docker exec airag-backend find /usr/lib -name "libaio*"

# 確認環境變數
docker exec airag-backend env | grep -E "ORACLE|LD_LIBRARY"

# 確認日誌
docker logs airag-backend 2>&1 | grep -i oracle
```

---

### 注意事項

- Oracle Instant Client zip **不可 commit 進 git**（`.gitignore` 已加入 `*.zip`）
- 每次換伺服器或換 CPU 架構時，需重新準備對應架構的 zip
- ARM64 版 Oracle Instant Client 最低版本為 **19.19**，建議使用最新版
- `oracledb.init_oracle_client()` 在整個 Python 進程中只能被呼叫一次
