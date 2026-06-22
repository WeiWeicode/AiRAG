import api from './api'

export default {
  async uploadFile(file) {
    const formData = new FormData()
    formData.append('file', file)
    const response = await api.post('/api/embedding/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
    return response.data
  },
  async chunkText(payload) {
    const response = await api.post('/api/embedding/chunk', payload)
    return response.data
  },
  async vectorize(payload) {
    const response = await api.post('/api/embedding/vectorize', payload)
    return response.data
  }
}
