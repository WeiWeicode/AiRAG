import api from './api'

export default {
  async getDatasets() {
    const response = await api.get('/api/evaluation/datasets')
    return response.data
  },
  async createDataset(payload) {
    const response = await api.post('/api/evaluation/datasets', payload)
    return response.data
  },
  async runEvaluation(payload) {
    const response = await api.post('/api/evaluation/run', payload)
    return response.data
  },
  async getReport(reportId) {
    const response = await api.get(`/api/evaluation/reports/${reportId}`)
    return response.data
  },
  async exportReport(reportId, format = 'csv') {
    const response = await api.get(`/api/evaluation/reports/${reportId}/export`, {
      params: { format },
      responseType: 'blob'
    })
    return response.data
  }
}
