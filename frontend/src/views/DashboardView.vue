<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import api from '../services/api'

const router = useRouter()

const stats = ref([
  { id: 'kbs', label: '知識庫總數', value: '0', desc: 'Active Knowledge Bases', icon: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path>' },
  { id: 'feedback', label: '人工標註筆數', value: '0', desc: 'Annotated Queries', icon: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line>' },
  { id: 'faithfulness', label: '綜合忠實度 (Faithfulness)', value: '0.00', desc: 'Average RAGAS score', icon: '<circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline>' },
  { id: 'evaluations', label: '已執行自動評估', value: '0', desc: 'Evaluation reports generated', icon: '<line x1="18" y1="20" x2="18" y2="10"></line><line x1="12" y1="20" x2="12" y2="4"></line><line x1="6" y1="20" x2="6" y2="14"></line>' },
  { id: 'zero_hit_rate', label: '近7日無命中問題比例', value: '0%', desc: 'Zero-Hit Query Rate (7d)', icon: '<circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line>' },
  { id: 'avg_retrieval_score', label: '近7日平均檢索分數', value: '0.00', desc: 'Avg Retrieval Score (7d)', icon: '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline>' }
])

const showZeroHitModal = ref(false)
const zeroHitLoading = ref(false)
const zeroHitItems = ref([])
const zeroHitTotal = ref(0)
const zeroHitPage = ref(1)
const zeroHitPageSize = ref(20)
const zeroHitTotalPages = computed(() => Math.max(1, Math.ceil(zeroHitTotal.value / zeroHitPageSize.value)))

const fetchDashboardStats = async () => {
  try {
    const kbResponse = await api.get('/api/knowledge-bases')
    if (kbResponse.data && kbResponse.data.items) {
      const kbStat = stats.value.find(s => s.id === 'kbs')
      if (kbStat) kbStat.value = String(kbResponse.data.items.length)
    }
  } catch (error) {
    console.error('Failed to fetch KB stats:', error)
  }

  try {
    const fbResponse = await api.get('/api/feedback')
    if (fbResponse.data) {
      const fbStat = stats.value.find(s => s.id === 'feedback')
      if (fbStat) fbStat.value = String(fbResponse.data.total || fbResponse.data.items?.length || 0)
    }
  } catch (error) {
    console.error('Failed to fetch feedback stats:', error)
  }

  try {
    const statsResponse = await api.get('/api/dashboard/retrieval-stats/summary?days=7')
    if (statsResponse.data) {
      const zeroHitStat = stats.value.find(s => s.id === 'zero_hit_rate')
      if (zeroHitStat) zeroHitStat.value = `${(statsResponse.data.zero_hit_rate * 100).toFixed(1)}%`
      const avgScoreStat = stats.value.find(s => s.id === 'avg_retrieval_score')
      if (avgScoreStat) avgScoreStat.value = statsResponse.data.avg_score?.toFixed(2) || '0.00'
    }
  } catch (error) {
    console.error('Failed to fetch retrieval stats:', error)
  }
}

const fetchZeroHitQuestions = async (page = 1) => {
  zeroHitLoading.value = true
  try {
    const res = await api.get('/api/dashboard/retrieval-stats/zero-hit-questions', {
      params: { days: 7, page, page_size: zeroHitPageSize.value }
    })
    zeroHitItems.value = res.data.items || []
    zeroHitTotal.value = res.data.total || 0
    zeroHitPage.value = res.data.page || page
  } catch (error) {
    console.error('Failed to fetch zero-hit questions:', error)
  } finally {
    zeroHitLoading.value = false
  }
}

const openZeroHitModal = () => {
  showZeroHitModal.value = true
  fetchZeroHitQuestions(1)
}

const goToZeroHitPage = (page) => {
  if (page < 1 || page > zeroHitTotalPages.value) return
  fetchZeroHitQuestions(page)
}

onMounted(() => {
  fetchDashboardStats()
})

const modules = [
  {
    title: 'RAG 功能測試 (E2E)',
    desc: '端到端檢索生成對話，支援對話歷史紀錄、引用來源定位與即時人工作答回饋標記。',
    path: '/rag-test',
    color: 'border-purple-500/20 hover:border-purple-500/40 bg-purple-500/5',
    btnColor: 'bg-purple-600 hover:bg-purple-500'
  },
  {
    title: '向量搜尋測試 (Retrieval)',
    desc: '進行純檢索測試，比較 Cosine 相似度，並可測試 Query 重寫及 HyDE 轉換效果。',
    path: '/retrieval-test',
    color: 'border-blue-500/20 hover:border-blue-500/40 bg-blue-500/5',
    btnColor: 'bg-blue-600 hover:bg-blue-500'
  },
  {
    title: '準確度評估 (Benchmarking)',
    desc: '載入測試數據集，透過 LLM-as-a-Judge 進行自動化 RAGAS 多維度評分並產出報告。',
    path: '/evaluation',
    color: 'border-emerald-500/20 hover:border-emerald-500/40 bg-emerald-500/5',
    btnColor: 'bg-emerald-600 hover:bg-emerald-500'
  },
  {
    title: 'Prompt / LLM 測試',
    desc: '自訂 System Prompt 及 Context 模板，支援多參數 A/B 對照溫度生成與變數替換預覽。',
    path: '/prompt-test',
    color: 'border-amber-500/20 hover:border-amber-500/40 bg-amber-500/5',
    btnColor: 'bg-amber-600 hover:bg-amber-500'
  },
  {
    title: '自訂資料向量化',
    desc: '支援 PDF/DOCX/TXT/MD 檔案解析、滑動調整切分參數預覽 Chunks、寫入 Qdrant 向量庫。',
    path: '/embedding-test',
    color: 'border-cyan-500/20 hover:border-cyan-500/40 bg-cyan-500/5',
    btnColor: 'bg-cyan-600 hover:bg-cyan-500'
  },
  {
    title: '標註與人工回饋歷史',
    desc: '集中管理人工標註歷史，支援將標註錯誤之問答批次匯出為測試集，或下載為 JSON/CSV。',
    path: '/feedback',
    color: 'border-rose-500/20 hover:border-rose-500/40 bg-rose-500/5',
    btnColor: 'bg-rose-600 hover:bg-rose-500'
  }
]
</script>

<template>
  <div class="flex-grow overflow-y-auto p-8 flex flex-col gap-8">
    <!-- Platform Intro -->
    <div class="relative bg-gradient-to-r from-[#8b5cf6]/10 to-[#3b82f6]/5 border border-white/8 rounded-2xl p-8 overflow-hidden">
      <div class="absolute w-[300px] h-[300px] bg-[#8b5cf6]/15 rounded-full blur-[80px] top-[-50px] right-[-50px] pointer-events-none"></div>
      <h2 class="text-2xl font-bold font-display text-white mb-2">歡迎使用 AiRAG 測試評估控制台</h2>
      <p class="text-sm text-[#9ca3af] max-w-[700px] leading-relaxed">
        本平台為一站式檢索增強生成 (RAG) 調優與測試工具。您可在此進行自訂資料切分、即時問答測試、自訂 Prompt A/B 溫度生成比較、以及透過 RAGAS 自動評估指標來定量優化 RAG 流程。
      </p>
    </div>

    <!-- Quick Stats Grid -->
    <div class="grid grid-cols-1 md:grid-cols-4 gap-5">
      <div
        v-for="stat in stats"
        :key="stat.label"
        class="bg-[#111827]/60 border border-white/8 rounded-xl p-5 flex items-center justify-between"
        :class="{ 'cursor-pointer hover:border-[#8b5cf6]/40 hover:bg-[#111827]/80 transition-all': stat.id === 'zero_hit_rate' }"
        @click="stat.id === 'zero_hit_rate' && openZeroHitModal()"
      >
        <div class="flex flex-col gap-1">
          <span class="text-[11px] font-semibold text-[#6b7280] uppercase tracking-wider">{{ stat.label }}</span>
          <span class="text-3xl font-extrabold text-white font-display leading-tight">{{ stat.value }}</span>
          <span class="text-[10px] text-[#9ca3af]">{{ stat.desc }}</span>
        </div>
        <div class="w-10 h-10 rounded-lg bg-white/3 border border-white/8 flex items-center justify-center text-[#8b5cf6]">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" v-html="stat.icon"></svg>
        </div>
      </div>
    </div>

    <!-- Modules Navigation Grid -->
    <div class="flex flex-col gap-4">
      <h3 class="text-lg font-bold text-white tracking-wide">測試評估模組</h3>
      <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div 
          v-for="mod in modules" 
          :key="mod.title" 
          class="border rounded-2xl p-6 flex flex-col justify-between transition-all duration-300 hover:translate-y-[-4px] hover:shadow-[0_10px_30px_rgba(0,0,0,0.2)]"
          :class="mod.color"
        >
          <div>
            <h4 class="text-base font-bold text-white mb-3">{{ mod.title }}</h4>
            <p class="text-xs text-[#9ca3af] leading-relaxed mb-6">{{ mod.desc }}</p>
          </div>
          <button 
            @click="router.push(mod.path)"
            class="w-full text-xs font-bold text-white py-3 rounded-xl flex items-center justify-center gap-1.5 transition-all shadow-[0_2px_8px_rgba(0,0,0,0.1)]"
            :class="mod.btnColor"
          >
            進入模組
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="5" y1="12" x2="19" y2="12"></line>
              <polyline points="12 5 19 12 12 19"></polyline>
            </svg>
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- 零命中問題清單下鑽 Modal -->
  <div v-if="showZeroHitModal" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
    <div class="bg-[#111827] border border-white/10 rounded-2xl w-full max-w-3xl max-h-[85vh] overflow-hidden shadow-2xl flex flex-col">
      <div class="p-6 border-b border-white/5 flex justify-between items-center">
        <h3 class="text-base font-bold text-white">近 7 日無命中問題清單</h3>
        <button @click="showZeroHitModal = false" class="text-[#9ca3af] hover:text-white transition-all text-xl">&times;</button>
      </div>
      <div class="p-6 flex flex-col gap-4 overflow-y-auto">
        <div v-if="zeroHitLoading" class="text-sm text-[#9ca3af] text-center py-8">載入中...</div>
        <div v-else-if="zeroHitItems.length === 0" class="text-sm text-[#9ca3af] text-center py-8">近 7 日沒有零命中的問題。</div>
        <table v-else class="w-full text-sm text-left border-collapse">
          <thead>
            <tr class="text-[11px] font-semibold text-[#6b7280] uppercase tracking-wider border-b border-white/8">
              <th class="py-2 pr-4">問題內容</th>
              <th class="py-2 pr-4">所屬知識庫</th>
              <th class="py-2 pr-4">查詢法</th>
              <th class="py-2 pr-4">發生時間</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in zeroHitItems" :key="item.id" class="border-b border-white/5">
              <td class="py-2.5 pr-4 text-white max-w-[280px] truncate" :title="item.question">{{ item.question }}</td>
              <td class="py-2.5 pr-4 text-[#9ca3af]">{{ item.knowledge_base_name || '-' }}</td>
              <td class="py-2.5 pr-4 text-[#9ca3af]">{{ item.search_type }}</td>
              <td class="py-2.5 pr-4 text-[#9ca3af] whitespace-nowrap">{{ new Date(item.created_at).toLocaleString() }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="zeroHitTotal > 0" class="p-4 border-t border-white/5 flex items-center justify-between text-xs text-[#9ca3af]">
        <span>共 {{ zeroHitTotal }} 筆，第 {{ zeroHitPage }} / {{ zeroHitTotalPages }} 頁</span>
        <div class="flex gap-2">
          <button
            @click="goToZeroHitPage(zeroHitPage - 1)"
            :disabled="zeroHitPage <= 1 || zeroHitLoading"
            class="px-3 py-1.5 rounded-lg bg-white/5 border border-white/8 text-white disabled:opacity-30 disabled:cursor-not-allowed hover:bg-white/10 transition-all"
          >上一頁</button>
          <button
            @click="goToZeroHitPage(zeroHitPage + 1)"
            :disabled="zeroHitPage >= zeroHitTotalPages || zeroHitLoading"
            class="px-3 py-1.5 rounded-lg bg-white/5 border border-white/8 text-white disabled:opacity-30 disabled:cursor-not-allowed hover:bg-white/10 transition-all"
          >下一頁</button>
        </div>
      </div>
    </div>
  </div>
</template>
