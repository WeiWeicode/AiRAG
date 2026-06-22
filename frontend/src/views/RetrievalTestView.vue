<script setup>
import { ref } from 'vue'
import { useParamsStore } from '../stores/paramsStore'
import KnowledgeBaseSelector from '../components/common/KnowledgeBaseSelector.vue'
import retrievalService from '../services/retrievalService'

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

const handleSearch = async () => {
  if (!queryText.value.trim()) return
  
  isSearching.value = true
  results.value = []
  originalQuery.value = ''
  transformedQuery.value = ''
  
  try {
    const payload = {
      query: queryText.value.trim(),
      knowledge_base_id: paramsStore.knowledgeBaseId,
      params: {
        top_k: paramsStore.topK,
        score_threshold: paramsStore.scoreThreshold,
        search_type: searchType.value,
        hnsw_ef_search: hnswEfSearch.value
      }
    }
    const response = await retrievalService.search(payload)
    results.value = response.results || []
    elapsedMs.value = response.elapsed_ms || 0
  } catch (error) {
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
        <!-- Results stats -->
        <div class="flex justify-between items-center mb-4 flex-shrink-0">
          <h3 class="font-semibold text-white text-sm">搜尋結果 ({{ results.length }} 筆)</h3>
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
            :key="idx" 
            class="bg-white/2 border border-white/8 rounded-xl p-4 hover:border-white/16 hover:bg-white/4 transition-all"
          >
            <div class="flex justify-between items-center gap-4 mb-3 border-b border-white/5 pb-2">
              <span class="text-xs font-semibold text-white truncate">
                [{{ res.metadata?.filename || '未知檔案' }}] P.{{ res.metadata?.page || '?' }} 
                <span class="text-[#6b7280] ml-2">段落索引: #{{ res.metadata?.chunk_index || idx }}</span>
              </span>
              <div class="flex gap-2">
                <span class="bg-[#10b981]/15 text-[#10b981] font-semibold font-display px-2 py-0.5 rounded text-[10px]">
                  Score: {{ (res.score || 0).toFixed(4) }}
                </span>
                <span v-if="res.distance" class="bg-[#3b82f6]/15 text-[#3b82f6] font-semibold font-display px-2 py-0.5 rounded text-[10px]">
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

        <!-- Search Type Select -->
        <div class="flex flex-col gap-2">
          <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">檢索模式 (Search Type)</label>
          <select 
            v-model="searchType" 
            class="bg-white/5 border border-white/8 rounded-lg text-white px-3.5 py-2.5 text-sm focus:outline-none focus:border-[#8b5cf6] transition-all"
          >
            <option value="vector" class="bg-[#111827] text-white">向量搜尋 (Vector Search)</option>
            <option value="hybrid" class="bg-[#111827] text-white">混合搜尋 (Hybrid Search)</option>
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
    </div>
  </div>
</template>
