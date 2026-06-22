# AiRAG 開發手冊 (AGENT.md)

> 本文件是 AI 程式助手（如 Claude、Gemini）在本專案中的行為準則。  
> 所有 AI 協作開發必須遵守以下規範。

---

## 1. 先思考再動手

### 規則
- **動手之前，先說明你的理解與假設**。用 1-3 句話摘要你打算做什麼、為什麼這樣做。
- **有任何疑問，先問，不要猜**。錯誤的假設比多問一個問題代價高得多。
- 如果需求模糊或有多種解讀方式，列出你看到的選項，讓人類選擇。

### 範例
```
❌ 錯誤：直接開始寫程式碼
✅ 正確：「我理解你想在 FeedbackPanel 加一個下拉選單，
    讓使用者選擇錯誤類型。我假設選項是從 API 動態取得，
    而不是前端寫死。這樣對嗎？」
```

---

## 2. 簡單優先

### 規則
- **用最少的程式碼解決當前問題**，不要加用不到的功能。
- 不要「順便」引入新的套件、設計模式或抽象層，除非任務明確要求。
- 不要寫「未來可能用到」的程式碼。等需要的時候再加。
- 如果一個問題能用 10 行解決，不要寫 50 行。

### 範例
```
❌ 錯誤：為了一個簡單的 config 讀取，建立 Factory Pattern + Strategy Pattern
✅ 正確：直接讀取 .env，用一個 dict 就好
```

---

## 3. 外科手術式修改

### 規則
- **只改必須改的地方**。不要順手「整理」、「重構」或「優化」不相關的程式碼。
- 不要改動現有的程式碼格式（縮排、空行、引號風格），除非那就是你的任務。
- 不要重新命名你沒被要求改的變數或函式。
- 每次修改都應該能用一句話解釋為什麼改。

### 範例
```
❌ 錯誤：修 bug 的同時，把整個檔案的 var 改成 let，並重新排列 import
✅ 正確：只修改造成 bug 的那 3 行，其他一字不動
```

---

## 4. 目標導向執行

### 規則
- **先定義成功標準**：在開始之前，明確說出「做到什麼程度算完成」。
- 自己迭代直到達成目標，不要每做一步就停下來問。
- 如果遇到阻塞（缺少資訊、權限不足），才停下來回報。
- 完成時，簡要說明做了什麼、驗證了什麼。

### 範例
```
❌ 錯誤：「我已經寫好了 API route，你要不要看一下再繼續？」
✅ 正確：「我完成了 feedback API 的 CRUD 四個端點，
    已經確認 schema 符合 03_API_CONTRACT.md 的定義，
    並加上了錯誤處理。」
```

---

## 5. 尊重既有風格

### 規則
- **遵循現有程式碼的命名規範、寫法與慣例**，不要悄悄引入自己的風格。
- 新增程式碼前，先看同目錄下的現有檔案，學習它的風格。
- 保持一致性比「更好的寫法」更重要。

### 本專案慣例
| 項目 | 規範 |
|:---|:---|
| 前端框架 | Vue 3 Composition API (`<script setup>`) |
| 前端樣式 | Tailwind CSS |
| 後端框架 | Python FastAPI |
| 後端命名 | 函式/變數 `snake_case`，類別 `PascalCase` |
| API 路徑 | `/api/{module}/{action}`，全小寫，用連字號分隔 |
| MongoDB ODM | beanie (Document Models) |
| 註解語言 | 繁體中文或英文皆可，同一檔案內統一 |

### 範例
```
❌ 錯誤：現有程式碼用 snake_case，你卻寫 camelCase
❌ 錯誤：現有程式碼用 async def，你卻寫 sync 版本
✅ 正確：看到 get_chat_history() 就寫 get_feedback_list()，保持風格一致
```

---

## 6. 失敗要明確說

### 規則
- **失敗就說失敗**，不能把「靜默跳過」包裝成「任務完成」。
- 如果某個步驟做不到、某個 API 回傳錯誤、某段程式碼無法通過測試，必須明確告知。
- 不要用 `try/except: pass` 吞掉錯誤。
- 不要刪掉失敗的測試案例來讓測試「通過」。

### 範例
```
❌ 錯誤：「已完成部署」（實際上有 2 個服務啟動失敗但沒提）
❌ 錯誤：靜默 catch 所有 exception，回傳空結果假裝成功
✅ 正確：「部署完成，但 embedding service 啟動失敗，
    錯誤訊息是 'Connection refused on port 8080'，
    可能是 llama.cpp 服務尚未啟動。」
```

---

## 7. 專案參考文件

開發前請先閱讀以下文件，確保理解專案全貌：

| 文件 | 路徑 | 說明 |
|:---|:---|:---|
| 產品需求 | `docs/01_RPD.md` | 功能定義與驗收標準 |
| 系統架構 | `docs/02_ARCHITECTURE.md` | 前後端架構與專案結構 |
| API 合約 | `docs/03_API_CONTRACT.md` | 所有 API 端點定義 |
| DB 結構 | `docs/04_DB_SCHEMA.md` | MongoDB / SQL Server / Qdrant 設計 |
| 驗收標準 | `docs/05_ACCEPTANCE.md` | 功能驗收 Checklist |

---

## 8. 技術棧速查

| 層級 | 技術 |
|:---|:---|
| 前端 | Vue 3 + Vite + Tailwind CSS + Pinia |
| 後端 | Python FastAPI |
| 應用資料庫 | MongoDB (motor + beanie) |
| 既有知識庫 | SQL Server (唯讀, pyodbc) |
| 向量資料庫 | Qdrant |
| LLM | vLLM — Qwen3.6-35B-A3B-FP8 |
| Embedding | llama.cpp — Qwen3-Embedding-8B-Q8_0.gguf |
| 部署 | Docker + Docker Compose |


## 9. 修正紀錄

Bug修改紀錄與新增功能紀錄、前端修改紀錄、後端修改紀錄
1.由用戶自行進行測試，你不需要開啟瀏覽器檢測
2.每次修正都需留紀錄

| 文件 | 路徑 | 說明 |
|:---|:---|:---|
| Bug修改紀錄 | `docs/DevelopmentProcess/BugFix.md` | Bug修改紀錄 |
| 新增功能紀錄 | `docs/DevelopmentProcess/NewFeatures.md` | 新增功能紀錄 |
| 前端修改紀錄 | `docs/DevelopmentProcess/FrontendCorrection.md` | 前端修改紀錄 |
| 後端修改紀錄 | `docs/DevelopmentProcess/BackendCorrection.md` | 後端修改紀錄 |
