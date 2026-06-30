<script setup>
import { ref, computed } from 'vue'
import { useParamsStore } from '../../stores/paramsStore'
import embeddingService from '../../services/embeddingService'

const paramsStore = useParamsStore()

// State
const jsonInputText = ref('')
const parsedItems = ref([])
const parseError = ref('')
const isVectorizing = ref(false)
const vectorizationStats = ref(null)

const validateAndParseJSON = () => {
  parseError.value = ''
  parsedItems.value = []
  vectorizationStats.value = null

  const trimmed = jsonInputText.value.trim()
  if (!trimmed) {
    parseError.value = '請輸入 JSON 文字或選擇檔案'
    return
  }

  try {
    const data = JSON.parse(trimmed)
    const items = Array.isArray(data) ? data : [data]

    // Validate fields
    const validItems = []
    for (let i = 0; i < items.length; i++) {
      const item = items[i]
      if (!item.id || !item.text_content || !item.embeddings_input) {
        throw new Error(`第 ${i + 1} 筆資料缺少必要欄位 (id, text_content, embeddings_input)`)
      }
      validItems.push({
        id: String(item.id),
        text_content: String(item.text_content),
        embeddings_input: String(item.embeddings_input),
        metadata: item.metadata || {},
        sparse_keywords: Array.isArray(item.sparse_keywords) ? item.sparse_keywords.map(String) : []
      })
    }

    parsedItems.value = validItems
  } catch (error) {
    parseError.value = 'JSON 解析或格式驗證失敗: ' + error.message
  }
}

const handleFileUpload = (event) => {
  const file = event.target.files[0]
  if (!file) return

  const reader = new FileReader()
  reader.onload = (e) => {
    jsonInputText.value = e.target.result
    validateAndParseJSON()
  }
  reader.onerror = () => {
    parseError.value = '讀取檔案失敗'
  }
  reader.readAsText(file)
}

const triggerVectorization = async () => {
  if (parsedItems.value.length === 0) {
    alert('請先解析並驗證有效的 JSON 資料')
    return
  }
  if (!paramsStore.knowledgeBaseId) {
    alert('請於右側面板選擇目標知識庫')
    return
  }

  isVectorizing.value = true
  vectorizationStats.value = null

  try {
    const payload = {
      knowledge_base_id: paramsStore.knowledgeBaseId,
      items: parsedItems.value
    }
    const response = await embeddingService.vectorizeJson(payload)
    vectorizationStats.value = {
      kbId: response.knowledge_base_id,
      insertedCount: response.inserted_count,
      model: response.embedding_model,
      elapsedMs: response.elapsed_ms
    }
    // Clear input on success
    jsonInputText.value = ''
    parsedItems.value = []
  } catch (error) {
    console.error('Semantic JSON indexing failed:', error)
    alert(error.response?.data?.detail || '寫入失敗，請檢查後端連線與資料庫')
  } finally {
    isVectorizing.value = false
  }
}

const clearAll = () => {
  jsonInputText.value = ''
  parsedItems.value = []
  parseError.value = ''
  vectorizationStats.value = null
}
</script>

<template>
  <div class="flex flex-col gap-5">
    <!-- JSON Input area -->
    <div class="bg-[#111827]/70 border border-white/8 rounded-2xl p-5 backdrop-blur-md flex flex-col gap-4">
      <div class="flex justify-between items-center">
        <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">匯入地端 AI 結構化 JSON</label>
        <span class="text-xs text-[#9ca3af]">目前目標知識庫: <strong class="text-white">{{ paramsStore.knowledgeBaseId || '尚未選擇' }}</strong></span>
      </div>

      <!-- File upload selector -->
      <div class="flex items-center gap-4">
        <label class="flex-grow flex items-center justify-center border-2 border-dashed border-white/10 hover:border-[#8b5cf6]/50 rounded-xl p-6 cursor-pointer bg-white/3 hover:bg-white/5 transition-all text-xs text-[#9ca3af] gap-2">
          <svg class="w-5 h-5 text-[#9ca3af]" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"/>
          </svg>
          <span>拖曳或點擊選擇地端 AI 產出的 JSON 檔案</span>
          <input type="file" accept=".json" class="hidden" @change="handleFileUpload" />
        </label>
      </div>

      <div class="flex flex-col gap-2">
        <div class="text-[10px] text-[#9ca3af] font-semibold uppercase tracking-wider">或直接在此貼上 JSON 文字內容</div>
        <textarea 
          v-model="jsonInputText"
          rows="8"
          class="bg-white/5 border border-white/8 rounded-lg text-white p-3.5 text-xs font-mono focus:outline-none focus:border-[#8b5cf6] resize-y"
          placeholder='範例格式：
{
  "id": "doc_01",
  "text_content": "原始文本...",
  "embeddings_input": "語意模型向量輸入描述...",
  "metadata": {"source_file": "doc.pdf", "page_number": 1},
  "sparse_keywords": ["關鍵字1", "關鍵字2"]
}'
          @input="validateAndParseJSON"
        ></textarea>
      </div>

      <!-- Error / Stats Info -->
      <div v-if="parseError" class="text-xs font-semibold text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2 flex items-center gap-1.5 animate-fade-in">
        <svg class="w-3.5 h-3.5 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10"></circle>
          <line x1="12" y1="8" x2="12" y2="12"></line>
          <line x1="12" y1="16" x2="12.01" y2="16"></line>
        </svg>
        {{ parseError }}
      </div>

      <div class="flex gap-3">
        <button 
          @click="validateAndParseJSON"
          :disabled="!jsonInputText.trim()"
          class="px-5 py-2.5 border border-white/8 hover:border-white/16 text-xs text-[#f3f4f6] font-semibold rounded-lg bg-white/5 transition-all"
        >
          驗證 JSON 格式
        </button>
        <button 
          @click="triggerVectorization"
          :disabled="isVectorizing || parsedItems.length === 0 || !paramsStore.knowledgeBaseId"
          class="px-5 py-2.5 bg-[#8b5cf6] hover:bg-[#a78bfa] hover:shadow-[0_4px_12px_rgba(139,92,246,0.3)] disabled:bg-purple-900/50 disabled:text-purple-300/50 text-xs text-white font-semibold rounded-lg transition-all"
        >
          {{ isVectorizing ? '語義密集/稀疏向量寫入中...' : `語義化寫入 (${parsedItems.length} 筆)` }}
        </button>
        <button 
          @click="clearAll"
          class="px-5 py-2.5 border border-red-500/20 hover:border-red-500/40 text-xs text-red-300 font-semibold rounded-lg bg-red-500/5 hover:bg-red-500/10 transition-all ml-auto"
        >
          清空
        </button>
      </div>
    </div>

    <!-- Success Stats -->
    <div 
      v-if="vectorizationStats" 
      class="bg-emerald-500/10 border border-emerald-500/20 rounded-2xl p-5 flex flex-col gap-2.5 animate-fade-in"
    >
      <div class="text-xs font-bold text-[#10b981] flex items-center gap-1.5">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="20 6 9 17 4 12"></polyline>
        </svg>
        語義結構化寫入成功 (Semantic hybrid search indices built)
      </div>
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 text-[10px] text-[#9ca3af] mt-1 pt-1.5 border-t border-emerald-500/10">
        <span>目標知識庫: <strong class="text-white">{{ vectorizationStats.kbId }}</strong></span>
        <span>寫入筆數: <strong class="text-white">{{ vectorizationStats.insertedCount }} 筆</strong></span>
        <span>密集向量模型: <strong class="text-white font-mono">{{ vectorizationStats.model }}</strong></span>
        <span>寫入耗時: <strong class="text-white font-display">{{ vectorizationStats.elapsedMs }} ms</strong></span>
      </div>
    </div>

    <!-- Preview parsed Items -->
    <div v-if="parsedItems.length > 0" class="bg-[#111827]/70 border border-white/8 rounded-2xl p-5 backdrop-blur-md flex flex-col gap-4 animate-fade-in">
      <div class="text-xs font-bold text-white border-b border-white/8 pb-2 tracking-wider">
        解析資料預覽 ({{ parsedItems.length }} 筆)
      </div>
      <div class="flex flex-col gap-4 max-h-[350px] overflow-y-auto pr-1">
        <div 
          v-for="(item, idx) in parsedItems" 
          :key="item.id || idx"
          class="bg-white/2 border border-white/8 rounded-xl p-4 flex flex-col gap-2.5 text-xs text-[#9ca3af]"
        >
          <div class="flex justify-between items-center text-white border-b border-white/5 pb-1.5">
            <span class="font-bold font-mono">ID: {{ item.id }}</span>
            <span class="text-[10px] bg-white/5 border border-white/8 px-2 py-0.5 rounded text-[#9ca3af]">
              檔案: {{ item.metadata?.source_file || 'unknown' }} | 頁數: {{ item.metadata?.page_number || 1 }}
            </span>
          </div>
          <div>
            <span class="font-bold text-[#e5e7eb] block mb-0.5">語義輸入 (embeddings_input):</span>
            <p class="leading-relaxed bg-white/3 p-2 rounded border border-white/5 text-[11px] text-white">{{ item.embeddings_input }}</p>
          </div>
          <div>
            <span class="font-bold text-[#e5e7eb] block mb-0.5">原始內容 (text_content):</span>
            <p class="leading-relaxed text-[11px]">{{ item.text_content }}</p>
          </div>
          <div v-if="item.sparse_keywords.length > 0">
            <span class="font-bold text-[#e5e7eb] block mb-0.5">關鍵字 (sparse_keywords):</span>
            <div class="flex flex-wrap gap-1.5 mt-1">
              <span 
                v-for="kw in item.sparse_keywords" 
                :key="kw"
                class="bg-[#8b5cf6]/10 border border-[#8b5cf6]/20 text-[#a78bfa] px-1.5 py-0.5 rounded text-[10px]"
              >
                {{ kw }}
              </span>
            </div>
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
