import api from './api'

export default {
  async search(payload) {
    const response = await api.post('/api/retrieval/search', payload)
    return response.data
  },
  async semanticHybridSearch(payload) {
    const response = await api.post('/api/retrieval/semantic-hybrid-search', payload)
    return response.data
  },
  async queryTransform(payload) {
    const response = await api.post('/api/retrieval/query-transform', payload)
    return response.data
  },
  async batchDeletePoints(knowledgeBaseId, pointIds) {
    const response = await api.post(`/api/retrieval/knowledge-bases/${knowledgeBaseId}/points/batch-delete`, {
      point_ids: pointIds
    })
    return response.data
  },
  async deleteFileByFilename(knowledgeBaseId, filename) {
    const response = await api.post(`/api/retrieval/knowledge-bases/${knowledgeBaseId}/files/delete-by-filename`, {
      filename: filename
    })
    return response.data
  }
}

