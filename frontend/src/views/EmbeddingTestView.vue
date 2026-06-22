<script setup>
import { ref } from 'vue'
import FileUploader from '../components/embedding/FileUploader.vue'
import ChunkPreview from '../components/embedding/ChunkPreview.vue'
import TokenCounter from '../components/embedding/TokenCounter.vue'
import ChunkingParams from '../components/params/ChunkingParams.vue'
import { useParamsStore } from '../stores/paramsStore'
import embeddingService from '../services/embeddingService'

const paramsStore = useParamsStore()

// State
const uploadedFileId = ref('')
const rawTextContent = ref('')
const isChunking = ref(false)
const chunksList = ref([])

const isVectorizing = ref(false)
const vectorizationStats = ref(null)

const handleUploadSuccess = (data) => {
  uploadedFileId.value = data.file_id || 'file_uploaded_id'
  rawTextContent.value = data.content || ''
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
    const payload = {
      chunks: chunksList.value.map(c => ({ index: c.index, content: c.content, metadata: {} })),
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
</script>

<template>
  <div class="flex-grow flex gap-6 p-6 overflow-hidden h-full min-h-0">
    <!-- Left Edit Area -->
    <div class="flex-grow flex flex-col gap-5 min-w-0 h-full overflow-y-auto pr-1">
      
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

    <!-- Right Side Config & Chunks Preview -->
    <div class="w-[320px] flex-shrink-0 flex flex-col gap-5 overflow-y-auto pr-1 h-full pb-6">
      <!-- Parameters -->
      <ChunkingParams />

      <!-- Chunks Result Feed -->
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
