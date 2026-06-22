<script setup>
import { ref } from 'vue'
import ScoreBoard from '../components/eval/ScoreBoard.vue'
import TestSetManager from '../components/eval/TestSetManager.vue'
import ReportChart from '../components/eval/ReportChart.vue'
import evalService from '../services/evalService'

const isEvaluating = ref(false)
const progressCount = ref(0)
const totalCount = ref(50)

// Report stats
const faithfulness = ref(0)
const relevancy = ref(0)
const precision = ref(0)
const recall = ref(0)

const reportDetails = ref([])

const startEvaluation = async (datasetId) => {
  isEvaluating.value = true
  progressCount.value = 0
  
  try {
    const payload = {
      dataset_id: datasetId,
      knowledge_base_id: datasetId === 'dataset_tech' ? 'tech_specs' : 'hr_docs',
      params: {
        model: 'Qwen3.6-35B-A3B-FP8',
        temperature: 0.3,
        top_k: 5
      }
    }
    const response = await evalService.runEvaluation(payload)
    if (response) {
      faithfulness.value = response.summary?.faithfulness || 0
      relevancy.value = response.summary?.answer_relevancy || response.summary?.relevancy || 0
      precision.value = response.summary?.context_precision || response.summary?.precision || 0
      recall.value = response.summary?.context_recall || response.summary?.recall || 0
      reportDetails.value = response.details || []
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
    />

    <!-- Running Progress Bar -->
    <div 
      v-if="isEvaluating" 
      class="bg-[#111827]/70 border border-[#8b5cf6]/20 rounded-2xl p-6 backdrop-blur-md flex flex-col gap-3.5 animate-pulse"
    >
      <div class="flex justify-between items-center text-xs font-semibold">
        <span class="text-[#a78bfa]">LLM-as-a-Judge 批次評估執行中...</span>
        <span class="text-white">評估進行中，請稍候...</span>
      </div>
      <div class="w-full bg-white/5 h-2 rounded-full overflow-hidden border border-white/5">
        <div 
          class="bg-gradient-to-r from-[#8b5cf6] to-[#3b82f6] h-full rounded-full transition-all duration-300 w-full"
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
