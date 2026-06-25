import { defineStore } from 'pinia'
import { useParamsStore } from './paramsStore'
import { useAuthStore } from './authStore'
import api from '../services/api'

export const useChatStore = defineStore('chat', {
  state: () => ({
    messages: [
      {
        id: 'welcome',
        role: 'assistant',
        content: '您好！我是 AiRAG 內部測試助手。您可以向我提問，我將根據您在右側設定的知識庫及參數進行檢索，並生成回答。',
        sources: null,
      }
    ],
    isLoading: false,
    history: [],
    historyTotal: 0,
  }),
  actions: {
    async fetchHistory(page = 1, pageSize = 20) {
      try {
        const response = await api.get('/api/rag/history', { params: { page, page_size: pageSize } })
        this.history = response.data.items
        this.historyTotal = response.data.total
      } catch (error) {
        console.error('Failed to fetch history:', error)
      }
    },
    async deleteHistory(sessionId) {
      try {
        await api.delete(`/api/rag/history/${sessionId}`)
        this.history = this.history.filter(h => h.id !== sessionId)
        this.historyTotal -= 1
      } catch (error) {
        console.error('Failed to delete history:', error)
      }
    },
    clearMessages() {
      this.messages = [
        {
          id: 'welcome',
          role: 'assistant',
          content: '您好！我是 AiRAG 內部測試助手。您可以向我提問，我將根據您在右側設定的知識庫及參數進行檢索，並生成回答。',
          sources: null,
          thinking: '',
          isThinking: false
        }
      ]
    },
    async sendQuestion(question) {
      const paramsStore = useParamsStore()
      const authStore = useAuthStore()
      
      const userMessage = {
        id: 'msg_user_' + Date.now(),
        role: 'user',
        content: question,
        created_at: new Date().toISOString()
      }
      this.messages.push(userMessage)

      const assistantMessageId = 'msg_assistant_' + Date.now()
      const assistantMessage = {
        id: assistantMessageId,
        role: 'assistant',
        content: '',
        sources: null,
        thinking: '',
        isThinking: false,
        created_at: new Date().toISOString()
      }
      this.messages.push(assistantMessage)
      
      this.isLoading = true
      
      try {
        const parsedFilterTags = paramsStore.filterTagsString.split(',')
          .map(t => t.trim())
          .filter(t => t.length > 0)

        const payload = {
          question,
          knowledge_base_id: paramsStore.knowledgeBaseId,
          chat_history: this.messages.slice(0, -2).map(m => ({ role: m.role, content: m.content })),
          params: {
            model: paramsStore.model,
            temperature: paramsStore.temperature,
            max_tokens: paramsStore.maxTokens,
            top_k: paramsStore.topK,
            score_threshold: paramsStore.scoreThreshold,
            filter_tags: parsedFilterTags.length > 0 ? parsedFilterTags : undefined,
            search_type: paramsStore.searchMode
          }
        }

        const response = await fetch(`${import.meta.env.VITE_API_BASE_URL || '/api'}/rag/chat`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': authStore.token ? `Bearer ${authStore.token}` : ''
          },
          body: JSON.stringify(payload)
        })

        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`)
        }

        const reader = response.body.getReader()
        const decoder = new TextDecoder('utf-8')
        let buffer = ''
        let rawContentAccumulator = ''
        let reasoningAccumulator = ''

        let currentEvent = null

        while (true) {
          const { value, done } = await reader.read()
          if (value) {
            buffer += decoder.decode(value, { stream: true })
          }

          const lines = buffer.split('\n')
          if (!done) {
            buffer = lines.pop()
          } else {
            buffer = ''
          }

          for (const line of lines) {
            const trimmedLine = line.trim()
            if (trimmedLine.startsWith('event:')) {
              currentEvent = trimmedLine.replace('event:', '').trim()
            } else if (trimmedLine.startsWith('data:')) {
              const dataStr = trimmedLine.replace('data:', '').trim()
              if (!dataStr) continue

              try {
                const data = JSON.parse(dataStr)
                if (currentEvent === 'chunk') {
                  if (data.type === 'reasoning') {
                    reasoningAccumulator += data.content
                  } else if (data.type === 'content') {
                    rawContentAccumulator += data.content
                  } else if (data.type === 'done') {
                    // Completed
                  }

                  const msg = this.messages.find(m => m.id === assistantMessageId)
                  if (msg) {
                    let contentToShow = rawContentAccumulator
                    let thinkingToShow = reasoningAccumulator
                    let hasClosedThinkTag = false

                    let thinkStartIdx = rawContentAccumulator.indexOf('<think>')
                    let tagLength = 7
                    let thinkEndIdx = -1
                    let endTagLength = 8

                    if (thinkStartIdx === -1) {
                      // Try <thought> tag
                      thinkStartIdx = rawContentAccumulator.indexOf('<thought>')
                      if (thinkStartIdx !== -1) {
                        tagLength = 9
                        thinkEndIdx = rawContentAccumulator.indexOf('</thought>')
                        endTagLength = 10
                      }
                    } else {
                      thinkEndIdx = rawContentAccumulator.indexOf('</think>')
                    }

                    if (thinkStartIdx !== -1) {
                      if (thinkEndIdx !== -1) {
                        hasClosedThinkTag = true
                        thinkingToShow = reasoningAccumulator + rawContentAccumulator.substring(thinkStartIdx + tagLength, thinkEndIdx)
                        contentToShow = rawContentAccumulator.substring(0, thinkStartIdx) + rawContentAccumulator.substring(thinkEndIdx + endTagLength)
                      } else {
                        thinkingToShow = reasoningAccumulator + rawContentAccumulator.substring(thinkStartIdx + tagLength)
                        contentToShow = rawContentAccumulator.substring(0, thinkStartIdx)
                      }
                    }

                    msg.thinking = thinkingToShow.trim()
                    msg.content = contentToShow
                    msg.isThinking = (reasoningAccumulator.length > 0 && contentToShow.length === 0) || (thinkStartIdx !== -1 && !hasClosedThinkTag)
                  }
                } else if (currentEvent === 'sources') {
                  const msg = this.messages.find(m => m.id === assistantMessageId)
                  if (msg) {
                    msg.sources = data.sources
                  }
                }
              } catch (e) {
                console.error('Failed to parse SSE JSON data:', dataStr, e)
              }
            }
          }

          if (done) break
        }
      } catch (error) {
        console.error('Error during streaming:', error)
        const msg = this.messages.find(m => m.id === assistantMessageId)
        if (msg) {
          msg.content = `[連線錯誤] 無法取得回覆：${error.message}`
        }
      } finally {
        this.isLoading = false
        const msg = this.messages.find(m => m.id === assistantMessageId)
        if (msg) {
          msg.isThinking = false
        }
      }
    }
  }
})
