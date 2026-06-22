import api from '../../services/api'

export default {
  async getHistory(page = 1, pageSize = 20) {
    const response = await api.get('/rag/history', { params: { page, page_size: pageSize } })
    return response.data
  },
  async deleteHistory(sessionId) {
    const response = await api.delete(`/rag/history/${sessionId}`)
    return response.data
  }
}
