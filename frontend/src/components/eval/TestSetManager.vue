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
        kb: '關聯知識庫',
        lastRun: '未執行'
      }))
      if (datasets.value.length > 0) {
        selectedDatasetId.value = datasets.value[0].id
        activeDataset.value = datasets.value[0]
      } else {
        selectedDatasetId.value = ''
        activeDataset.value = null
      }
    }
  } catch (error) {
    console.error('無法取得測試數據集列表，請檢查後端服務:', error)
  }
}

onMounted(() => {
  fetchDatasets()
})
</script>

<template>
  <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
    <div class="lg:col-span-2 bg-[#111827]/70 border border-white/8 rounded-2xl p-6 backdrop-blur-md">
      <div class="text-sm font-bold text-white mb-2 tracking-wider">自動化評估任務控制</div>
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
          @click="emit('start-eval', selectedDatasetId)"
          :disabled="isLoading"
          class="bg-[#8b5cf6] hover:bg-[#a78bfa] disabled:bg-purple-900/50 disabled:text-purple-300/50 hover:shadow-[0_4px_12px_rgba(139,92,246,0.3)] text-white font-semibold px-5 py-3 rounded-lg text-sm flex items-center justify-center gap-2 transition-all w-full sm:w-auto h-[42px] flex-shrink-0"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="flex-shrink-0">
            <polygon points="5 3 19 12 5 21 5 3"></polygon>
          </svg>
          開始自動評估
        </button>
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
</template>
