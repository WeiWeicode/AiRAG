import api from './api'

export default {
  getImageUrl(filename) {
    return `/api/embedding/images/${filename}`
  },

  async fetchImageBlobUrl(filename) {
    const response = await api.get(this.getImageUrl(filename), { responseType: 'blob' })
    return window.URL.createObjectURL(new Blob([response.data]))
  },

  async download(filename, displayName) {
    const response = await api.get(this.getImageUrl(filename), { responseType: 'blob' })
    const blobUrl = window.URL.createObjectURL(new Blob([response.data]))
    const link = document.createElement('a')
    link.href = blobUrl
    link.download = displayName || filename || 'download'
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(blobUrl)
  }
}
