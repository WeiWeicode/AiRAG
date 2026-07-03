import { defineStore } from 'pinia'

export const useParamsStore = defineStore('params', {
  state: () => ({
    // Retrieval parameters
    knowledgeBaseId: 'hr_docs',
    topK: 5,
    scoreThreshold: 0.70,
    searchMode: 'vector',
    hnswEfSearch: 64,
    filterTagsString: '',

    // 語義資料庫查詢法 (Semantic DB Query) 專用，留空則沿用後端全域預設值
    dbQueryMaxRows: null,
    dbQueryMaxChars: null,
    // 不限定知識庫：勾選後掃描所有知識庫的查詢設定檔，並自動選擇分數最高的候選（不列出候選讓使用者選）
    dbQueryAutoKb: false,

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
