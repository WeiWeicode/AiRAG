<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import appRegistrationService from '../services/appRegistrationService'

// App Registry list state
const appRegistrations = ref([])
const isLoading = ref(false)
const errorMessage = ref('')
const successMessage = ref('')

// Form state（同一份表單兼作新增與編輯，editingAppId 有值即為編輯模式）
const editingAppId = ref(null)
const isSubmitting = ref(false)
const form = reactive({
  app_id: '',
  display_name: '',
  base_url: '',
  content_docs_path_template: '',
  content_attachment_path_template: '',
  report_mode: 'webhook',
  is_active: true
})

const isEditing = computed(() => editingAppId.value !== null)

const reportModeOptions = [
  { label: 'webhook（AiRAG 回呼呼叫端回報進度）', value: 'webhook' },
  { label: 'direct_db（AiRAG 直連該 App 的 DB 回報，僅 kb 可用）', value: 'direct_db' },
]

const resetForm = () => {
  editingAppId.value = null
  form.app_id = ''
  form.display_name = ''
  form.base_url = ''
  form.content_docs_path_template = ''
  form.content_attachment_path_template = ''
  form.report_mode = 'webhook'
  form.is_active = true
}

const loadAppRegistrations = async () => {
  isLoading.value = true
  errorMessage.value = ''
  try {
    const res = await appRegistrationService.list()
    appRegistrations.value = res.data?.items || []
  } catch (err) {
    console.error('無法載入 App Registry 清單:', err)
    errorMessage.value = err.response?.data?.detail || '無法載入 App Registry 清單'
  } finally {
    isLoading.value = false
  }
}

const startEdit = (app) => {
  editingAppId.value = app.app_id
  form.app_id = app.app_id
  form.display_name = app.display_name
  form.base_url = app.base_url
  form.content_docs_path_template = app.content_docs_path_template
  form.content_attachment_path_template = app.content_attachment_path_template
  form.report_mode = app.report_mode
  form.is_active = app.is_active
  errorMessage.value = ''
  successMessage.value = ''
}

const handleSubmit = async () => {
  errorMessage.value = ''
  successMessage.value = ''

  if (!isEditing.value && !form.app_id.trim()) {
    errorMessage.value = '請輸入 App ID'
    return
  }
  if (!form.display_name.trim()) {
    errorMessage.value = '請輸入顯示名稱'
    return
  }
  if (!form.base_url.trim()) {
    errorMessage.value = '請輸入 Base URL'
    return
  }
  if (!form.content_docs_path_template.trim() || !form.content_attachment_path_template.trim()) {
    errorMessage.value = '請輸入文件與附件的路徑樣板'
    return
  }

  isSubmitting.value = true
  try {
    // 更新端點不接受 app_id 欄位（app_id 由路徑參數指定且不可改）
    const payload = {
      display_name: form.display_name.trim(),
      base_url: form.base_url.trim(),
      content_docs_path_template: form.content_docs_path_template.trim(),
      content_attachment_path_template: form.content_attachment_path_template.trim(),
      report_mode: form.report_mode,
      is_active: form.is_active
    }

    if (isEditing.value) {
      await appRegistrationService.update(editingAppId.value, payload)
      successMessage.value = `已更新 App Registry「${editingAppId.value}」`
    } else {
      await appRegistrationService.create({ app_id: form.app_id.trim(), ...payload })
      successMessage.value = `已建立 App Registry「${form.app_id.trim()}」`
    }
    resetForm()
    await loadAppRegistrations()
  } catch (err) {
    console.error('儲存 App Registry 失敗:', err)
    errorMessage.value = err.response?.data?.detail || '儲存 App Registry 失敗'
  } finally {
    isSubmitting.value = false
  }
}

const toggleActive = async (app) => {
  errorMessage.value = ''
  successMessage.value = ''
  try {
    await appRegistrationService.update(app.app_id, { is_active: !app.is_active })
    successMessage.value = `已將「${app.app_id}」設為${!app.is_active ? '啟用' : '停用'}`
    await loadAppRegistrations()
  } catch (err) {
    console.error('切換啟用狀態失敗:', err)
    errorMessage.value = err.response?.data?.detail || '切換啟用狀態失敗'
  }
}

const handleDelete = async (app) => {
  if (!confirm(`確定要刪除 App Registry「${app.app_id}」嗎？刪除後該 App 的同步觸發會立即失敗。若只是想暫停同步，請改用「停用」。`)) return
  errorMessage.value = ''
  successMessage.value = ''
  try {
    await appRegistrationService.remove(app.app_id)
    successMessage.value = `已刪除 App Registry「${app.app_id}」`
    if (editingAppId.value === app.app_id) resetForm()
    await loadAppRegistrations()
  } catch (err) {
    console.error('刪除 App Registry 失敗:', err)
    errorMessage.value = err.response?.data?.detail || '刪除 App Registry 失敗'
  }
}

onMounted(() => {
  loadAppRegistrations()
})
</script>

<template>
  <div class="flex-grow overflow-y-auto p-8 flex flex-col gap-8 h-full">
    <!-- Header -->
    <div class="flex flex-col gap-2">
      <h1 class="text-2xl font-bold text-white tracking-wide">App Registry 管理 (多應用 RAG 同步)</h1>
      <p class="text-sm text-[#9ca3af]">
        登錄可呼叫 <span class="font-mono text-purple-300">/api/external/ingest/trigger</span> 的接入應用。
        AiRAG 依觸發請求的 appId 查此表決定要呼叫哪個內容拉取 URL、用哪種方式回報進度。
        <span class="text-amber-300">未登錄或狀態為停用的 App，觸發時會直接回 400。</span>
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
      <!-- Left: Create / Edit Panel -->
      <div class="bg-[#111827]/70 border border-white/8 rounded-2xl p-6 backdrop-blur-md flex flex-col gap-6 h-fit">
        <h2 class="text-lg font-bold text-white tracking-wide border-b border-white/5 pb-3">
          {{ isEditing ? `編輯登錄：${editingAppId}` : '新增 App 登錄' }}
        </h2>

        <form @submit.prevent="handleSubmit" class="flex flex-col gap-4">
          <div class="flex flex-col gap-2">
            <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">App ID (必填，建立後不可修改)</label>
            <input
              v-model="form.app_id"
              type="text"
              placeholder="例：kb"
              :disabled="isEditing"
              class="bg-white/5 border border-white/8 rounded-lg text-white px-3.5 py-2.5 text-sm font-mono focus:outline-none focus:border-[#8b5cf6] focus:ring-2 focus:ring-[#8b5cf6]/15 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
            />
          </div>

          <div class="flex flex-col gap-2">
            <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">顯示名稱 (必填)</label>
            <input
              v-model="form.display_name"
              type="text"
              placeholder="例：碩禾知識庫"
              class="bg-white/5 border border-white/8 rounded-lg text-white px-3.5 py-2.5 text-sm focus:outline-none focus:border-[#8b5cf6] focus:ring-2 focus:ring-[#8b5cf6]/15 transition-all"
            />
          </div>

          <div class="flex flex-col gap-2">
            <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">Base URL (必填)</label>
            <input
              v-model="form.base_url"
              type="text"
              placeholder="例：http://10.10.130.122:5155/api/v1/rag-sync-content"
              class="bg-white/5 border border-white/8 rounded-lg text-white px-3.5 py-2.5 text-sm font-mono focus:outline-none focus:border-[#8b5cf6] focus:ring-2 focus:ring-[#8b5cf6]/15 transition-all"
            />
            <p class="text-[11px] text-[#6b7280]">內容拉取的網址前綴，須為 AiRAG 容器連得到的位址</p>
          </div>

          <div class="flex flex-col gap-2">
            <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">文件路徑樣板 (必填)</label>
            <input
              v-model="form.content_docs_path_template"
              type="text"
              placeholder="例：/article/{id}"
              class="bg-white/5 border border-white/8 rounded-lg text-white px-3.5 py-2.5 text-sm font-mono focus:outline-none focus:border-[#8b5cf6] focus:ring-2 focus:ring-[#8b5cf6]/15 transition-all"
            />
          </div>

          <div class="flex flex-col gap-2">
            <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">附件路徑樣板 (必填)</label>
            <input
              v-model="form.content_attachment_path_template"
              type="text"
              placeholder="例：/attachment-file/{id}"
              class="bg-white/5 border border-white/8 rounded-lg text-white px-3.5 py-2.5 text-sm font-mono focus:outline-none focus:border-[#8b5cf6] focus:ring-2 focus:ring-[#8b5cf6]/15 transition-all"
            />
            <p class="text-[11px] text-[#6b7280]">兩個樣板須含 <span class="font-mono">{id}</span>，會被替換為 sourceId</p>
          </div>

          <div class="flex flex-col gap-2">
            <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">回報模式</label>
            <select
              v-model="form.report_mode"
              class="bg-white/5 border border-white/8 rounded-lg text-white px-3.5 py-2.5 text-sm focus:outline-none focus:border-[#8b5cf6] focus:ring-2 focus:ring-[#8b5cf6]/15 transition-all"
            >
              <option v-for="opt in reportModeOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
            </select>
            <p class="text-[11px] text-[#6b7280]">
              選 webhook 時，呼叫端觸發必須帶 callbackUrl，否則會回 400
            </p>
          </div>

          <label class="flex items-center gap-2.5 cursor-pointer">
            <input v-model="form.is_active" type="checkbox" class="w-4 h-4 accent-[#8b5cf6]" />
            <span class="text-sm text-[#9ca3af]">啟用 (is_active)</span>
          </label>

          <div class="flex gap-3 mt-2">
            <button
              type="submit"
              :disabled="isSubmitting"
              class="flex-1 bg-[#8b5cf6] hover:bg-[#a78bfa] disabled:bg-purple-900/50 disabled:text-purple-300/50 text-white font-semibold py-2.5 px-4 rounded-lg text-sm transition-all shadow-[0_0_15px_rgba(139,92,246,0.3)]"
            >
              <span v-if="isSubmitting">儲存中...</span>
              <span v-else>{{ isEditing ? '更新登錄' : '建立登錄' }}</span>
            </button>
            <button
              v-if="isEditing"
              type="button"
              @click="resetForm"
              class="px-4 py-2.5 rounded-lg text-sm text-[#9ca3af] hover:text-white bg-white/5 hover:bg-white/10 transition-all"
            >
              取消編輯
            </button>
          </div>
        </form>
      </div>

      <!-- Right: App Registry List Table -->
      <div class="lg:col-span-2 bg-[#111827]/70 border border-white/8 rounded-2xl p-6 backdrop-blur-md flex flex-col gap-6">
        <div class="flex justify-between items-center border-b border-white/5 pb-3">
          <h2 class="text-lg font-bold text-white tracking-wide">已登錄的 App</h2>
          <span class="text-xs text-[#9ca3af] font-mono bg-white/5 px-2.5 py-1 rounded-md">
            總計: {{ appRegistrations.length }} 個
          </span>
        </div>

        <div class="overflow-x-auto">
          <table class="w-full text-left text-sm text-[#9ca3af]">
            <thead>
              <tr class="border-b border-white/8 text-xs uppercase tracking-wider text-[#6b7280]">
                <th class="pb-3 font-medium">App ID</th>
                <th class="pb-3 font-medium">名稱</th>
                <th class="pb-3 font-medium">Base URL</th>
                <th class="pb-3 font-medium">回報模式</th>
                <th class="pb-3 text-center font-medium">狀態</th>
                <th class="pb-3 text-center font-medium">操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-white/4">
              <tr v-if="isLoading" class="text-[#9ca3af] text-center">
                <td colspan="6" class="py-8">載入中...</td>
              </tr>
              <tr v-else-if="appRegistrations.length === 0" class="text-[#6b7280] text-center">
                <td colspan="6" class="py-8">尚無任何 App 登錄紀錄</td>
              </tr>
              <tr
                v-else
                v-for="app in appRegistrations"
                :key="app.app_id"
                class="hover:bg-white/1 transition-all"
              >
                <td class="py-4 font-mono font-semibold text-white">{{ app.app_id }}</td>
                <td class="py-4 text-xs">{{ app.display_name }}</td>
                <td class="py-4 text-[11px] font-mono max-w-[220px] truncate" :title="app.base_url">
                  {{ app.base_url }}
                </td>
                <td class="py-4 text-xs">
                  <span :class="app.report_mode === 'direct_db' ? 'text-sky-400' : 'text-[#9ca3af]'">
                    {{ app.report_mode }}
                  </span>
                </td>
                <td class="py-4 text-center">
                  <button
                    @click="toggleActive(app)"
                    :class="app.is_active
                      ? 'text-emerald-400 hover:bg-emerald-500/10'
                      : 'text-amber-400 hover:bg-amber-500/10'"
                    class="text-xs font-medium px-2.5 py-1 rounded-md transition-all"
                    :title="app.is_active ? '點擊停用' : '點擊啟用'"
                  >
                    {{ app.is_active ? '啟用中' : '已停用' }}
                  </button>
                </td>
                <td class="py-4 text-center whitespace-nowrap">
                  <button
                    @click="startEdit(app)"
                    class="text-purple-300 hover:text-purple-200 hover:underline text-xs mr-3"
                  >
                    編輯
                  </button>
                  <button
                    @click="handleDelete(app)"
                    class="text-rose-400 hover:text-rose-300 hover:underline text-xs"
                  >
                    刪除
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>
