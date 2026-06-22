import { defineStore } from 'pinia'

export const useParamsStore = defineStore('params', {
  state: () => ({
    // Retrieval parameters
    knowledgeBaseId: 'hr_docs',
    topK: 5,
    scoreThreshold: 0.70,
    searchMode: 'vector',
    hnswEfSearch: 64,

    // Generation parameters
    model: 'Qwen3.6-35B-A3B-FP8',
    temperature: 0.3,
    maxTokens: 1024,

    // Chunking / Embedding parameters
    chunkSize: 512,
    chunkOverlap: 50,
    separator: '\\n\\n',
  }),
  actions: {
    updateParams(newParams) {
      Object.assign(this, newParams)
    }
  }
})
