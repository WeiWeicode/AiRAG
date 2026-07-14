<!-- 前端修正紀錄(最新紀錄放最前面) -->

## 2026-07-14 AI 總結門檻審查問題修正 (8.1 Early Exit 警示渲染)

### 背景
依據 [`NewFeaturesPlan_SimilaritySummaryThresholdPlan.md`](NewFeaturesPlan_SimilaritySummaryThresholdPlan.md) 8.1 審查項修復。當觸發門檻 Hard Cutoff 跳過總結時，後端以 `event: message` 送出警示訊息，但前端之前遺漏此事件處理，導致訊息泡泡為空白。

### 變更內容
- `frontend/src/stores/chatStore.js`：
  - 於 `_streamChat()` 事件處理鏈新增 `else if (currentEvent === 'message')` 分支。
  - 將接收到的 `data.delta` 設定給 `msg.content`，並同步將 conclusion 步驟設為 `success` 及填入內容，確保對話主泡泡與步驟面板皆能完整呈現「⚠️ 未執行 AI 總結...」警示說明。

---

## 2026-07-13 AI 總結相似度門檻與拒絕生成機制實作

### 背景
依據 [`NewFeaturesPlan_SimilaritySummaryThresholdPlan.md`](NewFeaturesPlan_SimilaritySummaryThresholdPlan.md) 規劃，於前端「檢索設定 (Retrieval)」新增「AI 總結門檻 (AI Summary Threshold)」獨立 Slider 控制項，並為對話視窗參考文章標記「已採納」/「未採納」狀態。

### 變更內容
- `frontend/src/stores/paramsStore.js`：
  - 新增 `aiSummaryScoreThreshold`（預設 `0.60`）與 `aiSummaryScoreThresholdEnabled`（預設 `true`）狀態。
- `frontend/src/components/params/RagParamsPanel.vue`：
  - 於「相似度閾值 (Score Threshold)」下方新增獨立的 AI 總結門檻控制項（包含啟用/關閉 Checkbox、Slider 及說明文字）。
- `frontend/src/stores/chatStore.js`：
  - 於 API 請求 payload (`/api/rag/chat`) 之 `params` 中帶入 `ai_summary_score_threshold`。若使用者關閉該控制項則自動傳遞 `0.0`（代表全部允許）。
- `frontend/src/components/chat/SourceChunks.vue`：
  - 讀取每筆 chunk metadata 之 `included_in_ai_context` 狀態，為達標項目加上「已採納」綠色徽章，未達標項目加上「未採納」紅色徽章與半透明標示。

### 驗證
- 執行 `npm run build` 成功編譯，無範本或語法錯誤。
