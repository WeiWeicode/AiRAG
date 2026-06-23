import { defineStore } from 'pinia'
import api from '../services/api'

export const useFeedbackStore = defineStore('feedback', {
  state: () => ({
    feedbackList: [],
    totalFeedbacks: 0,
    isLoading: false,
  }),
  actions: {
    async fetchFeedbacks(params = {}) {
      this.isLoading = true
      try {
        const response = await api.get('/api/feedback', { params })
        this.feedbackList = response.data.items
        this.totalFeedbacks = response.data.total
      } catch (error) {
        console.error('Failed to fetch feedback history:', error)
      } finally {
        this.isLoading = false
      }
    },
    async submitFeedback(feedbackData) {
      try {
        const response = await api.post('/api/feedback', feedbackData)
        // Refresh local list if needed
        await this.fetchFeedbacks()
        return response.data
      } catch (error) {
        console.error('Failed to submit feedback:', error)
        throw error
      }
    },
    async syncToDataset(payload) {
      try {
        const response = await api.post('/api/feedback/export-to-dataset', payload)
        return response.data
      } catch (error) {
        console.error('Failed to sync feedback to dataset:', error)
        throw error
      }
    },
    async exportFeedback(format = 'json') {
      try {
        const response = await api.get('/api/feedback/export', {
          params: { format },
          responseType: 'blob'
        })
        return response.data
      } catch (error) {
        console.error('Failed to export feedback:', error)
        throw error
      }
    },
    async deleteFeedback(feedbackId) {
      try {
        const response = await api.delete(`/api/feedback/${feedbackId}`)
        return response.data
      } catch (error) {
        console.error('Failed to delete feedback:', error)
        throw error
      }
    },
    async batchDeleteFeedbacks(feedbackIds) {
      try {
        const response = await api.post('/api/feedback/batch-delete', { feedback_ids: feedbackIds })
        return response.data
      } catch (error) {
        console.error('Failed to batch delete feedbacks:', error)
        throw error
      }
    }
  }
})
