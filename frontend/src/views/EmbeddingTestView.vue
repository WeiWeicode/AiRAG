<script setup>
import { ref, watch, computed, onMounted } from 'vue'
import FileUploader from '../components/embedding/FileUploader.vue'
import ChunkPreview from '../components/embedding/ChunkPreview.vue'
import TokenCounter from '../components/embedding/TokenCounter.vue'
import ChunkingParams from '../components/params/ChunkingParams.vue'
import { useParamsStore } from '../stores/paramsStore'
import embeddingService from '../services/embeddingService'
import api from '../services/api'
import retrievalService from '../services/retrievalService'

const paramsStore = useParamsStore()

// State
const uploadedFileId = ref('')
const filename = ref('unknown')
const rawTextContent = ref('')

// Tags & Classes Management
const allTags = ref([])
const allClasses = ref([])
const selectedTags = ref([])
const selectedClasses = ref([])
const batchSelectedTags = ref([])
const batchSelectedClasses = ref([])
const newTagName = ref('')
const newClassName = ref('')

const fetchTagsAndClasses = async () => {
  try {
    allTags.value = await embeddingService.getTags()
    allClasses.value = await embeddingService.getClasses()
  } catch (error) {
    console.error('無法載入標籤或類別名單:', error)
  }
}

const handleCreateTag = async () => {
  const val = newTagName.value.trim()
  if (!val) return
  try {
    await embeddingService.createTag(val)
    newTagName.value = ''
    await fetchTagsAndClasses()
  } catch (error) {
    alert(error.response?.data?.detail || '建立標籤失敗')
  }
}

const handleCreateClass = async () => {
  const val = newClassName.value.trim()
  if (!val) return
  try {
    await embeddingService.createClass(val)
    newClassName.value = ''
    await fetchTagsAndClasses()
  } catch (error) {
    alert(error.response?.data?.detail || '建立類別失敗')
  }
}

onMounted(() => {
  fetchTagsAndClasses()
})
const isChunking = ref(false)
const chunksList = ref([])

const isVectorizing = ref(false)
const vectorizationStats = ref(null)

// Tab state and management state
const activeTab = ref('indexing') // indexing | management
const managementFilenames = ref([])
const managementFilterFilename = ref('')
const managementPoints = ref([])
const selectedManagementChunkIds = ref([])
const isLoadingManagement = ref(false)

const handleUploadSuccess = (data) => {
  uploadedFileId.value = data.file_id || 'file_uploaded_id'
  rawTextContent.value = data.content || ''
  if (data.filename) {
    filename.value = data.filename
  }
}

const estimateTokens = (text) => {
  if (!text) return 0
  const englishWords = (text.match(/\b[a-zA-Z0-9]+\b/g) || []).length
  const cjkChars = (text.match(/[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]/g) || []).length
  const otherChars = text.length - (englishWords * 4) - cjkChars
  const estimated = Math.round(cjkChars * 0.85 + englishWords * 1.3 + otherChars * 0.3)
  return Math.max(1, estimated)
}

const triggerChunking = async () => {
  if (!rawTextContent.value.trim()) {
    alert('請上傳檔案或在此貼上純文字內容以進行切分測試。')
    return
  }

  isChunking.value = true
  chunksList.value = []
  vectorizationStats.value = null
  
  try {
    const payload = {
      file_id: uploadedFileId.value || null,
      content: rawTextContent.value.trim(),
      params: {
        chunk_size: paramsStore.chunkSize,
        chunk_overlap: paramsStore.chunkOverlap,
        separator: paramsStore.separator.replace('\\n', '\n') // Unescape newline representation
      }
    }
    const response = await embeddingService.chunkText(payload)
    let chunks = response.chunks || []
    
    if (paramsStore.enableStructuring) {
      const tags = selectedTags.value.join(', ') || '一般'
      const fname = filename.value || 'unknown'
      
      chunks = chunks.map(c => {
        const structuredContent = `[檔案名稱] ${fname}\n[段落編號] 第 ${c.index + 1} 段\n[分類標籤] ${tags}\n[主要內容]\n${c.content}`
        return {
          ...c,
          content: structuredContent,
          char_count: structuredContent.length,
          token_count: estimateTokens(structuredContent)
        }
      })
    }
    
    chunksList.value = chunks
  } catch (error) {
    console.error('Backend chunking call failed:', error)
    alert('文本切分失敗，請檢查後端服務與連線')
  } finally {
    isChunking.value = false
  }
}

const resetFields = () => {
  uploadedFileId.value = ''
  filename.value = 'unknown'
  selectedTags.value = []
  selectedClasses.value = []
  rawTextContent.value = ''
  chunksList.value = []
  vectorizationStats.value = null
}

const triggerVectorization = async () => {
  if (chunksList.value.length === 0) {
    alert('請先點擊「開始文本切分」生成 Chunk 預覽，才能執行寫入向量庫動作。')
    return
  }

  isVectorizing.value = true
  vectorizationStats.value = null
  
  try {
    const payload = {
      chunks: chunksList.value.map(c => ({ 
        index: c.index, 
        content: c.content, 
        metadata: { 
          filename: filename.value || 'unknown',
          source: uploadedFileId.value ? 'upload' : 'manual',
          tags: selectedTags.value,
          classes: selectedClasses.value
        } 
      })),
      knowledge_base_id: paramsStore.knowledgeBaseId,
      embedding_model: 'Qwen3-Embedding-8B-Q8_0.gguf'
    }
    
    const response = await embeddingService.vectorize(payload)
    vectorizationStats.value = {
      kbId: response.knowledge_base_id || paramsStore.knowledgeBaseId,
      insertedCount: response.inserted_count || chunksList.value.length,
      model: response.embedding_model || 'Qwen3-Embedding-8B-Q8_0.gguf',
      elapsedMs: response.elapsed_ms || 0
    }
    
    // Auto-refresh management list if they have it open
    fetchManagementMetadata()
  } catch (error) {
    console.error('Backend vectorization call failed:', error)
    alert('向量化與寫入失敗，請檢查後端服務與資料庫連線')
  } finally {
    isVectorizing.value = false
  }
}

const fetchManagementMetadata = async () => {
  if (!paramsStore.knowledgeBaseId) return
  try {
    const response = await api.get(`/api/knowledge-bases/${paramsStore.knowledgeBaseId}/metadata`)
    managementFilenames.value = response.data?.filenames || []
    if (managementFilterFilename.value && !managementFilenames.value.includes(managementFilterFilename.value)) {
      managementFilterFilename.value = ''
      managementPoints.value = []
    }
  } catch (error) {
    console.error('無法取得知識庫元資料:', error)
  }
}

const loadManagementPoints = async () => {
  if (!paramsStore.knowledgeBaseId || !managementFilterFilename.value) {
    managementPoints.value = []
    return
  }
  
  isLoadingManagement.value = true
  selectedManagementChunkIds.value = []
  
  try {
    const payload = {
      query: '',
      knowledge_base_id: paramsStore.knowledgeBaseId,
      params: {
        top_k: 500,
        score_threshold: 0.0,
        search_type: 'vector',
        filter_filename: managementFilterFilename.value
      }
    }
    const response = await retrievalService.search(payload)
    const results = response.results || []
    
    // Sort by chunk_index ascending
    results.sort((a, b) => {
      const idxA = a.metadata?.chunk_index !== undefined ? a.metadata.chunk_index : 0
      const idxB = b.metadata?.chunk_index !== undefined ? b.metadata.chunk_index : 0
      return idxA - idxB
    })
    
    managementPoints.value = results
  } catch (error) {
    console.error('載入檔案向量段落失敗:', error)
    alert('載入失敗，請確認後端連線。')
  } finally {
    isLoadingManagement.value = false
  }
}

watch(() => paramsStore.knowledgeBaseId, (newId) => {
  if (newId) {
    fetchManagementMetadata()
    managementPoints.value = []
    selectedManagementChunkIds.value = []
  }
}, { immediate: true })

watch(activeTab, (newTab) => {
  if (newTab === 'management') {
    fetchManagementMetadata()
  }
})

const isAllManagementSelected = computed(() => {
  return managementPoints.value.length > 0 && selectedManagementChunkIds.value.length === managementPoints.value.length
})

const toggleSelectAllManagement = () => {
  if (isAllManagementSelected.value) {
    selectedManagementChunkIds.value = []
  } else {
    selectedManagementChunkIds.value = managementPoints.value.map(p => p.chunk_id)
  }
}

const handleDeleteSingleManagement = async (pointId) => {
  if (!confirm('確定要永久刪除此向量段落資料嗎？')) return
  
  try {
    await retrievalService.batchDeletePoints(paramsStore.knowledgeBaseId, [pointId])
    managementPoints.value = managementPoints.value.filter(p => p.chunk_id !== pointId)
    selectedManagementChunkIds.value = selectedManagementChunkIds.value.filter(id => id !== pointId)
    fetchManagementMetadata()
  } catch (error) {
    console.error('刪除向量段落失敗:', error)
    alert('刪除失敗，請檢查後端連線或權限。')
  }
}

const handleBatchDeleteManagement = async () => {
  if (selectedManagementChunkIds.value.length === 0) return
  if (!confirm(`確定要永久刪除選取的 ${selectedManagementChunkIds.value.length} 筆向量段落資料嗎？`)) return
  
  try {
    await retrievalService.batchDeletePoints(paramsStore.knowledgeBaseId, selectedManagementChunkIds.value)
    const deletedSet = new Set(selectedManagementChunkIds.value)
    managementPoints.value = managementPoints.value.filter(p => !deletedSet.has(p.chunk_id))
    selectedManagementChunkIds.value = []
    fetchManagementMetadata()
  } catch (error) {
    console.error('批次刪除向量段落失敗:', error)
    alert('批次刪除失敗，請檢查後端連線或權限。')
  }
}

// Batch indexing state
const batchFiles = ref([]) // array of { id, name, size, status, progress, chunksCount, elapsedTime, message, fileObject }
const batchChunkSize = ref(20) // default chunk batch size when vectorizing
const batchDuplicateMode = ref('overwrite') // overwrite | skip
const isBatchProcessing = ref(false)
const batchProcessIndex = ref(-1) // index of file currently processing
const isBatchDragActive = ref(false)
const batchFileInput = ref(null)

const selectedExtension = ref('.pdf')
const batchChunkSizeExt = ref(512)
const batchChunkOverlapExt = ref(50)
const batchSeparatorExt = ref('\\n\\n')
const batchChunkModeExt = ref('standard')

watch(selectedExtension, (newExt) => {
  if (newExt === '.4gl') {
    batchChunkModeExt.value = 'parent_child'
    batchSeparatorExt.value = '\\n\\n'
    batchChunkSizeExt.value = 512
    batchChunkOverlapExt.value = 50
  } else if (newExt === '.pdf' || newExt === '.docx') {
    batchChunkModeExt.value = 'standard'
    batchSeparatorExt.value = '\\n'
    batchChunkSizeExt.value = 512
    batchChunkOverlapExt.value = 50
  } else {
    batchChunkModeExt.value = 'standard'
    batchSeparatorExt.value = '\\n\\n'
    batchChunkSizeExt.value = 512
    batchChunkOverlapExt.value = 50
  }
  // Clear the queue when extension changes
  batchFiles.value = []
}, { immediate: true })

// Timer states
const batchTotalElapsedTime = ref(0) // milliseconds
const currentFileStartTime = ref(0) // milliseconds
let batchTimerInterval = null

const startBatchTimer = () => {
  const startTime = Date.now()
  batchTotalElapsedTime.value = 0
  currentFileStartTime.value = 0
  batchTimerInterval = setInterval(() => {
    batchTotalElapsedTime.value = Date.now() - startTime
    
    // Dynamically update active file's elapsed time
    if (batchProcessIndex.value >= 0 && batchProcessIndex.value < batchFiles.value.length) {
      const activeFile = batchFiles.value[batchProcessIndex.value]
      if (currentFileStartTime.value > 0) {
        activeFile.elapsedTime = formatDuration(Date.now() - currentFileStartTime.value)
      }
    }
  }, 100)
}

const stopBatchTimer = () => {
  if (batchTimerInterval) {
    clearInterval(batchTimerInterval)
    batchTimerInterval = null
  }
}

const formatDuration = (ms) => {
  if (!ms) return '0.0s'
  return (ms / 1000).toFixed(1) + 's'
}

const showClearCompleted = computed(() => batchFiles.value.some(f => f.status === 'success' || f.status === 'failed'))

const triggerBatchFileInput = () => {
  if (!isBatchProcessing.value) {
    batchFileInput.value.click()
  }
}

const addFilesToQueue = (filesList) => {
  for (let i = 0; i < filesList.length; i++) {
    const file = filesList[i]
    
    // Check file extension
    const ext = '.' + file.name.split('.').pop().toLowerCase()
    if (ext !== selectedExtension.value) {
      alert(`僅限上傳符合副檔名「${selectedExtension.value}」的檔案！\n不符檔案：${file.name}`)
      continue
    }

    if (batchFiles.value.some(f => f.name === file.name)) {
      continue
    }
    batchFiles.value.push({
      id: Math.random().toString(36).substr(2, 9),
      name: file.name,
      size: (file.size / 1024).toFixed(1) + ' KB',
      status: 'pending',
      progress: 0,
      chunksCount: 0,
      elapsedTime: '',
      message: '等待中',
      fileObject: file
    })
  }
}

const handleBatchFileSelect = (e) => {
  const files = e.target.files
  if (files && files.length > 0) {
    addFilesToQueue(files)
  }
}

const handleBatchFileDrop = (e) => {
  isBatchDragActive.value = false
  if (isBatchProcessing.value) return
  const files = e.dataTransfer.files
  if (files && files.length > 0) {
    addFilesToQueue(files)
  }
}

const clearCompletedBatchFiles = () => {
  batchFiles.value = batchFiles.value.filter(f => f.status !== 'success' && f.status !== 'failed')
}

const removeBatchFile = (index) => {
  if (isBatchProcessing.value && index === batchProcessIndex.value) {
    alert('正在處理該檔案，無法移除。')
    return
  }
  batchFiles.value.splice(index, 1)
}

const clearAllBatchFiles = () => {
  if (isBatchProcessing.value) {
    if (!confirm('正在執行寫入中，確定要清空並停止嗎？')) return
    isBatchProcessing.value = false
  }
  batchFiles.value = []
  batchProcessIndex.value = -1
}

const overallProgress = computed(() => {
  if (batchFiles.value.length === 0) return 0
  const total = batchFiles.value.length * 100
  const current = batchFiles.value.reduce((acc, f) => acc + (f.progress || 0), 0)
  return Math.round((current / total) * 100)
})

const completedFilesCount = computed(() => {
  return batchFiles.value.filter(f => f.status === 'success').length
})

const startBatchProcessing = async () => {
  if (!paramsStore.knowledgeBaseId) {
    alert('請選擇目標知識庫。')
    return
  }
  if (batchFiles.value.length === 0) {
    alert('請先新增要向量化之檔案。')
    return
  }
  
  isBatchProcessing.value = true
  startBatchTimer()
  
  // 取得當前知識庫中已存在的檔案名稱列表
  let existingFilenames = []
  try {
    const response = await api.get(`/api/knowledge-bases/${paramsStore.knowledgeBaseId}/metadata`)
    existingFilenames = response.data?.filenames || []
  } catch (error) {
    console.error('無法取得最新知識庫元資料:', error)
  }
  
  for (let i = 0; i < batchFiles.value.length; i++) {
    // If the process was cancelled/stopped mid-way
    if (!isBatchProcessing.value) break

    const fileItem = batchFiles.value[i]
    if (fileItem.status === 'success') {
      continue
    }
    
    batchProcessIndex.value = i
    currentFileStartTime.value = Date.now()
    
    // 若重複模式設定為略過，且該檔案名稱已存在於向量資料庫中，則不覆蓋直接略過
    if (batchDuplicateMode.value === 'skip' && existingFilenames.includes(fileItem.name)) {
      fileItem.status = 'success'
      fileItem.progress = 100
      fileItem.message = '檔案已存在於向量庫中，已自動略過不覆蓋。'
      fileItem.elapsedTime = '0.0s'
      continue
    }
    
    fileItem.status = 'parsing'
    fileItem.progress = 10
    fileItem.message = '正在上傳並解析檔案...'
    
    try {
      // 1. Upload & Parse file to backend
      const uploadData = await embeddingService.uploadFile(fileItem.fileObject)
      const content = uploadData.content || ''
      const fname = uploadData.filename || fileItem.name
      
      fileItem.status = 'chunking'
      fileItem.progress = 30
      fileItem.message = '正在切分文本段落...'
      
      // 2. Chunk text
      const chunkPayload = {
        file_id: uploadData.file_id || null,
        filename: fname,
        content: content,
        params: {
          chunk_size: batchChunkSizeExt.value,
          chunk_overlap: batchChunkOverlapExt.value,
          separator: batchSeparatorExt.value.replace('\\n', '\n'),
          chunk_mode: batchChunkModeExt.value
        }
      }
      const chunkData = await embeddingService.chunkText(chunkPayload)
      let chunks = chunkData.chunks || []
      
      // Handle structuring if enabled
      if (paramsStore.enableStructuring) {
        const tags = batchSelectedTags.value.join(', ') || '一般'
        
        chunks = chunks.map(c => {
          const structuredContent = `[檔案名稱] ${fname}\n[段落編號] 第 ${c.index + 1} 段\n[分類標籤] ${tags}\n[主要內容]\n${c.content}`
          return {
            ...c,
            content: structuredContent,
            char_count: structuredContent.length,
            token_count: estimateTokens(structuredContent)
          }
        })
      }
      
      fileItem.chunksCount = chunks.length
      
      if (chunks.length === 0) {
        throw new Error('切分後未生成任何 Chunks')
      }
      
      // 3. Check and delete same filename
      fileItem.status = 'deleting'
      fileItem.progress = 50
      fileItem.message = '清理向量庫中同名檔案資料...'
      
      const deleteResult = await retrievalService.deleteFileByFilename(paramsStore.knowledgeBaseId, fname)
      const deletedCount = deleteResult.deleted_count || 0
      
      // 4. Vectorize in batches of chunks
      fileItem.status = 'vectorizing'
      fileItem.progress = 60
      
      const batchSize = batchChunkSize.value || 20
      const totalBatches = Math.ceil(chunks.length / batchSize)
      let insertedTotal = 0
         
      for (let b = 0; b < totalBatches; b++) {
        if (!isBatchProcessing.value) break

        fileItem.message = `寫入向量庫分批 (${b + 1}/${totalBatches})...`
        
        const startIdx = b * batchSize
        const endIdx = Math.min(startIdx + batchSize, chunks.length)
        const chunkBatch = chunks.slice(startIdx, endIdx)
        
        const vectorizePayload = {
          chunks: chunkBatch.map(c => ({
            index: c.index,
            content: c.content,
            metadata: {
              filename: fname,
              source: 'upload',
              tags: batchSelectedTags.value,
              classes: batchSelectedClasses.value,
              ...(c.metadata || {})
            }
          })),
          knowledge_base_id: paramsStore.knowledgeBaseId,
          embedding_model: 'Qwen3-Embedding-8B-Q8_0.gguf'
        }
        
        const vectorizeResponse = await embeddingService.vectorize(vectorizePayload)
        insertedTotal += (vectorizeResponse.inserted_count || chunkBatch.length)
        
        // Dynamic progress update between 60% and 98%
        const ratio = (b + 1) / totalBatches
        fileItem.progress = Math.round(60 + ratio * 38)
      }
      
      if (isBatchProcessing.value) {
        fileItem.status = 'success'
        fileItem.progress = 100
        fileItem.message = `完成！清理舊資料 ${deletedCount} 筆，寫入新向量 ${insertedTotal} 筆`
        
        // 成功寫入後，將該檔案名稱加入 existingFilenames 清單中，以防同批次重複處理衝突
        if (!existingFilenames.includes(fname)) {
          existingFilenames.push(fname)
        }
      }
      
    } catch (error) {
      console.error(`處理 ${fileItem.name} 錯誤:`, error)
      fileItem.status = 'failed'
      fileItem.progress = 100
      fileItem.message = error.response?.data?.detail || error.message || '處理失敗'
    }
  }
  
  isBatchProcessing.value = false
  batchProcessIndex.value = -1
  stopBatchTimer()
  fetchManagementMetadata()
}
</script>

<template>
  <div class="flex-grow flex gap-6 p-6 overflow-hidden h-full min-h-0">
    <!-- Left Edit Area -->
    <div class="flex-grow flex flex-col gap-5 min-w-0 h-full overflow-y-auto pr-1">
      
      <!-- Tab selector -->
      <div class="flex gap-4 border-b border-white/8 pb-3 flex-shrink-0">
        <button 
          @click="activeTab = 'indexing'" 
          :class="[
            'text-sm font-semibold pb-1.5 border-b-2 transition-all',
            activeTab === 'indexing' ? 'text-[#a78bfa] border-[#8b5cf6]' : 'text-[#9ca3af] border-transparent hover:text-white'
          ]"
        >
          資料切分與向量化寫入
        </button>
        <button 
          @click="activeTab = 'batch_indexing'" 
          :class="[
            'text-sm font-semibold pb-1.5 border-b-2 transition-all',
            activeTab === 'batch_indexing' ? 'text-[#a78bfa] border-[#8b5cf6]' : 'text-[#9ca3af] border-transparent hover:text-white'
          ]"
        >
          自動分批寫入
        </button>
        <button 
          @click="activeTab = 'management'" 
          :class="[
            'text-sm font-semibold pb-1.5 border-b-2 transition-all',
            activeTab === 'management' ? 'text-[#a78bfa] border-[#8b5cf6]' : 'text-[#9ca3af] border-transparent hover:text-white'
          ]"
        >
          已向量化資料管理與刪除
        </button>
      </div>

      <!-- Tab 1: Indexing & Vectorization -->
      <div v-if="activeTab === 'indexing'" class="flex flex-col gap-5">
        <!-- Drag & Drop / Upload -->
        <div class="bg-[#111827]/70 border border-white/8 rounded-2xl p-5 backdrop-blur-md">
          <FileUploader @upload-success="handleUploadSuccess" />
        </div>

        <!-- Raw Text Area -->
        <div class="bg-[#111827]/70 border border-white/8 rounded-2xl p-5 backdrop-blur-md flex flex-col gap-3">
          <div class="flex justify-between items-center">
            <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">直接輸入/編輯文本內容</label>
            <TokenCounter :text="rawTextContent" />
          </div>
          
          <!-- Filename Input -->
          <div class="flex items-center gap-2.5 bg-white/3 border border-white/8 rounded-lg px-3 py-1.5 focus-within:border-[#8b5cf6] transition-all">
            <svg class="w-3.5 h-3.5 text-[#9ca3af] flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <polyline points="14 2 14 8 20 8"></polyline>
            </svg>
            <span class="text-xs text-[#9ca3af] select-none whitespace-nowrap">檔案名稱:</span>
            <input 
              v-model="filename"
              type="text" 
              class="flex-grow bg-transparent text-white text-xs outline-none"
              placeholder="請輸入檔案名稱 (例如: doc_01.txt)"
            />
          </div>

          <!-- Classification tags (Tab 1) -->
          <div class="flex flex-col gap-2 bg-white/3 border border-white/8 rounded-lg p-3">
            <div class="flex items-center justify-between border-b border-white/5 pb-2">
              <div class="flex items-center gap-2">
                <svg class="w-3.5 h-3.5 text-[#9ca3af] flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"></path>
                  <line x1="7" y1="7" x2="7.01" y2="7"></line>
                </svg>
                <span class="text-xs font-semibold text-[#f3f4f6]">分類標籤 (Tags)</span>
              </div>
              <div class="flex items-center gap-1">
                <input 
                  v-model="newTagName" 
                  type="text"
                  placeholder="建立新標籤..."
                  class="bg-white/5 border border-white/10 rounded px-2 py-0.5 text-[10px] text-white focus:outline-none focus:border-[#8b5cf6] w-28"
                  @keyup.enter="handleCreateTag"
                />
                <button 
                  @click="handleCreateTag"
                  class="bg-[#8b5cf6] hover:bg-[#a78bfa] text-white px-1.5 py-0.5 rounded text-[10px] font-bold"
                >
                  +
                </button>
              </div>
            </div>
            <div class="flex flex-wrap gap-2 max-h-24 overflow-y-auto pt-1">
              <span v-if="allTags.length === 0" class="text-[10px] text-[#6b7280]">尚無標籤，請於右側建立</span>
              <label 
                v-for="tag in allTags" 
                :key="tag"
                class="flex items-center gap-1.5 px-2 py-1 rounded bg-white/5 hover:bg-white/10 border border-white/8 text-[11px] text-[#d1d5db] cursor-pointer transition-all select-none"
                :class="{ 'border-[#8b5cf6] bg-[#8b5cf6]/10 text-white': selectedTags.includes(tag) }"
              >
                <input 
                  type="checkbox" 
                  v-model="selectedTags" 
                  :value="tag" 
                  class="hidden"
                />
                <span>{{ tag }}</span>
              </label>
            </div>
          </div>

          <!-- Class Options (Tab 1) -->
          <div class="flex flex-col gap-2 bg-white/3 border border-white/8 rounded-lg p-3">
            <div class="flex items-center justify-between border-b border-white/5 pb-2">
              <div class="flex items-center gap-2">
                <svg class="w-3.5 h-3.5 text-[#9ca3af] flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
                </svg>
                <span class="text-xs font-semibold text-[#f3f4f6]">類別選項 (Class 屬性)</span>
              </div>
              <div class="flex items-center gap-1">
                <input 
                  v-model="newClassName" 
                  type="text"
                  placeholder="建立新類別..."
                  class="bg-white/5 border border-white/10 rounded px-2 py-0.5 text-[10px] text-white focus:outline-none focus:border-[#8b5cf6] w-28"
                  @keyup.enter="handleCreateClass"
                />
                <button 
                  @click="handleCreateClass"
                  class="bg-[#8b5cf6] hover:bg-[#a78bfa] text-white px-1.5 py-0.5 rounded text-[10px] font-bold"
                >
                  +
                </button>
              </div>
            </div>
            <div class="flex flex-wrap gap-2 max-h-24 overflow-y-auto pt-1">
              <span v-if="allClasses.length === 0" class="text-[10px] text-[#6b7280]">尚無類別，請於右側建立</span>
              <label 
                v-for="c in allClasses" 
                :key="c"
                class="flex items-center gap-1.5 px-2 py-1 rounded bg-white/5 hover:bg-white/10 border border-white/8 text-[11px] text-[#d1d5db] cursor-pointer transition-all select-none"
                :class="{ 'border-[#8b5cf6] bg-[#8b5cf6]/10 text-white': selectedClasses.includes(c) }"
              >
                <input 
                  type="checkbox" 
                  v-model="selectedClasses" 
                  :value="c" 
                  class="hidden"
                />
                <span>{{ c }}</span>
              </label>
            </div>
          </div>

          <textarea 
            v-model="rawTextContent"
            rows="8"
            class="bg-white/5 border border-white/8 rounded-lg text-white p-3.5 text-xs focus:outline-none focus:border-[#8b5cf6] resize-y"
            placeholder="在此貼上您要匯入的長文內容，或是拖曳上傳檔案解析..."
          ></textarea>

          <div class="flex gap-3 mt-2">
            <button 
              @click="triggerChunking"
              :disabled="isChunking || !rawTextContent.trim()"
              class="px-5 py-2.5 border border-white/8 hover:border-white/16 text-xs text-[#f3f4f6] font-semibold rounded-lg bg-white/5 transition-all"
            >
              開始文本切分
            </button>
            <button 
              @click="triggerVectorization"
              :disabled="isVectorizing || chunksList.length === 0"
              class="px-5 py-2.5 bg-[#8b5cf6] hover:bg-[#a78bfa] hover:shadow-[0_4px_12px_rgba(139,92,246,0.3)] disabled:bg-purple-900/50 disabled:text-purple-300/50 text-xs text-white font-semibold rounded-lg transition-all"
            >
              {{ isVectorizing ? '寫入中...' : '向量化並寫入資料庫' }}
            </button>
            <button 
              @click="resetFields"
              class="px-5 py-2.5 border border-red-500/20 hover:border-red-500/40 text-xs text-red-300 font-semibold rounded-lg bg-red-500/5 hover:bg-red-500/10 transition-all ml-auto flex items-center gap-1.5"
            >
              <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/>
              </svg>
              清空與重置
            </button>
          </div>
        </div>

        <!-- Vectorization Summary Stats -->
        <div 
          v-if="vectorizationStats" 
          class="bg-emerald-500/10 border border-emerald-500/20 rounded-2xl p-5 flex flex-col gap-2.5 animate-fade-in"
        >
          <div class="text-xs font-bold text-[#10b981] flex items-center gap-1.5">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="20 6 9 17 4 12"></polyline>
            </svg>
            向量化寫入成功 (Write to Qdrant complete)
          </div>
          <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 text-[10px] text-[#9ca3af] mt-1 pt-1.5 border-t border-emerald-500/10">
            <span>目標知識庫: <strong class="text-white">{{ vectorizationStats.kbId }}</strong></span>
            <span>寫入段落數: <strong class="text-white">{{ vectorizationStats.insertedCount }} Chunks</strong></span>
            <span>向量模型: <strong class="text-white font-mono">{{ vectorizationStats.model }}</strong></span>
            <span>寫入耗時: <strong class="text-white font-display">{{ vectorizationStats.elapsedMs }} ms</strong></span>
          </div>
        </div>
      </div>

      <!-- Tab 3: Batch Indexing -->
      <div v-else-if="activeTab === 'batch_indexing'" class="flex flex-col gap-5">
        
        <!-- Batch Upload Card -->
        <div class="bg-[#111827]/70 border border-white/8 rounded-2xl p-5 backdrop-blur-md">
          <div class="flex flex-col gap-2">
            <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">批次文件上傳</label>
            
            <input 
              ref="batchFileInput" 
              type="file" 
              class="hidden" 
              multiple
              :accept="selectedExtension"
              @change="handleBatchFileSelect"
            />
 
            <!-- Dropzone -->
            <div 
              @click="triggerBatchFileInput"
              @dragover.prevent="isBatchDragActive = true"
              @dragleave.prevent="isBatchDragActive = false"
              @drop.prevent="handleBatchFileDrop"
              class="border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all duration-200"
              :class="[
                isBatchDragActive 
                  ? 'border-[#8b5cf6] bg-[#8b5cf6]/10 text-white' 
                  : 'border-white/8 bg-white/1 text-[#9ca3af] hover:border-white/16 hover:bg-white/3',
                isBatchProcessing ? 'opacity-50 cursor-not-allowed pointer-events-none' : ''
              ]"
            >
              <svg 
                width="36" 
                height="36" 
                viewBox="0 0 24 24" 
                fill="none" 
                stroke="currentColor" 
                stroke-width="2" 
                stroke-linecap="round" 
                stroke-linejoin="round" 
                class="mx-auto mb-3 text-[#6b7280]"
              >
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/>
              </svg>
              <div class="text-xs font-semibold">
                {{ isBatchProcessing ? '佇列處理中，請稍候...' : '拖曳多個檔案至此或點擊上傳' }}
              </div>
              <div class="text-[10px] text-[#6b7280] mt-1">目前僅限制上傳 {{ selectedExtension }} 格式之檔案</div>
            </div>
          </div>
        </div>

        <!-- Configurations Card -->
        <div class="bg-[#111827]/70 border border-white/8 rounded-2xl p-5 backdrop-blur-md flex flex-col gap-3.5">
          <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">批次寫入設定</label>
          
          <div class="flex flex-col gap-3">
            <!-- Extension restriction dropdown -->
            <div class="flex items-center gap-2.5 bg-white/3 border border-white/8 rounded-lg px-3 py-2 focus-within:border-[#8b5cf6] transition-all">
              <svg class="w-3.5 h-3.5 text-[#9ca3af] flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                <polyline points="14 2 14 8 20 8"></polyline>
              </svg>
              <span class="text-xs text-[#9ca3af] select-none whitespace-nowrap">限制上傳副檔名:</span>
              <select 
                v-model="selectedExtension"
                class="flex-grow bg-transparent text-white text-xs outline-none cursor-pointer"
              >
                <option value=".pdf" class="bg-[#111827] text-white">PDF (.pdf)</option>
                <option value=".docx" class="bg-[#111827] text-white">DOCX (.docx)</option>
                <option value=".txt" class="bg-[#111827] text-white">TXT (.txt)</option>
                <option value=".md" class="bg-[#111827] text-white">Markdown (.md)</option>
                <option value=".4gl" class="bg-[#111827] text-white">Genero 4GL (.4gl)</option>
              </select>
            </div>

            <!-- Duplicate Action config -->
            <div class="flex items-center gap-2.5 bg-white/3 border border-white/8 rounded-lg px-3 py-2 focus-within:border-[#8b5cf6] transition-all">
              <svg class="w-3.5 h-3.5 text-[#9ca3af] flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
              </svg>
              <span class="text-xs text-[#9ca3af] select-none whitespace-nowrap">重複檔案處理:</span>
              <select 
                v-model="batchDuplicateMode"
                class="flex-grow bg-transparent text-white text-xs outline-none cursor-pointer"
              >
                <option value="overwrite" class="bg-[#111827] text-white">刪除重新上傳(覆蓋)</option>
                <option value="skip" class="bg-[#111827] text-white">舊檔案略過不覆蓋</option>
              </select>
            </div>

            <!-- Batch size config -->
            <div class="flex items-center gap-2.5 bg-white/3 border border-white/8 rounded-lg px-3 py-2 focus-within:border-[#8b5cf6] transition-all">
              <svg class="w-3.5 h-3.5 text-[#9ca3af] flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect x="3" y="3" width="7" height="9" rx="1"></rect>
                <rect x="14" y="3" width="7" height="5" rx="1"></rect>
                <rect x="14" y="12" width="7" height="9" rx="1"></rect>
                <rect x="3" y="16" width="7" height="5" rx="1"></rect>
              </svg>
              <span class="text-xs text-[#9ca3af] select-none whitespace-nowrap">向量寫入批次大小:</span>
              <input 
                v-model.number="batchChunkSize"
                type="number"
                min="1"
                max="200"
                class="flex-grow bg-transparent text-white text-xs outline-none font-mono"
                placeholder="預設 20"
              />
            </div>

            <!-- Customized chunk parameters for selected extension -->
            <div class="border border-white/5 bg-white/1 p-3 rounded-lg flex flex-col gap-3">
              <div class="text-[11px] font-bold text-[#a78bfa] select-none border-b border-white/5 pb-1">
                依 {{ selectedExtension }} 客製化切分設定
              </div>
              
              <!-- Chunk Size -->
              <div class="flex flex-col gap-1">
                <div class="flex justify-between items-center text-[10px]">
                  <span class="text-[#9ca3af]">切分大小 (Chunk Size):</span>
                  <span class="text-[#a78bfa] font-bold font-mono">{{ batchChunkSizeExt }}</span>
                </div>
                <input 
                  v-model.number="batchChunkSizeExt" 
                  type="range" 
                  min="128" 
                  max="1024" 
                  step="64"
                  class="w-full h-1 bg-white/10 rounded-lg appearance-none cursor-pointer accent-[#8b5cf6]"
                />
              </div>

              <!-- Chunk Overlap -->
              <div class="flex flex-col gap-1">
                <div class="flex justify-between items-center text-[10px]">
                  <span class="text-[#9ca3af]">重疊大小 (Overlap Size):</span>
                  <span class="text-[#a78bfa] font-bold font-mono">{{ batchChunkOverlapExt }}</span>
                </div>
                <input 
                  v-model.number="batchChunkOverlapExt" 
                  type="range" 
                  min="0" 
                  max="200" 
                  step="10"
                  class="w-full h-1 bg-white/10 rounded-lg appearance-none cursor-pointer accent-[#8b5cf6]"
                />
              </div>

              <!-- Separator -->
              <div class="flex items-center gap-2.5 bg-white/3 border border-white/8 rounded px-2 py-1 focus-within:border-[#8b5cf6] transition-all">
                <span class="text-[10px] text-[#9ca3af] select-none whitespace-nowrap">切分符號:</span>
                <input 
                  v-model="batchSeparatorExt"
                  type="text" 
                  class="flex-grow bg-transparent text-white text-[10px] outline-none font-mono"
                  placeholder="例如: \n\n"
                />
              </div>

              <!-- Chunk Mode -->
              <div class="flex items-center gap-2.5 bg-white/3 border border-white/8 rounded px-2 py-1 focus-within:border-[#8b5cf6] transition-all">
                <span class="text-[10px] text-[#9ca3af] select-none whitespace-nowrap">切分模式:</span>
                <select 
                  v-model="batchChunkModeExt"
                  class="flex-grow bg-transparent text-white text-[10px] outline-none cursor-pointer"
                >
                  <option value="standard" class="bg-[#111827] text-white">標準字元切分</option>
                  <option value="parent_child" class="bg-[#111827] text-white">大小雙層結構 (Parent-Child)</option>
                </select>
              </div>
            </div>

            <!-- Classification tags (Tab 2) -->
            <div class="flex flex-col gap-2 bg-white/3 border border-white/8 rounded-lg p-3">
              <div class="flex items-center justify-between border-b border-white/5 pb-2">
                <div class="flex items-center gap-2">
                  <svg class="w-3.5 h-3.5 text-[#9ca3af] flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"></path>
                    <line x1="7" y1="7" x2="7.01" y2="7"></line>
                  </svg>
                  <span class="text-xs font-semibold text-[#f3f4f6]">分類標籤 (Tags)</span>
                </div>
                <div class="flex items-center gap-1">
                  <input 
                    v-model="newTagName" 
                    type="text"
                    placeholder="建立新標籤..."
                    class="bg-white/5 border border-white/10 rounded px-2 py-0.5 text-[10px] text-white focus:outline-none focus:border-[#8b5cf6] w-28"
                    @keyup.enter="handleCreateTag"
                  />
                  <button 
                    @click="handleCreateTag"
                    class="bg-[#8b5cf6] hover:bg-[#a78bfa] text-white px-1.5 py-0.5 rounded text-[10px] font-bold"
                  >
                    +
                  </button>
                </div>
              </div>
              <div class="flex flex-wrap gap-2 max-h-24 overflow-y-auto pt-1">
                <span v-if="allTags.length === 0" class="text-[10px] text-[#6b7280]">尚無標籤，請於上方建立</span>
                <label 
                  v-for="tag in allTags" 
                  :key="tag"
                  class="flex items-center gap-1.5 px-2 py-1 rounded bg-white/5 hover:bg-white/10 border border-white/8 text-[11px] text-[#d1d5db] cursor-pointer transition-all select-none"
                  :class="{ 'border-[#8b5cf6] bg-[#8b5cf6]/10 text-white': batchSelectedTags.includes(tag) }"
                >
                  <input 
                    type="checkbox" 
                    v-model="batchSelectedTags" 
                    :value="tag" 
                    class="hidden"
                  />
                  <span>{{ tag }}</span>
                </label>
              </div>
            </div>

            <!-- Class Options (Tab 2) -->
            <div class="flex flex-col gap-2 bg-white/3 border border-white/8 rounded-lg p-3">
              <div class="flex items-center justify-between border-b border-white/5 pb-2">
                <div class="flex items-center gap-2">
                  <svg class="w-3.5 h-3.5 text-[#9ca3af] flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
                  </svg>
                  <span class="text-xs font-semibold text-[#f3f4f6]">類別選項 (Class 屬性)</span>
                </div>
                <div class="flex items-center gap-1">
                  <input 
                    v-model="newClassName" 
                    type="text"
                    placeholder="建立新類別..."
                    class="bg-white/5 border border-white/10 rounded px-2 py-0.5 text-[10px] text-white focus:outline-none focus:border-[#8b5cf6] w-28"
                    @keyup.enter="handleCreateClass"
                  />
                  <button 
                    @click="handleCreateClass"
                    class="bg-[#8b5cf6] hover:bg-[#a78bfa] text-white px-1.5 py-0.5 rounded text-[10px] font-bold"
                  >
                    +
                  </button>
                </div>
              </div>
              <div class="flex flex-wrap gap-2 max-h-24 overflow-y-auto pt-1">
                <span v-if="allClasses.length === 0" class="text-[10px] text-[#6b7280]">尚無類別，請於上方建立</span>
                <label 
                  v-for="c in allClasses" 
                  :key="c"
                  class="flex items-center gap-1.5 px-2 py-1 rounded bg-white/5 hover:bg-white/10 border border-white/8 text-[11px] text-[#d1d5db] cursor-pointer transition-all select-none"
                  :class="{ 'border-[#8b5cf6] bg-[#8b5cf6]/10 text-white': batchSelectedClasses.includes(c) }"
                >
                  <input 
                    type="checkbox" 
                    v-model="batchSelectedClasses" 
                    :value="c" 
                    class="hidden"
                  />
                  <span>{{ c }}</span>
                </label>
              </div>
            </div>
          </div>
          <div class="text-[10px] text-[#6b7280] leading-normal mt-0.5">
            * 向量寫入分批大小是指每次向向量庫寫入的 Chunk 數量，設定太高可能會因為單一 HTTP Payload 太大而連線失敗。
          </div>
        </div>

        <!-- Global Progress Bar -->
        <div v-if="batchFiles.length > 0" class="bg-[#111827]/70 border border-white/8 rounded-2xl p-5 backdrop-blur-md flex flex-col gap-3 animate-fade-in">
          <div class="flex justify-between items-center text-xs">
            <div class="flex flex-col gap-0.5">
              <span class="font-bold text-white">批次總進度 (Overall Process)</span>
              <span class="text-[10px] text-[#9ca3af] font-mono">累積耗時: {{ formatDuration(batchTotalElapsedTime) }}</span>
            </div>
            <span class="text-[#a78bfa] font-semibold">{{ overallProgress }}% ({{ completedFilesCount }} / {{ batchFiles.length }} 已完成)</span>
          </div>
          <div class="w-full h-2.5 bg-white/5 rounded-full overflow-hidden">
            <div 
              class="h-full bg-gradient-to-r from-[#8b5cf6] to-[#a78bfa] rounded-full transition-all duration-300 shadow-[0_0_12px_rgba(139,92,246,0.6)]"
              :style="{ width: overallProgress + '%' }"
            ></div>
          </div>
        </div>

        <!-- File Queue List Table -->
        <div v-if="batchFiles.length > 0" class="bg-[#111827]/70 border border-white/8 rounded-2xl p-5 backdrop-blur-md flex flex-col gap-4">
          <div class="flex justify-between items-center">
            <span class="text-xs font-bold text-white tracking-wider">上傳檔案佇列 ({{ batchFiles.length }} 個檔案)</span>
            <div class="flex gap-2">
              <button 
                v-if="showClearCompleted"
                @click="clearCompletedBatchFiles"
                :disabled="isBatchProcessing"
                class="px-3 py-1.5 border border-white/8 hover:border-white/16 disabled:opacity-40 text-[10px] text-[#9ca3af] hover:text-white rounded-lg transition-all"
              >
                清除已完成
              </button>
              <button 
                @click="clearAllBatchFiles"
                class="px-3 py-1.5 border border-red-500/20 hover:border-red-500/40 text-[10px] text-red-300 rounded-lg bg-red-500/5 hover:bg-red-500/10 transition-all"
              >
                清空佇列
              </button>
            </div>
          </div>

          <div class="overflow-x-auto w-full border border-white/5 rounded-xl">
            <table class="w-full text-left border-collapse text-xs">
              <thead>
                <tr class="bg-white/3 border-b border-white/8 text-[#9ca3af] font-semibold">
                  <th class="p-3">檔案名稱</th>
                  <th class="p-3 w-20 font-semibold">大小</th>
                  <th class="p-3 w-20 text-center font-semibold">切分數</th>
                  <th class="p-3 w-20 text-center font-semibold">耗時</th>
                  <th class="p-3 w-40 font-semibold">進度/狀態</th>
                  <th class="p-3 font-semibold">訊息與結果</th>
                  <th class="p-3 w-16 text-center font-semibold">操作</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-white/5">
                <tr 
                  v-for="(f, idx) in batchFiles" 
                  :key="f.id"
                  class="hover:bg-white/1 transition-all"
                  :class="[idx === batchProcessIndex ? 'bg-[#8b5cf6]/5 border-l-2 border-l-[#8b5cf6]' : '']"
                >
                  <!-- Filename -->
                  <td class="p-3 font-medium text-white truncate max-w-[200px]" :title="f.name">
                    {{ f.name }}
                  </td>
                  
                  <!-- Size -->
                  <td class="p-3 text-[#9ca3af] font-mono">
                    {{ f.size }}
                  </td>
                  
                  <!-- Chunks Count -->
                  <td class="p-3 text-center text-white font-mono">
                    {{ f.chunksCount || '-' }}
                  </td>
                  
                  <!-- Elapsed Time -->
                  <td class="p-3 text-center text-[#a78bfa] font-mono">
                    {{ f.elapsedTime || '-' }}
                  </td>
                  
                  <!-- Status & Progress -->
                  <td class="p-3">
                    <div class="flex flex-col gap-1.5">
                      <!-- Badge & text -->
                      <span class="flex items-center gap-1.5 font-semibold text-[10px]">
                        <!-- Loader / Icons -->
                        <svg v-if="f.status === 'parsing' || f.status === 'chunking' || f.status === 'deleting' || f.status === 'vectorizing'" class="animate-spin h-3 w-3 text-[#a78bfa]" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                        </svg>
                        
                        <span 
                          :class="{
                            'text-[#9ca3af]': f.status === 'pending',
                            'text-[#f59e0b]': f.status === 'parsing' || f.status === 'chunking' || f.status === 'deleting',
                            'text-[#a78bfa]': f.status === 'vectorizing',
                            'text-emerald-400': f.status === 'success',
                            'text-red-400': f.status === 'failed'
                          }"
                        >
                          {{ 
                            f.status === 'pending' ? '等待中' :
                            f.status === 'parsing' ? '解析中' :
                            f.status === 'chunking' ? '切分中' :
                            f.status === 'deleting' ? '清理中' :
                            f.status === 'vectorizing' ? '寫入中' :
                            f.status === 'success' ? '已完成' :
                            f.status === 'failed' ? '失敗' : f.status
                          }}
                        </span>
                      </span>
                      
                      <!-- Mini Progress bar -->
                      <div class="w-full h-1 bg-white/5 rounded-full overflow-hidden">
                        <div 
                          class="h-full rounded-full transition-all duration-300"
                          :class="[
                            f.status === 'success' ? 'bg-emerald-400' :
                            f.status === 'failed' ? 'bg-red-400' : 'bg-[#8b5cf6]'
                          ]"
                          :style="{ width: f.progress + '%' }"
                        ></div>
                      </div>
                    </div>
                  </td>
                  
                  <!-- Message -->
                  <td class="p-3 text-[11px] leading-relaxed" :class="[f.status === 'failed' ? 'text-red-400/80 font-mono' : 'text-[#9ca3af]']">
                    {{ f.message }}
                  </td>
                  
                  <!-- Actions -->
                  <td class="p-3 text-center">
                    <button 
                      @click="removeBatchFile(idx)"
                      :disabled="isBatchProcessing && idx === batchProcessIndex"
                      class="text-gray-500 hover:text-red-400 hover:bg-white/5 p-1 rounded transition-all disabled:opacity-30 disabled:pointer-events-none"
                      title="從佇列移除"
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <line x1="18" y1="6" x2="6" y2="18"></line>
                        <line x1="6" y1="6" x2="18" y2="18"></line>
                      </svg>
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="flex gap-4 mt-2">
            <button 
              @click="startBatchProcessing"
              :disabled="isBatchProcessing || batchFiles.length === 0"
              class="px-6 py-2.5 bg-[#8b5cf6] hover:bg-[#a78bfa] hover:shadow-[0_4px_12px_rgba(139,92,246,0.3)] disabled:bg-purple-900/50 disabled:text-purple-300/50 text-xs text-white font-semibold rounded-lg transition-all flex items-center gap-2"
            >
              <svg v-if="isBatchProcessing" class="animate-spin h-3.5 w-3.5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              {{ isBatchProcessing ? '分批寫入處理中...' : '開始分批處理寫入' }}
            </button>

            <button 
              v-if="isBatchProcessing"
              @click="isBatchProcessing = false"
              class="px-5 py-2.5 border border-red-500/20 hover:border-red-500/40 text-xs text-red-300 font-semibold rounded-lg bg-red-500/5 hover:bg-red-500/10 transition-all flex items-center gap-1.5"
            >
              停止處理
            </button>
          </div>
        </div>
      </div>

      <!-- Tab 2: Vector Points Management & Deletion -->
      <div v-else-if="activeTab === 'management'" class="flex flex-col gap-5">
        <!-- File Selector Card -->
        <div class="bg-[#111827]/70 border border-white/8 rounded-2xl p-5 backdrop-blur-md flex flex-col gap-4">
          <div class="text-sm font-bold text-white tracking-wider flex justify-between items-center">
            <span>向量資料與檔案管理</span>
            <span class="text-xs text-[#9ca3af] font-normal">目前知識庫: <strong class="text-white">{{ paramsStore.knowledgeBaseId }}</strong></span>
          </div>

          <div class="flex gap-4 items-end">
            <div class="flex-grow flex flex-col gap-2">
              <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">選擇檔案名稱 (Filter Filename)</label>
              <select 
                v-model="managementFilterFilename" 
                @change="loadManagementPoints"
                class="bg-white/5 border border-white/8 rounded-lg text-white px-3.5 py-2.5 text-sm focus:outline-none focus:border-[#8b5cf6] transition-all w-full"
              >
                <option value="" class="bg-[#111827] text-white">-- 請選擇檔案 --</option>
                <option 
                  v-for="fn in managementFilenames" 
                  :key="fn" 
                  :value="fn" 
                  class="bg-[#111827] text-white"
                >
                  {{ fn }}
                </option>
              </select>
            </div>
            <button 
              @click="loadManagementPoints"
              :disabled="isLoadingManagement || !managementFilterFilename"
              class="bg-[#8b5cf6] hover:bg-[#a78bfa] disabled:bg-purple-900/50 disabled:text-purple-300/50 text-white font-semibold px-5 py-2.5 rounded-lg text-xs transition-all h-[42px] whitespace-nowrap flex items-center gap-1.5"
            >
              <svg v-if="isLoadingManagement" class="animate-spin h-3.5 w-3.5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              {{ isLoadingManagement ? '載入中...' : '重新整理 / 載入' }}
            </button>
          </div>
        </div>

        <!-- Chunks List Card -->
        <div v-if="managementFilterFilename" class="bg-[#111827]/70 border border-white/8 rounded-2xl p-5 backdrop-blur-md flex flex-col gap-4">
          <!-- Header stats & batch actions -->
          <div class="flex justify-between items-center pb-3 border-b border-white/5 flex-shrink-0">
            <div class="flex items-center gap-4">
              <span class="text-xs text-[#9ca3af]">該檔案在向量庫中共有 <strong class="text-white">{{ managementPoints.length }}</strong> 個段落 (Points)</span>
              <div v-if="managementPoints.length > 0" class="flex items-center gap-3 border-l border-white/10 pl-4">
                <label class="flex items-center gap-1.5 text-xs text-[#9ca3af] cursor-pointer select-none">
                  <input 
                    type="checkbox" 
                    :checked="isAllManagementSelected" 
                    @change="toggleSelectAllManagement"
                    class="rounded bg-white/5 border-white/10 text-[#8b5cf6] focus:ring-[#8b5cf6]/50 cursor-pointer"
                  />
                  全選
                </label>
                <button 
                  v-if="selectedManagementChunkIds.length > 0"
                  @click="handleBatchDeleteManagement"
                  class="bg-red-500/20 hover:bg-red-500/30 text-red-300 border border-red-500/30 px-2.5 py-1 rounded text-xs font-semibold flex items-center gap-1 transition-all animate-fade-in"
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="3 6 5 6 21 6"></polyline>
                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                  </svg>
                  批次刪除選取 ({{ selectedManagementChunkIds.length }})
                </button>
              </div>
            </div>
          </div>

          <!-- Points list -->
          <div class="flex flex-col gap-4 max-h-[500px] overflow-y-auto pr-1">
            <div v-if="isLoadingManagement" class="py-12 text-center text-xs text-[#9ca3af] flex items-center justify-center gap-2">
              <svg class="animate-spin h-4 w-4 text-[#8b5cf6]" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              載入資料中...
            </div>
            <div v-else-if="managementPoints.length === 0" class="text-center text-xs text-[#6b7280] py-12">
              該檔案在此知識庫中沒有向量段落，或已被全數刪除。
            </div>
            <div 
              v-else
              v-for="(point, idx) in managementPoints" 
              :key="point.chunk_id || idx"
              class="bg-white/2 border border-white/8 rounded-xl p-4 hover:border-white/16 hover:bg-white/4 transition-all flex flex-col gap-3"
            >
              <div class="flex justify-between items-center gap-4 border-b border-white/5 pb-2">
                <span class="text-xs font-semibold text-white truncate flex items-center gap-2 flex-grow min-w-0">
                  <input 
                    type="checkbox" 
                    v-model="selectedManagementChunkIds"
                    :value="point.chunk_id"
                    class="rounded bg-white/5 border-white/10 text-[#8b5cf6] focus:ring-[#8b5cf6]/50 cursor-pointer flex-shrink-0"
                  />
                  <span class="truncate">[{{ point.metadata?.filename || '未知檔案' }}] P.{{ point.metadata?.page || '?' }}</span>
                  <span class="text-[#6b7280] flex-shrink-0">段落索引: #{{ point.metadata?.chunk_index || idx }}</span>
                  
                  <!-- Parent-Child Chunks Badges -->
                  <span v-if="point.metadata?.parent_id" class="flex gap-1 flex-shrink-0">
                    <span class="bg-[#10b981]/10 border border-[#10b981]/20 text-[#34d399] px-1.5 py-0.5 rounded text-[9px]" :title="'父區塊 ID: ' + point.metadata.parent_id">
                      父區塊: {{ point.metadata.parent_id }}
                    </span>
                    <span v-if="point.metadata?.function_name" class="bg-[#3b82f6]/10 border border-[#3b82f6]/20 text-[#60a5fa] px-1.5 py-0.5 rounded text-[9px]">
                      類型: {{ point.metadata.type }} | 函數: {{ point.metadata.function_name }}
                    </span>
                  </span>

                  <span v-if="point.metadata?.tags?.length" class="flex gap-1 flex-shrink-0">
                    <span 
                      v-for="t in point.metadata.tags" 
                      :key="t"
                      class="bg-[#8b5cf6]/10 border border-[#8b5cf6]/20 text-[#a78bfa] px-1.5 py-0.5 rounded text-[9px]"
                    >
                      {{ t }}
                    </span>
                  </span>
                </span>
                <button 
                  @click="handleDeleteSingleManagement(point.chunk_id)"
                  class="text-red-400 hover:text-red-300 hover:bg-red-500/10 p-1.5 rounded transition-all flex-shrink-0"
                  title="刪除此向量段落"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="3 6 5 6 21 6"></polyline>
                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                  </svg>
                </button>
              </div>
              <p class="text-xs text-[#9ca3af] leading-relaxed whitespace-pre-wrap">
                {{ point.content }}
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Right Side Config & Chunks Preview -->
    <div class="w-[320px] flex-shrink-0 flex flex-col gap-5 overflow-y-auto pr-1 h-full pb-6">
      <!-- Parameters -->
      <ChunkingParams />

      <!-- Chunks Result Feed -->
      <div v-if="activeTab === 'indexing'" class="flex-grow bg-[#111827]/40 border border-white/8 rounded-2xl p-5 flex flex-col gap-4 min-h-[300px]">
        <div class="text-xs font-bold text-white border-b border-white/8 pb-2 tracking-wider">
          切分預覽 (Chunks Preview: {{ chunksList.length }} 段)
        </div>
        <div class="flex-grow overflow-y-auto max-h-[500px]">
          <div v-if="isChunking" class="text-xs text-[#9ca3af] py-6 text-center">正在進行切分運算...</div>
          <div v-else-if="chunksList.length === 0" class="text-xs text-[#6b7280] py-6 text-center">點擊「開始文本切分」檢視切分預覽</div>
          <ChunkPreview v-else :chunks="chunksList" />
        </div>
      </div>

      <!-- Batch Summary -->
      <div v-else-if="activeTab === 'batch_indexing'" class="flex-grow bg-[#111827]/40 border border-white/8 rounded-2xl p-5 flex flex-col gap-4 min-h-[300px]">
        <div class="text-xs font-bold text-white border-b border-white/8 pb-2 tracking-wider">
          批次寫入摘要 (Batch Summary)
        </div>
        <div class="flex flex-col gap-3 text-xs">
          <div class="flex justify-between items-center bg-white/3 border border-white/8 p-3 rounded-lg">
            <span class="text-[#9ca3af]">佇列檔案總數:</span>
            <span class="text-white font-bold">{{ batchFiles.length }}</span>
          </div>
          <div class="flex justify-between items-center bg-white/3 border border-white/8 p-3 rounded-lg">
            <span class="text-[#9ca3af]">已成功寫入:</span>
            <span class="text-emerald-400 font-bold">{{ completedFilesCount }}</span>
          </div>
          <div class="flex justify-between items-center bg-white/3 border border-white/8 p-3 rounded-lg">
            <span class="text-[#9ca3af]">執行進度:</span>
            <span class="text-[#a78bfa] font-bold">{{ overallProgress }}%</span>
          </div>
          <div class="flex justify-between items-center bg-white/3 border border-white/8 p-3 rounded-lg">
            <span class="text-[#9ca3af]">累積耗時:</span>
            <span class="text-[#a78bfa] font-mono font-bold">{{ formatDuration(batchTotalElapsedTime) }}</span>
          </div>
          
          <div class="mt-2 text-[10px] text-[#6b7280] leading-relaxed">
            * 系統會以單執行緒依序處理檔案。<br>
            * 若同名檔案存在於向量庫中，寫入前會自動將舊向量刪除，避免產生重複資料。
          </div>
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
