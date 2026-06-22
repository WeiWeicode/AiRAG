import api from './api'

export default {
  async submitFeedback(payload) {
    const response = await api.post('/api/feedback', payload)
    return response.data
  },
  async getFeedbacks(params = {}) {
    const response = await api.get('/api/feedback', { params })
    return response.data
  },
  async exportToDataset(payload) {
    const response = await api.post('/api/feedback/export-to-dataset', payload)
    return response.data
  },
  async exportFeedback(format = 'json') {
    const response = await api.get('/api/feedback/export', {
      params: { format },
      responseType: 'blob'
    })
    return response.data
  }
}
