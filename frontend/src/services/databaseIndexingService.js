import api from './api'

export default {
  async getConfigs() {
    const response = await api.get('/api/database-indexing/configs')
    return response.data
  },
  
  async saveConfig(payload) {
    if (payload.id) {
      const response = await api.put(`/api/database-indexing/configs/${payload.id}`, payload)
      return response.data
    } else {
      const response = await api.post('/api/database-indexing/configs', payload)
      return response.data
    }
  },
  
  async deleteConfig(configId) {
    const response = await api.delete(`/api/database-indexing/configs/${configId}`)
    return response.data
  },
  
  async testConnection(payload) {
    const response = await api.post('/api/database-indexing/test-connection', payload)
    return response.data
  },
  
  async fetchMetadata(payload) {
    const response = await api.post('/api/database-indexing/fetch-metadata', payload)
    return response.data
  },
  
  async ingest(payload) {
    const response = await api.post('/api/database-indexing/ingest', payload)
    return response.data
  }
}
