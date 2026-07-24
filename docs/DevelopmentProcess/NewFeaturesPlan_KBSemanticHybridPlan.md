# 新增集團知識庫專用語義混合查詢法 (`KB_semantic_hybrid`) 功能規劃與實作說明

> **文件狀態**：已完成實作 (Implemented)  
> **建立日期**：2026-07-24  
> **相關 PR / 提交**：新增集團知識庫專屬檢索模式 `KB_semantic_hybrid`

---

## 1. 背景與動機

為支援集團多單位、多階層與跨部門知識庫的獨立檢索需求，新增獨立檢索模式 `KB_semantic_hybrid`（集團知識庫語義混合查詢法）。透過此模式，可將集團內部文件檢索邏輯與既有 `semantic_hybrid` 進行隔離，方便未來加入專屬的語義重寫、系統 Prompt、部門與 `is_public` 機密權限過濾機制。

---

## 2. 核心權限過濾機制 (Point Payload `is_public`)

`KB_semantic_hybrid` 在檢索後處理階段呼叫 `PermissionService.filter_results_kb_semantic_hybrid()`，依據 Qdrant Point Payload 中的 `is_public` (boolean) 屬性執行精準過濾：

```json
{
  "is_public": false,
  "access_dept": "31700",
  "access_level": 10,
  "access_members": []
}
```

### 判斷邏輯矩陣

| `is_public` 值 | 說明 | 存取與放行條件 |
| :--- | :--- | :--- |
| **`true`** | 公開文件 | 不限制部門。必須符合 **職級門檻** (`user.level <= access_level`)，或列於白名單 `access_members` |
| **`false`** | 非公開 / 部門文件 | 必須符合 **部門限制** (`user.department` 或 `department_code` 等於 `access_dept`) **且** 符合 **職級門檻** (`user.level <= access_level`)，或列於白名單 `access_members` |
| **`None`** | 舊式文件 | 自動退回既有 `filter_results` 通用權限過濾規則 |

---

## 3. 程式碼變更與影響範圍

### 後端 (Backend)
1. **`backend/services/permission_service.py`**：新增 `filter_results_kb_semantic_hybrid()` 類別方法。
2. **`backend/routers/rag.py`**：`rag_chat_stream()` 新增 `KB_semantic_hybrid` 選項與專屬權限過濾分流。
3. **`backend/routers/retrieval.py`**：`/api/retrieval/search` 檢索測試端點新增 `KB_semantic_hybrid` 支援。

### 前端 (Frontend)
1. **`frontend/src/components/params/RagParamsPanel.vue`**：新增「集團知識庫語義混合查詢 (KB Semantic Hybrid)」下拉選項與指代消解判斷。
2. **`frontend/src/views/RetrievalTestView.vue`**：新增 `KB_semantic_hybrid` 檢索測試選項、RRF Score 顯示與步驟載入。
3. **`frontend/src/components/params/ApiJsonPreviewPanel.vue`**：更新 API 參數預覽說明。
4. **`frontend/src/components/eval/TestSetManager.vue`**：測試集管理頁面新增該模式選項。

---

## 4. 驗證結果

通過單元測試與模擬權限驗證：
- `is_public: true` 時，同部門與跨部門使用者皆可讀取，但高等級受限檔案（`level` 不足者）成功排除。
- `is_public: false` 時，非該部門使用者即便 `level` 符合亦被正確排除，同部門者方放行。
- 白名單成員（`access_members`）正確享有優先放行權限。
