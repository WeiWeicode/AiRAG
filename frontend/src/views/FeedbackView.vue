<script setup>
import { ref, onMounted } from 'vue'
import { useFeedbackStore } from '../stores/feedbackStore'

const feedbackStore = useFeedbackStore()

// Filter State
const errorFilter = ref('')
const page = ref(1)
const pageSize = ref(10)

// Selection State
const selectedIds = ref(new Set())

// Modal / Dataset creation State
const isSyncModalOpen = ref(false)
const syncDatasetName = ref('Feedback_Sync_' + new Date().toISOString().substring(0, 10))
const isSyncing = ref(false)

const errorLabels = {
  hallucination: '幻覺 (Hallucination)',
  incomplete: '資訊不完整',
  wrong_source: '引用來源錯誤',
  format_issue: '格式問題',
  other: '其他問題'
}

const getErrorBadgeClass = (type) => {
  const styles = {
    hallucination: 'bg-rose-500/10 text-[#ef4444] border-rose-500/20',
    incomplete: 'bg-amber-500/10 text-[#f59e0b] border-amber-500/20',
    wrong_source: 'bg-blue-500/10 text-[#3b82f6] border-blue-500/20',
    format_issue: 'bg-cyan-500/10 text-[#06b6d4] border-cyan-500/20',
    other: 'bg-white/5 text-[#9ca3af] border-white/8'
  }
  return styles[type] || styles.other
}

const fetchRecords = async () => {
  const params = {
    page: page.value,
    page_size: pageSize.value
  }
  if (errorFilter.value) {
    params.error_type = errorFilter.value
  }
  await feedbackStore.fetchFeedbacks(params)
}

const handleFilterChange = () => {
  page.value = 1
  selectedIds.value.clear()
  fetchRecords()
}

const toggleSelectAll = (e) => {
  if (e.target.checked) {
    feedbackStore.feedbackList.forEach(item => {
      selectedIds.value.add(item.feedback_id)
    })
  } else {
    selectedIds.value.clear()
  }
}

const toggleSelect = (id) => {
  if (selectedIds.value.has(id)) {
    selectedIds.value.delete(id)
  } else {
    selectedIds.value.add(id)
  }
}

const handleExport = async (format) => {
  try {
    const data = await feedbackStore.exportFeedback(format)
    const blob = new Blob([data], { type: format === 'json' ? 'application/json' : 'text/csv' })
    const link = document.createElement('a')
    link.href = window.URL.createObjectURL(blob)
    link.download = `Feedback_Export_${Date.now()}.${format}`
    link.click()
  } catch (error) {
    console.error('Failed to export feedback:', error)
    alert('匯出失敗，請檢查後端服務與連線狀態')
  }
}

const handleSyncToDataset = async () => {
  if (selectedIds.value.size === 0) {
    alert('請先勾選欲匯入測試集的回饋紀錄。')
    return
  }
  isSyncModalOpen.value = true
}

const submitSync = async () => {
  if (!syncDatasetName.value.trim()) return
  
  isSyncing.value = true
  try {
    const payload = {
      feedback_ids: Array.from(selectedIds.value),
      new_dataset_name: syncDatasetName.value.trim()
    }
    const response = await feedbackStore.syncToDataset(payload)
    alert(response.message || `成功匯入 ${payload.feedback_ids.length} 筆回饋至測試集！`)
    isSyncModalOpen.value = false
    selectedIds.value.clear()
  } catch (error) {
    console.error('Failed to sync feedback to dataset:', error)
    alert('同步建立測試數據集失敗，請檢查後端服務')
  } finally {
    isSyncing.value = false
  }
}

const isDeleting = ref(false)

const handleDelete = async (id) => {
  if (!confirm('確定要刪除此筆回饋紀錄嗎？')) return
  
  try {
    await feedbackStore.deleteFeedback(id)
    selectedIds.value.delete(id)
    await fetchRecords()
  } catch (error) {
    alert('刪除失敗，請檢查後端服務與連線')
  }
}

const handleBatchDelete = async () => {
  if (selectedIds.value.size === 0) return
  if (!confirm(`確定要刪除選取的 ${selectedIds.value.size} 筆回饋紀錄嗎？`)) return
  
  isDeleting.value = true
  try {
    await feedbackStore.batchDeleteFeedbacks(Array.from(selectedIds.value))
    selectedIds.value.clear()
    await fetchRecords()
  } catch (error) {
    alert('批次刪除失敗，請檢查後端服務與連線')
  } finally {
    isDeleting.value = false
  }
}

onMounted(() => {
  fetchRecords()
})
</script>

<template>
  <div class="flex-grow overflow-y-auto p-8 flex flex-col gap-6 h-full">
    <!-- Filters & Actions Header bar -->
    <div class="bg-[#111827]/70 border border-white/8 rounded-2xl p-5 backdrop-blur-md flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 flex-shrink-0">
      
      <!-- Filter controls -->
      <div class="flex flex-wrap items-center gap-4">
        <div class="flex flex-col gap-1.5">
          <label class="text-[10px] font-semibold text-[#6b7280] uppercase tracking-wider">篩選錯誤分類</label>
          <select 
            v-model="errorFilter"
            @change="handleFilterChange"
            class="bg-white/5 border border-white/8 rounded-lg text-white px-3.5 py-2 text-xs focus:outline-none focus:border-[#8b5cf6] transition-all min-w-[150px]"
          >
            <option value="" class="bg-[#111827] text-white">全部問題類型</option>
            <option value="hallucination" class="bg-[#111827] text-white">幻覺 (Hallucination)</option>
            <option value="incomplete" class="bg-[#111827] text-white">資訊不完整</option>
            <option value="wrong_source" class="bg-[#111827] text-white">引用來源錯誤</option>
            <option value="format_issue" class="bg-[#111827] text-white">格式問題</option>
            <option value="other" class="bg-[#111827] text-white">其他問題</option>
          </select>
        </div>
      </div>

      <!-- Action buttons -->
      <div class="flex gap-2">
        <button 
          @click="handleExport('csv')"
          class="px-4 py-2 border border-white/8 hover:border-white/16 text-xs text-[#9ca3af] hover:text-white rounded-lg bg-white/3 font-semibold transition-all"
        >
          匯出 CSV
        </button>
        <button 
          @click="handleExport('json')"
          class="px-4 py-2 border border-white/8 hover:border-white/16 text-xs text-[#9ca3af] hover:text-white rounded-lg bg-white/3 font-semibold transition-all"
        >
          匯出 JSON
        </button>
        <button 
          @click="handleSyncToDataset"
          :disabled="selectedIds.size === 0"
          class="px-4 py-2 bg-[#8b5cf6] hover:bg-[#a78bfa] hover:shadow-[0_4px_12px_rgba(139,92,246,0.3)] disabled:bg-purple-900/50 disabled:text-purple-300/50 text-xs text-white font-semibold rounded-lg transition-all"
        >
          匯入至評估測試集 ({{ selectedIds.size }})
        </button>
        <button 
          @click="handleBatchDelete"
          :disabled="selectedIds.size === 0 || isDeleting"
          class="px-4 py-2 bg-rose-600 hover:bg-rose-500 hover:shadow-[0_4px_12px_rgba(244,63,94,0.3)] disabled:bg-rose-950/50 disabled:text-rose-300/30 text-xs text-white font-semibold rounded-lg transition-all"
        >
          {{ isDeleting ? '刪除中...' : `刪除選取 (${selectedIds.size})` }}
        </button>
      </div>
    </div>

    <!-- Data Table Container -->
    <div class="flex-grow bg-[#111827]/40 border border-white/8 rounded-2xl p-6 overflow-hidden flex flex-col">
      <div class="flex-grow overflow-y-auto">
        <table class="w-full text-left border-collapse text-xs">
          <thead>
            <tr class="border-b border-white/8 text-[#6b7280] font-semibold">
              <th class="pb-3 w-[40px] text-center">
                <input 
                  type="checkbox" 
                  @change="toggleSelectAll" 
                  :checked="feedbackStore.feedbackList.length > 0 && selectedIds.size === feedbackStore.feedbackList.length"
                  class="rounded bg-white/5 border-white/8 text-[#8b5cf6] focus:ring-[#8b5cf6]/20"
                />
              </th>
              <th class="pb-3 w-[150px] font-medium">記錄編號</th>
              <th class="pb-3 font-medium">問答與回饋標記比對</th>
              <th class="pb-3 text-center w-[120px] font-medium">錯誤類型</th>
              <th class="pb-3 text-right w-[150px] font-medium">提交時間</th>
              <th class="pb-3 text-center w-[80px] font-medium">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-white/4">
            <tr v-if="feedbackStore.isLoading" class="text-[#9ca3af] text-center">
              <td colspan="6" class="py-8">載入中...</td>
            </tr>
            <tr v-else-if="feedbackStore.feedbackList.length === 0" class="text-[#6b7280] text-center">
              <td colspan="6" class="py-8">尚無符合條件的回饋紀錄</td>
            </tr>
            <tr 
              v-else
              v-for="item in feedbackStore.feedbackList" 
              :key="item.feedback_id" 
              class="hover:bg-white/1 transition-all"
            >
              <td class="py-4 text-center">
                <input 
                  type="checkbox" 
                  :checked="selectedIds.has(item.feedback_id)"
                  @change="toggleSelect(item.feedback_id)"
                  class="rounded bg-white/5 border-white/8 text-[#8b5cf6] focus:ring-[#8b5cf6]/20"
                />
              </td>
              <td class="py-4 font-mono text-[10px] text-[#6b7280] truncate max-w-[130px]" :title="item.feedback_id">
                {{ item.feedback_id }}
              </td>
              <td class="py-4 pr-6 flex flex-col gap-1.5 max-w-[500px]">
                <div class="font-bold text-white">Q: {{ item.question || '使用者問題' }}</div>
                <div class="text-[#9ca3af]"><strong class="text-purple-400">AI:</strong> {{ item.ai_answer || 'AI 生成回答' }}</div>
                <div class="text-[#6b7280]"><strong class="text-emerald-500">GT:</strong> {{ item.correct_answer || '人工標註正確答案' }}</div>
                <div v-if="item.note" class="text-[10px] text-[#6b7280] bg-black/15 px-2 py-1 rounded border border-white/3 italic">備註: {{ item.note }}</div>
              </td>
              <td class="py-4 text-center">
                <span class="px-2.5 py-0.5 rounded-full border text-[10px] font-semibold" :class="getErrorBadgeClass(item.error_type)">
                  {{ errorLabels[item.error_type] || item.error_type }}
                </span>
              </td>
              <td class="py-4 text-right text-[#6b7280] font-display">
                {{ new Date(item.created_at || Date.now()).toLocaleString() }}
              </td>
              <td class="py-4 text-center">
                <button 
                  @click="handleDelete(item.feedback_id)"
                  class="text-rose-400 hover:text-rose-300 hover:bg-rose-500/10 p-1.5 rounded-lg transition-all"
                  title="刪除此紀錄"
                >
                  <svg class="w-4 h-4 mx-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
                  </svg>
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Sync Dataset Modal Dialog -->
    <div 
      v-if="isSyncModalOpen" 
      class="fixed inset-0 bg-black/60 backdrop-blur-[4px] z-50 flex items-center justify-center p-4"
    >
      <div class="w-full max-w-[420px] bg-[#111827] border border-white/8 rounded-2xl p-6 shadow-[0_10px_40px_rgba(0,0,0,0.5)] flex flex-col gap-5">
        <div class="flex justify-between items-center pb-2 border-b border-white/5">
          <h3 class="font-semibold text-white text-sm">建立並同步至評估測試集</h3>
          <button @click="isSyncModalOpen = false" class="text-[#6b7280] hover:text-white text-base">&times;</button>
        </div>
        
        <p class="text-xs text-[#9ca3af] leading-relaxed">
          系統將把您勾選的 <strong>{{ selectedIds.size }} 筆</strong> 回饋紀錄（含問題與人工標註答案）包裝成新的評估測試集，可於「準確度評估」模組中直接呼叫執行。
        </p>

        <div class="flex flex-col gap-2">
          <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">測試數據集名稱 (Dataset Name)</label>
          <input 
            v-model="syncDatasetName" 
            type="text" 
            class="bg-white/5 border border-white/8 rounded-lg text-white px-3.5 py-2.5 text-xs focus:outline-none focus:border-[#8b5cf6] transition-all"
            placeholder="請輸入測試集名稱..."
          />
        </div>

        <div class="flex justify-end gap-3 mt-2">
          <button 
            @click="isSyncModalOpen = false"
            class="px-4 py-2 border border-white/8 bg-white/8 hover:bg-white/12 text-xs text-[#f3f4f6] font-semibold rounded-lg transition-all"
          >
            取消
          </button>
          <button 
            @click="submitSync"
            :disabled="isSyncing || !syncDatasetName.trim()"
            class="px-4 py-2 bg-[#8b5cf6] hover:bg-[#a78bfa] disabled:bg-purple-900/50 disabled:text-purple-300/50 text-xs text-white font-semibold rounded-lg transition-all"
          >
            {{ isSyncing ? '建立同步中...' : '確認建立並匯入' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
