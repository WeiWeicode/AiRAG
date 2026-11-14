import api from './api'

export default {
  // 列出本機 Ollama 已下載的模型與後端目前採用的預設模型
  list() {
    return api.get('/api/models/list')
  }
}
