<script setup>
import { ref, watch, computed, onMounted } from 'vue'
import { useParamsStore } from '../../stores/paramsStore'
import api from '../../services/api'
import retrievalService from '../../services/retrievalService'
import attachmentService from '../../services/attachmentService'
import imageService from '../../services/imageService'

const paramsStore = useParamsStore()

// State
const managementFilenames = ref([])
const managementFilterFilename = ref('')
const managementPoints = ref([])
const selectedManagementChunkIds = ref([])
const isLoadingManagement = ref(false)

const managementStructuredMetadata = ref([])
const selectedLinks = ref([])
const isSavingLinks = ref(false)

const selectedAttachments = ref([])
const isSavingAttachments = ref(false)
const allAttachments = ref([])

const imageUrls = ref({})
const imageLoadFailed = ref({})

const loadChunkImage = async (filename) => {
  if (!filename || imageUrls.value[filename] || imageLoadFailed.value[filename]) return
  try {
    const url = await imageService.fetchImageBlobUrl(filename)
    imageUrls.value[filename] = url
  } catch (err) {
    console.error('Failed to load image blob:', err)
    // 圖片端點需要 JWT，直接用 <img src="/api/..."> 一定會 401，不設無意義的 fallback 網址，
    // 改記錄載入失敗狀態讓畫面顯示明確的失敗佔位圖
    imageLoadFailed.value[filename] = true
  }
}

const downloadImage = (filename) => {
  imageService.download(filename, filename)
}

const fetchAllAttachments = async () => {
  if (!paramsStore.knowledgeBaseId) {
    allAttachments.value = []
    return
  }
  try {
    const res = await attachmentService.list(paramsStore.knowledgeBaseId)
    allAttachments.value = res.items || []
  } catch (error) {
    console.error('無法取得附件清單:', error)
  }
}

const candidateLinks = computed(() => {
  return managementFilenames.value.filter(fn => fn !== managementFilterFilename.value)
})

const getAttachmentName = (attachmentId) => {
  const found = allAttachments.value.find(a => a.id === attachmentId)
  return found ? found.original_filename : attachmentId
}

const fetchManagementMetadata = async () => {
  if (!paramsStore.knowledgeBaseId) return
  try {
    const response = await api.get(`/api/knowledge-bases/${paramsStore.knowledgeBaseId}/metadata`)
    managementFilenames.value = response.data?.filenames || []
    managementStructuredMetadata.value = response.data?.structured_metadata || []
    
    if (managementFilterFilename.value && !managementFilenames.value.includes(managementFilterFilename.value)) {
      managementFilterFilename.value = ''
      managementPoints.value = []
      selectedLinks.value = []
      selectedAttachments.value = []
    } else if (managementFilterFilename.value) {
      const metadataItem = managementStructuredMetadata.value.find(item => item.filename === managementFilterFilename.value)
      selectedLinks.value = metadataItem?.links_to ? [...metadataItem.links_to] : []
      selectedAttachments.value = metadataItem?.linked_attachments ? [...metadataItem.linked_attachments] : []
    }
  } catch (error) {
    console.error('無法取得知識庫元資料:', error)
  }
}

const loadManagementPoints = async () => {
  if (!paramsStore.knowledgeBaseId || !managementFilterFilename.value) {
    managementPoints.value = []
    selectedLinks.value = []
    return
  }
  
  // Sync selectedLinks and selectedAttachments for this file
  const metadataItem = managementStructuredMetadata.value.find(item => item.filename === managementFilterFilename.value)
  selectedLinks.value = metadataItem?.links_to ? [...metadataItem.links_to] : []
  selectedAttachments.value = metadataItem?.linked_attachments ? [...metadataItem.linked_attachments] : []
  
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
        filter_filename: managementFilterFilename.value,
        disable_parent_merge: true
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
    results.forEach(point => {
      if (point.metadata?.chunk_type === 'image' && point.metadata?.image_filename) {
        loadChunkImage(point.metadata.image_filename)
      }
    })
  } catch (error) {
    console.error('載入檔案向量段落失敗:', error)
    alert('載入失敗，請確認後端連線。')
  } finally {
    isLoadingManagement.value = false
  }
}

const handleSaveLinks = async () => {
  if (!managementFilterFilename.value) return
  isSavingLinks.value = true
  try {
    await retrievalService.updateLinks(
      paramsStore.knowledgeBaseId,
      managementFilterFilename.value,
      selectedLinks.value
    )
    alert('儲存關聯成功！')
    await fetchManagementMetadata()
    await loadManagementPoints()
  } catch (error) {
    console.error('儲存關聯失敗:', error)
    alert('儲存關聯失敗，請確認後端連線。')
  } finally {
    isSavingLinks.value = false
  }
}

const handleSaveAttachments = async () => {
  if (!managementFilterFilename.value) return
  isSavingAttachments.value = true
  try {
    await retrievalService.updateAttachments(
      paramsStore.knowledgeBaseId,
      managementFilterFilename.value,
      selectedAttachments.value
    )
    alert('儲存關聯附件成功！')
    await fetchManagementMetadata()
    await loadManagementPoints()
  } catch (error) {
    console.error('儲存關聯附件失敗:', error)
    alert('儲存關聯附件失敗，請確認後端連線。')
  } finally {
    isSavingAttachments.value = false
  }
}

watch(() => paramsStore.knowledgeBaseId, (newId) => {
  if (newId) {
    fetchManagementMetadata()
    fetchAllAttachments()
    managementPoints.value = []
    selectedManagementChunkIds.value = []
  }
}, { immediate: true })

watch(managementPoints, (newPoints) => {
  if (!newPoints) return
  newPoints.forEach(p => {
    if (p.metadata?.chunk_type === 'image' && p.metadata?.image_filename) {
      loadChunkImage(p.metadata.image_filename)
    }
  })
}, { deep: true })

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

const handleDeleteFile = async () => {
  if (!managementFilterFilename.value) return
  if (!confirm(`確定要永久刪除檔案「${managementFilterFilename.value}」的所有向量段落資料嗎？`)) return
  
  isLoadingManagement.value = true
  try {
    const response = await retrievalService.deleteFileByFilename(paramsStore.knowledgeBaseId, managementFilterFilename.value)
    alert(`成功刪除檔案，共移除 ${response.deleted_count || 0} 筆向量段落。`)
    managementFilterFilename.value = ''
    managementPoints.value = []
    selectedManagementChunkIds.value = []
    fetchManagementMetadata()
  } catch (error) {
    console.error('刪除整個檔案失敗:', error)
    alert('刪除整個檔案失敗，請檢查後端連線或權限。')
  } finally {
    isLoadingManagement.value = false
  }
}

onMounted(() => {
  fetchManagementMetadata()
  fetchAllAttachments()
})
</script>

<template>
  <div class="flex flex-col gap-5">
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
        <button 
          v-if="managementFilterFilename"
          @click="handleDeleteFile"
          :disabled="isLoadingManagement"
          class="bg-red-500/20 hover:bg-red-500/30 text-red-300 border border-red-500/30 font-semibold px-5 py-2.5 rounded-lg text-xs transition-all h-[42px] whitespace-nowrap flex items-center gap-1.5"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="3 6 5 6 21 6"></polyline>
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
          </svg>
          刪除整個檔案
        </button>
      </div>

      <!-- Links To Association Section -->
      <div v-if="managementFilterFilename" class="border-t border-white/5 pt-4 flex flex-col gap-3 animate-fade-in">
        <div class="flex flex-col gap-1.5">
          <span class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">設定關聯檔案 (Links To)</span>
          <span class="text-[11px] text-[#6b7280]">設定關聯檔案後，雙階段檢索會同時拉取這些關聯檔案的內容作為上下文。</span>
        </div>
        <div class="flex gap-4">
          <div class="flex-grow bg-white/3 border border-white/8 rounded-lg p-3 max-h-[160px] overflow-y-auto flex flex-col gap-2">
            <div v-if="candidateLinks.length === 0" class="text-xs text-[#6b7280] py-4 text-center">
              無其他可用檔案以建立關聯
            </div>
            <label 
              v-else
              v-for="fn in candidateLinks" 
              :key="fn" 
              class="flex items-center gap-2 text-xs text-white cursor-pointer select-none hover:text-[#8b5cf6] transition-all"
            >
              <input 
                type="checkbox" 
                v-model="selectedLinks" 
                :value="fn"
                class="rounded bg-white/5 border-white/10 text-[#8b5cf6] focus:ring-[#8b5cf6]/50 cursor-pointer"
              />
              <span class="truncate">{{ fn }}</span>
            </label>
          </div>
          <div class="flex flex-col justify-end">
            <button 
              @click="handleSaveLinks"
              :disabled="isLoadingManagement || isSavingLinks"
              class="bg-emerald-600 hover:bg-emerald-500 disabled:bg-emerald-900/50 disabled:text-emerald-300/50 text-white font-semibold px-5 py-2.5 rounded-lg text-xs transition-all h-[42px] whitespace-nowrap flex items-center gap-1.5"
            >
              <svg v-if="isSavingLinks" class="animate-spin h-3.5 w-3.5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              <span>{{ isSavingLinks ? '儲存中...' : '儲存關聯關係' }}</span>
            </button>
          </div>
        </div>
      </div>

      <!-- Linked Attachments Section -->
      <div v-if="managementFilterFilename" class="border-t border-white/5 pt-4 flex flex-col gap-3 animate-fade-in">
        <div class="flex flex-col gap-1.5">
          <span class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">設定關聯附件 (Linked Attachments)</span>
          <span class="text-[11px] text-[#6b7280]">設定關聯附件後，若使用「語義混合附件查詢法」檢索到此檔案段落，會自動夾帶這些附件的下載連結與說明。</span>
        </div>
        <div class="flex gap-4">
          <div class="flex-grow bg-white/3 border border-white/8 rounded-lg p-3 max-h-[160px] overflow-y-auto flex flex-col gap-2">
            <div v-if="allAttachments.length === 0" class="text-xs text-[#6b7280] py-4 text-center">
              請先到「關聯附件管理與上傳」頁面為此知識庫上傳附件。
            </div>
            <label 
              v-else
              v-for="att in allAttachments" 
              :key="att.id" 
              class="flex items-center gap-2 text-xs text-white cursor-pointer select-none hover:text-[#8b5cf6] transition-all"
            >
              <input 
                type="checkbox" 
                v-model="selectedAttachments" 
                :value="att.id"
                class="rounded bg-white/5 border-white/10 text-[#8b5cf6] focus:ring-[#8b5cf6]/50 cursor-pointer"
              />
              <span class="truncate" :title="att.description">{{ att.original_filename }} <span v-if="att.description" class="text-[#6b7280]">({{ att.description }})</span></span>
            </label>
          </div>
          <div class="flex flex-col justify-end">
            <button 
              @click="handleSaveAttachments"
              :disabled="isLoadingManagement || isSavingAttachments"
              class="bg-emerald-600 hover:bg-emerald-500 disabled:bg-emerald-900/50 disabled:text-emerald-300/50 text-white font-semibold px-5 py-2.5 rounded-lg text-xs transition-all h-[42px] whitespace-nowrap flex items-center gap-1.5"
            >
              <svg v-if="isSavingAttachments" class="animate-spin h-3.5 w-3.5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              <span>{{ isSavingAttachments ? '儲存中...' : '儲存關聯附件' }}</span>
            </button>
          </div>
        </div>
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
              <span v-if="point.metadata?.chunk_type === 'image'" class="bg-purple-500/10 border border-purple-500/20 text-[#a78bfa] px-1.5 py-0.5 rounded text-[9px] flex items-center gap-1 select-none flex-shrink-0">
                🖼️ 圖片段落
              </span>
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

              <!-- Links To Badges -->
              <span v-if="point.metadata?.links_to?.length" class="flex gap-1 flex-shrink-0">
                <span 
                  v-for="link in point.metadata.links_to" 
                  :key="link"
                  class="bg-blue-500/10 border border-blue-500/20 text-[#60a5fa] px-1.5 py-0.5 rounded text-[9px]"
                  :title="'關聯檔案: ' + link"
                >
                  🔗 {{ link }}
                </span>
              </span>

              <!-- Linked Attachments Badges -->
              <span v-if="point.metadata?.linked_attachments?.length" class="flex gap-1 flex-shrink-0">
                <span
                  v-for="aid in point.metadata.linked_attachments"
                  :key="aid"
                  class="bg-emerald-500/10 border border-emerald-500/20 text-[#34d399] px-1.5 py-0.5 rounded text-[9px]"
                  :title="'關聯附件 ID: ' + aid"
                >
                  📎 {{ getAttachmentName(aid) }}
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
          
          <div v-if="point.metadata?.chunk_type === 'image'" class="flex flex-col sm:flex-row gap-4 items-start animate-fade-in">
            <div class="w-full sm:w-48 h-32 rounded-lg bg-black/40 flex items-center justify-center overflow-hidden border border-white/8 relative group flex-shrink-0">
              <img
                v-if="imageUrls[point.metadata.image_filename]"
                :src="imageUrls[point.metadata.image_filename]"
                class="max-h-full max-w-full object-contain"
                alt="Document Image"
              />
              <div v-else-if="imageLoadFailed[point.metadata.image_filename]" class="flex flex-col items-center gap-1 text-[#6b7280] text-[10px]">
                <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/>
                  <line x1="4" y1="4" x2="20" y2="20"/>
                </svg>
                圖片載入失敗
              </div>
              <svg v-else class="animate-spin h-5 w-5 text-[#6b7280]" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              <div v-if="imageUrls[point.metadata.image_filename]" class="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                <button
                  @click="downloadImage(point.metadata.image_filename)"
                  class="p-2 bg-[#8b5cf6] hover:bg-[#a78bfa] rounded-full text-white transition-all shadow-lg cursor-pointer"
                  title="下載原圖"
                >
                  <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>
                  </svg>
                </button>
              </div>
            </div>
            <div class="flex-grow flex flex-col gap-1.5 w-full">
              <span class="text-[10px] font-semibold text-[#a78bfa] uppercase tracking-wider select-none">圖片描述 (AI Generated Caption)</span>
              <p class="text-xs text-white leading-relaxed whitespace-pre-wrap">
                {{ point.content }}
              </p>
            </div>
          </div>
          <p v-else class="text-xs text-[#9ca3af] leading-relaxed whitespace-pre-wrap">
            {{ point.content }}
          </p>
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
