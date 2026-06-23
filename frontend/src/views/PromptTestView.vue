<script setup>
import { ref, computed, onMounted } from 'vue'
import LlmParamsPanel from '../components/params/LlmParamsPanel.vue'
import TokenCounter from '../components/embedding/TokenCounter.vue'
import api from '../services/api'
import { useParamsStore } from '../stores/paramsStore'
import { useAuthStore } from '../stores/authStore'

const paramsStore = useParamsStore()


const DEFAULT_SYSTEM_PROMPT = 'You are an expert AI Assistant. Refer to the provided Context to answer the user query accurately. If you don\'t know the answer, state that you do not know.'
const DEFAULT_USER_PROMPT_TEMPLATE = '根據以下提供的參考資料回答問題：\n{context}\n\n使用者問題：{question}\n\n請以繁體中文回答：'
const DEFAULT_MANUAL_CONTEXT = '【公司請假福利調整公告】\n自 2026 年起，全體正職員工之有薪病假額度自每年 3 日調整為每年 5 日，超出之病假以半薪計算。此外，員工生日當月可享有「生日假」1 日，須於當月使用完畢，不可遞延或折現。申請流程比照一般事假於 BPM 系統登錄即可。'
const DEFAULT_TEST_QUESTION = '請問 2026 年病假的福利有什麼改變？另外生日假可以留到下個月請嗎？'

// Prompt inputs
const systemPrompt = ref(DEFAULT_SYSTEM_PROMPT)
const userPromptTemplate = ref(DEFAULT_USER_PROMPT_TEMPLATE)
const manualContext = ref(DEFAULT_MANUAL_CONTEXT)
const testQuestion = ref(DEFAULT_TEST_QUESTION)

// Preview output state
const showPreview = ref(false)
const previewSystem = ref('')
const previewUser = ref('')
const previewTokens = ref(0)
const isPreviewLoading = ref(false)

// A/B test results state
const isGenerating = ref(false)
const abResults = ref([])

// --- Feature 1: Records states ---
const showRecordsModal = ref(false)
const promptRecords = ref([])
const recordNameInput = ref('')
const showSaveRecordModal = ref(false)

// --- Feature 2: Templates states ---
const showTemplatesModal = ref(false)
const promptTemplates = ref([])
const templateNameInput = ref('')
const showSaveTemplateModal = ref(false)

// --- Feature 3: Qdrant chunks search states ---
const showQdrantModal = ref(false)
const qdrantKbs = ref([])
const selectedQdrantKb = ref('')
const qdrantSearchQuery = ref('')
const qdrantResults = ref([])
const isQdrantSearching = ref(false)
const qdrantSearchFilename = ref('')
const uniqueFilenames = ref([])
const uniqueTags = ref([])
const selectedFilterTags = ref([])

const toggleFilterTag = (tag) => {
  const idx = selectedFilterTags.value.indexOf(tag)
  if (idx > -1) {
    selectedFilterTags.value.splice(idx, 1)
  } else {
    selectedFilterTags.value.push(tag)
  }
}

const fetchKbMetadata = async () => {
  if (!selectedQdrantKb.value) return
  try {
    const response = await api.get(`/api/knowledge-bases/${selectedQdrantKb.value}/metadata`)
    uniqueFilenames.value = response.data.filenames || []
    uniqueTags.value = response.data.tags || []
    selectedFilterTags.value = []
    qdrantSearchFilename.value = ''
  } catch (error) {
    console.error('Failed to fetch KB metadata:', error)
  }
}

const openQdrantModal = () => {
  showQdrantModal.value = true
  fetchKbMetadata()
}

// --- Feature 4: Evaluation dataset import states ---
const showDatasetsModal = ref(false)
const evalDatasets = ref([])
const selectedDatasetId = ref('')
const datasetItems = ref([])
const isDatasetLoading = ref(false)
const selectedDatasetItemIdx = ref(-1)
const selectedQuestionGroundTruth = ref('')

// --- Core Actions ---

const handlePreview = async () => {
  if (!manualContext.value.trim() || !testQuestion.value.trim()) {
    alert('請填寫參考資料 (Context) 及測試問題 (Question)')
    return
  }

  showPreview.value = true
  isPreviewLoading.value = true
  
  try {
    const response = await api.post('/api/prompt/preview', {
      context: manualContext.value,
      question: testQuestion.value,
      system_prompt: systemPrompt.value,
      user_prompt_template: userPromptTemplate.value
    })
    
    previewSystem.value = response.data.rendered_system_prompt
    previewUser.value = response.data.rendered_user_prompt
    previewTokens.value = response.data.total_estimated_tokens
  } catch (error) {
    console.error('Backend preview API failed:', error)
    alert('預覽組合 Prompt 失敗，請檢查後端服務與連線')
    showPreview.value = false
  } finally {
    isPreviewLoading.value = false
  }
}

const handleABTest = async () => {
  if (!manualContext.value.trim() || !testQuestion.value.trim()) {
    alert('請填寫參考資料 (Context) 及測試問題 (Question)')
    return
  }

  isGenerating.value = true
  
  // 初始化 Variant A 與 B 的 placeholder 結果，讓使用者在生成中看到對照卡片與思考狀態
  abResults.value = [
    {
      label: "Variant A (低溫度 - 0.1)",
      answer: "",
      thinking: "",
      isThinking: true,
      elapsed_ms: 0,
      params: { temperature: 0.1, top_p: 0.9, max_tokens: paramsStore.maxTokens }
    },
    {
      label: "Variant B (高溫度 - 0.9)",
      answer: "",
      thinking: "",
      isThinking: true,
      elapsed_ms: 0,
      params: { temperature: 0.9, top_p: 0.9, max_tokens: paramsStore.maxTokens }
    }
  ]
  
  const authStore = useAuthStore()
  
  try {
    const payload = {
      context: manualContext.value,
      question: testQuestion.value,
      variants: [
        {
          label: "Variant A (低溫度 - 0.1)",
          system_prompt: systemPrompt.value,
          user_prompt_template: userPromptTemplate.value,
          params: { temperature: 0.1, top_p: 0.9, max_tokens: paramsStore.maxTokens }
        },
        {
          label: "Variant B (高溫度 - 0.9)",
          system_prompt: systemPrompt.value,
          user_prompt_template: userPromptTemplate.value,
          params: { temperature: 0.9, top_p: 0.9, max_tokens: paramsStore.maxTokens }
        }
      ]
    }
    
    const response = await fetch(`${import.meta.env.VITE_API_BASE_URL || ''}/api/prompt/ab-test`, {
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
    
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop()
      
      for (const line of lines) {
        const trimmed = line.trim()
        if (trimmed.startsWith('data:')) {
          const dataStr = trimmed.substring(5).trim()
          if (!dataStr) continue
          
          try {
            const data = JSON.parse(dataStr)
            const idx = data.index
            
            if (idx >= 0 && idx < abResults.value.length) {
              const resObj = abResults.value[idx]
              
              if (data.type === 'reasoning') {
                resObj.thinking += data.content
                resObj.isThinking = true
              } else if (data.type === 'content') {
                resObj.answer += data.content
                
                // 檢查是否含有 <think> 或 <thought> 標記
                let thinkStartIdx = resObj.answer.indexOf('<think>')
                let tagLength = 7
                let thinkEndIdx = -1
                let endTagLength = 8
                
                if (thinkStartIdx === -1) {
                  thinkStartIdx = resObj.answer.indexOf('<thought>')
                  if (thinkStartIdx !== -1) {
                    tagLength = 9
                    thinkEndIdx = resObj.answer.indexOf('</thought>')
                    endTagLength = 10
                  }
                } else {
                  thinkEndIdx = resObj.answer.indexOf('</think>')
                }
                
                if (thinkStartIdx !== -1) {
                  if (thinkEndIdx !== -1) {
                    resObj.thinking = resObj.answer.substring(thinkStartIdx + tagLength, thinkEndIdx).trim()
                    resObj.answer = resObj.answer.substring(0, thinkStartIdx) + resObj.answer.substring(thinkEndIdx + endTagLength)
                    resObj.isThinking = false
                  } else {
                    resObj.thinking = resObj.answer.substring(thinkStartIdx + tagLength).trim()
                    resObj.answer = resObj.answer.substring(0, thinkStartIdx)
                    resObj.isThinking = true
                  }
                } else {
                  if (!resObj.thinking) {
                    resObj.isThinking = false
                  } else {
                    resObj.isThinking = false
                  }
                }
              } else if (data.type === 'done') {
                resObj.elapsed_ms = data.elapsed_ms
                resObj.isThinking = false
              } else if (data.type === 'error') {
                resObj.answer = data.content
                resObj.isThinking = false
              }
            }
          } catch (e) {
            console.error('Failed to parse SSE JSON:', e)
          }
        }
      }
    }
  } catch (error) {
    console.error('Backend A/B test streaming failed:', error)
    alert('A/B 參數對照生成失敗，請檢查後端服務與連線')
  } finally {
    isGenerating.value = false
    // 確保全部結束時，標記為已思考結束
    abResults.value.forEach(r => {
      r.isThinking = false
    })
  }
}

// --- Feature 1: Records Logic ---

const fetchRecords = async () => {
  try {
    const response = await api.get('/api/prompt/records')
    promptRecords.value = response.data || []
  } catch (error) {
    console.error('Failed to fetch records:', error)
  }
}

const openRecordsModal = () => {
  fetchRecords()
  showRecordsModal.value = true
}

const openSaveRecordModal = () => {
  if (abResults.value.length === 0 && !previewSystem.value) {
    alert('請先點選 [預覽組合 Prompt] 或 [A/B 參數對照生成] 產生結果，方可儲存。')
    return
  }
  const qSummary = testQuestion.value.trim() ? testQuestion.value.substring(0, 15) : '無問題'
  recordNameInput.value = `測試紀錄 - ${qSummary} (${new Date().toLocaleString()})`
  showSaveRecordModal.value = true
}

const saveRecord = async () => {
  if (!recordNameInput.value.trim()) {
    alert('請輸入紀錄標題')
    return
  }
  try {
    const payload = {
      name: recordNameInput.value,
      system_prompt: systemPrompt.value,
      user_prompt_template: userPromptTemplate.value,
      context: manualContext.value,
      question: testQuestion.value,
      results: abResults.value.map(r => ({
        label: r.label,
        answer: r.answer,
        params: r.params,
        elapsed_ms: r.elapsed_ms
      }))
    }
    await api.post('/api/prompt/records', payload)
    alert('測試紀錄已成功儲存！')
    showSaveRecordModal.value = false
    fetchRecords()
  } catch (error) {
    console.error('Failed to save record:', error)
    alert('儲存紀錄失敗，請檢查後端連線')
  }
}

const restoreRecord = (record) => {
  systemPrompt.value = record.system_prompt
  userPromptTemplate.value = record.user_prompt_template
  manualContext.value = record.context
  testQuestion.value = record.question
  abResults.value = record.results || []
  
  if (record.results && record.results.length > 0) {
    showPreview.value = false
  } else {
    previewSystem.value = record.system_prompt
    previewUser.value = record.user_prompt_template.replace('{context}', record.context).replace('{question}', record.question)
    previewTokens.value = Math.round((previewSystem.value.length + previewUser.value.length) * 1.3)
    showPreview.value = true
  }
  showRecordsModal.value = false
}

const deleteRecord = async (recordId) => {
  if (!confirm('確認要刪除此筆歷史紀錄嗎？')) return
  try {
    await api.delete(`/api/prompt/records/${recordId}`)
    await fetchRecords()
  } catch (error) {
    console.error('Failed to delete record:', error)
    alert('刪除失敗')
  }
}

// --- Feature 2: Templates Logic ---

const fetchTemplates = async () => {
  try {
    const response = await api.get('/api/prompt/templates')
    promptTemplates.value = response.data || []
  } catch (error) {
    console.error('Failed to fetch templates:', error)
  }
}

const selectTemplate = (template) => {
  if (template.system_prompt !== null) {
    systemPrompt.value = template.system_prompt
  }
  userPromptTemplate.value = template.user_prompt_template
  showTemplatesModal.value = false
}

const openSaveTemplateModal = () => {
  templateNameInput.value = `自訂範本 - ${new Date().toLocaleDateString()}`
  showSaveTemplateModal.value = true
}

const saveTemplate = async () => {
  if (!templateNameInput.value.trim()) {
    alert('請輸入範本名稱')
    return
  }
  try {
    const payload = {
      name: templateNameInput.value,
      system_prompt: systemPrompt.value,
      user_prompt_template: userPromptTemplate.value
    }
    await api.post('/api/prompt/templates', payload)
    alert('範本已成功儲存！')
    showSaveTemplateModal.value = false
    fetchTemplates()
  } catch (error) {
    console.error('Failed to save template:', error)
    alert('儲存範本失敗')
  }
}

const deleteTemplate = async (templateId) => {
  if (!confirm('確認要刪除此 Prompt 範本嗎？')) return
  try {
    await api.delete(`/api/prompt/templates/${templateId}`)
    await fetchTemplates()
  } catch (error) {
    console.error('Failed to delete template:', error)
    alert('刪除範本失敗')
  }
}

// --- Feature 3: Qdrant Chunks Retrieval Logic ---

const fetchQdrantKbs = async () => {
  try {
    const response = await api.get('/api/knowledge-bases')
    qdrantKbs.value = response.data.items || []
    if (qdrantKbs.value.length > 0 && !selectedQdrantKb.value) {
      selectedQdrantKb.value = qdrantKbs.value[0].id
    }
  } catch (error) {
    console.error('Failed to fetch KBs:', error)
  }
}

const searchQdrantChunks = async () => {
  isQdrantSearching.value = true
  try {
    const hasQuery = !!qdrantSearchQuery.value.trim()
    const payload = {
      query: qdrantSearchQuery.value,
      knowledge_base_id: selectedQdrantKb.value,
      params: {
        top_k: 1000,
        score_threshold: hasQuery ? 0.2 : 0.0,
        filter_filename: qdrantSearchFilename.value.trim() || undefined,
        filter_tags: selectedFilterTags.value.length > 0 ? selectedFilterTags.value : undefined
      }
    }
    const response = await api.post('/api/retrieval/search', payload)
    qdrantResults.value = (response.data.results || []).map(r => ({
      ...r,
      selected: false
    }))
  } catch (error) {
    console.error('Failed to retrieve chunks:', error)
    alert('檢索失敗，請檢查知識庫 ID 或後端連線')
  } finally {
    isQdrantSearching.value = false
  }
}

const confirmQdrantReference = () => {
  const selectedChunks = qdrantResults.value.filter(r => r.selected)
  if (selectedChunks.length === 0) {
    alert('請勾選至少一個段落')
    return
  }
  
  // 依 chunk_index 排序選取的段落
  selectedChunks.sort((a, b) => {
    const indexA = (a.metadata && a.metadata.chunk_index !== undefined && a.metadata.chunk_index !== null) ? a.metadata.chunk_index : 0
    const indexB = (b.metadata && b.metadata.chunk_index !== undefined && b.metadata.chunk_index !== null) ? b.metadata.chunk_index : 0
    return indexA - indexB
  })

  const contentToSet = selectedChunks.map(r => `【資料來源：${r.metadata.filename || '未知'} - P.${r.metadata.page || 1}】\n${r.content}`).join('\n\n---\n\n')
  
  manualContext.value = contentToSet
  showQdrantModal.value = false
  qdrantSearchQuery.value = ''
  qdrantSearchFilename.value = ''
  selectedFilterTags.value = []
  qdrantResults.value = []
}

const isAllChunksSelected = computed(() => {
  return qdrantResults.value.length > 0 && qdrantResults.value.every(r => r.selected)
})

const toggleSelectAllChunks = (event) => {
  const checked = event.target.checked
  qdrantResults.value.forEach(r => {
    r.selected = checked
  })
}

// --- Feature 4: Evaluation Dataset Import Logic ---

const fetchDatasets = async () => {
  try {
    const response = await api.get('/api/evaluation/datasets')
    evalDatasets.value = response.data.items || []
    if (evalDatasets.value.length > 0 && !selectedDatasetId.value) {
      selectedDatasetId.value = evalDatasets.value[0].dataset_id
      fetchDatasetDetails()
    }
  } catch (error) {
    console.error('Failed to fetch datasets:', error)
  }
}

const fetchDatasetDetails = async () => {
  if (!selectedDatasetId.value) return
  isDatasetLoading.value = true
  selectedDatasetItemIdx.value = -1
  try {
    const response = await api.get(`/api/evaluation/datasets/${selectedDatasetId.value}`)
    datasetItems.value = response.data.items || []
  } catch (error) {
    console.error('Failed to fetch dataset details:', error)
  } finally {
    isDatasetLoading.value = false
  }
}

const selectDatasetItem = (idx) => {
  selectedDatasetItemIdx.value = idx
}

const confirmDatasetImport = () => {
  if (selectedDatasetItemIdx.value === -1) {
    alert('請選擇一個問答項目')
    return
  }
  const item = datasetItems.value[selectedDatasetItemIdx.value]
  testQuestion.value = item.question
  selectedQuestionGroundTruth.value = item.ground_truth || ''
  
  const loadContexts = confirm('是否一併將該問答對應的相關上下文段落載入至參考資料中？')
  if (loadContexts) {
    let contextsStr = ''
    if (item.relevant_contexts && item.relevant_contexts.length > 0) {
      contextsStr += `【相關上下文】\n${item.relevant_contexts.join('\n---\n')}`
    }
    
    if (contextsStr) {
      if (manualContext.value.trim()) {
        manualContext.value += '\n\n---\n\n' + contextsStr
      } else {
        manualContext.value = contextsStr
      }
    }
  }
  showDatasetsModal.value = false
}

const clearSelectedQuestion = () => {
  selectedQuestionGroundTruth.value = ''
  selectedDatasetItemIdx.value = -1
}

const resetToDefaults = () => {
  systemPrompt.value = DEFAULT_SYSTEM_PROMPT
  userPromptTemplate.value = DEFAULT_USER_PROMPT_TEMPLATE
  manualContext.value = DEFAULT_MANUAL_CONTEXT
  testQuestion.value = DEFAULT_TEST_QUESTION
  selectedQuestionGroundTruth.value = ''
  selectedDatasetItemIdx.value = -1
  showPreview.value = false
  abResults.value = []
}

// --- Mounted ---
onMounted(() => {
  fetchTemplates()
  fetchRecords()
  fetchQdrantKbs()
  fetchDatasets()
})
</script>

<template>
  <div class="flex-grow flex gap-6 p-6 overflow-hidden h-full min-h-0">
    <!-- Left Main Prompt Panel -->
    <div class="flex-grow flex flex-col gap-5 min-w-0 h-full overflow-y-auto pr-1">
      <!-- Input Panel -->
      <div class="bg-[#111827]/70 border border-white/8 rounded-2xl p-6 backdrop-blur-md flex flex-col gap-4">
        <div class="flex justify-between items-center border-b border-white/5 pb-3">
          <div class="text-sm font-bold text-white tracking-wider">Prompt 參數與 Context 注入測試</div>
          <div class="flex gap-2">
            <button 
              @click="resetToDefaults"
              class="px-3 py-1.5 border border-white/10 hover:border-white/20 text-[11px] text-[#9ca3af] hover:text-white font-semibold rounded-lg bg-white/5 transition-all flex items-center gap-1.5"
            >
              🔄 回復預設值
            </button>
            <button 
              @click="openRecordsModal"
              class="px-3 py-1.5 border border-[#8b5cf6]/30 hover:border-[#8b5cf6] text-[11px] text-[#a78bfa] font-semibold rounded-lg bg-[#8b5cf6]/10 transition-all flex items-center gap-1.5"
            >
              📂 檢視歷史紀錄
            </button>
          </div>
        </div>
        
        <!-- System Prompt -->
        <div class="flex flex-col gap-2">
          <div class="flex justify-between items-center">
            <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">系統設定 (System Prompt)</label>
            <div class="flex gap-2 text-[10px]">
              <button 
                @click="showTemplatesModal = true"
                class="text-[#a78bfa] hover:text-[#c084fc] font-semibold flex items-center gap-1"
              >
                📂 載入範本
              </button>
              <span class="text-white/20">|</span>
              <button 
                @click="openSaveTemplateModal"
                class="text-[#a78bfa] hover:text-[#c084fc] font-semibold flex items-center gap-1"
              >
                💾 儲存為範本
              </button>
            </div>
          </div>
          <textarea 
            v-model="systemPrompt" 
            rows="2"
            class="bg-white/5 border border-white/8 rounded-lg text-white p-3 text-xs font-mono focus:outline-none focus:border-[#8b5cf6] resize-y"
          ></textarea>
        </div>

        <!-- User Prompt Template -->
        <div class="flex flex-col gap-2">
          <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">使用者範本 (User Prompt Template)</label>
          <textarea 
            v-model="userPromptTemplate" 
            rows="2"
            class="bg-white/5 border border-white/8 rounded-lg text-white p-3 text-xs font-mono focus:outline-none focus:border-[#8b5cf6] resize-y"
          ></textarea>
        </div>

        <!-- Manual Context -->
        <div class="flex flex-col gap-2">
          <div class="flex justify-between items-center">
            <div class="flex items-center gap-3">
              <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">參考資料 (Context / RAG Chunks)</label>
              <button 
                @click="openQdrantModal"
                class="text-[10px] text-[#a78bfa] hover:text-[#c084fc] font-semibold flex items-center gap-1"
              >
                🔍 檢索並引用 Qdrant Chunks
              </button>
            </div>
            <TokenCounter :text="manualContext" />
          </div>
          <textarea 
            v-model="manualContext" 
            rows="4"
            class="bg-white/5 border border-white/8 rounded-lg text-white p-3.5 text-xs focus:outline-none focus:border-[#8b5cf6] resize-y"
            placeholder="請貼上測試用參考文本段落，或由上方 [檢索並引用 Qdrant Chunks] 注入知識庫內容..."
          ></textarea>
        </div>

        <!-- Question -->
        <div class="flex flex-col gap-2">
          <div class="flex justify-between items-center">
            <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">測試問題 (User Query)</label>
            <button 
              @click="showDatasetsModal = true"
              class="text-[10px] text-[#a78bfa] hover:text-[#c084fc] font-semibold flex items-center gap-1"
            >
              🎯 引用評估集問題
            </button>
          </div>
          <input 
            v-model="testQuestion"
            type="text" 
            class="bg-white/5 border border-white/8 rounded-lg text-white px-3.5 py-2.5 text-xs focus:outline-none focus:border-[#8b5cf6]"
            placeholder="請輸入測試問題，或由上方 [引用評估集問題] 載入測試集問答..."
          />
          <!-- Ground Truth Display if imported from dataset -->
          <div v-if="selectedQuestionGroundTruth" class="bg-purple-950/20 border border-purple-500/20 rounded-lg p-3 text-xs text-[#9ca3af] flex flex-col gap-1.5 animate-fade-in mt-1">
            <div class="flex justify-between items-center">
              <span class="text-white font-bold flex items-center gap-1">🎯 引用標準答案 (Ground Truth)</span>
              <button 
                @click="clearSelectedQuestion" 
                class="text-[#a78bfa] hover:text-white text-[10px] font-semibold"
              >
                清除引用
              </button>
            </div>
            <div class="bg-black/30 p-2.5 rounded border border-white/5 font-mono text-[11px] text-[#9ca3af] whitespace-pre-wrap leading-relaxed">
              {{ selectedQuestionGroundTruth }}
            </div>
          </div>
        </div>

        <!-- Actions -->
        <div class="flex justify-between items-center mt-2">
          <div class="flex gap-3">
            <button 
              @click="handlePreview"
              :disabled="isGenerating || isPreviewLoading"
              class="px-5 py-2.5 border border-white/8 hover:border-white/16 text-xs text-[#f3f4f6] font-semibold rounded-lg bg-white/5 transition-all"
            >
              預覽組合 Prompt
            </button>
            <button 
              @click="handleABTest"
              :disabled="isGenerating || isPreviewLoading"
              class="px-5 py-2.5 bg-[#8b5cf6] hover:bg-[#a78bfa] hover:shadow-[0_4px_12px_rgba(139,92,246,0.3)] disabled:bg-purple-900/50 disabled:text-purple-300/50 text-xs text-white font-semibold rounded-lg transition-all flex items-center gap-1.5"
            >
              <svg v-if="isGenerating" class="animate-spin h-3.5 w-3.5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              {{ isGenerating ? '產生中...' : 'A/B 參數對照生成' }}
            </button>
          </div>
          <button 
            @click="openSaveRecordModal"
            class="px-4 py-2 border border-purple-500/30 hover:border-purple-500 text-xs text-[#a78bfa] font-semibold rounded-lg bg-purple-500/10 transition-all flex items-center gap-1"
          >
            💾 儲存本次測試與結果
          </button>
        </div>
      </div>

      <!-- Preview Modal or Panel -->
      <div 
        v-if="showPreview" 
        class="bg-[#111827]/40 border border-white/8 rounded-2xl p-6 flex flex-col gap-4 relative animate-fade-in"
      >
        <button @click="showPreview = false" class="absolute top-4 right-4 text-[#6b7280] hover:text-white text-base">
          &times;
        </button>
        <div class="text-sm font-bold text-white tracking-wider flex items-center gap-2">
          組合 Prompt 預覽 
          <span class="text-[10px] font-bold px-1.5 py-0.5 rounded bg-[#8b5cf6]/10 text-[#a78bfa] font-display">Est. Tokens: {{ previewTokens }}</span>
        </div>
        
        <div v-if="isPreviewLoading" class="text-xs text-[#9ca3af] py-4">正在渲染中...</div>
        <div v-else class="flex flex-col gap-4 text-xs font-mono">
          <div class="flex flex-col gap-1.5">
            <span class="text-white font-bold">System Prompt:</span>
            <pre class="bg-black/30 p-3.5 rounded-lg border border-white/5 max-h-[250px] overflow-y-auto whitespace-pre-wrap leading-relaxed text-[#9ca3af]">{{ previewSystem }}</pre>
          </div>
          <div class="flex flex-col gap-1.5">
            <span class="text-white font-bold">User Prompt:</span>
            <pre class="bg-black/30 p-3.5 rounded-lg border border-white/5 max-h-[300px] overflow-y-auto whitespace-pre-wrap leading-relaxed text-[#9ca3af]">{{ previewUser }}</pre>
          </div>
        </div>
      </div>

      <!-- A/B Comparison Result Side-by-Side Grid -->
      <div 
        v-if="abResults.length > 0" 
        class="grid grid-cols-1 gap-6 animate-fade-in"
        :class="selectedQuestionGroundTruth ? 'md:grid-cols-3' : 'md:grid-cols-2'"
      >
        <div 
          v-for="(res, idx) in abResults" 
          :key="idx" 
          class="bg-[#111827]/40 border border-white/8 rounded-2xl p-6 flex flex-col gap-4"
        >
          <div class="flex justify-between items-center border-b border-white/5 pb-2.5">
            <span class="text-sm font-bold text-white">{{ res.label }}</span>
            <span class="text-[10px] text-[#6b7280]">
              <template v-if="res.elapsed_ms > 0">
                耗時: <strong class="text-white">{{ res.elapsed_ms }}</strong> ms
              </template>
              <template v-else>
                生成中...
              </template>
            </span>
          </div>

          <!-- 思考過程風貌 -->
          <div v-if="res.thinking || res.isThinking" class="border border-white/10 rounded-xl bg-white/5 overflow-hidden text-[11px]">
            <div class="flex items-center justify-between px-3 py-2 text-[#9ca3af] bg-white/5">
              <div class="flex items-center gap-1.5">
                <svg v-if="res.isThinking" class="animate-spin h-3 w-3 text-purple-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                <svg v-else class="h-3 w-3 text-emerald-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
                <span>{{ res.isThinking ? '思考中...' : '已完成思考' }}</span>
              </div>
            </div>
            <div class="px-3 py-2 border-t border-white/5 text-[10px] text-white/50 whitespace-pre-wrap font-mono leading-relaxed max-h-[150px] overflow-y-auto">
              {{ res.thinking || '正在整理思緒...' }}
            </div>
          </div>

          <div class="text-xs text-[#9ca3af] leading-relaxed whitespace-pre-wrap bg-black/25 p-4 rounded-xl border border-white/3 min-h-[120px]">
            {{ res.answer || (res.isThinking ? '思考中...' : '等待回應...') }}
          </div>
          <div class="flex gap-4 text-[10px] text-[#6b7280]">
            <span>溫度: <strong class="text-white">{{ res.params.temperature }}</strong></span>
            <span>max_tokens: <strong class="text-white">{{ res.params.max_tokens || 1024 }}</strong></span>
          </div>
        </div>

        <!-- Ground Truth Card if selectedQuestionGroundTruth exists -->
        <div 
          v-if="selectedQuestionGroundTruth"
          class="bg-[#8b5cf6]/10 border border-[#8b5cf6]/20 rounded-2xl p-6 flex flex-col gap-4"
        >
          <div class="flex justify-between items-center border-b border-[#8b5cf6]/15 pb-2.5">
            <span class="text-sm font-bold text-white flex items-center gap-1">🎯 標準答案 (Ground Truth)</span>
            <span class="text-[10px] text-[#8b5cf6]">評估集標準答案</span>
          </div>
          <div class="text-xs text-[#a78bfa] leading-relaxed whitespace-pre-wrap bg-black/25 p-4 rounded-xl border border-[#8b5cf6]/10 min-h-[120px]">
            {{ selectedQuestionGroundTruth }}
          </div>
          <div class="flex gap-4 text-[10px] text-[#6b7280]">
            <span>來源: <strong class="text-white">測試評估集問題</strong></span>
          </div>
        </div>
      </div>
    </div>

    <!-- Right Side Settings -->
    <div class="w-[320px] flex-shrink-0 flex flex-col gap-5 overflow-y-auto pr-1 h-full pb-6">
      <LlmParamsPanel />
    </div>

    <!-- 歷史紀錄 Modal -->
    <div v-if="showRecordsModal" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
      <div class="bg-[#111827]/90 border border-white/10 rounded-2xl p-6 max-w-4xl w-full flex flex-col gap-4 shadow-2xl backdrop-blur-xl max-h-[85vh]">
        <div class="flex justify-between items-center border-b border-white/5 pb-3">
          <h3 class="text-sm font-bold text-white tracking-wider flex items-center gap-2">
            <span>📂 歷史測試紀錄</span>
            <span class="text-xs font-normal text-[#9ca3af]">({{ promptRecords.length }} 筆紀錄)</span>
          </h3>
          <button @click="showRecordsModal = false" class="text-[#6b7280] hover:text-white text-xl font-bold">&times;</button>
        </div>
        
        <div class="flex-grow overflow-y-auto flex flex-col gap-3 min-h-0 pr-1 text-xs">
          <div v-if="promptRecords.length === 0" class="text-center text-[#6b7280] py-8">
            目前無儲存的測試紀錄
          </div>
          <div 
            v-for="record in promptRecords" 
            :key="record.id"
            class="bg-white/5 border border-white/8 rounded-xl p-4 flex flex-col gap-3 hover:border-white/16 transition-all"
          >
            <div class="flex justify-between items-start border-b border-white/5 pb-2">
              <div>
                <h4 class="font-bold text-white text-sm">{{ record.name }}</h4>
                <p class="text-[10px] text-[#6b7280] mt-0.5">儲存時間: {{ new Date(record.created_at).toLocaleString() }}</p>
              </div>
              <div class="flex gap-2">
                <button 
                  @click="restoreRecord(record)"
                  class="px-2.5 py-1 bg-[#8b5cf6] hover:bg-[#a78bfa] text-[10px] text-white font-semibold rounded-md transition-all"
                >
                  還原參數
                </button>
                <button 
                  @click="deleteRecord(record.id)"
                  class="px-2.5 py-1 bg-red-600/20 hover:bg-red-600 text-[10px] text-red-400 hover:text-white font-semibold rounded-md border border-red-500/20 transition-all"
                >
                  刪除
                </button>
              </div>
            </div>
            
            <div class="grid grid-cols-2 gap-4 text-[11px]">
              <div class="flex flex-col gap-1 text-[#9ca3af]">
                <div><span class="text-white font-semibold text-[10px]">系統設定:</span> <span class="line-clamp-2 font-mono text-[9px]">{{ record.system_prompt }}</span></div>
                <div><span class="text-white font-semibold text-[10px]">使用者範本:</span> <span class="line-clamp-2 font-mono text-[9px]">{{ record.user_prompt_template }}</span></div>
              </div>
              <div class="flex flex-col gap-1 text-[#9ca3af]">
                <div><span class="text-white font-semibold text-[10px]">問題:</span> <span class="line-clamp-2">{{ record.question }}</span></div>
                <div><span class="text-white font-semibold text-[10px]">參考資料:</span> <span class="line-clamp-2">{{ record.context }}</span></div>
              </div>
            </div>

            <!-- Variants if present -->
            <div v-if="record.results && record.results.length > 0" class="flex gap-3 overflow-x-auto pt-2 border-t border-white/5">
              <div 
                v-for="(var_res, idx) in record.results" 
                :key="idx"
                class="bg-black/35 rounded-lg p-2.5 border border-white/5 min-w-[200px] flex-grow flex flex-col gap-1"
              >
                <div class="flex justify-between text-[10px] text-white border-b border-white/5 pb-1 font-bold">
                  <span>{{ var_res.label }}</span>
                  <span class="text-[9px] text-[#6b7280]">{{ var_res.elapsed_ms }} ms</span>
                </div>
                <div class="text-[10px] text-[#9ca3af] line-clamp-3 leading-relaxed mt-1">
                  {{ var_res.answer }}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 儲存紀錄名稱 Modal -->
    <div v-if="showSaveRecordModal" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
      <div class="bg-[#111827]/90 border border-white/10 rounded-2xl p-6 max-w-md w-full flex flex-col gap-4 shadow-2xl backdrop-blur-xl">
        <div class="flex justify-between items-center border-b border-white/5 pb-3">
          <h3 class="text-sm font-bold text-white tracking-wider">💾 儲存本次測試與結果</h3>
          <button @click="showSaveRecordModal = false" class="text-[#6b7280] hover:text-white text-xl font-bold">&times;</button>
        </div>
        <div class="flex flex-col gap-2">
          <label class="text-xs text-[#9ca3af] font-semibold">請輸入紀錄標題</label>
          <input 
            v-model="recordNameInput"
            type="text" 
            class="bg-white/5 border border-white/8 rounded-lg text-white px-3 py-2 text-xs focus:outline-none focus:border-[#8b5cf6]"
            placeholder="請輸入紀錄標題..."
          />
        </div>
        <div class="flex justify-end gap-3 pt-2">
          <button 
            @click="showSaveRecordModal = false"
            class="px-4 py-2 border border-white/8 hover:border-white/16 text-xs text-[#f3f4f6] font-semibold rounded-lg bg-white/5 transition-all"
          >
            取消
          </button>
          <button 
            @click="saveRecord"
            class="px-4 py-2 bg-[#8b5cf6] hover:bg-[#a78bfa] text-xs text-white font-semibold rounded-lg transition-all"
          >
            確定儲存
          </button>
        </div>
      </div>
    </div>

    <!-- 載入範本 Modal -->
    <div v-if="showTemplatesModal" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
      <div class="bg-[#111827]/90 border border-white/10 rounded-2xl p-6 max-w-lg w-full flex flex-col gap-4 shadow-2xl backdrop-blur-xl max-h-[75vh]">
        <div class="flex justify-between items-center border-b border-white/5 pb-3">
          <h3 class="text-sm font-bold text-white tracking-wider">📂 載入既有 Prompt 範本</h3>
          <button @click="showTemplatesModal = false" class="text-[#6b7280] hover:text-white text-xl font-bold">&times;</button>
        </div>
        
        <div class="flex-grow overflow-y-auto flex flex-col gap-2.5 pr-1 text-xs">
          <div v-if="promptTemplates.length === 0" class="text-center text-[#6b7280] py-6">
            載入中或目前無儲存範本
          </div>
          <div 
            v-for="tpl in promptTemplates" 
            :key="tpl.id"
            class="bg-white/5 border border-white/8 rounded-lg p-3 hover:border-white/16 transition-all flex flex-col gap-2"
          >
            <div class="flex justify-between items-center">
              <span class="font-bold text-white text-xs flex items-center gap-1.5">
                {{ tpl.name }}
                <span v-if="tpl.is_default" class="text-[9px] bg-[#8b5cf6]/20 text-[#a78bfa] px-1 py-0.2 rounded font-normal">系統預設</span>
              </span>
              <div class="flex gap-2">
                <button 
                  @click="selectTemplate(tpl)"
                  class="px-2 py-1 bg-[#8b5cf6]/20 hover:bg-[#8b5cf6] text-[#a78bfa] hover:text-white text-[10px] font-semibold rounded transition-all"
                >
                  套用範本
                </button>
                <button 
                  v-if="!tpl.is_default"
                  @click="deleteTemplate(tpl.id)"
                  class="text-red-400 hover:text-red-300 text-xs px-1"
                  title="刪除此範本"
                >
                  🗑️
                </button>
              </div>
            </div>
            <div class="text-[10px] text-[#6b7280] bg-black/20 p-2 rounded font-mono line-clamp-2">
              {{ tpl.user_prompt_template }}
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 儲存為範本 Modal -->
    <div v-if="showSaveTemplateModal" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
      <div class="bg-[#111827]/90 border border-white/10 rounded-2xl p-6 max-w-md w-full flex flex-col gap-4 shadow-2xl backdrop-blur-xl">
        <div class="flex justify-between items-center border-b border-white/5 pb-3">
          <h3 class="text-sm font-bold text-white tracking-wider">💾 儲存為 Prompt 範本</h3>
          <button @click="showSaveTemplateModal = false" class="text-[#6b7280] hover:text-white text-xl font-bold">&times;</button>
        </div>
        <div class="flex flex-col gap-2">
          <label class="text-xs text-[#9ca3af] font-semibold">範本名稱</label>
          <input 
            v-model="templateNameInput"
            type="text" 
            class="bg-white/5 border border-white/8 rounded-lg text-white px-3 py-2 text-xs focus:outline-none focus:border-[#8b5cf6]"
            placeholder="請輸入範本名稱..."
          />
        </div>
        <div class="flex justify-end gap-3 pt-2">
          <button 
            @click="showSaveTemplateModal = false"
            class="px-4 py-2 border border-white/8 hover:border-white/16 text-xs text-[#f3f4f6] font-semibold rounded-lg bg-white/5 transition-all"
          >
            取消
          </button>
          <button 
            @click="saveTemplate"
            class="px-4 py-2 bg-[#8b5cf6] hover:bg-[#a78bfa] text-xs text-white font-semibold rounded-lg transition-all"
          >
            儲存範本
          </button>
        </div>
      </div>
    </div>

    <!-- 引用 Qdrant Chunks Modal -->
    <div v-if="showQdrantModal" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
      <div class="bg-[#111827]/90 border border-white/10 rounded-2xl p-6 max-w-3xl w-full flex flex-col gap-4 shadow-2xl backdrop-blur-xl max-h-[85vh]">
        <div class="flex justify-between items-center border-b border-white/5 pb-3">
          <h3 class="text-sm font-bold text-white tracking-wider">🔍 檢索並多選引用 Qdrant Chunks</h3>
          <button @click="showQdrantModal = false" class="text-[#6b7280] hover:text-white text-xl font-bold">&times;</button>
        </div>
        
        <!-- Controls -->
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div class="flex flex-col gap-1.5">
            <label class="text-[10px] text-[#9ca3af] font-semibold">選擇知識庫</label>
            <select 
              v-model="selectedQdrantKb" 
              @change="fetchKbMetadata"
              class="bg-white/5 border border-white/8 rounded-lg text-white px-2 py-1.5 text-xs focus:outline-none focus:border-[#8b5cf6] bg-[#111827]"
            >
              <option v-for="kb in qdrantKbs" :key="kb.id" :value="kb.id" class="bg-[#111827] text-white">
                {{ kb.name }}
              </option>
            </select>
          </div>
          <div class="flex flex-col gap-1.5">
            <label class="text-[10px] text-[#9ca3af] font-semibold">檢索關鍵字/查詢句</label>
            <input 
              v-model="qdrantSearchQuery"
              type="text" 
              @keyup.enter="searchQdrantChunks"
              class="bg-white/5 border border-white/8 rounded-lg text-white px-3 py-1.5 text-xs focus:outline-none focus:border-[#8b5cf6]"
              placeholder="輸入搜尋內容..."
            />
          </div>
          <div class="flex flex-col gap-1.5">
            <label class="text-[10px] text-[#9ca3af] font-semibold">篩選檔案名稱 (Filename)</label>
            <input 
              v-model="qdrantSearchFilename"
              type="text" 
              list="filename-suggestions"
              class="bg-white/5 border border-white/8 rounded-lg text-white px-3 py-1.5 text-xs focus:outline-none focus:border-[#8b5cf6]"
              placeholder="輸入或選取檔案名稱..."
            />
            <datalist id="filename-suggestions">
              <option v-for="fn in uniqueFilenames" :key="fn" :value="fn" />
            </datalist>
          </div>
          <div class="flex flex-col gap-1.5">
            <label class="text-[10px] text-[#9ca3af] font-semibold">操作與搜尋</label>
            <button 
              @click="searchQdrantChunks"
              :disabled="isQdrantSearching"
              class="w-full py-1.5 bg-[#8b5cf6] hover:bg-[#a78bfa] disabled:bg-purple-950 text-xs text-white font-semibold rounded-lg transition-all"
            >
              {{ isQdrantSearching ? '搜尋中...' : '執行關鍵字檢索' }}
            </button>
          </div>
        </div>

        <!-- Tags filter selector -->
        <div v-if="uniqueTags.length > 0" class="flex flex-col gap-1.5 border-t border-white/5 pt-2">
          <label class="text-[10px] text-[#9ca3af] font-semibold">篩選標籤 (Tags - 可複選)</label>
          <div class="flex flex-wrap gap-1.5 max-h-[75px] overflow-y-auto pr-1">
            <button 
              v-for="tag in uniqueTags" 
              :key="tag"
              @click="toggleFilterTag(tag)"
              class="px-2 py-0.5 rounded text-[10px] font-semibold transition-all border"
              :class="selectedFilterTags.includes(tag) 
                ? 'bg-[#8b5cf6]/20 border-[#8b5cf6] text-[#c084fc]' 
                : 'bg-white/5 border-white/5 text-[#9ca3af] hover:bg-white/10'"
            >
              {{ tag }}
            </button>
          </div>
        </div>

        <!-- Chunks list -->
        <div class="flex-grow overflow-y-auto flex flex-col gap-2.5 pr-1 text-xs min-h-[200px]">
          <div v-if="qdrantResults.length === 0" class="text-center text-[#6b7280] py-8">
            請輸入關鍵字進行知識庫檢索
          </div>
          <!-- Select All Controls -->
          <div v-if="qdrantResults.length > 0" class="flex justify-between items-center px-1 pb-2 border-b border-white/5">
            <span class="text-[#6b7280] text-[10px]">已檢索到 {{ qdrantResults.length }} 筆段落</span>
            <label class="flex items-center gap-1.5 cursor-pointer text-[#a78bfa] hover:text-white select-none">
              <input 
                type="checkbox" 
                :checked="isAllChunksSelected" 
                @change="toggleSelectAllChunks"
                class="rounded border-white/10 bg-white/5 text-[#8b5cf6] focus:ring-[#8b5cf6]"
              />
              <span class="text-[10px] font-semibold">全選 / 全不選</span>
            </label>
          </div>
          <div 
            v-for="item in qdrantResults" 
            :key="item.chunk_id"
            class="bg-white/5 border border-white/8 rounded-lg p-3 flex gap-3 hover:bg-white/10 transition-all cursor-pointer"
            @click="item.selected = !item.selected"
          >
            <div class="flex items-start pt-0.5">
              <input 
                type="checkbox" 
                v-model="item.selected"
                @click.stop
                class="rounded border-white/10 bg-white/5 text-[#8b5cf6] focus:ring-[#8b5cf6]"
              />
            </div>
            <div class="flex-grow flex flex-col gap-1.5">
              <div class="flex justify-between items-center text-[10px] text-[#6b7280]">
                <span>來源: <strong class="text-white">{{ item.metadata.filename || '未知' }}</strong> (P.{{ item.metadata.page || 1 }})</span>
                <span class="text-[#a78bfa] font-bold">相似度: {{ item.score.toFixed(4) }}</span>
              </div>
              <p class="text-[#9ca3af] leading-relaxed select-text">{{ item.content }}</p>
            </div>
          </div>
        </div>

        <div class="flex justify-end gap-3 border-t border-white/5 pt-3">
          <button 
            @click="showQdrantModal = false"
            class="px-4 py-2 border border-white/8 hover:border-white/16 text-xs text-[#f3f4f6] font-semibold rounded-lg bg-white/5 transition-all"
          >
            取消
          </button>
          <button 
            @click="confirmQdrantReference"
            :disabled="qdrantResults.filter(r => r.selected).length === 0"
            class="px-4 py-2 bg-[#8b5cf6] hover:bg-[#a78bfa] disabled:bg-purple-900/50 disabled:text-purple-300/50 text-xs text-white font-semibold rounded-lg transition-all"
          >
            確認引用 (已選 {{ qdrantResults.filter(r => r.selected).length }} 項)
          </button>
        </div>
      </div>
    </div>

    <!-- 引用評估集問題 Modal -->
    <div v-if="showDatasetsModal" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
      <div class="bg-[#111827]/90 border border-white/10 rounded-2xl p-6 max-w-3xl w-full flex flex-col gap-4 shadow-2xl backdrop-blur-xl max-h-[85vh]">
        <div class="flex justify-between items-center border-b border-white/5 pb-3">
          <h3 class="text-sm font-bold text-white tracking-wider">🎯 引用評估集測試問題</h3>
          <button @click="showDatasetsModal = false" class="text-[#6b7280] hover:text-white text-xl font-bold">&times;</button>
        </div>
        
        <!-- Dataset Selector -->
        <div class="flex flex-col gap-1.5">
          <label class="text-[10px] text-[#9ca3af] font-semibold">選擇評估測試集</label>
          <select 
            v-model="selectedDatasetId" 
            @change="fetchDatasetDetails"
            class="bg-white/5 border border-white/8 rounded-lg text-white px-2 py-1.5 text-xs focus:outline-none focus:border-[#8b5cf6] bg-[#111827]"
          >
            <option v-for="ds in evalDatasets" :key="ds.dataset_id" :value="ds.dataset_id" class="bg-[#111827] text-white">
              {{ ds.name }} ({{ ds.item_count }} 題)
            </option>
          </select>
        </div>

        <!-- Questions list -->
        <div class="flex-grow overflow-y-auto flex flex-col gap-2 pr-1 text-xs min-h-[220px]">
          <div v-if="isDatasetLoading" class="text-center text-[#6b7280] py-8">
            載入問答明細中...
          </div>
          <div v-else-if="datasetItems.length === 0" class="text-center text-[#6b7280] py-8">
            無可用問答項目
          </div>
          <div 
            v-else
            v-for="(item, idx) in datasetItems" 
            :key="idx"
            class="bg-white/5 border rounded-lg p-3 hover:bg-white/10 transition-all cursor-pointer flex flex-col gap-1.5"
            :class="selectedDatasetItemIdx === idx ? 'border-[#8b5cf6] bg-[#8b5cf6]/5' : 'border-white/8'"
            @click="selectDatasetItem(idx)"
          >
            <div class="font-semibold text-white flex justify-between">
              <span>Q{{ idx + 1 }}: {{ item.question }}</span>
              <span v-if="selectedDatasetItemIdx === idx" class="text-[#a78bfa] font-bold">已選定</span>
            </div>
            <div class="text-[11px] text-[#9ca3af] pl-2 border-l border-white/5">
              <span class="text-[#6b7280]">標準答案 (GT):</span> {{ item.ground_truth }}
            </div>
          </div>
        </div>

        <div class="flex justify-end gap-3 border-t border-white/5 pt-3">
          <button 
            @click="showDatasetsModal = false"
            class="px-4 py-2 border border-white/8 hover:border-white/16 text-xs text-[#f3f4f6] font-semibold rounded-lg bg-white/5 transition-all"
          >
            取消
          </button>
          <button 
            @click="confirmDatasetImport"
            :disabled="selectedDatasetItemIdx === -1"
            class="px-4 py-2 bg-[#8b5cf6] hover:bg-[#a78bfa] disabled:bg-purple-900/50 disabled:text-purple-300/50 text-xs text-white font-semibold rounded-lg transition-all"
          >
            確定引用此問題
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}
.animate-fade-in {
  animation: fadeIn 0.35s cubic-bezier(0.4, 0, 0.2, 1);
}
</style>

