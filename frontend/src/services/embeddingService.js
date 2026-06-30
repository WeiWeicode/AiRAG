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
  },
  async vectorizeJson(payload) {
    const response = await api.post('/api/embedding/vectorize-json', payload)
    return response.data
  },
  async getTags() {
    const response = await api.get('/api/embedding/tags')
    return response.data
  },
  async createTag(name) {
    const response = await api.post('/api/embedding/tags', { name })
    return response.data
  },
  async getClasses() {
    const response = await api.get('/api/embedding/classes')
    return response.data
  },
  async createClass(name) {
    const response = await api.post('/api/embedding/classes', { name })
    return response.data
  }
}

