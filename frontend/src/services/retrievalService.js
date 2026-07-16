import api from './api'

export default {
  async search(payload) {
    const response = await api.post('/api/retrieval/search', payload)
    return response.data
  },
  async semanticHybridSearch(payload) {
    const response = await api.post('/api/retrieval/semantic-hybrid-search', payload)
    return response.data
  },
  async queryTransform(payload) {
    const response = await api.post('/api/retrieval/query-transform', payload)
    return response.data
  },
  async batchDeletePoints(knowledgeBaseId, pointIds) {
    const response = await api.post(`/api/retrieval/knowledge-bases/${knowledgeBaseId}/points/batch-delete`, {
      point_ids: pointIds
    })
    return response.data
  },
  async deleteFileByFilename(knowledgeBaseId, filename) {
    const response = await api.post(`/api/retrieval/knowledge-bases/${knowledgeBaseId}/files/delete-by-filename`, {
      filename: filename
    })
    return response.data
  },
  async updateLinks(knowledgeBaseId, filename, linksTo) {
    const response = await api.post(`/api/retrieval/knowledge-bases/${knowledgeBaseId}/files/update-links`, {
      filename: filename,
      links_to: linksTo
    })
    return response.data
  },
  async updateAttachments(knowledgeBaseId, filename, attachmentIds) {
    const response = await api.post(`/api/retrieval/knowledge-bases/${knowledgeBaseId}/files/update-attachments`, {
      filename: filename,
      attachment_ids: attachmentIds
    })
    return response.data
  },
  async updatePermissions(knowledgeBaseId, filename, isConfidential, confidentialLevel, confidentialDepartments) {
    const response = await api.post(`/api/retrieval/knowledge-bases/${knowledgeBaseId}/files/update-permissions`, {
      filename: filename,
      is_confidential: isConfidential,
      confidential_level: confidentialLevel,
      confidential_departments: confidentialDepartments
    })
    return response.data
  }
}

