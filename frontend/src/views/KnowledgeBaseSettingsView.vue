<script setup>
import { ref, onMounted } from 'vue'
import knowledgeBaseService from '../services/knowledgeBaseService'
import { useParamsStore } from '../stores/paramsStore'

const paramsStore = useParamsStore()

// Knowledge Base list state
const knowledgeBases = ref([])
const isLoading = ref(false)
const errorMessage = ref('')
const successMessage = ref('')

// Form state
const kbName = ref('')
const kbDescription = ref('')
const isCreating = ref(false)

// Delete modal state
const showDeleteModal = ref(false)
const targetKb = ref(null)
const confirmInput = ref('')
const isDeleting = ref(false)

const loadKnowledgeBases = async () => {
  isLoading.value = true
  errorMessage.value = ''
  try {
    const res = await knowledgeBaseService.list()
    if (res.data && res.data.items) {
      knowledgeBases.value = res.data.items
    }
  } catch (err) {
    console.error('無法載入知識庫清單:', err)
    errorMessage.value = err.response?.data?.detail || '無法載入知識庫清單'
  } finally {
    isLoading.value = false
  }
}

const handleCreate = async () => {
  errorMessage.value = ''
  successMessage.value = ''

  if (!kbName.value.trim()) {
    errorMessage.value = '請輸入知識庫名稱'
    return
  }

  isCreating.value = true
  try {
    await knowledgeBaseService.create({
      name: kbName.value.trim(),
      description: kbDescription.value.trim() || undefined
    })
    successMessage.value = `成功建立知識庫「${kbName.value.trim()}」`
    kbName.value = ''
    kbDescription.value = ''
    await loadKnowledgeBases()
  } catch (err) {
    console.error('建立知識庫失敗:', err)
    errorMessage.value = err.response?.data?.detail || '建立知識庫失敗'
  } finally {
    isCreating.value = false
  }
}

const openDeleteModal = (kb) => {
  targetKb.value = kb
  confirmInput.value = ''
  showDeleteModal.value = true
}

const closeDeleteModal = () => {
  showDeleteModal.value = false
  targetKb.value = null
  confirmInput.value = ''
}

const handleDeleteConfirm = async () => {
  if (!targetKb.value) return
  if (confirmInput.value !== targetKb.value.name) {
    errorMessage.value = '輸入的知識庫名稱不相符'
    return
  }

  const deletedId = targetKb.value.id
  const deletedName = targetKb.value.name
  isDeleting.value = true
  errorMessage.value = ''
  successMessage.value = ''

  try {
    await knowledgeBaseService.remove(deletedId)
    successMessage.value = `成功刪除知識庫「${deletedName}」及其向量資料`
    closeDeleteModal()

    await loadKnowledgeBases()

    // 連動重置全域選擇狀態
    if (deletedId === paramsStore.knowledgeBaseId) {
      const remainingFirst = knowledgeBases.value.length > 0 ? knowledgeBases.value[0].id : null
      paramsStore.knowledgeBaseId = remainingFirst
    }
  } catch (err) {
    console.error('刪除知識庫失敗:', err)
    errorMessage.value = err.response?.data?.detail || '刪除知識庫失敗'
  } finally {
    isDeleting.value = false
  }
}

onMounted(() => {
  loadKnowledgeBases()
})
</script>

<template>
  <div class="flex-grow overflow-y-auto p-8 flex flex-col gap-8 h-full">
    <!-- Header -->
    <div class="flex flex-col gap-2">
      <h1 class="text-2xl font-bold text-white tracking-wide">知識庫管理 (Knowledge Base / Collections)</h1>
      <p class="text-sm text-[#9ca3af]">
        建立與管理系統內的向量知識庫。刪除知識庫將同步清除 Qdrant 內對應的 Collection 向量資料。
      </p>
    </div>

    <!-- Alert Messages -->
    <div v-if="errorMessage" class="bg-rose-500/10 border border-rose-500/20 text-rose-300 px-4 py-3 rounded-xl text-sm flex justify-between items-center">
      <span>{{ errorMessage }}</span>
      <button @click="errorMessage = ''" class="text-rose-400 hover:text-rose-200">✕</button>
    </div>

    <div v-if="successMessage" class="bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 px-4 py-3 rounded-xl text-sm flex justify-between items-center">
      <span>{{ successMessage }}</span>
      <button @click="successMessage = ''" class="text-emerald-400 hover:text-emerald-200">✕</button>
    </div>

    <!-- Main Content Layout -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
      <!-- Left: Create Knowledge Base Panel -->
      <div class="bg-[#111827]/70 border border-white/8 rounded-2xl p-6 backdrop-blur-md flex flex-col gap-6 h-fit">
        <h2 class="text-lg font-bold text-white tracking-wide border-b border-white/5 pb-3">手動建立知識庫</h2>
        
        <form @submit.prevent="handleCreate" class="flex flex-col gap-4">
          <div class="flex flex-col gap-2">
            <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">知識庫名稱 (必填)</label>
            <input 
              v-model="kbName" 
              type="text" 
              placeholder="例：研發部技術文件庫" 
              class="bg-white/5 border border-white/8 rounded-lg text-white px-3.5 py-2.5 text-sm focus:outline-none focus:border-[#8b5cf6] focus:ring-2 focus:ring-[#8b5cf6]/15 transition-all"
              required
            />
          </div>

          <div class="flex flex-col gap-2">
            <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">知識庫描述 (選填)</label>
            <textarea 
              v-model="kbDescription" 
              placeholder="請簡述此知識庫的用途或收錄範圍..." 
              rows="3"
              class="bg-white/5 border border-white/8 rounded-lg text-white px-3.5 py-2.5 text-sm focus:outline-none focus:border-[#8b5cf6] focus:ring-2 focus:ring-[#8b5cf6]/15 transition-all resize-none"
            ></textarea>
          </div>

          <button 
            type="submit" 
            :disabled="isCreating"
            class="mt-2 bg-[#8b5cf6] hover:bg-[#a78bfa] disabled:bg-purple-900/50 disabled:text-purple-300/50 text-white font-semibold py-2.5 px-4 rounded-lg text-sm transition-all shadow-[0_0_15px_rgba(139,92,246,0.3)] flex items-center justify-center gap-2"
          >
            <span v-if="isCreating">建立中...</span>
            <span v-else>建立知識庫</span>
          </button>
        </form>
      </div>

      <!-- Right: Knowledge Base List Table -->
      <div class="lg:col-span-2 bg-[#111827]/70 border border-white/8 rounded-2xl p-6 backdrop-blur-md flex flex-col gap-6">
        <div class="flex justify-between items-center border-b border-white/5 pb-3">
          <h2 class="text-lg font-bold text-white tracking-wide">既有知識庫清單</h2>
          <span class="text-xs text-[#9ca3af] font-mono bg-white/5 px-2.5 py-1 rounded-md">
            總計: {{ knowledgeBases.length }} 個知識庫
          </span>
        </div>

        <div class="overflow-x-auto">
          <table class="w-full text-left text-sm text-[#9ca3af]">
            <thead>
              <tr class="border-b border-white/8 text-xs uppercase tracking-wider text-[#6b7280]">
                <th class="pb-3 font-medium">知識庫名稱</th>
                <th class="pb-3 font-medium">描述</th>
                <th class="pb-3 text-center font-medium">已向量化段落</th>
                <th class="pb-3 text-right font-medium">建立時間</th>
                <th class="pb-3 text-center font-medium">操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-white/4">
              <tr v-if="isLoading" class="text-[#9ca3af] text-center">
                <td colspan="5" class="py-8">載入中...</td>
              </tr>
              <tr v-else-if="knowledgeBases.length === 0" class="text-[#6b7280] text-center">
                <td colspan="5" class="py-8">尚無任何知識庫紀錄</td>
              </tr>
              <tr 
                v-else
                v-for="kb in knowledgeBases" 
                :key="kb.id" 
                class="hover:bg-white/1 transition-all"
              >
                <td class="py-4 font-semibold text-white">
                  {{ kb.name }}
                </td>
                <td class="py-4 text-xs text-[#9ca3af] max-w-[200px] truncate" :title="kb.description">
                  {{ kb.description || '無' }}
                </td>
                <td class="py-4 text-center font-mono text-xs text-purple-300">
                  {{ kb.chunk_count || 0 }}
                </td>
                <td class="py-4 text-right text-xs text-[#6b7280] font-display">
                  {{ new Date(kb.created_at || Date.now()).toLocaleString() }}
                </td>
                <td class="py-4 text-center">
                  <button 
                    @click="openDeleteModal(kb)"
                    class="text-rose-400 hover:text-rose-300 hover:bg-rose-500/10 p-1.5 rounded-lg transition-all"
                    title="刪除知識庫"
                  >
                    <svg class="w-4 h-4 mx-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
                    </svg>
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Delete Confirmation Modal -->
    <div v-if="showDeleteModal" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
      <div class="bg-[#111827] border border-rose-500/30 rounded-2xl p-6 max-w-md w-full flex flex-col gap-5 shadow-2xl">
        <div class="flex items-center gap-3 text-rose-400 border-b border-rose-500/10 pb-3">
          <svg class="w-6 h-6 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path>
          </svg>
          <h3 class="text-base font-bold text-white">二次確認：刪除知識庫</h3>
        </div>

        <div class="flex flex-col gap-3 text-sm text-[#9ca3af]">
          <p class="text-rose-300 font-medium">
            ⚠️ 警告：此操作將一併刪除 Qdrant 向量資料庫內該知識庫的所有段落與向量資料，且資料完全無法復原！
          </p>
          <p>
            請輸入知識庫名稱 <strong class="text-white select-all font-mono">{{ targetKb?.name }}</strong> 以確認刪除：
          </p>
          <input 
            v-model="confirmInput" 
            type="text" 
            :placeholder="targetKb?.name"
            class="bg-white/5 border border-white/10 rounded-lg text-white px-3.5 py-2 text-sm focus:outline-none focus:border-rose-500 transition-all font-mono"
          />
        </div>

        <div class="flex justify-end gap-3 pt-2">
          <button 
            @click="closeDeleteModal"
            class="px-4 py-2 rounded-lg text-sm text-[#9ca3af] hover:text-white bg-white/5 hover:bg-white/10 transition-all"
          >
            取消
          </button>
          <button 
            @click="handleDeleteConfirm"
            :disabled="confirmInput !== targetKb?.name || isDeleting"
            class="px-4 py-2 rounded-lg text-sm font-semibold text-white bg-rose-600 hover:bg-rose-500 disabled:opacity-40 disabled:cursor-not-allowed transition-all shadow-[0_0_15px_rgba(225,29,72,0.3)]"
          >
            <span v-if="isDeleting">刪除中...</span>
            <span v-else>確認刪除</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
