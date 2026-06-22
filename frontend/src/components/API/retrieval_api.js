import api from '../../services/api'

export default {
  async search(payload) {
    const response = await api.post('/retrieval/search', payload)
    return response.data
  },
  async queryTransform(payload) {
    const response = await api.post('/retrieval/query-transform', payload)
    return response.data
  }
}
