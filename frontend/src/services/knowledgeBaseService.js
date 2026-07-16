import api from './api'

export default {
  list() {
    return api.get('/api/knowledge-bases')
  },
  create(payload) {
    // payload: { name, description }
    return api.post('/api/knowledge-bases', payload)
  },
  remove(id) {
    return api.delete(`/api/knowledge-bases/${id}`)
  }
}
