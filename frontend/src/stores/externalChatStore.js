import { defineStore } from 'pinia'
import { useParamsStore } from './paramsStore'
import { streamChat } from '../composables/useChatStream'

// 組出送往 /api/external/chat 的 request body，chatStore.js 內部的 payload 結構為藍本，
// 額外多帶 custom_system_prompt。抽成獨立函式，讓 ApiJsonPreviewPanel.vue 的即時預覽
// 與這裡實際送出的 payload 共用同一份邏輯，避免兩處各自組一次造成不一致。
export function buildExternalChatPayload(paramsStore, { question, chatHistory = [], selectedDbProfileId } = {}) {
  const parsedFilterTags = paramsStore.filterTagsString.split(',')
    .map(t => t.trim())
    .filter(t => t.length > 0)

  // 語義資料庫查詢法且勾選「不限定知識庫」時，不帶 knowledge_base_id，讓後端掃描所有知識庫的查詢設定檔
  const useAutoKb = paramsStore.searchMode === 'semantic_db_query' && paramsStore.dbQueryAutoKb

  // autoContextEnabled 為 false 時強制送出 0（明確關閉），不論 historyTurnCount 欄位內容為何
  const rawTurns = paramsStore.autoContextEnabled ? paramsStore.historyTurnCount : 0
  const historyContextTurns = (rawTurns === '' || rawTurns === null || Number.isNaN(rawTurns)) ? null : rawTurns

  const trimmedCustomPrompt = (paramsStore.customSystemPrompt || '').trim()

  return {
    question,
    knowledge_base_id: useAutoKb ? null : paramsStore.knowledgeBaseId,
    chat_history: chatHistory,
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
      pinned_filename: paramsStore.pinnedFilename,
      custom_system_prompt: trimmedCustomPrompt ? trimmedCustomPrompt : undefined,
      // 外部 API 改用 external_user 取代 simulated_user_id（見 NewFeaturesPlan_ExternalApiTestPlan.md 第 8.3 節決議 1）
      external_user: {
        employee_id: paramsStore.externalEmployeeId,
        name: paramsStore.externalEmployeeName,
        department_code: paramsStore.externalDepartmentCode,
        department_name: paramsStore.externalDepartmentName,
        job_title_name: paramsStore.externalJobTitleName,
        job_title_level: paramsStore.externalJobTitleLevel
      }
    }
  }
}

export const useExternalChatStore = defineStore('externalChat', {
  state: () => ({
    messages: [
      {
        id: 'welcome',
        role: 'assistant',
        content: '您好！這是「外部 API 測試」對話視窗，會直接呼叫 /api/external/chat 端點（需帶 X-API-Key 與使用者身分資訊），行為與 RAG 功能測試一致。',
        sources: null,
      }
    ],
    isLoading: false,
  }),
  actions: {
    clearMessages() {
      this.messages = [
        {
          id: 'welcome',
          role: 'assistant',
          content: '您好！這是「外部 API 測試」對話視窗，會直接呼叫 /api/external/chat 端點（需帶 X-API-Key 與使用者身分資訊），行為與 RAG 功能測試一致。',
          sources: null,
          thinking: '',
          isThinking: false
        }
      ]
    },
    async sendQuestion(question) {
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

    async selectDbQueryProfile(assistantMessageId, profileId) {
      const msg = this.messages.find(m => m.id === assistantMessageId)
      if (!msg) return
      msg.awaitingProfileSelection = false
      msg.dbQueryCandidates = null
      await this._streamChat(msg.question, assistantMessageId, profileId)
    },

    async _streamChat(question, assistantMessageId, selectedDbProfileId) {
      const paramsStore = useParamsStore()

      const payload = buildExternalChatPayload(paramsStore, {
        question,
        chatHistory: this.messages.slice(0, -2).map(m => ({ role: m.role, content: m.content })),
        selectedDbProfileId
      })

      await streamChat({
        endpoint: `${import.meta.env.VITE_API_BASE_URL || '/api'}/external/chat`,
        headers: {
          'Content-Type': 'application/json',
          // 與內部 JWT 各自獨立，改用 X-API-Key（見 NewFeaturesPlan_ExternalApiTestPlan.md 第 10 節）
          'X-API-Key': paramsStore.externalApiKey || ''
        },
        payload,
        messages: this.messages,
        assistantMessageId,
        setLoading: (value) => { this.isLoading = value }
      })
    }
  }
})
