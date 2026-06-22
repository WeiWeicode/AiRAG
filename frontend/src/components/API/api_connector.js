import axios from 'axios'

export default {
  async checkHealth() {
    try {
      const response = await axios.get('/health')
      return response.data
    } catch (error) {
      console.error('Health check failed:', error)
      return { status: 'unhealthy', error: error.message }
    }
  }
}
