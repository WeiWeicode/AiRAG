<script setup>
import { ref, watch, computed, onMounted, onUnmounted } from 'vue'
import { useParamsStore } from '../../stores/paramsStore'
import embeddingService from '../../services/embeddingService'
import api from '../../services/api'
import retrievalService from '../../services/retrievalService'

const paramsStore = useParamsStore()

// Tags & Classes Management
const allTags = ref([])
const allClasses = ref([])
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

const estimateTokens = (text) => {
  if (!text) return 0
  const englishWords = (text.match(/\b[a-zA-Z0-9]+\b/g) || []).length
  const cjkChars = (text.match(/[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]/g) || []).length
  const otherChars = text.length - (englishWords * 4) - cjkChars
  const estimated = Math.round(cjkChars * 0.85 + englishWords * 1.3 + otherChars * 0.3)
  return Math.max(1, estimated)
}

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
}

onMounted(() => {
  fetchTagsAndClasses()
})

onUnmounted(() => {
  stopBatchTimer()
})
</script>

<template>
  <div class="flex flex-col gap-5">
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

        <!-- Classification tags -->
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

        <!-- Class Options -->
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

    <!-- Teleport Batch Summary to right sidebar container -->
    <Teleport to="#sidebar-batch-indexing" defer>
      <div class="flex-grow bg-[#111827]/40 border border-white/8 rounded-2xl p-5 flex flex-col gap-4 min-h-[300px]">
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
    </Teleport>
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
