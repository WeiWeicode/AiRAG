<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useParamsStore } from '../../stores/paramsStore'
import databaseIndexingService from '../../services/databaseIndexingService'
import aiDbQueryService from '../../services/aiDbQueryService'
import api from '../../services/api'

const paramsStore = useParamsStore()

const dbConfigs = ref([])
const selectedConfigId = ref('')
const knowledgeBases = ref([])

const loadKnowledgeBases = async () => {
  try {
    const response = await api.get('/api/knowledge-bases')
    knowledgeBases.value = response.data?.items || []
  } catch (error) {
    console.error('無法取得知識庫列表:', error)
  }
}

const currentKbName = computed(() => {
  const kb = knowledgeBases.value.find(k => k.id === paramsStore.knowledgeBaseId)
  return kb ? kb.name : (paramsStore.knowledgeBaseId || '（未選擇知識庫）')
})

const editingProfileId = ref('')
const profileName = ref('')
const platformDescription = ref('')
const tables = ref([])
const selectedTable = ref('')
const tablePurpose = ref('')
const columns = ref([]) // [{ column_name, enabled, meaning, max_length }]
const isDefault = ref(false) // 必定查詢：問題與任何設定檔都無明顯關聯時，仍會強制加入查詢

const isLoadingTables = ref(false)
const isLoadingColumns = ref(false)
const isSaving = ref(false)

const profiles = ref([])
const isLoadingProfiles = ref(false)

const loadDbConfigs = async () => {
  try {
    dbConfigs.value = await databaseIndexingService.getConfigs()
  } catch (error) {
    console.error('無法載入資料庫設定檔列表:', error)
  }
}

const loadProfiles = async () => {
  if (!paramsStore.knowledgeBaseId) {
    profiles.value = []
    return
  }
  isLoadingProfiles.value = true
  try {
    profiles.value = await aiDbQueryService.getProfiles(paramsStore.knowledgeBaseId)
  } catch (error) {
    console.error('無法載入查詢設定檔列表:', error)
  } finally {
    isLoadingProfiles.value = false
  }
}

const resetForm = () => {
  editingProfileId.value = ''
  profileName.value = ''
  platformDescription.value = ''
  selectedTable.value = ''
  tablePurpose.value = ''
  columns.value = []
  tables.value = []
  isDefault.value = false
}

const handleConfigChange = async () => {
  selectedTable.value = ''
  tablePurpose.value = ''
  columns.value = []
  tables.value = []
  if (!selectedConfigId.value) return

  isLoadingTables.value = true
  try {
    const res = await aiDbQueryService.listTables(selectedConfigId.value)
    tables.value = res.tables || []
  } catch (error) {
    alert(error.response?.data?.detail || '取得表格清單失敗')
  } finally {
    isLoadingTables.value = false
  }
}

const handleTableChange = async () => {
  columns.value = []
  if (!selectedConfigId.value || !selectedTable.value) return

  isLoadingColumns.value = true
  try {
    const res = await aiDbQueryService.listColumns(selectedConfigId.value, selectedTable.value)
    columns.value = (res.columns || []).map(col => ({
      column_name: col,
      enabled: true,
      meaning: col,
      max_length: null
    }))
  } catch (error) {
    alert(error.response?.data?.detail || '取得欄位清單失敗')
  } finally {
    isLoadingColumns.value = false
  }
}

const composedPreview = computed(() => {
  const config = dbConfigs.value.find(c => c.id === selectedConfigId.value)
  const kbName = currentKbName.value
  if (!config || !selectedTable.value) return '請先選取資料庫連線設定檔與表格以產生預覽。'

  const enabledCols = columns.value.filter(c => c.enabled)
  const colsText = enabledCols.length
    ? enabledCols.map(c => {
        let d = `${c.column_name}（${c.meaning || c.column_name}）`
        if (c.max_length) d += `（此欄位內容較長，查詢時超過 ${c.max_length} 字將自動截斷）`
        return d
      }).join('、')
    : '（未指定任何欄位）'

  return (
    `這是資料庫查詢的設定檔：${config.name} 平台，資料庫是 ${kbName}，` +
    `功能是${platformDescription.value || '（未提供描述）'}，` +
    `表單是 ${selectedTable.value}，功能是${tablePurpose.value || '（未提供描述）'}，` +
    `以下為欄位說明：${colsText}`
  )
})

const handleSaveProfile = async () => {
  if (!paramsStore.knowledgeBaseId) {
    alert('請先在右側選擇目標知識庫。')
    return
  }
  if (!profileName.value.trim()) {
    alert('請輸入查詢設定檔名稱。')
    return
  }
  if (!selectedConfigId.value || !selectedTable.value) {
    alert('請選取資料庫連線設定檔與表格。')
    return
  }

  isSaving.value = true
  try {
    const payload = {
      id: editingProfileId.value || undefined,
      name: profileName.value.trim(),
      database_config_id: selectedConfigId.value,
      knowledge_base_id: paramsStore.knowledgeBaseId,
      platform_description: platformDescription.value,
      table_name: selectedTable.value,
      table_purpose: tablePurpose.value,
      columns: columns.value.map(c => ({
        column_name: c.column_name,
        enabled: c.enabled,
        meaning: c.meaning,
        max_length: c.max_length ? Number(c.max_length) : null
      })),
      is_default: isDefault.value
    }
    await aiDbQueryService.saveProfile(payload)
    alert('查詢設定檔儲存成功')
    resetForm()
    await loadProfiles()
  } catch (error) {
    alert(error.response?.data?.detail || '儲存查詢設定檔失敗')
  } finally {
    isSaving.value = false
  }
}

const handleEditProfile = async (profile) => {
  editingProfileId.value = profile.id
  profileName.value = profile.name
  selectedConfigId.value = profile.database_config_id
  platformDescription.value = profile.platform_description
  tablePurpose.value = profile.table_purpose
  columns.value = (profile.columns || []).map(c => ({ ...c }))
  isDefault.value = !!profile.is_default

  isLoadingTables.value = true
  try {
    const res = await aiDbQueryService.listTables(selectedConfigId.value)
    tables.value = res.tables || []
  } catch (error) {
    tables.value = []
  } finally {
    isLoadingTables.value = false
  }
  selectedTable.value = profile.table_name
}

const handleDeleteProfile = async (profile) => {
  if (!confirm(`確定要刪除查詢設定檔「${profile.name}」嗎？`)) return
  try {
    await aiDbQueryService.deleteProfile(profile.id)
    await loadProfiles()
  } catch (error) {
    alert(error.response?.data?.detail || '刪除查詢設定檔失敗')
  }
}

watch(() => paramsStore.knowledgeBaseId, () => {
  loadProfiles()
})

onMounted(() => {
  loadDbConfigs()
  loadKnowledgeBases()
  loadProfiles()
})
</script>

<template>
  <div class="flex flex-col gap-5">
    <!-- Profile builder card -->
    <div class="bg-[#111827]/70 border border-white/8 rounded-2xl p-5 backdrop-blur-md flex flex-col gap-4">
      <div class="border-b border-white/5 pb-3">
        <span class="text-xs font-bold text-white tracking-wider">建立 / 編輯 AI 查詢設定檔</span>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div class="flex flex-col gap-1.5">
          <span class="text-[11px] text-[#9ca3af]">設定檔名稱</span>
          <input
            v-model="profileName"
            type="text"
            placeholder="例如: 知識庫文章查詢"
            class="bg-white/5 border border-white/8 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-[#8b5cf6]"
          />
        </div>

        <div class="flex flex-col gap-1.5">
          <span class="text-[11px] text-[#9ca3af]">選取資料庫連線設定檔（平台）</span>
          <select
            v-model="selectedConfigId"
            @change="handleConfigChange"
            class="bg-white/5 border border-white/8 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-[#8b5cf6] cursor-pointer"
          >
            <option value="" class="bg-[#111827]">-- 請選擇 --</option>
            <option v-for="c in dbConfigs" :key="c.id" :value="c.id" class="bg-[#111827]">
              {{ c.name }} ({{ c.db_type }})
            </option>
          </select>
        </div>

        <div class="flex flex-col gap-1.5 md:col-span-2">
          <span class="text-[11px] text-[#9ca3af]">平台/資料庫功能描述（自由輸入，例如：放置集團文章、知識庫文件）</span>
          <input
            v-model="platformDescription"
            type="text"
            placeholder="例如: 放置集團文章、知識庫文件"
            class="bg-white/5 border border-white/8 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-[#8b5cf6]"
          />
        </div>

        <div class="flex flex-col gap-1.5">
          <span class="text-[11px] text-[#9ca3af]">選取表格</span>
          <select
            v-model="selectedTable"
            @change="handleTableChange"
            :disabled="!selectedConfigId || isLoadingTables"
            class="bg-white/5 border border-white/8 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-[#8b5cf6] cursor-pointer disabled:opacity-40"
          >
            <option value="" class="bg-[#111827]">{{ isLoadingTables ? '載入中...' : '-- 請選擇 --' }}</option>
            <option v-for="t in tables" :key="t" :value="t" class="bg-[#111827]">{{ t }}</option>
          </select>
        </div>

        <div class="flex flex-col gap-1.5">
          <span class="text-[11px] text-[#9ca3af]">表單功能描述（例如：放置文章）</span>
          <input
            v-model="tablePurpose"
            type="text"
            placeholder="例如: 放置文章"
            class="bg-white/5 border border-white/8 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-[#8b5cf6]"
          />
        </div>

        <div class="flex flex-col gap-1.5 md:col-span-2">
          <label class="flex items-center gap-2 text-xs text-[#9ca3af] cursor-pointer">
            <input type="checkbox" v-model="isDefault" class="rounded bg-white/5 border-white/10 text-[#8b5cf6] cursor-pointer" />
            設為必定查詢設定檔（使用者問題與任何設定檔都無明顯關聯時，此設定檔仍會被強制加入查詢）
          </label>
        </div>
      </div>

      <!-- Columns mapper -->
      <div v-if="columns.length > 0" class="flex flex-col gap-2">
        <span class="text-xs font-semibold text-[#9ca3af]">欄位篩選與含意標註</span>
        <div class="overflow-x-auto w-full border border-white/5 rounded-xl">
          <table class="w-full text-left border-collapse text-xs">
            <thead>
              <tr class="bg-white/3 border-b border-white/8 text-[#9ca3af] font-semibold">
                <th class="p-3 w-16 text-center">啟用</th>
                <th class="p-3">欄位名稱</th>
                <th class="p-3">欄位意義</th>
                <th class="p-3 w-40">截斷長度（選填，供 nvarchar(max) 等大型欄位使用）</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-white/5">
              <tr v-for="col in columns" :key="col.column_name" class="hover:bg-white/1 transition-all">
                <td class="p-3 text-center">
                  <input type="checkbox" v-model="col.enabled" class="rounded bg-white/5 border-white/10 text-[#8b5cf6] cursor-pointer" />
                </td>
                <td class="p-3 font-mono text-white font-semibold">{{ col.column_name }}</td>
                <td class="p-3">
                  <input
                    v-model="col.meaning"
                    type="text"
                    :disabled="!col.enabled"
                    class="bg-white/5 border border-white/10 rounded px-2.5 py-1 text-xs text-white focus:outline-none focus:border-[#8b5cf6] disabled:opacity-40 w-full max-w-md"
                    placeholder="請輸入欄位意義描述"
                  />
                </td>
                <td class="p-3">
                  <input
                    v-model.number="col.max_length"
                    type="number"
                    :disabled="!col.enabled"
                    class="bg-white/5 border border-white/10 rounded px-2.5 py-1 text-xs text-white focus:outline-none focus:border-[#8b5cf6] disabled:opacity-40 w-full"
                    placeholder="預設值"
                  />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Preview -->
      <div class="flex flex-col gap-2 bg-[#111827]/40 border border-white/5 rounded-xl p-4">
        <span class="text-xs font-semibold text-[#9ca3af]">自動組合的自然語言描述預覽</span>
        <pre class="bg-black/20 border border-white/5 p-3 rounded text-[11px] text-[#a78bfa] overflow-x-auto whitespace-pre-wrap font-mono leading-relaxed max-h-48">{{ composedPreview }}</pre>
      </div>

      <div class="flex justify-end gap-3 border-t border-white/5 pt-4">
        <button
          v-if="editingProfileId"
          @click="resetForm"
          class="px-4 py-2 border border-white/8 hover:border-white/16 text-xs text-[#f3f4f6] font-semibold rounded-lg bg-white/5 transition-all"
        >
          取消編輯
        </button>
        <button
          @click="handleSaveProfile"
          :disabled="isSaving"
          class="px-6 py-2.5 bg-[#8b5cf6] hover:bg-[#a78bfa] text-xs text-white font-semibold rounded-lg transition-all"
        >
          {{ isSaving ? '儲存中...' : (editingProfileId ? '更新設定檔' : '儲存新設定檔') }}
        </button>
      </div>
    </div>

    <!-- Existing profiles list -->
    <div class="bg-[#111827]/70 border border-white/8 rounded-2xl p-5 backdrop-blur-md flex flex-col gap-3">
      <div class="border-b border-white/5 pb-3 flex justify-between items-center">
        <span class="text-xs font-bold text-white tracking-wider">目前知識庫的查詢設定檔清單</span>
        <span class="text-[11px] text-[#9ca3af]">{{ isLoadingProfiles ? '載入中...' : `共 ${profiles.length} 筆` }}</span>
      </div>
      <div v-if="!profiles.length" class="text-xs text-[#9ca3af] py-2">尚無查詢設定檔。</div>
      <div v-for="p in profiles" :key="p.id" class="flex justify-between items-center bg-white/3 border border-white/5 rounded-lg px-4 py-2.5">
        <div class="flex flex-col gap-0.5">
          <span class="text-xs font-semibold text-white flex items-center gap-1.5">
            {{ p.name }}
            <span v-if="p.is_default" class="text-[9px] bg-[#8b5cf6]/20 text-[#a78bfa] px-1.5 py-0.5 rounded font-normal">必定查詢</span>
          </span>
          <span class="text-[11px] text-[#9ca3af]">表格: {{ p.table_name }}｜{{ p.table_purpose }}</span>
        </div>
        <div class="flex gap-2">
          <button @click="handleEditProfile(p)" class="px-3 py-1.5 border border-white/8 hover:border-white/16 text-[11px] text-[#f3f4f6] rounded-lg bg-white/5 transition-all">編輯</button>
          <button @click="handleDeleteProfile(p)" class="px-3 py-1.5 border border-red-500/20 hover:border-red-500/40 text-[11px] text-red-300 rounded-lg bg-red-500/5 transition-all">刪除</button>
        </div>
      </div>
    </div>
  </div>
</template>
