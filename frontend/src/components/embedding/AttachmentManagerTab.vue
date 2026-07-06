<script setup>
import { ref, watch, onMounted } from 'vue'
import { useParamsStore } from '../../stores/paramsStore'
import attachmentService from '../../services/attachmentService'

const paramsStore = useParamsStore()

// State
const attachments = ref([])
const isLoading = ref(false)
const isUploading = ref(false)

// Form Fields
const uploadFile = ref(null)
const description = ref('')
const tags = ref('')
const classes = ref('')
const fileInputRef = ref(null)

const fetchAttachments = async () => {
  if (!paramsStore.knowledgeBaseId) return
  isLoading.value = true
  try {
    const res = await attachmentService.list(paramsStore.knowledgeBaseId)
    attachments.value = res.items || []
  } catch (error) {
    console.error('無法取得附件清單:', error)
  } finally {
    isLoading.value = false
  }
}

const handleFileChange = (e) => {
  const files = e.target.files
  if (files && files.length > 0) {
    uploadFile.value = files[0]
  }
}

const handleUpload = async () => {
  if (!paramsStore.knowledgeBaseId) return
  if (!uploadFile.value) {
    alert('請選擇要上傳的檔案')
    return
  }

  isUploading.value = true
  try {
    const payload = {
      knowledge_base_id: paramsStore.knowledgeBaseId,
      description: description.value,
      tags: tags.value,
      classes: classes.value,
      file: uploadFile.value
    }
    await attachmentService.upload(payload)
    alert('上傳成功！')
    
    // Clear form
    uploadFile.value = null
    description.value = ''
    tags.value = ''
    classes.value = ''
    if (fileInputRef.value) {
      fileInputRef.value.value = ''
    }
    
    await fetchAttachments()
  } catch (error) {
    console.error('上傳失敗:', error)
    alert('上傳失敗，請確認檔案大小與格式。')
  } finally {
    isUploading.value = false
  }
}

const handleDelete = async (id, filename) => {
  if (!confirm(`確定要刪除附件「${filename}」嗎？`)) return
  try {
    await attachmentService.remove(id)
    alert('刪除成功')
    await fetchAttachments()
  } catch (error) {
    console.error('刪除失敗:', error)
    alert('刪除失敗，請稍後再試。')
  }
}

const handleDownload = async (id, filename) => {
  try {
    await attachmentService.download(id, filename)
  } catch (error) {
    console.error('下載附件失敗:', error)
    alert('下載附件失敗，請確認後端連線。')
  }
}

// Listen for KB change
watch(() => paramsStore.knowledgeBaseId, (newVal) => {
  if (newVal) {
    fetchAttachments()
  }
}, { immediate: true })

onMounted(() => {
  fetchAttachments()
})
</script>

<template>
  <div class="flex flex-col gap-5">
    <!-- Upload Attachment Card -->
    <div class="bg-[#111827]/70 border border-white/8 rounded-2xl p-5 backdrop-blur-md flex flex-col gap-4">
      <div class="text-sm font-bold text-white tracking-wider flex justify-between items-center">
        <span>上傳關聯附件</span>
        <span class="text-xs text-[#9ca3af] font-normal">目前知識庫: <strong class="text-white">{{ paramsStore.knowledgeBaseId }}</strong></span>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <!-- Left inputs -->
        <div class="flex flex-col gap-3">
          <div class="flex flex-col gap-1.5">
            <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">選擇檔案</label>
            <input 
              type="file" 
              ref="fileInputRef"
              @change="handleFileChange"
              class="bg-white/5 border border-white/8 rounded-lg text-white px-3.5 py-2 text-sm focus:outline-none focus:border-[#8b5cf6] transition-all file:mr-4 file:py-1 file:px-3 file:rounded-md file:border-0 file:text-xs file:font-semibold file:bg-white/10 file:text-white hover:file:bg-white/20 file:cursor-pointer"
            />
          </div>

          <div class="flex flex-col gap-1.5">
            <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">檔案描述（備註）</label>
            <textarea
              v-model="description"
              rows="3"
              placeholder="請輸入此檔案之用途或備註（選填，僅供顯示參考。AI 讀取附件內容時，會優先自動擷取檔案本身的實際文字內容，只有在無法自動擷取時才會改用這裡的備註）"
              class="bg-white/5 border border-white/8 rounded-lg text-white px-3.5 py-2.5 text-sm focus:outline-none focus:border-[#8b5cf6] transition-all resize-none"
            ></textarea>
          </div>
        </div>

        <!-- Right inputs -->
        <div class="flex flex-col gap-3">
          <div class="flex flex-col gap-1.5">
            <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">標籤 (Tags)</label>
            <input 
              type="text" 
              v-model="tags"
              placeholder="例如: 說明書, 保固, 使用說明（選填，逗號分隔）"
              class="bg-white/5 border border-white/8 rounded-lg text-white px-3.5 py-2.5 text-sm focus:outline-none focus:border-[#8b5cf6] transition-all"
            />
          </div>

          <div class="flex flex-col gap-1.5">
            <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">類別 / 階層 (Classes)</label>
            <input 
              type="text" 
              v-model="classes"
              placeholder="例如: 產品文件, 手冊（選填，逗號分隔）"
              class="bg-white/5 border border-white/8 rounded-lg text-white px-3.5 py-2.5 text-sm focus:outline-none focus:border-[#8b5cf6] transition-all"
            />
          </div>

          <div class="flex-grow flex items-end justify-end">
            <button 
              @click="handleUpload"
              :disabled="isUploading || !uploadFile"
              class="bg-[#8b5cf6] hover:bg-[#a78bfa] disabled:bg-purple-900/50 disabled:text-purple-300/50 text-white font-semibold px-6 py-2.5 rounded-lg text-xs transition-all flex items-center gap-1.5 cursor-pointer"
            >
              <svg v-if="isUploading" class="animate-spin h-3.5 w-3.5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              <span>{{ isUploading ? '上傳中...' : '開始上傳附件' }}</span>
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Attachments List Card -->
    <div class="bg-[#111827]/70 border border-white/8 rounded-2xl p-5 backdrop-blur-md flex flex-col gap-4">
      <div class="text-sm font-bold text-white tracking-wider flex justify-between items-center pb-3 border-b border-white/5">
        <span>已上傳附件列表 (共 {{ attachments.length }} 個)</span>
      </div>

      <div class="flex flex-col gap-3 max-h-[500px] overflow-y-auto pr-1">
        <div v-if="isLoading" class="py-12 text-center text-xs text-[#9ca3af] flex items-center justify-center gap-2">
          <svg class="animate-spin h-4 w-4 text-[#8b5cf6]" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
          讀取清單中...
        </div>

        <div v-else-if="attachments.length === 0" class="text-center text-xs text-[#6b7280] py-12">
          目前無任何附件檔案。請使用上方表單上傳。
        </div>

        <div 
          v-else
          v-for="att in attachments" 
          :key="att.id"
          class="bg-white/2 border border-white/8 rounded-xl p-4 hover:border-white/16 hover:bg-white/4 transition-all flex justify-between items-start gap-4"
        >
          <div class="flex flex-col gap-1.5 flex-grow min-w-0">
            <div class="flex items-center gap-2">
              <span class="text-xs font-semibold text-white truncate max-w-[250px] md:max-w-[400px]" :title="att.original_filename">
                📂 {{ att.original_filename }}
              </span>
              <span class="text-[10px] text-[#6b7280] flex-shrink-0">
                ({{ (att.size / 1024).toFixed(1) }} KB)
              </span>
              <span
                v-if="att.has_extracted_content"
                class="bg-emerald-500/10 border border-emerald-500/20 text-[#34d399] px-1.5 py-0.5 rounded text-[9px] flex-shrink-0"
                title="AI 讀取附件內容時，將使用自動從檔案擷取出的實際文字內容"
              >
                ✓ 已擷取實際內容
              </span>
              <span
                v-else
                class="bg-amber-500/10 border border-amber-500/20 text-amber-300 px-1.5 py-0.5 rounded text-[9px] flex-shrink-0"
                :title="att.extraction_error ? ('自動擷取失敗：' + att.extraction_error + '，AI 讀取附件內容時將改用下方備註') : 'AI 讀取附件內容時將改用下方備註'"
              >
                ⚠ 無法自動擷取內容
              </span>
            </div>

            <p v-if="att.description" class="text-xs text-[#9ca3af] leading-relaxed whitespace-pre-wrap">
              {{ att.description }}
            </p>
            <p v-else class="text-xs text-[#52525b] italic">
              無說明描述
            </p>

            <!-- Tags & Classes badges -->
            <div class="flex flex-wrap gap-1 mt-1.5">
              <span 
                v-for="t in att.tags" 
                :key="t" 
                class="bg-[#8b5cf6]/10 border border-[#8b5cf6]/20 text-[#a78bfa] px-1.5 py-0.5 rounded text-[9px]"
              >
                {{ t }}
              </span>
              <span 
                v-for="c in att.classes" 
                :key="c" 
                class="bg-blue-500/10 border border-blue-500/20 text-[#60a5fa] px-1.5 py-0.5 rounded text-[9px]"
              >
                {{ c }}
              </span>
            </div>
          </div>

          <div class="flex items-center gap-2 flex-shrink-0">
            <button 
              @click="handleDownload(att.id, att.original_filename)"
              class="text-emerald-400 hover:text-emerald-300 hover:bg-emerald-500/10 p-1.5 rounded transition-all cursor-pointer"
              title="下載此附件"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                <polyline points="7 10 12 15 17 10"></polyline>
                <line x1="12" y1="15" x2="12" y2="3"></line>
              </svg>
            </button>
            <button 
              @click="handleDelete(att.id, att.original_filename)"
              class="text-red-400 hover:text-red-300 hover:bg-red-500/10 p-1.5 rounded transition-all cursor-pointer"
              title="刪除此附件"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="3 6 5 6 21 6"></polyline>
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
</style>
