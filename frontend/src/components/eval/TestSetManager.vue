<script setup>
import { ref, onMounted } from 'vue'
import evalService from '../../services/evalService'

const props = defineProps({
  isLoading: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['start-eval', 'select-dataset'])

const selectedDatasetId = ref('')
const datasets = ref([])
const activeDataset = ref(null)
const maxTokens = ref(8192)
const searchType = ref('vector')

// Import Dataset modal state
const showImportModal = ref(false)
const importName = ref('')
const importDescription = ref('')
const importJson = ref(`[
  {
    "question": "範例問題？",
    "ground_truth": "範例標準答案。"
  }
]`)
const importError = ref('')

const handleDatasetChange = () => {
  const dataset = datasets.value.find(d => d.id === selectedDatasetId.value)
  if (dataset) {
    activeDataset.value = dataset
    emit('select-dataset', dataset)
  } else {
    activeDataset.value = null
  }
}

const fetchDatasets = async () => {
  try {
    const response = await evalService.getDatasets()
    if (response && response.items) {
      datasets.value = response.items.map(item => ({
        id: item.dataset_id,
        name: `${item.name} (${item.item_count} 筆問答)`,
        count: item.item_count,
        kb: item.dataset_id === 'dataset_tech' ? '預設知識庫 (技術規格)' : (item.dataset_id === 'dataset_hr' ? '預設知識庫 (人事規章)' : '關聯知識庫'),
        lastRun: '未執行'
      }))
      if (datasets.value.length > 0) {
        // Keep selected if exists, otherwise first
        const exists = datasets.value.find(d => d.id === selectedDatasetId.value)
        if (!exists) {
          selectedDatasetId.value = datasets.value[0].id
          activeDataset.value = datasets.value[0]
        } else {
          activeDataset.value = exists
        }
        emit('select-dataset', activeDataset.value)
      } else {
        selectedDatasetId.value = ''
        activeDataset.value = null
      }
    }
  } catch (error) {
    console.error('無法取得測試數據集列表，請檢查後端服務:', error)
  }
}

const handleImport = async () => {
  importError.value = ''
  if (!importName.value.trim()) {
    importError.value = '測試集名稱為必填項目'
    return
  }
  try {
    const items = JSON.parse(importJson.value)
    if (!Array.isArray(items)) {
      importError.value = '問答內容必須是 JSON 陣列格式'
      return
    }
    for (let i = 0; i < items.length; i++) {
      if (!items[i].question || !items[i].ground_truth) {
        importError.value = `第 ${i + 1} 項問答格式不正確，缺少 "question" 或 "ground_truth"`
        return
      }
    }
    const payload = {
      name: importName.value.trim(),
      description: importDescription.value.trim(),
      items: items.map(item => ({
        question: item.question.trim(),
        ground_truth: item.ground_truth.trim(),
        relevant_contexts: item.relevant_contexts || []
      }))
    }
    const response = await evalService.createDataset(payload)
    if (response && response.dataset_id) {
      showImportModal.value = false
      importName.value = ''
      importDescription.value = ''
      importJson.value = '[\n  {\n    "question": "範例問題？",\n    "ground_truth": "範例標準答案。"\n  }\n]'
      
      selectedDatasetId.value = response.dataset_id
      await fetchDatasets()
    }
  } catch (err) {
    importError.value = 'JSON 解析失敗，請檢查格式是否正確: ' + err.message
  }
}

onMounted(() => {
  fetchDatasets()
})
</script>

<template>
  <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
    <div class="lg:col-span-2 bg-[#111827]/70 border border-white/8 rounded-2xl p-6 backdrop-blur-md">
      <div class="flex justify-between items-center mb-2">
        <div class="text-sm font-bold text-white tracking-wider">自動化評估任務控制</div>
        <button 
          @click="showImportModal = true"
          class="px-3 py-1.5 border border-[#8b5cf6]/30 hover:border-[#8b5cf6] text-xs text-[#a78bfa] hover:text-white rounded-lg bg-[#8b5cf6]/5 font-semibold transition-all flex items-center gap-1.5"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
            <polyline points="17 8 12 3 7 8"></polyline>
            <line x1="12" y1="3" x2="12" y2="15"></line>
          </svg>
          匯入測試集
        </button>
      </div>
      <p class="text-xs text-[#9ca3af] mb-5 leading-relaxed">
        選擇測試數據集並呼叫預載之 <strong>LLM-as-a-Judge</strong> 評估引擎。評估將依據 RAGAS 指標框架對回答之忠實度、相關性及上下文精準度進行自動跑分。
      </p>
      
      <div class="flex flex-col sm:flex-row items-end gap-4">
        <div class="flex-grow flex flex-col gap-2 w-full">
          <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">選擇測試數據集 (Test Dataset)</label>
          <select 
            v-model="selectedDatasetId"
            @change="handleDatasetChange"
            :disabled="isLoading"
            class="bg-white/5 border border-white/8 rounded-lg text-white px-3.5 py-2.5 text-sm focus:outline-none focus:border-[#8b5cf6] transition-all w-full"
          >
            <option v-for="d in datasets" :key="d.id" :value="d.id" class="bg-[#111827] text-white">
              {{ d.name }}
            </option>
          </select>
        </div>
        <button 
          @click="emit('start-eval', { datasetId: selectedDatasetId, maxTokens, searchType })"
          :disabled="isLoading"
          class="bg-[#8b5cf6] hover:bg-[#a78bfa] disabled:bg-purple-900/50 disabled:text-purple-300/50 hover:shadow-[0_4px_12px_rgba(139,92,246,0.3)] text-white font-semibold px-5 py-3 rounded-lg text-sm flex items-center justify-center gap-2 transition-all w-full sm:w-auto h-[42px] flex-shrink-0"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="flex-shrink-0">
            <polygon points="5 3 19 12 5 21 5 3"></polygon>
          </svg>
          開始自動評估
        </button>
      </div>

      <!-- Max Tokens & Search Type Parameters -->
      <div class="mt-4 flex flex-col gap-4 bg-white/3 border border-white/5 rounded-xl p-4">
        <!-- Search Type Selector -->
        <div class="flex flex-col gap-2">
          <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">檢索模式 (Search Type)</label>
          <select 
            v-model="searchType" 
            :disabled="isLoading"
            class="bg-white/5 border border-white/8 rounded-lg text-white px-3 py-2 text-xs focus:outline-none focus:border-[#8b5cf6] transition-all w-full"
          >
            <option value="vector" class="bg-[#111827] text-white">向量搜尋 (Vector Search)</option>
            <option value="hybrid" class="bg-[#111827] text-white">混合搜尋 (Hybrid Search)</option>
          </select>
        </div>

        <!-- Max Tokens Slider -->
        <div class="flex flex-col gap-2 border-t border-white/5 pt-3">
          <div class="flex justify-between items-center text-xs font-semibold">
            <span class="text-[#9ca3af]">單筆生成最大 Token 數 (MAX TOKENS)</span>
            <span class="text-white font-mono bg-[#8b5cf6]/20 border border-[#8b5cf6]/30 px-2 py-0.5 rounded text-[10px]">{{ maxTokens }}</span>
          </div>
          <div class="flex items-center gap-3 mt-1">
            <span class="text-[10px] text-[#6b7280]">512</span>
            <input 
              v-model.number="maxTokens"
              type="range" 
              min="512" 
              max="16384" 
              step="256"
              :disabled="isLoading"
              class="flex-grow h-1.5 bg-white/10 rounded-lg appearance-none cursor-pointer accent-[#8b5cf6] focus:outline-none"
            />
            <span class="text-[10px] text-[#6b7280]">8192</span>
          </div>
          <p class="text-[10px] text-[#6b7280] leading-relaxed">
            較高的限制可避免長文答覆或 Reasoning 模型思考過程 (Thinking) 被截斷，但會增加評估產生的耗時。
          </p>
        </div>
      </div>

      <!-- 效能與斷線警告提示 -->
      <div class="mt-4 text-xs text-amber-400 bg-amber-500/10 border border-amber-500/20 px-3.5 py-3 rounded-xl flex items-start gap-2.5 leading-relaxed">
        <svg class="flex-shrink-0 mt-0.5 text-amber-400" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
          <line x1="12" y1="9" x2="12" y2="13"></line>
          <line x1="12" y1="17" x2="12.01" y2="17"></line>
        </svg>
        <div>
          <strong>效能提示：</strong> 由於本系統採用推理大模型 (Reasoning Model) 進行評估，生成與思考耗時較長。為了防範連線逾時 (HTTP Timeout) 斷線，每次評估上限強制為 <strong>5 筆問答</strong>，超出部分將自動忽略。
        </div>
      </div>
    </div>

    <!-- Dataset info panel -->
    <div class="bg-[#111827]/70 border border-white/8 rounded-2xl p-6 backdrop-blur-md flex flex-col justify-between">
      <div>
        <div class="text-sm font-bold text-white mb-4 tracking-wider">測試集資訊</div>
        <div class="flex flex-col gap-3.5 text-xs">
          <div class="flex justify-between items-center border-b border-white/5 pb-2">
            <span class="text-[#9ca3af]">數據集名稱</span>
            <span class="font-semibold text-white truncate max-w-[150px]">{{ activeDataset?.name ? activeDataset.name.split(' (')[0] : '-' }}</span>
          </div>
          <div class="flex justify-between items-center border-b border-white/5 pb-2">
            <span class="text-[#9ca3af]">總問答筆數</span>
            <span class="font-bold text-white font-display">{{ activeDataset?.count ?? 0 }} 筆</span>
          </div>
          <div class="flex justify-between items-center border-b border-white/5 pb-2">
            <span class="text-[#9ca3af]">關聯知識庫</span>
            <span class="text-white">{{ activeDataset?.kb || '-' }}</span>
          </div>
          <div class="flex justify-between items-center">
            <span class="text-[#9ca3af]">上次評估時間</span>
            <span class="text-[#6b7280]">{{ activeDataset?.lastRun || '-' }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- Import Modal Overlay -->
  <div v-if="showImportModal" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
    <div class="bg-[#111827] border border-white/10 rounded-2xl w-full max-w-lg overflow-hidden shadow-2xl flex flex-col">
      <div class="p-6 border-b border-white/5 flex justify-between items-center">
        <h3 class="text-base font-bold text-white">匯入新測試集</h3>
        <button @click="showImportModal = false" class="text-[#9ca3af] hover:text-white transition-all text-xl">&times;</button>
      </div>
      <div class="p-6 flex flex-col gap-4 overflow-y-auto max-h-[70vh]">
        <div class="flex flex-col gap-1.5">
          <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">測試集名稱</label>
          <input v-model="importName" type="text" placeholder="例如：技術規格-進階問答" class="bg-white/5 border border-white/8 rounded-lg text-white px-3.5 py-2.5 text-sm focus:outline-none focus:border-[#8b5cf6] transition-all w-full" />
        </div>
        <div class="flex flex-col gap-1.5">
          <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">說明描述 (選填)</label>
          <input v-model="importDescription" type="text" placeholder="評估特定模組準確度之問答" class="bg-white/5 border border-white/8 rounded-lg text-white px-3.5 py-2.5 text-sm focus:outline-none focus:border-[#8b5cf6] transition-all w-full" />
        </div>
        <div class="flex flex-col gap-1.5">
          <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">問答內容 (JSON Array)</label>
          <textarea v-model="importJson" rows="8" class="bg-white/5 border border-white/8 rounded-lg text-white px-3.5 py-2.5 text-xs font-mono focus:outline-none focus:border-[#8b5cf6] transition-all w-full resize-y"></textarea>
          <div class="text-[10px] text-[#6b7280]">
            請提供 JSON 陣列格式，每個物件需包含 "question" 與 "ground_truth" 鍵。
          </div>
        </div>
        <div v-if="importError" class="text-xs text-red-400 bg-red-400/10 border border-red-400/20 px-3 py-2 rounded-lg">
          {{ importError }}
        </div>
      </div>
      <div class="p-6 border-t border-white/5 flex justify-end gap-3 bg-[#111827]/50">
        <button @click="showImportModal = false" class="px-4 py-2 border border-white/8 text-xs text-[#9ca3af] hover:text-white rounded-lg transition-all">取消</button>
        <button @click="handleImport" class="bg-[#8b5cf6] hover:bg-[#a78bfa] text-white px-4 py-2 rounded-lg text-xs font-semibold transition-all">確認匯入</button>
      </div>
    </div>
  </div>
</template>
