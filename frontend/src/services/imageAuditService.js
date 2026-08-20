import api from './api'

export default {
  scan(refresh = false) {
    return api.get('/api/image-audit/scan', { params: { refresh } })
  },
  cleanup(filenames, includeRecent = false) {
    return api.post('/api/image-audit/cleanup', { filenames, include_recent: includeRecent })
  },
  // 一鍵清除：後端自行以「複驗後仍無引用」的全部孤兒檔為對象，不需前端把數千筆檔名送上去
  cleanupAll(includeRecent = false) {
    return api.post('/api/image-audit/cleanup', {
      filenames: [],
      delete_all_orphans: true,
      include_recent: includeRecent
    })
  }
}
