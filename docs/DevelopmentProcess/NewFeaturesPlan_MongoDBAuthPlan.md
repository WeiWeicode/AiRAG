# MongoDB 存取認證與最小權限帳號規劃文件

> 狀態：**已施作完成（2026-08-13）** —— 認證已啟用、兩個帳號建立完成，核心驗收條件（驗證 5 / 6 / 7）皆實測通過，見第 9 節。後續追蹤項目見第 7 節第 2、4、7、8 項。
> 預估效益：**高** —— 目前 MongoDB 完全未啟用認證且 27017 對內網開放，任何能連到該主機的人都可無密碼讀寫全部資料（含 `external_api_keys` 的金鑰雜湊、`user_profiles` 人員資料、全部對話與稽核紀錄）。本案封住此缺口，並為外部應用（KB）建立最小權限唯讀帳號。
> 影響範圍：**高（以部署層為主，另含一處必要的 Python 修改）** —— 需修改 [docker-compose.yml](../../docker-compose.yml) 並重啟 `mongodb` / `backend` / `worker` 三個容器。啟用認證後未帶憑證的連線一律被拒，**必須安排維護時間窗，不可在營運時段直接施作**。

> **需求來源**：GigaSolar KB 專案規劃「AI 歷史訊息」功能（見該 repo `docs/DevelopmentProcess/AI_CHAT_HISTORY_PLAN.md`），KB 後端需唯讀存取本專案 MongoDB 的 `external_chat_logs` collection。評估連線方式時發現本專案 MongoDB 未啟用認證，遂另立本案處理。**KB 端的需求只是觸發點，本案本身是獨立的安全性修補，即使 KB 功能不做也建議執行。**

> **連線本身不需要改程式碼**：[backend/models/mongodb.py:192](../../backend/models/mongodb.py:192) 是 `AsyncIOMotorClient(settings.MONGODB_URL)`，帳號密碼直接由連線字串帶入；`settings.MONGODB_DATABASE` 由 `client[...]`（`:195`）另外指定，不受連線字串變更影響。
>
> **但有且僅有一處 Python 必須改**：同檔 [:191](../../backend/models/mongodb.py:191) 的 `logger.info(f"Connecting to MongoDB at: {settings.MONGODB_URL}")` 會把整串連線字串原樣寫入容器 log。憑證加進去之後，這行等於把 `airag_admin` 的 root 密碼明文留在 `docker logs airag-backend` / `airag-worker` 裡——缺口從「無認證」變成「密碼躺在 log」，並未真正修補。見 Step 4.3。

---

## 1. 問題背景與現狀

### 1.1 現狀：MongoDB 未啟用認證

[docker-compose.yml:73-83](../../docker-compose.yml:73) 的 `mongodb` 服務定義：

```yaml
  mongodb:
    image: mongo:7
    container_name: airag-mongodb
    ports:
      - "27017:27017"
    volumes:
      - mongo_data:/data/db
    environment:
      - MONGO_INITDB_DATABASE=airag
    networks:
      - airag-network
```

* **沒有 `MONGO_INITDB_ROOT_USERNAME` / `MONGO_INITDB_ROOT_PASSWORD`**，也沒有 `command: ["--auth"]` → `mongo:7` 官方映像在此情況下以**無認證模式**啟動。
* **`ports: - "27017:27017"` 將 27017 publish 到宿主機**，等於對公司內網開放。

兩者相加的實際結果：**內網任何一台機器都能以 `mongosh mongodb://<host>:27017` 直接連入，無需任何憑證，且擁有完整讀寫與刪除權限**（含 `dropDatabase`）。

### 1.2 暴露的敏感資料

`airag` database 內目前登記於 [backend/models/mongodb.py:18-36](../../backend/models/mongodb.py:18) 的 Beanie Document 共 20 個 collection，其中風險較高者：

| Collection | 內容 | 風險 |
|:---|:---|:---|
| `external_api_keys` | 外部 API 金鑰的 **bcrypt 雜湊** 與 `scope` | 雜湊外洩可離線破解；`is_active` 可被直接改寫，等同繞過金鑰管理 |
| `app_registrations` | 各外部應用的登錄資訊、`base_url`、`report_mode` | 可被竄改指向惡意端點；`is_active` 遭改動曾造成同步全面失效（見 [RAG_SYNC_PLAN.md](RAG_SYNC_PLAN.md) v1.9） |
| `user_profiles` / `departments` | 人員與部門資料 | 個資 |
| `external_chat_logs` | 各外部應用使用者的提問與 AI 回答全文、身分快照 | 可完整還原他人問過什麼 |
| `chat_sessions` / `chat_messages` | 內部使用者對話 | 同上 |
| `database_configs` / `db_query_profiles` | **關聯式資料庫連線設定**（`semantic_db_query` 用） | 明碼存放其他系統的 DB 帳密，見下方 |

> ⚠️ **已確認（不再是待確認事項）**：`database_configs` **確實以明碼儲存資料庫密碼**。[backend/models/database_config.py:12](../../backend/models/database_config.py:12) 是裸 `password: str`，[backend/routers/database_indexing.py:178](../../backend/routers/database_indexing.py:178)、[:211](../../backend/routers/database_indexing.py:211) 直接寫入 `request.password`，全流程無任何加解密。
>
> 因此 1.1 的缺口等於**同時外洩其他系統（SQL Server / Oracle）的資料庫憑證**，本案優先度依此上調。另注意：啟用認證只擋住「未授權的外部連線」，並未解決明碼儲存本身——持有 `airag_admin` 者、以及任何一份 dump 檔仍看得到這些密碼，該項應另案處理（見第 7 節第 7 項）。

### 1.3 為什麼不能只靠「加環境變數」修掉

`mongo:7` 官方映像的 `MONGO_INITDB_ROOT_USERNAME` / `MONGO_INITDB_ROOT_PASSWORD` **只在資料目錄為空時（首次初始化）才會建立帳號**。本專案的 `mongo_data` volume 已有既有資料，直接加上這兩個變數：

* 不會建立任何帳號；
* 若同時開啟 `--auth`，結果是**一個啟用了認證但沒有任何帳號的資料庫**——所有服務連不上，且無法登入修復（只能重啟為無 auth 模式救援）。

**因此正確順序必為：先在無認證狀態下手動建立帳號 → 再開啟認證。** 這是本案最容易做錯的一步。

---

## 2. 目標與非目標

### 2.1 目標

1. MongoDB 啟用認證（`--auth`），未帶憑證一律拒絕連線。
2. 建立管理者帳號供 AiRAG 自身服務（`backend` / `worker`）使用。
3. 建立 **KB 專用唯讀帳號**，權限僅限 `airag.external_chat_logs` 的 `find`，不得讀取其他 collection、不得寫入。
4. Python 程式碼僅動一處：連線 log 的密碼遮蔽（Step 4.3），不觸及任何商業邏輯。

### 2.2 非目標（本案不處理）

* 不改變 27017 的 port 對外開放狀態（見第 7 節第 2 項的後續建議）。
* 不導入 TLS / 傳輸加密。
* 不重新設計 AiRAG 內部各服務的權限分離（`backend` 與 `worker` 共用同一組管理者帳號）。
* 不處理既有 `external_api_keys` 金鑰是否需要輪替（見第 7 節第 4 項）。

---

## 3. 權限設計

### 3.1 帳號與角色矩陣

| 帳號 | 建立於 | 角色 | 可存取範圍 | 使用者 |
|:---|:---|:---|:---|:---|
| `airag_admin` | `admin` db | 內建 `root` | 全部 | AiRAG `backend`、`worker` 容器，以及維運人工操作 |
| `kb_reader` | `airag` db | 自訂 `readExternalChatLogs` | 僅 `airag.external_chat_logs` 的 `find` | GigaSolar KB 後端 |

### 3.2 為什麼 KB 帳號不用內建的 `read` 角色

內建 `read` 角色的授權範圍是**整個 database**，KB 會連帶讀得到 `external_api_keys`（金鑰雜湊）、`user_profiles`（個資）、`database_configs`（連線設定）等與其需求完全無關的資料。KB 實際只需要一個 collection 的讀取，因此改用自訂角色把資源範圍縮到 collection 層級：

```js
privileges: [
  { resource: { db: "airag", collection: "external_chat_logs" }, actions: ["find"] }
]
```

`actions` 只給 `find`：沒有 `insert` / `update` / `remove` / `dropCollection`，也沒有 `listCollections`（KB 端 Node driver 直接指名 collection 查詢，不需要列舉權限）。

> 這也呼應 [RAG_SYNC_PLAN.md](RAG_SYNC_PLAN.md) 第 9 節第 6 項的技術債檢討——該處「AiRAG 直連 KB DB 暫用 `sa` 帳號」正是反例，本案不應重蹈。

### 3.3 收斂到欄位層級的後續選項（本案不做）

自訂角色的最小資源單位是 collection，**無法限制欄位**——`kb_reader` 讀得到 `external_chat_logs` 的每一個欄位（含身分快照與問答全文）。若日後確認 KB 端其實只需要部分欄位，可在 `airag` db 建立一個只投影必要欄位的 read-only view，改授權該 view 即可：授權 view 的 `find` **不需要**同時授權底層 collection，能真正把欄位擋掉。

本案先以 collection 層級收斂為準（相較現況已是巨大改善），欄位層級待 KB 端功能定案後再評估。

---

## 4. 施作步驟

> **前置**：安排維護時間窗。步驟 4 之後、步驟 5 完成之前，AiRAG 全服務不可用。

### Step 0 — 維護時間窗前的前置確認（不可等到當下才做）

**0.1 確認 `mongodump` 存在於映像中**：MongoDB 4.4 起 database tools 已從 server 套件拆出，`mongo:7` 映像**不保證**內含 `mongodump`。請提前實測：

```bash
docker exec airag-mongodb which mongodump mongosh
```

若 `mongodump` 不存在，退路二選一：(a) 另跑一個含 tools 的容器接同一個網路做 dump；(b) 直接停容器後複製 `mongo_data` volume。**不要在維護時間窗當下才發現沒有這個指令。**

**0.2 決定密碼字元集**：`MONGODB_URL` 是 URI，密碼中的 `@ : / ? # [ ] %` 會破壞解析（motor 會直接拋 `InvalidURI`），而寫進宿主機 `.env` 的 `$` 會被 docker compose 再展開一次（需寫成 `$$`）。**本案兩組密碼一律限用英數與 `-` `_` `.`**，長度取足即可，不要為了字元多樣性換來連不上。若非得用特殊字元，連線字串中必須 percent-encode。

### Step 1 — 施作前備份（必做）

```bash
docker exec airag-mongodb mongodump --db airag --archive=/data/db/airag_backup_before_auth.archive
```

```bash
docker cp airag-mongodb:/data/db/airag_backup_before_auth.archive /var/backups/airag/airag_backup_before_auth.archive
```

> ⚠️ **這份 dump 是本案敏感度最高的單一檔案**：內含 `database_configs` 的明碼 DB 帳密（見 1.2）、`external_api_keys` 的 bcrypt 雜湊、全部人員資料與對話紀錄。
>
> * **落點不可放在專案目錄**（原指令的 `./` 多半就是 repo 根目錄，有隨手 commit 的風險）。請放到版控範圍外的受管路徑。
> * 驗證全數通過後即刪除，或移入既有的備份保管機制；不要長期留在宿主機家目錄。
> * 同理，Step 1 第一段留在 `/data/db/` 內的那份也要一併刪除（該路徑就是 `mongo_data` volume）。

### Step 2 — 在「仍為無認證」狀態下建立管理者帳號

```bash
docker exec -it airag-mongodb mongosh
```

```js
use admin
db.createUser({
  user: "airag_admin",
  pwd: passwordPrompt(),
  roles: [ { role: "root", db: "admin" } ]
})
```

> 使用 `passwordPrompt()` 而非把密碼寫在指令裡，避免密碼進入 shell history。密碼字元集依 Step 0.2 的限制。
>
> ⚠️ **`pwd` 若改寫成字面值，一定要加引號**：mongosh 就是 JavaScript，`pwd: mySecret123`（未加引號，此處僅為示意，非實際密碼）會被當成變數名稱並拋 `ReferenceError`，**`createUser` 整個沒有執行、帳號不會建立**。若沒注意到這個錯誤就往下做，會在 Step 5 重建容器後才以 `Authentication failed` 爆出來，且症狀與「密碼打錯」完全一樣、極易誤判（實際發生過一次）。
>
> **每個 `createUser` / `createRole` 都要確認回傳 `{ ok: 1 }` 再往下做。** 建完後可用 `db.getSiblingDB("admin").system.users.find({}, {user:1, db:1, _id:0}).toArray()` 核對兩個帳號確實存在且 db 正確。

### Step 3 — 建立 KB 專用唯讀角色與帳號

```js
use airag
db.createRole({
  role: "readExternalChatLogs",
  privileges: [
    { resource: { db: "airag", collection: "external_chat_logs" }, actions: ["find"] }
  ],
  roles: []
})
```

```js
db.createUser({
  user: "kb_reader",
  pwd: passwordPrompt(),
  roles: [ { role: "readExternalChatLogs", db: "airag" } ]
})
```

### Step 4 — 修改 `docker-compose.yml`

**4.1 `mongodb` 服務（[docker-compose.yml:73](../../docker-compose.yml:73)）新增 `command`：**

```yaml
  mongodb:
    image: mongo:7
    container_name: airag-mongodb
    command: ["--auth"]
    ports:
      - "27017:27017"
    volumes:
      - mongo_data:/data/db
    environment:
      - MONGO_INITDB_DATABASE=airag
    networks:
      - airag-network
```

**4.2 `backend`（[docker-compose.yml:24](../../docker-compose.yml:24)）與 `worker`（[:51](../../docker-compose.yml:51)）的 `MONGODB_URL` 補上憑證：**

```yaml
      - MONGODB_URL=mongodb://airag_admin:${MONGO_ADMIN_PASSWORD}@mongodb:27017/?authSource=admin
```

並於宿主機 `.env` 加入 `MONGO_ADMIN_PASSWORD=<密碼>`（`${...}` 由 compose 在宿主機層展開，與容器內 `.env` 無關）。

> ⚠️ **這裡有個容易踩的坑**：`MONGODB_URL` 是寫在 compose 的 `environment:` 區塊，而 [backend/config.py:6](../../backend/config.py:6) 的 `load_dotenv()` **預設不覆蓋既有環境變數**。因此**只改容器內的 `backend/.env` 完全不會生效**，compose 的 `environment:` 一定會贏。必須改 compose。
>
> 另外依 [RAG_SYNC_PLAN.md](RAG_SYNC_PLAN.md) v1.6 第 5 點的既有經驗，`.env` 是 bind mount 而非 `env_file:` 注入，修改後仍需重建容器才會重新 `load_dotenv()`。

**4.3 遮蔽連線 log 中的密碼（本案唯一的 Python 修改，必做）**

[backend/models/mongodb.py:191](../../backend/models/mongodb.py:191) 目前是：

```python
logger.info(f"Connecting to MongoDB at: {settings.MONGODB_URL}")
```

4.2 完成後，這行會把 `airag_admin` 的 root 密碼明文寫進 `docker logs airag-backend` 與 `airag-worker`（`init_mongodb()` 是兩者共用，見 [backend/worker.py:33](../../backend/worker.py:33)）。log 通常比 DB 更容易被查看、轉貼與外流，等於把缺口換了個位置而非修掉。

改為輸出遮蔽後的字串（僅保留 host/port 供排錯，不含帳密），例如以標準庫解析後重組 netloc 再輸出。**驗證第 3 項請以遮蔽後的輸出為準。**

> 這個修改與認證本身無先後相依，可在維護時間窗前先行改好併入，維護當下只需重建容器。

### Step 5 — 重建容器

```bash
docker compose up -d --force-recreate mongodb backend worker
```

### Step 6 — 通知 KB 端設定連線字串

KB 後端 `.env`：

```
AIRAG_MONGODB_URL=mongodb://kb_reader:<密碼>@<AiRAG 主機 IP>:27017/?authSource=airag
AIRAG_MONGODB_DATABASE=airag
```

> `authSource=airag` **不可省略也不可寫成 `admin`**。`kb_reader` 建立於 `airag` database，認證來源必須指向該 db，否則一律認證失敗。這是跨團隊交接時最常見的錯誤來源，交付連線字串時請一併說明。

---

## 5. 驗證清單

| # | 驗證項目 | 指令 / 方式 | 預期結果 |
|:--:|:---|:---|:---|
| 1 | 無憑證連線被拒 | `docker exec -it airag-mongodb mongosh --eval "db.adminCommand({listDatabases:1})"` | 回 `requires authentication` |
| 2 | 管理者帳號可用 | 以 `airag_admin` 連線後 `show collections` | 能正常列出 collection，且**與施作前記錄的清單一致** |
| 3 | AiRAG 服務正常 | `docker logs airag-backend --tail 50` | 出現 `Connecting to MongoDB at: ...`（[mongodb.py:191](../../backend/models/mongodb.py:191)）、**該行不含密碼**（Step 4.3）、且無認證錯誤 |
| 3b | worker 連線正常 | `docker logs airag-worker --tail 50` | 同上，且 arq worker 正常啟動 |
| 4 | 問答端點正常 | 打一次 `POST /api/external/chat` | SSE 正常回應，且 `external_chat_logs` 有新增一筆 |
| 5 | **KB 帳號可讀目標 collection** | 見下方指令 A | 回傳筆數 |
| 6 | **KB 帳號不可寫入** | 見下方指令 B | 回 `not authorized` |
| 7 | **KB 帳號不可讀其他 collection** | 見下方指令 C | 回 `not authorized` |

指令 A：

```bash
docker exec -it airag-mongodb mongosh "mongodb://kb_reader:<密碼>@localhost:27017/airag?authSource=airag" --eval "db.external_chat_logs.countDocuments()"
```

指令 B：

```bash
docker exec -it airag-mongodb mongosh "mongodb://kb_reader:<密碼>@localhost:27017/airag?authSource=airag" --eval "db.external_chat_logs.insertOne({t:1})"
```

指令 C：

```bash
docker exec -it airag-mongodb mongosh "mongodb://kb_reader:<密碼>@localhost:27017/airag?authSource=airag" --eval "db.external_api_keys.find().toArray()"
```

> **驗證 6 與 7 是本案的核心驗收條件**，只驗證 5 通過不足以證明權限有收斂——請務必三項都跑過。
>
> 補充：驗證 2 之所以不寫死「20 個 collection」，是因為 Beanie 的 `document_models`（[mongodb.py:196-217](../../backend/models/mongodb.py:196)）雖登記 20 個，但 collection 要到首次寫入才真正建立，實際數量幾乎必定少於 20。**請在 Step 1 備份時先記下當下的 `show collections` 結果，施作後比對一致即可**，不要拿 20 這個數字當判準而誤判成故障。

---

## 6. 回滾方案

### 6.1 先分流：不是每種失敗都要回滾

回滾（拔掉 `--auth`）等於把 1.1 的缺口整個打開，是最後手段。連不上時請先看 log 的錯誤型態：

| 徵狀 | 真正原因 | 正解 |
|:---|:---|:---|
| `InvalidURI` / URI 解析錯誤 | 密碼含未 encode 的特殊字元，或 `.env` 的 `$` 被 compose 展開 | 依 Step 0.2 改用安全字元集，`db.changeUserPassword("airag_admin", passwordPrompt())` 換掉即可 |
| `Authentication failed` | ①**帳號其實沒建成功**（Step 2 的 `pwd` 未加引號等）②密碼打錯 ③`authSource` 寫錯 | 先分辨是哪一種，見下方 6.1.1；**都不需要回滾** |
| `requires authentication`（AiRAG 端） | compose 的 `MONGODB_URL` 沒生效（只改了 `backend/.env`） | 見 Step 4.2 的坑，改 compose 後 `--force-recreate` |

以上都能在不關閉認證的前提下修好。**只有在上述都排除、且已超出可接受的中斷時間**時，才執行下列全回滾。

#### 6.1.1 `Authentication failed` 的分辨與修復

先看 backend log 的 `Connecting to MongoDB at:` 那行（已遮蔽密碼，但保留帳號與 `authSource`）：密碼顯示 `<empty>` 就是宿主機 `.env` 沒有 `MONGO_ADMIN_PASSWORD`（或 `.env` 不在 `docker-compose.yml` 同一目錄），補上即可。

帳號與 `authSource` 都正確時，用**認證後**的 mongosh 直接試：

```bash
docker exec -it airag-mongodb mongosh --quiet -u airag_admin -p --authenticationDatabase admin --eval 'db.getSiblingDB("admin").system.users.find({},{user:1,db:1,_id:0}).toArray()'
```

若仍失敗，用 localhost exception 判別「帳號不存在」與「密碼不同」——**MongoDB 在完全沒有任何帳號時，允許從本機建立第一個帳號，即使 `--auth` 已開啟**，而 `docker exec` 進容器即屬本機：

```bash
docker exec -it airag-mongodb mongosh
```

```js
use admin
db.createUser({ user: "airag_admin", pwd: passwordPrompt(), roles: [ { role: "root", db: "admin" } ] })
```

* 回 `{ ok: 1 }` → **帳號原本就不存在**（Step 2 靜默失敗），至此已修復；接著要先 `db.getSiblingDB("admin").auth("airag_admin", passwordPrompt())` 再補建角色與 `kb_reader`（localhost exception 在第一個帳號建立後即關閉）。
* 回 `requires authentication` / `not authorized` → 帳號存在，是**密碼不同**。此時才需要暫時移除 `--auth` 重建 `mongodb`，以 `db.changeUserPassword("airag_admin", passwordPrompt())` 重設後再把 `--auth` 加回去。

### 6.2 全回滾

1. 移除 [docker-compose.yml](../../docker-compose.yml) `mongodb` 服務的 `command: ["--auth"]`。
2. 將 `backend` / `worker` 的 `MONGODB_URL` 改回 `mongodb://mongodb:27017`。
3. `docker compose up -d --force-recreate mongodb backend worker`。

已建立的帳號與角色會保留在資料庫中（不影響無認證模式運作），下次重試時**不需要重建帳號**，直接從 Step 4 開始即可。

資料本身在本案全程不會被修改；Step 1 的備份是為了防範操作失誤，正常流程用不到。

---

## 7. 風險與注意事項

1. **帳號必須先建、認證後開**。順序顛倒會造成「有認證但無帳號」的鎖死狀態，救援方式是移除 `--auth` 重啟（即第 6 節回滾）。
2. **本案不關閉 27017 的對外 publish。** 啟用認證後未授權者已無法讀取資料，但 port 仍暴露於內網。後續建議另案評估：移除 `ports:` 區塊改走 `airag-network` 內部網路（KB 在不同主機，需先確認網路可達性）、或以防火牆限制來源 IP。
3. **`backend` 與 `worker` 共用 `root` 帳號**。本案優先處理「有沒有認證」這件事，服務間的權限分離屬後續優化。若日後要做，`worker` 實際只需要 `readWrite` 於 `airag`，不需要 `root`。
4. **既有 API 金鑰是否輪替**：1.1 的缺口存在期間，`external_api_keys` 的 bcrypt 雜湊可能已被取得。是否要在本案後一併輪替所有外部 API 金鑰（刪除重建，`scope` 記得帶對，見 [RAG_SYNC_PLAN.md](RAG_SYNC_PLAN.md) v1.8 第 1 點的既有踩坑），建議由維運依實際暴露風險評估。
5. **工具腳本會一併受影響**：[backend/check_db.py](../../backend/check_db.py) 透過 `models.mongodb.init_mongodb()` 連線，在容器內執行會自動沿用新憑證；但若習慣在宿主機直接跑，需同步更新宿主機 `.env` 的 `MONGODB_URL`。
6. **密碼管理**：`MONGO_ADMIN_PASSWORD` 與 `kb_reader` 密碼不得進入 git。宿主機 `.env` 應已在 `.gitignore` 內，交付 KB 端時請走既有的密鑰傳遞管道，不要用聊天軟體明文傳送。另外密碼也不得進入 log——這正是 Step 4.3 的理由。
7. **明碼儲存的 DB 憑證是另一條線**：1.2 已確認 `database_configs.password` 為明碼。本案讓「外部無憑證者」讀不到它，但持有 `airag_admin` 者、以及任何一份 dump 仍看得見。是否改為加密儲存（或改用只有連線字串引用的密鑰管理）建議另案評估，不要因為本案完成就視為已解決。
8. **Redis 是同一個暴露面的另一半**：[docker-compose.yml:65-71](../../docker-compose.yml:65) 的 `redis` 同樣**無密碼**且把 6379 publish 到宿主機，arq 的 ingest 任務 payload 全部經過它。Qdrant 已有 `QDRANT__SERVICE__API_KEY`，本案處理 MongoDB 之後，**內網無認證的資料面就只剩 Redis**。建議緊接著以同樣方式（`--requirepass` + compose 帶入）另案收斂，否則容易誤以為「這條線已經全部收斂」。
9. ~~**`.env.example` 需同步**~~：**已完成**，[backend/.env.example](../../backend/.env.example) 的 `MONGODB_URL` 已補上帶憑證與 `authSource` 的範例格式（佔位符）、密碼字元集限制，以及「compose 的 `environment:` 會覆蓋此檔」的提醒。

---

## 8. 待確認事項

| # | 項目 | 待確認內容 |
|:--:|:---|:---|
| ~~1~~ | ~~`database_configs` 是否明碼存放密碼~~ | **已確認為明碼**（見 1.2），本案優先度依此上調；明碼儲存本身轉為第 7 節第 7 項的後續案 |
| 2 | KB 後端主機（`10.10.130.220`）到 AiRAG MongoDB 的網路可達性 | **仍待實測**。已驗證「經宿主機 IP `10.10.130.45:27017` 可連」，但發起端仍在 AiRAG 主機上，未經過 KB 端防火牆。需由 KB 那台實際連一次 |
| ~~3~~ | ~~維護時間窗~~ | 已於 2026-08-13 施作完成 |
| 4 | 是否一併輪替既有 API 金鑰 | 見第 7 節第 4 項。**本案完成後仍未決**，需維運評估 |
| 5 | 27017 是否於後續另案收斂 | 見第 7 節第 2 項 |
| ~~6~~ | ~~`mongo:7` 映像是否內含 `mongodump`~~ | 施作時已備份完成 |
| 7 | Redis 無認證是否納入同一波處理 | 見第 7 節第 8 項。MongoDB 收斂後，**內網無認證的資料面只剩 Redis** |

---

## 9. 施作結果與驗收記錄（2026-08-13）

### 9.1 驗收結果

| # | 驗證項目 | 結果 |
|:--:|:---|:---|
| 1 | 無憑證連線被拒 | ✅ **間接證實**。認證若未生效就不存在「授權」概念，驗證 6/7 不可能回 `not authorized`，故 `--auth` 確已強制執行 |
| 2 | 管理者帳號可用 | ✅ 帳號重建後可正常登入 |
| 3 | AiRAG 服務正常 | ✅ backend 啟動成功、無認證錯誤 |
| 4 | 問答端點正常 | — 未逐項回報 |
| 5 | **KB 帳號可讀目標 collection** | ✅ 經宿主機 IP `10.10.130.45:27017` 讀到 **82 筆** |
| 6 | **KB 帳號不可寫入** | ✅ `insertOne` 回 `not authorized on airag to execute command { insert: "external_chat_logs" ... }` |
| 7 | **KB 帳號不可讀其他 collection** | ✅ `external_api_keys.find()` 回 `not authorized on airag` |

驗證 6 證明角色的 `actions` 確實只有 `find`（未誤帶 `insert`）；驗證 7 證明用的是自訂角色而非內建 `read`（若為內建 `read`，此處會直接回傳金鑰雜湊）。**兩者即本案的核心驗收條件，皆通過。**

### 9.2 施作過程中實際踩到的坑

**`createUser` 的 `pwd` 未加引號 → 帳號靜默未建立。** 施作者將 `passwordPrompt()` 改寫為字面值時寫成 `pwd: <密碼>`（**未加引號**），mongosh 即 JavaScript，該 token 被當成未定義變數並拋 `ReferenceError`，**`createUser` 整個沒有執行**。當下未察覺，直到 Step 5 重建容器後才以 `Authentication failed` 爆出來，症狀與「密碼打錯」完全相同。

修復未動用回滾：利用 **localhost exception**（MongoDB 在完全沒有任何帳號時，允許從本機建立第一個帳號，即使 `--auth` 已開啟）於容器內重建 `airag_admin`，再認證後補建 `kb_reader`。此經驗已回寫至 Step 2 的警告與 6.1.1 的分辨流程。

### 9.3 後續追蹤（本案未涵蓋）

| 項目 | 出處 |
|:---|:---|
| KB 主機 `10.10.130.220` 的實際可達性測試 | 8 節第 2 項 |
| 既有外部 API 金鑰是否輪替 | 7 節第 4 項 |
| `database_configs` 明碼儲存 DB 憑證 | 7 節第 7 項 |
| Redis 無認證 + 6379 對外 publish | 7 節第 8 項 |
| 27017 是否收斂為內部網路 / 防火牆限制來源 | 7 節第 2 項 |
| `backend` / `worker` 仍共用 `root` 帳號 | 7 節第 3 項 |

> **施作後清理**：Step 1 產出的備份檔含 `database_configs` 明碼憑證與全部對話紀錄，驗收完成後應確認宿主機與容器 `/data/db/` 內的副本都已刪除或移入受管保存。
