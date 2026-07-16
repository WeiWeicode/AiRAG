import { defineStore } from 'pinia'

export const useParamsStore = defineStore('params', {
  state: () => ({
    // Retrieval parameters
    knowledgeBaseId: 'hr_docs',
    topK: 5,
    scoreThreshold: 0.70,
    aiSummaryScoreThreshold: 0.60,
    aiSummaryScoreThresholdEnabled: true,
    searchMode: 'vector',
    hnswEfSearch: 64,
    filterTagsString: '',

    // 語義資料庫查詢法 (Semantic DB Query) 專用，留空則沿用後端全域預設值
    dbQueryMaxRows: null,
    dbQueryMaxChars: null,
    // 不限定知識庫：勾選後掃描所有知識庫的查詢設定檔，並自動選擇分數最高的候選（不列出候選讓使用者選）
    dbQueryAutoKb: false,

    // 檢索內容分批摘要門檻，留空則沿用後端全域預設值
    contextSummarizeThreshold: null,

    // 是否讓 AI 讀取關聯附件描述進行摘要總結
    readAttachmentContent: false,

    // 多輪對話指代消解：自動指代消解總開關（預設開啟），關閉時前端強制送出 history_context_turns=0
    autoContextEnabled: true,
    // 語義 JSON 轉換階段納入的歷史則數，留空則沿用後端預設值 SEMANTIC_JSON_HISTORY_TURNS
    historyTurnCount: null,
    // 手動鎖定檔案，null = 不鎖定，由 AI 自動判斷
    pinnedFilename: null,

    // 權限控管：模擬使用者開關與選擇
    simulatedUserEnabled: false,
    simulatedUserId: null,

    // Generation parameters
    model: 'Qwen3.6-35B-A3B-FP8',
    temperature: 0.3,
    maxTokens: 22768,

    // Chunking / Embedding parameters
    chunkSize: 512,
    chunkOverlap: 50,
    separator: '\\n\\n',
    enableStructuring: true,
  }),
  actions: {
    updateParams(newParams) {
      Object.assign(this, newParams)
    }
  }
})
