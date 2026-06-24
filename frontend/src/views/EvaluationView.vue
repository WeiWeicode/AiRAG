<script setup>
import { ref } from 'vue'
import ScoreBoard from '../components/eval/ScoreBoard.vue'
import TestSetManager from '../components/eval/TestSetManager.vue'
import ReportChart from '../components/eval/ReportChart.vue'
import evalService from '../services/evalService'
import { useAuthStore } from '../stores/authStore'

const authStore = useAuthStore()

const isEvaluating = ref(false)
const progressCount = ref(0)
const totalCount = ref(50)

// Report stats
const faithfulness = ref(0)
const relevancy = ref(0)
const precision = ref(0)
const recall = ref(0)

const reportDetails = ref([])

// Dataset edit/tweak state
const datasetDetails = ref(null)
const isSavingDataset = ref(false)

const handleDatasetSelect = async (dataset) => {
  if (!dataset) {
    datasetDetails.value = null
    return
  }
  try {
    const data = await evalService.getDatasetDetails(dataset.id)
    datasetDetails.value = data
  } catch (error) {
    console.error('Failed to load dataset details:', error)
    datasetDetails.value = null
  }
}

const addQaItem = () => {
  if (!datasetDetails.value) return
  if (!datasetDetails.value.items) {
    datasetDetails.value.items = []
  }
  datasetDetails.value.items.push({
    question: '',
    ground_truth: '',
    relevant_contexts: []
  })
}

const removeQaItem = (idx) => {
  if (!datasetDetails.value || !datasetDetails.value.items) return
  datasetDetails.value.items.splice(idx, 1)
}

const saveDatasetChanges = async () => {
  if (!datasetDetails.value) return
  isSavingDataset.value = true
  try {
    const payload = {
      name: datasetDetails.value.name,
      description: datasetDetails.value.description,
      items: datasetDetails.value.items.map(item => ({
        question: item.question.trim(),
        ground_truth: item.ground_truth.trim(),
        relevant_contexts: item.relevant_contexts || []
      }))
    }
    await evalService.updateDataset(datasetDetails.value.dataset_id, payload)
    alert('測試集修改已成功儲存至資料庫！')
  } catch (error) {
    console.error('Failed to save dataset changes:', error)
    alert('儲存修改失敗，請檢查後端服務')
  } finally {
    isSavingDataset.value = false
  }
}

const startEvaluation = async (data) => {
  const datasetId = typeof data === 'object' ? data.datasetId : data
  const maxTokensVal = typeof data === 'object' ? data.maxTokens : 16384

  // 自動在評估前保存修改
  if (datasetDetails.value && datasetDetails.value.dataset_id === datasetId) {
    try {
      const payload = {
        name: datasetDetails.value.name,
        description: datasetDetails.value.description,
        items: datasetDetails.value.items.map(item => ({
          question: item.question.trim(),
          ground_truth: item.ground_truth.trim(),
          relevant_contexts: item.relevant_contexts || []
        }))
      }
      await evalService.updateDataset(datasetId, payload)
    } catch (error) {
      console.warn('Auto-saving dataset before eval failed:', error)
    }
  }

  isEvaluating.value = true
  progressCount.value = 0
  totalCount.value = 0
  reportDetails.value = []
  
  // 重置分數顯示
  faithfulness.value = 0
  relevancy.value = 0
  precision.value = 0
  recall.value = 0
  
  try {
    const payload = {
      dataset_id: datasetId,
      knowledge_base_id: datasetId === 'dataset_tech' ? 'tech_specs' : 'hr_docs',
      params: {
        model: 'Qwen3.6-35B-A3B-FP8',
        temperature: 0.3,
        top_k: 5,
        max_tokens: maxTokensVal
      }
    }
    
    const response = await fetch(`${import.meta.env.VITE_API_BASE_URL || '/api'}/evaluation/run`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': authStore.token ? `Bearer ${authStore.token}` : ''
      },
      body: JSON.stringify(payload)
    })
    
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`)
    }
    
    const reader = response.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    let currentEvent = null
    
    while (true) {
      const { value, done } = await reader.read()
      if (value) {
        buffer += decoder.decode(value, { stream: true })
      }
      
      const lines = buffer.split('\n')
      if (!done) {
        buffer = lines.pop()
      } else {
        buffer = ''
      }
      
      for (const line of lines) {
        const trimmedLine = line.trim()
        if (trimmedLine.startsWith('event:')) {
          currentEvent = trimmedLine.replace('event:', '').trim()
        } else if (trimmedLine.startsWith('data:')) {
          const dataStr = trimmedLine.replace('data:', '').trim()
          if (!dataStr) continue
          
          try {
            const data = JSON.parse(dataStr)
            if (currentEvent === 'init') {
              totalCount.value = data.total
              progressCount.value = 0
            } else if (currentEvent === 'progress') {
              progressCount.value = data.index
            } else if (currentEvent === 'item_done') {
              // 將已完成的單筆問答結果即時加入明細表格中
              reportDetails.value.push(data)
            } else if (currentEvent === 'result') {
              // 更新最終匯整總分數
              faithfulness.value = data.summary?.faithfulness || 0
              relevancy.value = data.summary?.relevancy || data.summary?.answer_relevancy || 0
              precision.value = data.summary?.precision || data.summary?.context_precision || 0
              recall.value = data.summary?.recall || data.summary?.context_recall || 0
              // 覆蓋為最完整的最終明細
              reportDetails.value = data.details || []
            }
          } catch (e) {
            console.error('Failed to parse SSE JSON data:', dataStr, e)
          }
        }
      }
      if (done) break
    }
  } catch (error) {
    console.error('Backend evaluation call failed:', error)
    alert('評估執行失敗，請檢查後端服務與連線')
  } finally {
    isEvaluating.value = false
  }
}

const getScoreColor = (score) => {
  if (score >= 0.85) return 'text-[#10b981] bg-[#10b981]/10 border-[#10b981]/20'
  if (score >= 0.70) return 'text-[#f59e0b] bg-[#f59e0b]/10 border-[#f59e0b]/20'
  return 'text-[#ef4444] bg-[#ef4444]/10 border-[#ef4444]/20'
}

const handleExport = async (format) => {
  try {
    const csvContent = "data:text/csv;charset=utf-8," 
      + "Question,Generated,GroundTruth,Faithfulness,Relevancy\n"
      + reportDetails.value.map(r => `"${r.question}","${r.generated_answer}","${r.ground_truth}",${r.scores?.faithfulness || 0},${r.scores?.relevancy || 0}`).join("\n");
    const encodedUri = encodeURI(csvContent)
    const link = document.createElement("a")
    link.setAttribute("href", encodedUri)
    link.setAttribute("download", `RAGAS_Report_${Date.now()}.${format}`)
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  } catch (error) {
    console.error('Export report failed:', error)
  }
}
</script>

<template>
  <div class="flex-grow overflow-y-auto p-8 flex flex-col gap-8 h-full">
    <!-- Dataset Selection & Run Control -->
    <TestSetManager 
      :is-loading="isEvaluating"
      @start-eval="startEvaluation"
      @select-dataset="handleDatasetSelect"
    />

    <!-- Dataset Tweak Panel -->
    <div 
      v-if="datasetDetails" 
      class="bg-[#111827]/70 border border-white/8 rounded-2xl p-6 backdrop-blur-md flex flex-col gap-5"
    >
      <div class="flex justify-between items-center border-b border-white/5 pb-3">
        <div>
          <h3 class="text-sm font-bold text-white tracking-wider">測試集項目微調</h3>
          <p class="text-xs text-[#9ca3af] mt-1">
            您可以即時調整、新增或刪除此測試集中的問答項目，隨後點選「儲存修改」寫入資料庫。
          </p>
        </div>
        <div class="flex gap-2">
          <button 
            @click="addQaItem"
            class="px-3.5 py-2 border border-white/8 hover:border-white/16 text-xs text-[#9ca3af] hover:text-white rounded-lg bg-white/3 font-semibold transition-all flex items-center gap-1.5"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="12" y1="5" x2="12" y2="19"></line>
              <line x1="5" y1="12" x2="19" y2="12"></line>
            </svg>
            新增問答項目
          </button>
          <button 
            @click="saveDatasetChanges"
            :disabled="isSavingDataset"
            class="bg-[#8b5cf6] hover:bg-[#a78bfa] disabled:bg-purple-900/50 hover:shadow-[0_4px_12px_rgba(139,92,246,0.3)] text-white font-semibold px-4 py-2 rounded-lg text-xs flex items-center justify-center gap-1.5 transition-all"
          >
            <span v-if="isSavingDataset">儲存中...</span>
            <span v-else>儲存修改</span>
          </button>
        </div>
      </div>

      <div class="flex flex-col gap-4 max-h-[300px] overflow-y-auto pr-2">
        <div 
          v-for="(item, idx) in datasetDetails.items" 
          :key="idx" 
          class="bg-white/3 border border-white/5 rounded-xl p-4 flex flex-col gap-3 relative group"
        >
          <div class="absolute top-4 right-4 opacity-0 group-hover:opacity-100 transition-opacity">
            <button 
              @click="removeQaItem(idx)"
              class="p-1.5 text-[#ef4444] hover:bg-red-500/10 rounded-lg transition-all"
              title="刪除此項目"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="3 6 5 6 21 6"></polyline>
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
              </svg>
            </button>
          </div>
          
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div class="flex flex-col gap-1.5">
              <label class="text-[10px] font-bold text-[#6b7280] uppercase tracking-wider">問題 (Question)</label>
              <textarea 
                v-model="item.question" 
                rows="2" 
                class="bg-white/5 border border-white/8 rounded-lg text-white px-3 py-2 text-xs focus:outline-none focus:border-[#8b5cf6] transition-all w-full resize-none"
                placeholder="輸入測試問題"
              ></textarea>
            </div>
            <div class="flex flex-col gap-1.5">
              <label class="text-[10px] font-bold text-[#6b7280] uppercase tracking-wider">標準答案 (Ground Truth)</label>
              <textarea 
                v-model="item.ground_truth" 
                rows="2" 
                class="bg-white/5 border border-white/8 rounded-lg text-white px-3 py-2 text-xs focus:outline-none focus:border-[#8b5cf6] transition-all w-full resize-none"
                placeholder="輸入該問題的標準參考解答"
              ></textarea>
            </div>
          </div>
        </div>

        <div 
          v-if="datasetDetails.items.length === 0" 
          class="text-center py-8 text-xs text-[#6b7280]"
        >
          測試集中尚無問答項目，請點選「新增問答項目」開始。
        </div>
      </div>
    </div>

    <!-- Running Progress Bar -->
    <div 
      v-if="isEvaluating" 
      class="bg-[#111827]/70 border border-[#8b5cf6]/20 rounded-2xl p-6 backdrop-blur-md flex flex-col gap-3.5"
    >
      <div class="flex justify-between items-center text-xs font-semibold">
        <span class="text-[#a78bfa]">LLM-as-a-Judge 批次評估執行中...</span>
        <span class="text-white">已完成 {{ progressCount }} / {{ totalCount }} 筆問答</span>
      </div>
      <div class="w-full bg-white/5 h-2 rounded-full overflow-hidden border border-white/5">
        <div 
          class="bg-gradient-to-r from-[#8b5cf6] to-[#3b82f6] h-full rounded-full transition-all duration-300"
          :style="{ width: `${totalCount > 0 ? (progressCount / totalCount) * 100 : 0}%` }"
        ></div>
      </div>
    </div>

    <!-- Metrics Dashboard -->
    <div class="flex flex-col gap-4">
      <h3 class="text-base font-bold text-white tracking-wide">RAGAS 自動評量大盤指標</h3>
      <ScoreBoard 
        :faithfulness="faithfulness"
        :relevancy="relevancy"
        :precision="precision"
        :recall="recall"
      />
    </div>

    <!-- SVG Chart and Detailed Data Grid -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <!-- SVG Chart -->
      <div class="lg:col-span-1">
        <ReportChart 
          :faithfulness="faithfulness"
          :relevancy="relevancy"
          :precision="precision"
          :recall="recall"
        />
      </div>

      <!-- Comparison Detailed Table -->
      <div class="lg:col-span-2 bg-[#111827]/40 border border-white/8 rounded-2xl p-6 flex flex-col gap-4">
        <div class="flex justify-between items-center">
          <span class="text-sm font-bold text-white tracking-wider">問答比對明細</span>
          <div class="flex gap-2">
            <button 
              @click="handleExport('csv')"
              class="px-3.5 py-2 border border-white/8 hover:border-white/16 text-xs text-[#9ca3af] hover:text-white rounded-lg bg-white/3 font-semibold transition-all"
            >
              匯出 CSV 報告
            </button>
            <button 
              @click="handleExport('json')"
              class="px-3.5 py-2 border border-[#8b5cf6]/30 hover:border-[#8b5cf6] text-xs text-[#a78bfa] hover:text-white rounded-lg bg-[#8b5cf6]/5 font-semibold transition-all"
            >
              匯出 JSON 報告
            </button>
          </div>
        </div>

        <div class="overflow-x-auto">
          <table class="w-full text-left border-collapse text-xs">
            <thead>
              <tr class="border-b border-white/8 text-[#6b7280] font-semibold">
                <th class="pb-3 font-medium">問題與回答比對</th>
                <th class="pb-3 text-center px-2 font-medium w-[70px]">忠實度</th>
                <th class="pb-3 text-center px-2 font-medium w-[70px]">相關性</th>
                <th class="pb-3 text-center px-2 font-medium w-[70px]">精確率</th>
                <th class="pb-3 text-center px-2 font-medium w-[70px]">召回率</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-white/4">
              <tr 
                v-for="(item, idx) in reportDetails" 
                :key="idx" 
                class="hover:bg-white/1 transition-all"
              >
                <td class="py-4 pr-4 flex flex-col gap-1.5 max-w-[400px]">
                  <div class="font-bold text-white">Q: {{ item.question }}</div>
                  <div class="text-[#9ca3af]"><strong class="text-purple-400">Gen:</strong> {{ item.generated_answer }}</div>
                  <div class="text-[#6b7280]"><strong class="text-emerald-500">GT:</strong> {{ item.ground_truth }}</div>
                </td>
                <td class="py-4 text-center px-2">
                  <span class="px-2 py-0.5 rounded border font-semibold font-display text-[10px]" :class="getScoreColor(item.scores.faithfulness)">
                    {{ item.scores.faithfulness.toFixed(2) }}
                  </span>
                </td>
                <td class="py-4 text-center px-2">
                  <span class="px-2 py-0.5 rounded border font-semibold font-display text-[10px]" :class="getScoreColor(item.scores.relevancy)">
                    {{ item.scores.relevancy.toFixed(2) }}
                  </span>
                </td>
                <td class="py-4 text-center px-2">
                  <span class="px-2 py-0.5 rounded border font-semibold font-display text-[10px]" :class="getScoreColor(item.scores.precision)">
                    {{ item.scores.precision.toFixed(2) }}
                  </span>
                </td>
                <td class="py-4 text-center px-2">
                  <span class="px-2 py-0.5 rounded border font-semibold font-display text-[10px]" :class="getScoreColor(item.scores.recall)">
                    {{ item.scores.recall.toFixed(2) }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>
