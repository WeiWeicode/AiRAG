<script setup>
import { ref, watch, computed, onMounted } from 'vue'
import FileUploader from './FileUploader.vue'
import ChunkPreview from './ChunkPreview.vue'
import TokenCounter from './TokenCounter.vue'
import { useParamsStore } from '../../stores/paramsStore'
import embeddingService from '../../services/embeddingService'
import imageService from '../../services/imageService'

const paramsStore = useParamsStore()

// State
const uploadedFileId = ref('')
const filename = ref('unknown')
const rawTextContent = ref('')
const extractImages = ref(false)
const extractedImages = ref([])

const imageUrls = ref({})
const imageLoadFailed = ref({})

const loadExtractedImages = async () => {
  for (const img of extractedImages.value) {
    const filename = img.image_filename
    if (filename && !imageUrls.value[filename] && !imageLoadFailed.value[filename]) {
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
  }
}

watch(extractedImages, () => {
  loadExtractedImages()
}, { deep: true })

const allTags = ref([])
const allClasses = ref([])
const selectedTags = ref([])
const selectedClasses = ref([])
const newTagName = ref('')
const newClassName = ref('')

const isChunking = ref(false)
const chunksList = ref([])
const isVectorizing = ref(false)
const vectorizationStats = ref(null)

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

const handleUploadSuccess = (data) => {
  uploadedFileId.value = data.file_id || 'file_uploaded_id'
  rawTextContent.value = data.content || ''
  if (data.filename) {
    filename.value = data.filename
  }
  extractedImages.value = data.images || []
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
  if (!rawTextContent.value.trim() && extractedImages.value.length === 0) {
    alert('請上傳檔案或在此貼上純文字內容以進行切分測試。')
    return
  }

  isChunking.value = true
  chunksList.value = []
  vectorizationStats.value = null
  
  try {
    const payload = {
      file_id: uploadedFileId.value || null,
      filename: filename.value || null,
      content: rawTextContent.value.trim(),
      params: {
        chunk_size: paramsStore.chunkSize,
        chunk_overlap: paramsStore.chunkOverlap,
        separator: paramsStore.separator.replace('\\n', '\n'),
        chunk_mode: paramsStore.chunkMode || 'standard'
      },
      images: extractedImages.value
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
  extractImages.value = false
  extractedImages.value = []
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
          classes: selectedClasses.value,
          ...c.metadata
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
  } catch (error) {
    console.error('Backend vectorization call failed:', error)
    alert('向量化與寫入失敗，請檢查後端服務與資料庫連線')
  } finally {
    isVectorizing.value = false
  }
}

const downloadImage = (filename) => {
  imageService.download(filename, filename)
}
</script>

<template>
  <div class="flex flex-col gap-5">
    <!-- Drag & Drop / Upload -->
    <div class="bg-[#111827]/70 border border-white/8 rounded-2xl p-5 backdrop-blur-md">
      <FileUploader :extract-images="extractImages" @upload-success="handleUploadSuccess" />
      <div class="flex items-center gap-2 mt-3 px-1">
        <input 
          v-model="extractImages"
          type="checkbox" 
          id="chk-extract-images"
          class="rounded border-white/10 bg-white/5 text-[#8b5cf6] focus:ring-0 focus:ring-offset-0 cursor-pointer"
        />
        <label for="chk-extract-images" class="text-xs text-[#9ca3af] cursor-pointer select-none">
          上傳時自動擷取文件內嵌圖片並呼叫多模態 AI 自動描述圖片內容 (支援 PDF, Word 格式)
        </label>
      </div>
    </div>

    <!-- Extracted Images Gallery -->
    <div v-if="extractedImages.length > 0" class="bg-[#111827]/70 border border-white/8 rounded-2xl p-5 backdrop-blur-md flex flex-col gap-3">
      <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">
        已擷取的文件圖片 ({{ extractedImages.length }} 張)
      </label>
      <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4">
        <div 
          v-for="img in extractedImages" 
          :key="img.image_filename"
          class="bg-white/3 border border-white/8 rounded-xl p-3 flex flex-col gap-2 relative group overflow-hidden"
        >
          <div class="h-28 rounded-lg bg-black/40 flex items-center justify-center overflow-hidden border border-white/5 relative">
            <img
              v-if="imageUrls[img.image_filename]"
              :src="imageUrls[img.image_filename]"
              class="max-h-full max-w-full object-contain animate-fade-in"
              alt="Extracted doc image"
            />
            <div v-else-if="imageLoadFailed[img.image_filename]" class="flex flex-col items-center gap-1 text-[#6b7280] text-[10px]">
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
            <div v-if="imageUrls[img.image_filename]" class="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center gap-2">
              <button
                @click="downloadImage(img.image_filename)"
                class="p-2 bg-[#8b5cf6] hover:bg-[#a78bfa] rounded-full text-white transition-all shadow-lg"
                title="下載原圖"
              >
                <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>
                </svg>
               </button>
            </div>
          </div>
          <div class="flex flex-col gap-1">
            <div class="flex items-center justify-between text-[10px]">
              <span class="text-[#a78bfa] font-semibold">
                {{ img.page ? `第 ${img.page} 頁` : '段落圖片' }}
              </span>
              <span
                v-if="img.caption_failed"
                class="px-1.5 py-0.5 rounded bg-red-500/10 border border-red-500/20 text-red-400 font-bold"
              >
                描述失敗
              </span>
              <span
                v-else-if="img.caption_truncated"
                class="px-1.5 py-0.5 rounded bg-amber-500/10 border border-amber-500/20 text-amber-400 font-bold"
                title="AI 描述內容因長度上限被截斷，可能不完整（常見於複雜表格圖片）"
              >
                描述可能被截斷
              </span>
            </div>
            <p class="text-[11px] text-[#d1d5db] line-clamp-3 leading-relaxed" :title="img.description">
              {{ img.description }}
            </p>
          </div>
        </div>
      </div>
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

    <!-- Teleport Chunks Result Feed to right sidebar container -->
    <Teleport to="#sidebar-single-indexing" defer>
      <div class="flex-grow bg-[#111827]/40 border border-white/8 rounded-2xl p-5 flex flex-col gap-4 min-h-[300px]">
        <div class="text-xs font-bold text-white border-b border-white/8 pb-2 tracking-wider">
          切分預覽 (Chunks Preview: {{ chunksList.length }} 段)
        </div>
        <div class="flex-grow overflow-y-auto max-h-[500px]">
          <div v-if="isChunking" class="text-xs text-[#9ca3af] py-6 text-center">正在進行切分運算...</div>
          <div v-else-if="chunksList.length === 0" class="text-xs text-[#6b7280] py-6 text-center">點擊「開始文本切分」檢視切分預覽</div>
          <ChunkPreview v-else :chunks="chunksList" />
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
