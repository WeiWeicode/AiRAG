import api from './api'

export default {
  list() {
    return api.get('/api/app-registrations')
  },
  create(payload) {
    return api.post('/api/app-registrations', payload)
  },
  update(appId, payload) {
    return api.put(`/api/app-registrations/${appId}`, payload)
  },
  remove(appId) {
    return api.delete(`/api/app-registrations/${appId}`)
  }
}
