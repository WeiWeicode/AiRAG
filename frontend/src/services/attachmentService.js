import api from './api'

export default {
  /**
   * 上傳附件檔案
   * @param {Object} payload { knowledge_base_id: string, description: string, tags: string, classes: string, file: File }
   */
  async upload(payload) {
    const formData = new FormData()
    formData.append('knowledge_base_id', payload.knowledge_base_id)
    formData.append('description', payload.description || '')
    formData.append('tags', payload.tags || '')
    formData.append('classes', payload.classes || '')
    formData.append('file', payload.file)

    const response = await api.post('/api/attachments/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
    return response.data
  },

  /**
   * 取得指定知識庫之附件清單
   * @param {string} knowledgeBaseId
   */
  async list(knowledgeBaseId) {
    const response = await api.get('/api/attachments', {
      params: { knowledge_base_id: knowledgeBaseId },
    })
    return response.data
  },

  /**
   * 刪除指定附件
   * @param {string} id
   */
  async remove(id) {
    const response = await api.delete(`/api/attachments/${id}`)
    return response.data
  },

  /**
   * 獲取附件下載路徑 URL
   * @param {string} id
   */
  getDownloadUrl(id) {
    return `/api/attachments/${id}/download`
  },

  /**
   * 下載附件（下載端點需要驗證，無法用 window.open 直接開啟，改用帶 Authorization
   * 標頭的 axios 請求取得 blob，再觸發瀏覽器另存新檔）
   * @param {string} id
   * @param {string} filename 觸發下載時使用的檔名（原始檔名）
   */
  async download(id, filename) {
    const response = await api.get(this.getDownloadUrl(id), { responseType: 'blob' })
    const blobUrl = window.URL.createObjectURL(new Blob([response.data]))
    const link = document.createElement('a')
    link.href = blobUrl
    link.download = filename || 'download'
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(blobUrl)
  }
}
