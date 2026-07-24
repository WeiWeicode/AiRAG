import api from './api'

export default {
  list() {
    return api.get('/api/external-api-keys')
  },
  create(name, scope = 'chat') {
    return api.post('/api/external-api-keys', { name, scope })
  },
  remove(id) {
    return api.delete(`/api/external-api-keys/${id}`)
  }
}
