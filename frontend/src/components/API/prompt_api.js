import api from '../../services/api'

export default {
  async generate(payload) {
    // Note: generate is SSE-based in the contract, but can also be requested via standard HTTP if needed,
    // or handled directly. Let's offer standard API trigger here:
    const response = await api.post('/prompt/generate', payload)
    return response.data
  },
  async preview(payload) {
    const response = await api.post('/prompt/preview', payload)
    return response.data
  },
  async abTest(payload) {
    const response = await api.post('/prompt/ab-test', payload)
    return response.data
  }
}
