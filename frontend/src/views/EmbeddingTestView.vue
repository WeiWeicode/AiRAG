<script setup>
import { ref, watch, computed } from 'vue'
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
const tagsString = ref('')
const rawTextContent = ref('')
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
    chunksList.value = response.chunks || []
  } catch (error) {
    console.error('Backend chunking call failed:', error)
    alert('文本切分失敗，請檢查後端服務與連線')
  } finally {
    isChunking.value = false
  }
}

const triggerVectorization = async () => {
  if (chunksList.value.length === 0) {
    alert('請先點擊「開始文本切分」生成 Chunk 預覽，才能執行寫入向量庫動作。')
    return
  }

  isVectorizing.value = true
  vectorizationStats.value = null
  
  try {
    const parsedTags = tagsString.value.split(',')
      .map(t => t.trim())
      .filter(t => t.length > 0)

    const payload = {
      chunks: chunksList.value.map(c => ({ 
        index: c.index, 
        content: c.content, 
        metadata: { 
          filename: filename.value || 'unknown',
          source: uploadedFileId.value ? 'upload' : 'manual',
          tags: parsedTags
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

          <!-- Tags Input -->
          <div class="flex items-center gap-2.5 bg-white/3 border border-white/8 rounded-lg px-3 py-1.5 focus-within:border-[#8b5cf6] transition-all">
            <svg class="w-3.5 h-3.5 text-[#9ca3af] flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"></path>
              <line x1="7" y1="7" x2="7.01" y2="7"></line>
            </svg>
            <span class="text-xs text-[#9ca3af] select-none whitespace-nowrap">分類標籤:</span>
            <input 
              v-model="tagsString"
              type="text" 
              class="flex-grow bg-transparent text-white text-xs outline-none"
              placeholder="請輸入標籤，以英文逗號分隔 (例如: HR, 請假規定, 2026)"
            />
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
