import api from './api'

export default {
  async getProfiles(knowledgeBaseId) {
    const params = knowledgeBaseId ? { knowledge_base_id: knowledgeBaseId } : {}
    const response = await api.get('/api/ai-db-query/profiles', { params })
    return response.data
  },

  async saveProfile(payload) {
    if (payload.id) {
      const response = await api.put(`/api/ai-db-query/profiles/${payload.id}`, payload)
      return response.data
    } else {
      const response = await api.post('/api/ai-db-query/profiles', payload)
      return response.data
    }
  },

  async deleteProfile(profileId) {
    const response = await api.delete(`/api/ai-db-query/profiles/${profileId}`)
    return response.data
  },

  async listTables(configId) {
    const response = await api.post('/api/ai-db-query/list-tables', { config_id: configId })
    return response.data
  },

  async listColumns(configId, tableName) {
    const response = await api.post('/api/ai-db-query/list-columns', { config_id: configId, table_name: tableName })
    return response.data
  },

  async matchProfiles(payload) {
    const response = await api.post('/api/ai-db-query/match-profiles', payload)
    return response.data
  },

  async executeQuery(payload) {
    const response = await api.post('/api/ai-db-query/execute', payload)
    return response.data
  }
}
