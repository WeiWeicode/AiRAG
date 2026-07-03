<script setup>
import { ref, watch, computed, onMounted } from 'vue'
import { useParamsStore } from '../../stores/paramsStore'
import databaseIndexingService from '../../services/databaseIndexingService'
import DBQueryProfileManager from './DBQueryProfileManager.vue'

const paramsStore = useParamsStore()

// 子模式切換：① 將資料庫內容轉向量（既有功能，完全不動）／② AI 查詢設定檔（新增）
const activeMode = ref('vectorize')

// State
const dbConfigs = ref([])
const selectedConfigId = ref('')
const dbName = ref('')
const dbType = ref('sqlserver')
const dbHost = ref('127.0.0.1')
const dbPort = ref(1433)
const dbDatabase = ref('')
const dbUsername = ref('')
const dbPassword = ref('')
const dbSqlQuery = ref('SELECT TOP 10 * FROM articles')
const isTestingDbConn = ref(false)

const isFetchingDbMeta = ref(false)
const dbColumns = ref([])
const dbSampleRow = ref({})
const dbParsedTable = ref('')
const dbTableMeaning = ref('')
const dbColumnsConfig = ref({})

const dbIngestionMode = ref('natural_language')
const isDbIngesting = ref(false)
const dbIngestStats = ref(null)
const oneChunkPerRow = ref(true)

watch(dbType, (newType) => {
  if (newType === 'sqlserver') {
    dbPort.value = 1433
    if (dbSqlQuery.value.includes('ROWNUM')) {
      dbSqlQuery.value = 'SELECT TOP 10 * FROM articles'
    }
  } else if (newType === 'oracle') {
    dbPort.value = 1521
    if (dbSqlQuery.value.includes('TOP')) {
      dbSqlQuery.value = 'SELECT * FROM articles WHERE ROWNUM <= 10'
    }
  }
})

const loadDbConfigs = async () => {
  try {
    dbConfigs.value = await databaseIndexingService.getConfigs()
  } catch (error) {
    console.error('無法載入資料庫設定檔列表:', error)
  }
}

const handleDbConfigChange = () => {
  if (!selectedConfigId.value) {
    dbName.value = ''
    dbType.value = 'sqlserver'
    dbHost.value = '127.0.0.1'
    dbPort.value = 1433
    dbDatabase.value = ''
    dbUsername.value = ''
    dbPassword.value = ''
    return
  }
  const config = dbConfigs.value.find(c => c.id === selectedConfigId.value)
  if (config) {
    dbName.value = config.name
    dbType.value = config.db_type
    dbHost.value = config.host
    dbPort.value = config.port
    dbDatabase.value = config.database
    dbUsername.value = config.username
    dbPassword.value = config.password
  }
}

const handleSaveDbConfig = async () => {
  const nameVal = dbName.value.trim()
  if (!nameVal) {
    alert('請輸入設定檔名稱')
    return
  }
  try {
    const payload = {
      id: selectedConfigId.value || undefined,
      name: nameVal,
      db_type: dbType.value,
      host: dbHost.value ? dbHost.value.trim() : '',
      port: Number(dbPort.value),
      database: dbDatabase.value ? dbDatabase.value.trim() : '',
      username: dbUsername.value ? dbUsername.value.trim() : '',
      password: dbPassword.value
    }
    const saved = await databaseIndexingService.saveConfig(payload)
    alert('設定檔儲存成功')
    await loadDbConfigs()
    selectedConfigId.value = saved.id
  } catch (error) {
    alert(error.response?.data?.detail || '儲存設定檔失敗')
  }
}

const handleDeleteDbConfig = async () => {
  if (!selectedConfigId.value) return
  if (!confirm('確定要永久刪除此設定檔嗎？')) return
  try {
    await databaseIndexingService.deleteConfig(selectedConfigId.value)
    alert('設定檔已刪除')
    selectedConfigId.value = ''
    handleDbConfigChange()
    await loadDbConfigs()
  } catch (error) {
    alert(error.response?.data?.detail || '刪除設定檔失敗')
  }
}

const handleTestDbConnection = async () => {
  isTestingDbConn.value = true
  try {
    const payload = {
      db_type: dbType.value,
      host: dbHost.value ? dbHost.value.trim() : '',
      port: Number(dbPort.value),
      database: dbDatabase.value ? dbDatabase.value.trim() : '',
      username: dbUsername.value ? dbUsername.value.trim() : '',
      password: dbPassword.value
    }
    await databaseIndexingService.testConnection(payload)
    alert('資料庫連線測試成功！')
  } catch (error) {
    alert(error.response?.data?.detail || '連線測試失敗，請檢查網路、IP/Port 與帳密')
  } finally {
    isTestingDbConn.value = false
  }
}

const validateSqlBeforeSend = (sql) => {
  const q = sql.trim().toUpperCase()
  if (!q.startsWith('SELECT') && !q.startsWith('WITH')) {
    alert('前端校驗失敗：僅允許執行 SELECT 或 WITH 開頭的唯讀查詢語句。')
    return false
  }
  const forbidden = ['INSERT', 'UPDATE', 'DELETE', 'DROP', 'ALTER', 'CREATE', 'TRUNCATE', 'RENAME', 'MERGE', 'EXEC', 'EXECUTE']
  for (const kw of forbidden) {
    const regex = new RegExp('\\b' + kw + '\\b')
    if (regex.test(q)) {
      alert(`前端校驗失敗：檢測到不允許使用的寫入或敏感關鍵字 "${kw}"。`)
      return false
    }
  }
  return true
}

const handleFetchDbMetadata = async () => {
  if (!dbSqlQuery.value.trim()) {
    alert('請輸入 SQL 語法。')
    return
  }
  if (!validateSqlBeforeSend(dbSqlQuery.value)) {
    return
  }
  
  isFetchingDbMeta.value = true
  dbColumns.value = []
  dbSampleRow.value = {}
  dbParsedTable.value = ''
  dbTableMeaning.value = ''
  dbColumnsConfig.value = {}
  
  try {
    const payload = {
      sql_query: dbSqlQuery.value,
      connection: {
        db_type: dbType.value,
        host: dbHost.value,
        port: Number(dbPort.value),
        database: dbDatabase.value,
        username: dbUsername.value,
        password: dbPassword.value
      }
    }
    const res = await databaseIndexingService.fetchMetadata(payload)
    dbColumns.value = res.columns || []
    dbSampleRow.value = res.sample_row || {}
    dbParsedTable.value = res.table_name || 'TABLE'
    
    const configMap = {}
    dbColumns.value.forEach(col => {
      configMap[col] = {
        enabled: true,
        meaning: col
      }
    })
    dbColumnsConfig.value = configMap
  } catch (error) {
    alert(error.response?.data?.detail || '取得中介資料與樣品資料失敗，請檢查資料庫連線或 SQL 語句')
  } finally {
    isFetchingDbMeta.value = false
  }
}

const dbPreviewText = computed(() => {
  if (!dbColumns.value.length || !dbColumnsConfig.value) return '無預覽資料。請先分析 SQL 以獲取資料結構'
  
  if (dbIngestionMode.value === 'json') {
    const filteredRow = { tableName: dbParsedTable.value }
    dbColumns.value.forEach(col => {
      const cfg = dbColumnsConfig.value[col]
      if (cfg && cfg.enabled) {
        filteredRow[col] = dbSampleRow.value[col] !== undefined ? dbSampleRow.value[col] : null
      }
    })
    return JSON.stringify(filteredRow, null, 2)
  } else {
    const tableMeaning = dbTableMeaning.value.trim() || '通用資料'
    const tableName = dbParsedTable.value || 'TABLE'
    
    const isValEmpty = (val) => {
      if (val === undefined || val === null) return true
      const s = String(val).trim()
      return s === '' || s.toLowerCase() === 'null' || s.toLowerCase() === 'none'
    }

    const nonEmptyParts = []
    const emptyCols = []

    dbColumns.value.forEach(col => {
      const cfg = dbColumnsConfig.value[col]
      if (cfg && cfg.enabled) {
        const val = dbSampleRow.value[col]
        const meaning = (cfg.meaning || '').trim()
        const hasCustomMeaning = meaning && meaning !== col

        if (isValEmpty(val)) {
          if (hasCustomMeaning) {
            if (meaning.includes('為') || meaning.includes('是')) {
              nonEmptyParts.push(`${meaning}（${col}=空值）`)
            } else {
              nonEmptyParts.push(`${meaning}（${col}）為空值`)
            }
          } else {
            emptyCols.push(col)
          }
        } else {
          if (!hasCustomMeaning) {
            nonEmptyParts.push(`${col}為「${val}」`)
          } else if (meaning.includes('為') || meaning.includes('是')) {
            nonEmptyParts.push(`${meaning}（${col}=${val}）`)
          } else {
            nonEmptyParts.push(`${meaning}（${col}）為「${val}」`)
          }
        }
      }
    })

    const header = `這是 ERP 的${tableMeaning}表單（${tableName}）。`
    let body = ''
    if (nonEmptyParts.length > 0) {
      body = `此筆資料的${nonEmptyParts.join('；')}`
    }

    let text = header
    if (body) {
      text += body
      if (emptyCols.length > 0) {
        text += `，${emptyCols.map(c => `(${c})`).join('、')}皆為空值，未做描述。`
      } else {
        text += '。'
      }
    } else {
      if (emptyCols.length > 0) {
        text = text.slice(0, -1) + `，其中${emptyCols.map(c => `(${c})`).join('、')}皆為空值，未做描述。`
      }
    }

    return text
  }
})

const handleDbIngestion = async () => {
  if (!paramsStore.knowledgeBaseId) {
    alert('請先在右側選擇目標知識庫。')
    return
  }
  if (!dbColumns.value.length) {
    alert('請先點擊「分析 SQL 與取得樣品資料」進行解析配置後，才能匯入。')
    return
  }
  
  isDbIngesting.value = true
  dbIngestStats.value = null
  
  try {
    const payload = {
      sql_query: dbSqlQuery.value,
      connection: {
        db_type: dbType.value,
        host: dbHost.value,
        port: Number(dbPort.value),
        database: dbDatabase.value,
        username: dbUsername.value,
        password: dbPassword.value
      },
      ingestion_mode: dbIngestionMode.value,
      table_meaning: dbTableMeaning.value,
      columns_config: dbColumnsConfig.value,
      knowledge_base_id: paramsStore.knowledgeBaseId,
      one_chunk_per_row: oneChunkPerRow.value
    }
    
    const res = await databaseIndexingService.ingest(payload)
    dbIngestStats.value = {
      kbId: res.knowledge_base_id || paramsStore.knowledgeBaseId,
      insertedCount: res.inserted_count || 0,
      filename: res.filename,
      elapsedMs: res.elapsed_ms || 0
    }
    
    alert(`匯入成功！共寫入 ${res.inserted_count} 筆向量段落。`)
  } catch (error) {
    alert(error.response?.data?.detail || '匯入向量庫失敗，請檢查後端連線')
  } finally {
    isDbIngesting.value = false
  }
}

onMounted(() => {
  loadDbConfigs()
})
</script>

<template>
  <div class="flex flex-col gap-5">
    <!-- 子模式切換 -->
    <div class="flex gap-2 bg-white/3 border border-white/8 rounded-xl p-1.5 w-fit">
      <button
        @click="activeMode = 'vectorize'"
        class="px-4 py-2 text-xs font-semibold rounded-lg transition-all"
        :class="activeMode === 'vectorize' ? 'bg-[#8b5cf6] text-white' : 'text-[#9ca3af] hover:text-white'"
      >
        ① 將資料庫內容轉向量
      </button>
      <button
        @click="activeMode = 'profile'"
        class="px-4 py-2 text-xs font-semibold rounded-lg transition-all"
        :class="activeMode === 'profile' ? 'bg-[#8b5cf6] text-white' : 'text-[#9ca3af] hover:text-white'"
      >
        ② AI 查詢設定檔
      </button>
    </div>

    <DBQueryProfileManager v-if="activeMode === 'profile'" />

    <template v-else>
    <!-- Connection Settings Card -->
    <div class="bg-[#111827]/70 border border-white/8 rounded-2xl p-5 backdrop-blur-md flex flex-col gap-4">
      <div class="flex justify-between items-center border-b border-white/5 pb-3">
        <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">1. 資料庫連線設定</label>
        <div class="flex items-center gap-2">
          <span class="text-xs text-[#9ca3af]">快速載入設定檔:</span>
          <select 
            v-model="selectedConfigId" 
            @change="handleDbConfigChange"
            class="bg-white/5 border border-white/10 rounded px-2.5 py-1 text-xs text-white focus:outline-none focus:border-[#8b5cf6] cursor-pointer"
          >
            <option value="" class="bg-[#111827] text-[#9ca3af]">-- 新增自訂設定 --</option>
            <option v-for="c in dbConfigs" :key="c.id" :value="c.id" class="bg-[#111827] text-white">
              {{ c.name }} ({{ c.db_type }})
            </option>
          </select>
        </div>
      </div>
      
      <!-- Config details form -->
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <!-- Config Name -->
        <div class="flex flex-col gap-1.5">
          <span class="text-[11px] text-[#9ca3af]">設定檔顯示名稱</span>
          <input 
            v-model="dbName"
            type="text"
            placeholder="例如: ERP_Oracle_Prod"
            class="bg-white/5 border border-white/8 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-[#8b5cf6] transition-all"
          />
        </div>
        
        <!-- DB Type -->
        <div class="flex flex-col gap-1.5">
          <span class="text-[11px] text-[#9ca3af]">資料庫類型</span>
          <select 
            v-model="dbType"
            class="bg-white/5 border border-white/8 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-[#8b5cf6] cursor-pointer transition-all"
          >
            <option value="sqlserver" class="bg-[#111827]">Microsoft SQL Server</option>
            <option value="oracle" class="bg-[#111827]">Oracle Database</option>
          </select>
        </div>

        <!-- Host/IP -->
        <div class="flex flex-col gap-1.5">
          <span class="text-[11px] text-[#9ca3af]">伺服器 IP / 主機名</span>
          <input 
            v-model="dbHost"
            type="text"
            placeholder="127.0.0.1"
            class="bg-white/5 border border-white/8 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-[#8b5cf6] transition-all"
          />
        </div>

        <!-- Port -->
        <div class="flex flex-col gap-1.5">
          <span class="text-[11px] text-[#9ca3af]">連接埠 (Port)</span>
          <input 
            v-model.number="dbPort"
            type="number"
            placeholder="1433"
            class="bg-white/5 border border-white/8 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-[#8b5cf6] transition-all font-mono"
          />
        </div>

        <!-- Database Name -->
        <div class="flex flex-col gap-1.5">
          <span class="text-[11px] text-[#9ca3af]">{{ dbType === 'oracle' ? '服務名稱 / SID (Service Name)' : '資料庫名稱 (Database)' }}</span>
          <input 
            v-model="dbDatabase"
            type="text"
            placeholder="例如: airag_db"
            class="bg-white/5 border border-white/8 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-[#8b5cf6] transition-all"
          />
        </div>

        <!-- Username -->
        <div class="flex flex-col gap-1.5">
          <span class="text-[11px] text-[#9ca3af]">帳號 (Username)</span>
          <input 
            v-model="dbUsername"
            type="text"
            placeholder="sa"
            class="bg-white/5 border border-white/8 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-[#8b5cf6] transition-all"
          />
        </div>

        <!-- Password -->
        <div class="flex flex-col gap-1.5">
          <span class="text-[11px] text-[#9ca3af]">密碼 (Password)</span>
          <input 
            v-model="dbPassword"
            type="password"
            placeholder="••••••••"
            class="bg-white/5 border border-white/8 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-[#8b5cf6] transition-all"
          />
        </div>
      </div>

      <!-- Action buttons for connection -->
      <div class="flex gap-3 justify-end border-t border-white/5 pt-3.5 mt-1">
        <button 
          @click="handleDeleteDbConfig"
          v-if="selectedConfigId"
          class="px-4 py-2 border border-red-500/20 hover:border-red-500/40 text-xs text-red-300 font-semibold rounded-lg bg-red-500/5 hover:bg-red-500/10 transition-all"
        >
          刪除此設定檔
        </button>
        <button 
          @click="handleSaveDbConfig"
          :disabled="!dbName"
          class="px-4 py-2 border border-white/8 hover:border-white/16 text-xs text-[#f3f4f6] font-semibold rounded-lg bg-white/5 transition-all disabled:opacity-50"
        >
          儲存目前設定檔
        </button>
        <button 
          @click="handleTestDbConnection"
          :disabled="isTestingDbConn"
          class="px-4 py-2 bg-[#8b5cf6] hover:bg-[#a78bfa] text-xs text-white font-semibold rounded-lg transition-all flex items-center gap-1.5"
        >
          <svg v-if="isTestingDbConn" class="animate-spin h-3 w-3 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
          {{ isTestingDbConn ? '測試連線中...' : '測試資料庫連線' }}
        </button>
      </div>
    </div>

    <!-- SQL Settings & Field Mapping Card -->
    <div class="bg-[#111827]/70 border border-white/8 rounded-2xl p-5 backdrop-blur-md flex flex-col gap-4">
      <div class="flex flex-col gap-1.5">
        <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">2. 自訂 SQL 查詢語句 (唯讀 Select/With 語法，防止 SQL 注入)</label>
        <textarea 
          v-model="dbSqlQuery"
          rows="4"
          class="bg-white/5 border border-white/8 rounded-lg text-white p-3 text-xs focus:outline-none focus:border-[#8b5cf6] resize-y font-mono"
          placeholder="例如: SELECT TOP 10 * FROM orders WHERE status = 'COMPLETED'"
        ></textarea>
      </div>

      <div class="flex justify-end mt-1">
        <button 
          @click="handleFetchDbMetadata"
          :disabled="isFetchingDbMeta || !dbSqlQuery.trim()"
          class="px-5 py-2.5 bg-[#8b5cf6] hover:bg-[#a78bfa] text-xs text-white font-semibold rounded-lg transition-all flex items-center gap-1.5"
        >
          <svg v-if="isFetchingDbMeta" class="animate-spin h-3.5 w-3.5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
          分析 SQL 與取得樣品資料
        </button>
      </div>
    </div>

    <!-- Metadata configuration area -->
    <div v-if="dbColumns.length > 0" class="bg-[#111827]/70 border border-white/8 rounded-2xl p-5 backdrop-blur-md flex flex-col gap-5 animate-fade-in">
      <div class="border-b border-white/5 pb-3">
        <span class="text-xs font-bold text-white tracking-wider">3. 向量轉換與欄位中文對應配置</span>
      </div>

      <!-- General Ingestion Settings -->
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4 border-b border-white/5 pb-4">
        <div class="flex flex-col gap-1.5">
          <span class="text-[11px] text-[#9ca3af]">向量匯入格式模式 (Ingestion Mode)</span>
          <select 
            v-model="dbIngestionMode"
            class="bg-white/5 border border-white/8 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-[#8b5cf6] cursor-pointer"
          >
            <option value="natural_language" class="bg-[#111827] text-white">自然語言敘述模式 (Natural Language Description)</option>
            <option value="json" class="bg-[#111827] text-white">JSON 鍵值結構化模式 (Structured JSON)</option>
          </select>
        </div>

        <div class="flex flex-col gap-1.5" v-if="dbIngestionMode === 'natural_language'">
          <span class="text-[11px] text-[#9ca3af]">ERP 表單/資料的主體意義描述 (e.g. 採購、銷貨)</span>
          <input 
            v-model="dbTableMeaning"
            type="text"
            placeholder="例如: 採購"
            class="bg-white/5 border border-white/8 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-[#8b5cf6]"
          />
        </div>
      </div>

      <!-- Columns mapper table -->
      <div class="flex flex-col gap-2">
        <span class="text-xs font-semibold text-[#9ca3af]">欄位篩選與含意標註</span>
        <div class="overflow-x-auto w-full border border-white/5 rounded-xl">
          <table class="w-full text-left border-collapse text-xs">
            <thead>
              <tr class="bg-white/3 border-b border-white/8 text-[#9ca3af] font-semibold">
                <th class="p-3 w-16 text-center">啟用</th>
                <th class="p-3">資料庫欄位名稱</th>
                <th class="p-3">欄位範例值</th>
                <th class="p-3" v-if="dbIngestionMode === 'natural_language'">欄位中文意義描述</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-white/5">
              <tr v-for="col in dbColumns" :key="col" class="hover:bg-white/1 transition-all">
                <!-- Enabled checkbox -->
                <td class="p-3 text-center">
                  <input 
                    type="checkbox" 
                    v-model="dbColumnsConfig[col].enabled"
                    class="rounded bg-white/5 border-white/10 text-[#8b5cf6] focus:ring-[#8b5cf6]/50 cursor-pointer"
                  />
                </td>
                
                <!-- Column Name -->
                <td class="p-3 font-mono text-white font-semibold">
                  {{ col }}
                </td>

                <!-- Sample value -->
                <td class="p-3 text-[#9ca3af] truncate max-w-[200px]" :title="dbSampleRow[col]">
                  {{ dbSampleRow[col] !== undefined ? dbSampleRow[col] : 'NULL' }}
                </td>

                <!-- Column meaning (NL only) -->
                <td class="p-3" v-if="dbIngestionMode === 'natural_language'">
                  <input 
                    v-model="dbColumnsConfig[col].meaning"
                    type="text"
                    :disabled="!dbColumnsConfig[col].enabled"
                    class="bg-white/5 border border-white/10 rounded px-2.5 py-1 text-xs text-white focus:outline-none focus:border-[#8b5cf6] disabled:opacity-40 disabled:cursor-not-allowed w-full max-w-md"
                    placeholder="請輸入欄位的中文意義描述"
                  />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Preview card -->
      <div class="flex flex-col gap-2 bg-[#111827]/40 border border-white/5 rounded-xl p-4">
        <span class="text-xs font-semibold text-[#9ca3af]">單筆資料轉換向量預覽 (Sample Preview)</span>
        <pre class="bg-black/20 border border-white/5 p-3 rounded text-[11px] text-[#a78bfa] overflow-x-auto whitespace-pre-wrap font-mono leading-relaxed max-h-48">{{ dbPreviewText }}</pre>
      </div>

      <!-- Action Area -->
      <div class="flex justify-between items-center border-t border-white/5 pt-4">
        <label class="flex items-center gap-2 text-xs text-[#9ca3af] cursor-pointer">
          <input 
            type="checkbox" 
            v-model="oneChunkPerRow"
            class="rounded bg-white/5 border-white/10 text-[#8b5cf6] focus:ring-[#8b5cf6]/50 cursor-pointer"
          />
          每筆資料列獨立存成一個向量 (One Chunk per Row)
        </label>
        
        <button 
          @click="handleDbIngestion"
          :disabled="isDbIngesting || !dbColumns.length"
          class="px-6 py-2.5 bg-[#8b5cf6] hover:bg-[#a78bfa] hover:shadow-[0_4px_12px_rgba(139,92,246,0.3)] disabled:bg-purple-900/50 disabled:text-purple-300/50 text-xs text-white font-semibold rounded-lg transition-all flex items-center gap-2"
        >
          <svg v-if="isDbIngesting" class="animate-spin h-3.5 w-3.5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
          {{ isDbIngesting ? '匯入處理中...' : '開始批次匯入向量庫' }}
        </button>
      </div>

      <!-- Ingestion result stats -->
      <div 
        v-if="dbIngestStats" 
        class="bg-emerald-500/10 border border-emerald-500/20 rounded-2xl p-5 flex flex-col gap-2.5 animate-fade-in"
      >
        <div class="text-xs font-bold text-[#10b981] flex items-center gap-1.5">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="20 6 9 17 4 12"></polyline>
          </svg>
          資料庫向量匯入成功
        </div>
        <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 text-[10px] text-[#9ca3af] mt-1 pt-1.5 border-t border-emerald-500/10">
          <span>目標知識庫: <strong class="text-white">{{ dbIngestStats.kbId }}</strong></span>
          <span>寫入向量數: <strong class="text-white">{{ dbIngestStats.insertedCount }} Chunks</strong></span>
          <span>產出虛擬檔名: <strong class="text-white font-mono">{{ dbIngestStats.filename }}</strong></span>
          <span>匯入總耗時: <strong class="text-white font-display">{{ dbIngestStats.elapsedMs }} ms</strong></span>
        </div>
      </div>
    </div>
    </template>
  </div>
</template>

<style scoped>
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}
.animate-fade-in {
  animation: fadeIn 0.35s cubic-bezier(0.4, 0, 0.2, 1);
}
</style>
