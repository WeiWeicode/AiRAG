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
        contextSummary: null,
        thinking: '',
        isThinking: false,
        question,
        dbQueryCandidates: null,
        awaitingProfileSelection: false,
        steps: [
          { key: 'semantic_analysis', name: '語義分析', status: 'pending', content: '', expanded: false },
          { key: 'vector_search', name: '向量資料查詢', status: 'pending', content: '', expanded: false },
          { key: 'llm_thinking', name: '思考中', status: 'pending', content: '', expanded: false },
          { key: 'conclusion', name: '結論', status: 'pending', content: '', expanded: false }
        ],
        created_at: new Date().toISOString()
      }
      this.messages.push(assistantMessage)

      await this._streamChat(question, assistantMessageId)
    },

    // 語義資料庫查詢法：使用者從候選查詢設定檔清單中選定一個後，帶著 selected_db_profile_id 重新請求，
    // 沿用同一則 assistant 訊息繼續串流（不新增使用者訊息）。
    async selectDbQueryProfile(assistantMessageId, profileId) {
      const msg = this.messages.find(m => m.id === assistantMessageId)
      if (!msg) return
      msg.awaitingProfileSelection = false
      msg.dbQueryCandidates = null
      await this._streamChat(msg.question, assistantMessageId, profileId)
    },

    async _streamChat(question, assistantMessageId, selectedDbProfileId) {
      const paramsStore = useParamsStore()
      const authStore = useAuthStore()

      this.isLoading = true

      try {
        const parsedFilterTags = paramsStore.filterTagsString.split(',')
          .map(t => t.trim())
          .filter(t => t.length > 0)

        // 語義資料庫查詢法且勾選「不限定知識庫」時，不帶 knowledge_base_id，讓後端掃描所有知識庫的查詢設定檔
        const useAutoKb = paramsStore.searchMode === 'semantic_db_query' && paramsStore.dbQueryAutoKb

        // autoContextEnabled 為 false 時強制送出 0（明確關閉），不論 historyTurnCount 欄位內容為何
        const rawTurns = paramsStore.autoContextEnabled ? paramsStore.historyTurnCount : 0
        // 正規化：<input type="number"> 被清空時 v-model.number 可能保留為空字串 ''（parseFloat('') 是 NaN，
        // Vue 的 .number 修飾符會退回原始字串），若原樣送出會被 Pydantic Optional[int] 判成 422 Validation Error
        const historyContextTurns = (rawTurns === '' || rawTurns === null || Number.isNaN(rawTurns)) ? null : rawTurns

        const payload = {
          question,
          knowledge_base_id: useAutoKb ? null : paramsStore.knowledgeBaseId,
          chat_history: this.messages.slice(0, -2).map(m => ({ role: m.role, content: m.content })),
          selected_db_profile_id: selectedDbProfileId,
          params: {
            model: paramsStore.model,
            temperature: paramsStore.temperature,
            max_tokens: paramsStore.maxTokens,
            top_k: paramsStore.topK,
            score_threshold: paramsStore.scoreThreshold,
            ai_summary_score_threshold: paramsStore.aiSummaryScoreThresholdEnabled ? paramsStore.aiSummaryScoreThreshold : 0.0,
            filter_tags: parsedFilterTags.length > 0 ? parsedFilterTags : undefined,
            search_type: paramsStore.searchMode,
            context_summarize_trigger_tokens: paramsStore.contextSummarizeThreshold || undefined,
            read_attachment_content: paramsStore.readAttachmentContent,
            history_context_turns: historyContextTurns,
            pinned_filename: paramsStore.pinnedFilename
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

                    // Update steps dynamically
                    if (msg.steps) {
                      if (data.type === 'reasoning' || msg.isThinking) {
                        const thinkStep = msg.steps.find(s => s.key === 'llm_thinking')
                        if (thinkStep) {
                          thinkStep.status = 'running'
                          thinkStep.content = msg.thinking || reasoningAccumulator
                        }
                      }
                      if (data.type === 'content' && contentToShow.length > 0) {
                        const thinkStep = msg.steps.find(s => s.key === 'llm_thinking')
                        if (thinkStep && thinkStep.status === 'running') {
                          thinkStep.status = 'success'
                        }
                        const conclStep = msg.steps.find(s => s.key === 'conclusion')
                        if (conclStep) {
                          conclStep.status = 'running'
                          conclStep.content = contentToShow
                        }
                      }
                    }
                  }
                } else if (currentEvent === 'step') {
                  const msg = this.messages.find(m => m.id === assistantMessageId)
                  if (msg) {
                    if (data.step === 'profile_candidates') {
                      msg.dbQueryCandidates = data.candidates || []
                      msg.awaitingProfileSelection = true
                    } else if (msg.steps) {
                      let stepObj = msg.steps.find(s => s.key === data.step)
                      if (!stepObj) {
                        stepObj = { key: data.step, name: data.label || data.step, status: 'pending', content: '', expanded: false }
                        const insertAt = msg.steps.findIndex(s => s.key === 'llm_thinking')
                        msg.steps.splice(insertAt === -1 ? msg.steps.length : insertAt, 0, stepObj)
                      }
                      stepObj.status = data.status
                      stepObj.content = data.content
                      if (data.label) {
                        stepObj.name = data.label
                      }
                    }
                  }
                } else if (currentEvent === 'message') {
                  const msg = this.messages.find(m => m.id === assistantMessageId)
                  if (msg && typeof data.delta === 'string') {
                    msg.content = data.delta
                    const conclStep = msg.steps?.find(s => s.key === 'conclusion')
                    if (conclStep) {
                      conclStep.status = 'success'
                      conclStep.content = data.delta
                    }
                  }
                } else if (currentEvent === 'sources') {
                  const msg = this.messages.find(m => m.id === assistantMessageId)
                  if (msg) {
                    msg.sources = data.sources
                    msg.contextSummary = data.context_summary || null
                    msg.attachments = data.attachments || null
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
          if (msg.steps) {
            const conclStep = msg.steps.find(s => s.key === 'conclusion')
            if (conclStep) {
              conclStep.status = 'failed'
              conclStep.content = `[連線錯誤] ${error.message}`
            }
          }
        }
      } finally {
        this.isLoading = false
        const msg = this.messages.find(m => m.id === assistantMessageId)
        if (msg) {
          msg.isThinking = false
          if (msg.steps && !msg.awaitingProfileSelection) {
            msg.steps.forEach(s => {
              if (s.status === 'running' || s.status === 'pending') {
                s.status = 'success'
                if (s.key === 'conclusion') {
                  s.content = msg.content
                }
              }
            })
          }
        }
      }
    }
  }
})
