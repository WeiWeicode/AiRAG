import api from './api'

export default {
  async getHistory(page = 1, pageSize = 20) {
    const response = await api.get('/api/rag/history', {
      params: { page, page_size: pageSize }
    })
    return response.data
  },
  async deleteHistory(sessionId) {
    const response = await api.delete(`/api/rag/history/${sessionId}`)
    return response.data
  }
}
