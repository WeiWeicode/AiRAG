import api from '../../services/api'

export default {
  async upload(file) {
    const formData = new FormData()
    formData.append('file', file)
    const response = await api.post('/embedding/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    })
    return response.data
  },
  async chunk(payload) {
    const response = await api.post('/embedding/chunk', payload)
    return response.data
  },
  async vectorize(payload) {
    const response = await api.post('/embedding/vectorize', payload)
    return response.data
  }
}
