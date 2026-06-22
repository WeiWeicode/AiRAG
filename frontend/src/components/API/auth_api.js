import api from '../../services/api'

export default {
  async login(username, password) {
    const response = await api.post('/auth/login', { username, password })
    return response.data
  }
}
