import { defineStore } from 'pinia'
import axios from 'axios'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem('token') || null,
    user: JSON.parse(localStorage.getItem('user')) || null,
  }),
  getters: {
    isAuthenticated: (state) => !!state.token,
  },
  actions: {
    async login(username, password) {
      try {
        const response = await axios.post('/api/auth/login', { username, password })
        const { access_token } = response.data
        this.token = access_token
        this.user = { username, role: 'AI Engineer' } // Fallback/default role as in demo.html
        
        localStorage.setItem('token', access_token)
        localStorage.setItem('user', JSON.stringify(this.user))
        
        // Setup authorization header for future requests
        axios.defaults.headers.common['Authorization'] = `Bearer ${access_token}`
        return true
      } catch (error) {
        console.error('Login failed:', error)
        throw error
      }
    },
    logout() {
      this.token = null
      this.user = null
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      delete axios.defaults.headers.common['Authorization']
    }
  }
})
