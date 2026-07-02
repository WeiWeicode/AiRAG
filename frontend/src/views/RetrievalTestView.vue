<script setup>
import { ref, watch, computed } from 'vue'
import { useParamsStore } from '../stores/paramsStore'
import KnowledgeBaseSelector from '../components/common/KnowledgeBaseSelector.vue'
import retrievalService from '../services/retrievalService'
import api from '../services/api'

const paramsStore = useParamsStore()

// Local retrieval settings
const searchType = ref('vector') // vector | hybrid
const hnswEfSearch = ref(128)
const queryText = ref('')
const isSearching = ref(false)
const results = ref([])
const elapsedMs = ref(0)

// Query Transformation state
const originalQuery = ref('')
const transformedQuery = ref('')
const activeStrategy = ref('')
const semanticSteps = ref(null)

// Filename and selection states
const filenames = ref([])
const filterFilename = ref('')
const selectedChunkIds = ref([])

const fetchMetadata = async () => {
  if (!paramsStore.knowledgeBaseId) return
  try {
    const response = await api.get(`/api/knowledge-bases/${paramsStore.knowledgeBaseId}/metadata`)
    filenames.value = response.data?.filenames || []
    if (filterFilename.value && !filenames.value.includes(filterFilename.value)) {
      filterFilename.value = ''
    }
  } catch (error) {
    console.error('無法取得知識庫元資料，請檢查後端連線:', error)
  }
}

watch(() => paramsStore.knowledgeBaseId, (newId) => {
  if (newId) {
    fetchMetadata()
    selectedChunkIds.value = []
  }
}, { immediate: true })

const isAllSelected = computed(() => {
  return results.value.length > 0 && selectedChunkIds.value.length === results.value.length
})

const toggleSelectAll = () => {
  if (isAllSelected.value) {
    selectedChunkIds.value = []
  } else {
    selectedChunkIds.value = results.value.map(r => r.chunk_id)
  }
}

const handleSearch = async () => {
  if (!queryText.value.trim()) return
  
  isSearching.value = true
  results.value = []
  originalQuery.value = ''
  transformedQuery.value = ''
  selectedChunkIds.value = []
  
  if (['semantic_hybrid', 'semantic_hybrid_feedback'].includes(searchType.value)) {
    semanticSteps.value = [
      { key: 'semantic_analysis', name: '語義分析', status: 'running', content: '正在發送提問至地端 AI 進行語義分析與結構化轉換...\n原始提問："' + queryText.value.trim() + '"', expanded: true },
      { key: 'vector_search', name: '向量資料查詢', status: 'pending', content: '', expanded: false }
    ]
  } else {
    semanticSteps.value = null
  }
  
  try {
    const parsedFilterTags = paramsStore.filterTagsString.split(',')
      .map(t => t.trim())
      .filter(t => t.length > 0)

    const payload = {
      query: queryText.value.trim(),
      knowledge_base_id: paramsStore.knowledgeBaseId,
      params: {
        top_k: paramsStore.topK,
        score_threshold: paramsStore.scoreThreshold,
        search_type: searchType.value,
        hnsw_ef_search: hnswEfSearch.value,
        filter_tags: parsedFilterTags.length > 0 ? parsedFilterTags : undefined,
        filter_filename: filterFilename.value || undefined
      }
    }
    const isSemanticHybridFamily = ['semantic_hybrid', 'semantic_hybrid_feedback'].includes(searchType.value)
    const response = isSemanticHybridFamily
      ? await retrievalService.semanticHybridSearch(payload)
      : await retrievalService.search(payload)
    results.value = response.results || []
    elapsedMs.value = response.elapsed_ms || 0

    if (isSemanticHybridFamily && response && semanticSteps.value) {
      const jsonStr = response.semantic_json ? JSON.stringify(response.semantic_json, null, 2) : '{}'
      const embeddingsInput = response.embeddings_input || queryText.value.trim()
      const vectorPreview = response.query_vector_preview || '無'
      const vectorSize = response.vector_size || 4096

      semanticSteps.value[0].status = 'success'
      semanticSteps.value[0].expanded = false
      semanticSteps.value[0].content = 
        `【地端 AI 語義密集嵌入】\n` +
        `結構化 JSON：\n` +
        `\`\`\`json\n${jsonStr}\n\`\`\`\n` +
        `密集向量模型: ${response.embedding_model || 'Qwen3-Embedding-8B-Q8_0.gguf'}\n` +
        `向量維度: ${vectorSize}\n` +
        `部分向量: ${vectorPreview}`

      const count = response.results ? response.results.length : 0
      const elapsed = response.elapsed_ms || 0
      const keywords = response.sparse_keywords ? response.sparse_keywords.join(', ') : '無'

      semanticSteps.value[1].status = 'success'
      semanticSteps.value[1].expanded = true
      semanticSteps.value[1].content = 
        `【Qdrant 向量資料庫檢索與融合】\n` +
        `檢索模式: 語義混合搜尋 (Semantic Hybrid Search)\n` +
        `稀疏關鍵字: [${keywords}]\n` +
        `混合檢索結果: 成功尋得 ${count} 筆向量段落\n` +
        `資料檢索與 RRF 融合耗時: ${elapsed} ms`
    }
  } catch (error) {
    if (semanticSteps.value) {
      semanticSteps.value.forEach(step => {
        if (step.status === 'running') {
          step.status = 'failed'
          step.content = '執行出錯：' + error.message
        }
      })
    }
    console.error('Retrieval search failed:', error)
    alert('搜尋失敗，請檢查後端連線或參數設定')
  } finally {
    isSearching.value = false
  }
}

const handleTransform = async (strategy) => {
  if (!queryText.value.trim()) return
  
  isSearching.value = true
  results.value = []
  selectedChunkIds.value = []
  
  try {
    const payload = {
      query: queryText.value.trim(),
      strategy,
      knowledge_base_id: paramsStore.knowledgeBaseId
    }
    const response = await retrievalService.queryTransform(payload)
    originalQuery.value = response.original_query
    transformedQuery.value = response.transformed_query
    activeStrategy.value = response.strategy
    results.value = response.results || []
    elapsedMs.value = response.elapsed_ms || 0
  } catch (error) {
    console.error('Query transform failed:', error)
    alert('Query 轉換測試失敗，請檢查後端服務')
  } finally {
    isSearching.value = false
  }
}

const handleDeleteSingle = async (pointId) => {
  if (!confirm('確定要永久刪除此向量段落資料嗎？')) return
  
  try {
    await retrievalService.batchDeletePoints(paramsStore.knowledgeBaseId, [pointId])
    results.value = results.value.filter(res => res.chunk_id !== pointId)
    selectedChunkIds.value = selectedChunkIds.value.filter(id => id !== pointId)
    fetchMetadata()
  } catch (error) {
    console.error('刪除向量資料失敗:', error)
    alert('刪除失敗，請檢查後端連線或權限設定')
  }
}

const handleBatchDelete = async () => {
  if (selectedChunkIds.value.length === 0) return
  if (!confirm(`確定要永久刪除選取的 ${selectedChunkIds.value.length} 筆向量資料段落嗎？`)) return
  
  try {
    await retrievalService.batchDeletePoints(paramsStore.knowledgeBaseId, selectedChunkIds.value)
    const deletedSet = new Set(selectedChunkIds.value)
    results.value = results.value.filter(res => !deletedSet.has(res.chunk_id))
    selectedChunkIds.value = []
    fetchMetadata()
  } catch (error) {
    console.error('批次刪除向量資料失敗:', error)
    alert('批次刪除失敗，請檢查後端連線或權限設定')
  }
}
</script>

<template>
  <div class="flex-grow flex gap-6 p-6 overflow-hidden h-full min-h-0">
    <!-- Left Main Search Area -->
    <div class="flex-grow flex flex-col gap-5 min-w-0 h-full">
      <!-- Search Input Box -->
      <div class="bg-[#111827]/70 border border-white/8 rounded-2xl p-5 backdrop-blur-md flex flex-col gap-4">
        <div class="text-sm font-bold text-white tracking-wider">向量檢索與語意搜尋</div>
        
        <div class="flex gap-3">
          <input 
            v-model="queryText"
            type="text" 
            class="flex-grow bg-[#111827] border border-white/10 rounded-xl text-white px-4 py-3.5 text-sm focus:outline-none focus:border-[#8b5cf6] focus:ring-2 focus:ring-[#8b5cf6]/15 transition-all"
            placeholder="請輸入搜尋關鍵字或問題..."
            @keydown.enter="handleSearch"
            :disabled="isSearching"
          />
          <button 
            @click="handleSearch"
            :disabled="isSearching || !queryText.trim()"
            class="bg-[#8b5cf6] hover:bg-[#a78bfa] disabled:bg-purple-900/50 disabled:text-purple-300/50 hover:shadow-[0_4px_12px_rgba(139,92,246,0.3)] text-white font-semibold px-6 rounded-xl text-sm transition-all flex items-center gap-1.5 h-[46px]"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="11" cy="11" r="8"></circle>
              <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
            </svg>
            搜尋
          </button>
        </div>

        <div class="flex gap-3 mt-1.5">
          <button 
            @click="handleTransform('rewrite')"
            :disabled="isSearching || !queryText.trim()"
            class="px-4 py-2 border border-[#8b5cf6]/30 hover:border-[#8b5cf6] text-[#a78bfa] hover:text-white rounded-lg text-xs font-semibold hover:bg-[#8b5cf6]/10 transition-all"
          >
            Query Rewriting (重寫)
          </button>
          <button 
            @click="handleTransform('hyde')"
            :disabled="isSearching || !queryText.trim()"
            class="px-4 py-2 border border-[#8b5cf6]/30 hover:border-[#8b5cf6] text-[#a78bfa] hover:text-white rounded-lg text-xs font-semibold hover:bg-[#8b5cf6]/10 transition-all"
          >
            HyDE (假設性文件檢索)
          </button>
        </div>
      </div>

      <!-- Search Results Area -->
      <div class="flex-grow bg-[#111827]/40 border border-white/8 rounded-2xl p-6 overflow-hidden flex flex-col">
        <!-- Results stats & Batch Actions -->
        <div class="flex justify-between items-center mb-4 flex-shrink-0">
          <div class="flex items-center gap-4">
            <h3 class="font-semibold text-white text-sm">搜尋結果 ({{ results.length }} 筆)</h3>
          </div>
          <span v-if="elapsedMs" class="text-xs text-[#6b7280]">查詢耗時: <strong class="text-white">{{ elapsedMs }}</strong> ms</span>
        </div>

        <!-- Query transform explanation if active -->
        <div 
          v-if="transformedQuery" 
          class="bg-[#8b5cf6]/10 border border-[#8b5cf6]/30 rounded-xl p-4 mb-4 flex flex-col gap-1.5 text-xs flex-shrink-0"
        >
          <div>
            <span class="font-bold text-[#a78bfa]">[{{ activeStrategy === 'hyde' ? 'HyDE 假設文件' : 'Query 重寫' }}]</span> 
            原查詢：<span class="text-[#9ca3af]">{{ originalQuery }}</span>
          </div>
          <div class="pt-1.5 border-t border-white/5">
            轉換後查詢：<span class="text-white font-medium">{{ transformedQuery }}</span>
          </div>
        </div>

        <!-- RAG Steps Process (for semantic_hybrid) -->
        <div v-if="semanticSteps && semanticSteps.length > 0" class="mb-4 flex flex-col gap-2 flex-shrink-0">
          <div class="text-[10px] text-white/40 font-semibold uppercase tracking-wider mb-1">語義混合查詢分析步驟</div>
          
          <div 
            v-for="step in semanticSteps" 
            :key="step.key" 
            class="border border-white/10 rounded-xl bg-white/3 overflow-hidden transition-all"
            :class="{ 'border-[#8b5cf6]/20 bg-[#8b5cf6]/5': step.status === 'running' }"
          >
            <!-- Step Header -->
            <button 
              @click="step.expanded = !step.expanded"
              class="w-full flex items-center justify-between px-4 py-2.5 text-xs text-white/70 hover:text-white hover:bg-white/5 transition-all focus:outline-none"
            >
              <div class="flex items-center gap-2.5">
                <!-- Status icon -->
                <span v-if="step.status === 'pending'" class="w-3.5 h-3.5 rounded-full border border-white/20 flex-shrink-0"></span>
                <svg v-else-if="step.status === 'running'" class="animate-spin h-3.5 w-3.5 text-purple-400 flex-shrink-0" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                <svg v-else-if="step.status === 'success'" class="h-3.5 w-3.5 text-emerald-400 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
                <svg v-else-if="step.status === 'failed'" class="h-3.5 w-3.5 text-red-400 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18"></line>
                  <line x1="6" y1="6" x2="18" y2="18"></line>
                </svg>
                <span class="font-semibold text-white/80">{{ step.name }}</span>
                <span v-if="step.status === 'running'" class="text-[9px] bg-purple-500/20 text-purple-300 px-1.5 py-0.5 rounded font-normal animate-pulse">執行中</span>
              </div>
              
              <!-- Chevron -->
              <svg 
                class="w-3.5 h-3.5 transition-transform duration-200 text-white/40" 
                :class="{ 'rotate-180': step.expanded }"
                viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
              >
                <polyline points="6 9 12 15 18 9"></polyline>
              </svg>
            </button>
            
            <!-- Step Content -->
            <div 
              v-show="step.expanded"
              class="px-4 pb-3.5 pt-1.5 border-t border-white/5 text-xs text-white/60 whitespace-pre-wrap font-mono leading-relaxed max-h-[300px] overflow-y-auto bg-[#0a0f1d]/50"
            >
              {{ step.content || '尚無詳細資訊...' }}
            </div>
          </div>
        </div>

        <!-- Results Scroll Area -->
        <div class="flex-grow overflow-y-auto flex flex-col gap-4">
          <div v-if="isSearching" class="h-40 flex items-center justify-center text-[#9ca3af] text-sm gap-2">
            <!-- Simple loading spinner -->
            <svg class="animate-spin h-5 w-5 text-[#8b5cf6]" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            資料檢索中...
          </div>
          <div v-else-if="results.length === 0" class="h-40 flex items-center justify-center text-[#6b7280] text-sm">
            請輸入查詢文字以進行搜尋測試
          </div>
          
          <div 
            v-else
            v-for="(res, idx) in results" 
            :key="res.chunk_id || idx" 
            class="bg-white/2 border border-white/8 rounded-xl p-4 hover:border-white/16 hover:bg-white/4 transition-all"
          >
            <div class="flex justify-between items-center gap-4 mb-3 border-b border-white/5 pb-2">
              <span class="text-xs font-semibold text-white truncate flex items-center gap-2 flex-grow min-w-0">
                <span class="truncate">[{{ res.metadata?.filename || '未知檔案' }}] P.{{ res.metadata?.page || '?' }}</span>
                <span class="text-[#6b7280] flex-shrink-0">段落索引: #{{ res.metadata?.chunk_index || idx }}</span>
                <span v-if="res.metadata?.tags?.length" class="flex gap-1 flex-shrink-0">
                  <span 
                    v-for="t in res.metadata.tags" 
                    :key="t"
                    class="bg-[#8b5cf6]/10 border border-[#8b5cf6]/20 text-[#a78bfa] px-1.5 py-0.5 rounded text-[9px]"
                  >
                    {{ t }}
                  </span>
                </span>
              </span>
              <div class="flex gap-2 items-center flex-shrink-0">
                <span class="bg-[#10b981]/15 text-[#10b981] font-semibold font-display px-2 py-0.5 rounded text-[10px]">
                  {{ ['hybrid', 'semantic_hybrid'].includes(searchType) ? 'RRF Score' : 'Score' }}: {{ (res.score || 0).toFixed(4) }}
                </span>
                <span v-if="!['hybrid', 'semantic_hybrid'].includes(searchType) && res.distance" class="bg-[#3b82f6]/15 text-[#3b82f6] font-semibold font-display px-2 py-0.5 rounded text-[10px]">
                  Distance: {{ (res.distance || 0).toFixed(4) }}
                </span>
              </div>
            </div>
            
            <p class="text-xs text-[#9ca3af] leading-relaxed whitespace-pre-wrap">
              {{ res.content }}
            </p>
          </div>
        </div>
      </div>
    </div>

    <!-- Right Parameter Panel -->
    <div class="w-[320px] flex-shrink-0 flex flex-col gap-5 overflow-y-auto pr-1 h-full pb-6">
      <div class="flex flex-col gap-5 bg-white/3 border border-white/8 rounded-2xl p-5 backdrop-blur-md">
        <div class="text-sm font-bold text-white border-b border-white/8 pb-2 tracking-wider">
          檢索參數設定
        </div>

        <KnowledgeBaseSelector />

        <!-- Top-K Slider -->
        <div class="flex flex-col gap-2">
          <div class="flex justify-between items-center">
            <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">檢索數量 (Top-K)</label>
            <span class="text-xs font-bold text-[#a78bfa] font-display">{{ paramsStore.topK }}</span>
          </div>
          <input 
            v-model.number="paramsStore.topK" 
            type="range" 
            min="1" 
            max="20" 
            class="w-full h-1 bg-white/10 rounded-lg appearance-none cursor-pointer accent-[#8b5cf6]"
          />
        </div>

        <!-- Score Threshold Slider -->
        <div class="flex flex-col gap-2">
          <div class="flex justify-between items-center">
            <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">相似度閾值 (Score Threshold)</label>
            <span class="text-xs font-bold text-[#a78bfa] font-display">{{ paramsStore.scoreThreshold.toFixed(2) }}</span>
          </div>
          <input 
            v-model.number="paramsStore.scoreThreshold" 
            type="range" 
            min="0" 
            max="1" 
            step="0.05" 
            class="w-full h-1 bg-white/10 rounded-lg appearance-none cursor-pointer accent-[#8b5cf6]"
          />
        </div>

        <!-- Filename Filter -->
        <div class="flex flex-col gap-2">
          <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">檔案名稱過濾 (Filter Filename)</label>
          <select 
            v-model="filterFilename" 
            class="bg-white/5 border border-white/8 rounded-lg text-white px-3.5 py-2.5 text-sm focus:outline-none focus:border-[#8b5cf6] transition-all"
          >
            <option value="" class="bg-[#111827] text-white">-- 全部檔案 --</option>
            <option 
              v-for="fn in filenames" 
              :key="fn" 
              :value="fn" 
              class="bg-[#111827] text-white"
            >
              {{ fn }}
            </option>
          </select>
        </div>

        <!-- Tags Filter -->
        <div class="flex flex-col gap-2">
          <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">標籤過濾篩選 (Filter Tags)</label>
          <input 
            v-model="paramsStore.filterTagsString" 
            type="text" 
            class="bg-white/5 border border-white/8 rounded-lg text-white px-3 py-2 text-xs focus:outline-none focus:border-[#8b5cf6] transition-all"
            placeholder="輸入篩選標籤，以英文逗號分隔"
          />
        </div>

        <!-- Search Type Select -->
        <div class="flex flex-col gap-2">
          <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">檢索模式 (Search Type)</label>
          <select 
            v-model="searchType" 
            class="bg-white/5 border border-white/8 rounded-lg text-white px-3.5 py-2.5 text-sm focus:outline-none focus:border-[#8b5cf6] transition-all"
          >
            <option value="vector" class="bg-[#111827] text-white">向量搜尋 (Vector Search)</option>
            <option value="hybrid" class="bg-[#111827] text-white">混合搜尋 (Hybrid Search)</option>
            <option value="semantic_hybrid" class="bg-[#111827] text-white">語義混合搜尋 (Semantic Hybrid Search)</option>
            <option value="semantic_hybrid_feedback" class="bg-[#111827] text-white">語義混合回饋查詢法 (Semantic Hybrid + Feedback)</option>
          </select>
        </div>

        <!-- efSearch Slider -->
        <div class="flex flex-col gap-2">
          <div class="flex justify-between items-center">
            <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">HNSW ef_search</label>
            <span class="text-xs font-bold text-[#a78bfa] font-display">{{ hnswEfSearch }}</span>
          </div>
          <input 
            v-model.number="hnswEfSearch" 
            type="range" 
            min="32" 
            max="256" 
            step="8" 
            class="w-full h-1 bg-white/10 rounded-lg appearance-none cursor-pointer accent-[#8b5cf6]"
          />
        </div>
      </div>

      <!-- Parameter Explanation Card -->
      <div class="flex flex-col gap-4 bg-white/3 border border-white/8 rounded-2xl p-5 backdrop-blur-md">
        <div class="text-sm font-bold text-white border-b border-white/8 pb-2 tracking-wider flex items-center gap-1.5">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#a78bfa" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="12" y1="16" x2="12" y2="12"></line>
            <line x1="12" y1="8" x2="12.01" y2="8"></line>
          </svg>
          檢索參數說明
        </div>
        
        <div class="flex flex-col gap-3.5 text-xs text-[#9ca3af] leading-relaxed">
          <div>
            <div class="font-bold text-[#e5e7eb] mb-1">檢索數量 (Top-K)</div>
            <p>決定向量資料庫最多回傳幾筆相關段落。較高的 Top-K 能提供更豐富的脈絡資訊，但會增加後續 LLM 處理的 Token 消耗與生成延遲。</p>
          </div>
          
          <div>
            <div class="font-bold text-[#e5e7eb] mb-1">相似度閾值 (Score Threshold)</div>
            <p>設定最低相關度門檻（0.0 到 1.0）。只有高於此門檻的段落才會被檢索。調高可篩除無關雜訊，調低可避免漏掉潛在相關資料。</p>
          </div>
          
          <div>
            <div class="font-bold text-[#e5e7eb] mb-1">檢索模式 (Search Type)</div>
            <ul class="list-disc pl-4 mt-0.5 space-y-0.5">
              <li><span class="text-[#a78bfa]">向量搜尋</span>：依據語意概念進行特徵相似度比對。</li>
              <li><span class="text-[#a78bfa]">混合搜尋</span>：結合語意搜尋與傳統全文關鍵字檢索。</li>
              <li><span class="text-[#a78bfa]">語義混合搜尋</span>：透過專用語義模組對自然語言進行語意密集檢索，並融合關鍵字稀疏檢索進行 RRF 加速。</li>
            </ul>
          </div>
          
          <div>
            <div class="font-bold text-[#e5e7eb] mb-1">HNSW ef_search</div>
            <p>控制 Qdrant 在 HNSW 索引樹中搜尋時的候選列表大小。數值調高（例如 128 以上）會提高精準度但增加少許耗時；調低能提升效能。</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
