<script setup>
import { ref, onMounted } from 'vue'
import userService from '../services/userService'
import externalApiKeyService from '../services/externalApiKeyService'

// Departments state
const departments = ref([])
const newDeptName = ref('')
const newDeptCode = ref('')
const isAddingDept = ref(false)
const deptError = ref('')
const deptSuccess = ref('')

// External API Keys state
const apiKeys = ref([])
const newApiKeyName = ref('')
const isAddingApiKey = ref(false)
const apiKeyError = ref('')
const newlyCreatedKey = ref('')

// User Roster state
const users = ref([])
const newUserName = ref('')
const selectedDept = ref('')
const selectedJobTitle = ref('一般人員')
const customLevel = ref(10)
const isAddingUser = ref(false)
const userError = ref('')
const userSuccess = ref('')

const jobTitleOptions = [
  { label: '一般人員 (等級 10)', value: '一般人員' },
  { label: '組長 (等級 8)', value: '組長' },
  { label: '課長 (等級 7)', value: '課長' },
  { label: '經理 (等級 6)', value: '經理' },
  { label: '總經理 (等級 4)', value: '總經理' },
  { label: '自訂 (手動輸入 1~10)', value: '自訂' },
]

const loadDepartments = async () => {
  try {
    const res = await userService.getDepartments()
    departments.value = res.data || []
    if (departments.value.length > 0 && !selectedDept.value) {
      selectedDept.value = departments.value[0].name
    }
  } catch (err) {
    console.error('無法載入部門清單:', err)
  }
}

const loadUsers = async () => {
  try {
    const res = await userService.listUsers()
    users.value = res.data || []
  } catch (err) {
    console.error('無法載入使用者名冊:', err)
  }
}

const handleAddDepartment = async () => {
  deptError.value = ''
  deptSuccess.value = ''
  if (!newDeptName.value.trim()) {
    deptError.value = '請輸入部門名稱'
    return
  }
  if (!newDeptCode.value.trim()) {
    deptError.value = '請輸入部門代號'
    return
  }
  isAddingDept.value = true
  try {
    await userService.createDepartment(newDeptName.value.trim(), newDeptCode.value.trim())
    deptSuccess.value = `成功新增部門「${newDeptName.value.trim()}」`
    newDeptName.value = ''
    newDeptCode.value = ''
    await loadDepartments()
  } catch (err) {
    deptError.value = err.response?.data?.detail || '新增部門失敗'
  } finally {
    isAddingDept.value = false
  }
}

const handleDeleteDepartment = async (deptId, deptName) => {
  if (!confirm(`確定要刪除部門「${deptName}」嗎？`)) return
  deptError.value = ''
  deptSuccess.value = ''
  try {
    await userService.deleteDepartment(deptId)
    deptSuccess.value = `成功刪除部門「${deptName}」`
    await loadDepartments()
  } catch (err) {
    console.error('刪除部門失敗:', err)
    deptError.value = err.response?.data?.detail || '刪除部門失敗'
  }
}

const handleAddUser = async () => {
  userError.value = ''
  userSuccess.value = ''
  if (!newUserName.value.trim()) {
    userError.value = '請輸入使用者姓名'
    return
  }
  if (!selectedDept.value) {
    userError.value = '請先建立並選擇所屬部門'
    return
  }
  if (selectedJobTitle.value === '自訂' && (customLevel.value < 1 || customLevel.value > 10)) {
    userError.value = '自訂等級必須介於 1 至 10'
    return
  }

  isAddingUser.value = true
  try {
    const payload = {
      name: newUserName.value.trim(),
      department: selectedDept.value,
      job_title: selectedJobTitle.value,
      level: selectedJobTitle.value === '自訂' ? customLevel.value : 10
    }
    await userService.createUser(payload)
    userSuccess.value = `成功新增使用者「${newUserName.value.trim()}」`
    newUserName.value = ''
    await loadUsers()
  } catch (err) {
    userError.value = err.response?.data?.detail || '新增使用者失敗'
  } finally {
    isAddingUser.value = false
  }
}

const handleDeleteUser = async (userId, userName) => {
  if (!confirm(`確定要刪除使用者「${userName}」嗎？`)) return
  try {
    await userService.deleteUser(userId)
    await loadUsers()
  } catch (err) {
    console.error('刪除使用者失敗:', err)
  }
}

const loadApiKeys = async () => {
  try {
    const res = await externalApiKeyService.list()
    apiKeys.value = res.data || []
  } catch (err) {
    console.error('無法載入外部 API 金鑰清單:', err)
  }
}

const handleAddApiKey = async () => {
  apiKeyError.value = ''
  newlyCreatedKey.value = ''
  if (!newApiKeyName.value.trim()) {
    apiKeyError.value = '請輸入金鑰用途名稱'
    return
  }
  isAddingApiKey.value = true
  try {
    const res = await externalApiKeyService.create(newApiKeyName.value.trim())
    newlyCreatedKey.value = res.data.api_key
    newApiKeyName.value = ''
    await loadApiKeys()
  } catch (err) {
    apiKeyError.value = err.response?.data?.detail || '建立金鑰失敗'
  } finally {
    isAddingApiKey.value = false
  }
}

const handleDeleteApiKey = async (keyId, keyName) => {
  if (!confirm(`確定要刪除金鑰「${keyName}」嗎？刪除後該金鑰立即失效。`)) return
  try {
    await externalApiKeyService.remove(keyId)
    await loadApiKeys()
  } catch (err) {
    console.error('刪除金鑰失敗:', err)
  }
}

onMounted(() => {
  loadDepartments()
  loadUsers()
  loadApiKeys()
})
</script>

<template>
  <div class="flex-grow overflow-y-auto p-8 flex flex-col gap-8 h-full">
    <!-- Header banner -->
    <div class="bg-[#111827]/70 border border-white/8 rounded-2xl p-5 backdrop-blur-md flex justify-between items-center flex-shrink-0">
      <div>
        <h2 class="text-lg font-bold text-white tracking-wide">角色與權限設定 (Role & Access Control)</h2>
        <p class="text-xs text-white/50 mt-0.5">管理測試環境的部門主檔與模擬使用者名冊</p>
      </div>
    </div>

    <!-- Panel 1: 部門管理 -->
        <section class="bg-[#111827]/70 border border-white/8 rounded-2xl p-6 backdrop-blur-xl shadow-xl">
          <div class="flex items-center justify-between mb-4 pb-3 border-b border-white/8">
            <div>
              <h3 class="text-lg font-bold text-white flex items-center gap-2">
                <span class="w-2 h-2 rounded-full bg-purple-500"></span>
                部門主檔管理
              </h3>
              <p class="text-xs text-white/50 mt-0.5">用於文件與使用者權限比對（未設定表示不限部門）</p>
            </div>
          </div>

          <!-- Alert Messages -->
          <div v-if="deptError" class="mb-4 p-3 bg-red-500/10 border border-red-500/30 rounded-xl text-red-400 text-xs flex items-center gap-2">
            <span>⚠️</span> {{ deptError }}
          </div>
          <div v-if="deptSuccess" class="mb-4 p-3 bg-emerald-500/10 border border-emerald-500/30 rounded-xl text-emerald-400 text-xs flex items-center gap-2">
            <span>✅</span> {{ deptSuccess }}
          </div>

          <!-- Add Form -->
          <div class="flex gap-3 mb-6">
            <input
              v-model="newDeptName"
              type="text"
              placeholder="輸入新部門名稱 (例如：研發部、人資部)"
              class="flex-1 bg-[#1f2937]/60 border border-white/10 rounded-xl px-4 py-2.5 text-sm text-white placeholder-white/30 focus:outline-none focus:border-purple-500/50 transition-colors"
              @keyup.enter="handleAddDepartment"
            />
            <input
              v-model="newDeptCode"
              type="text"
              placeholder="部門代號 (例如：RD、HR)"
              class="w-48 bg-[#1f2937]/60 border border-white/10 rounded-xl px-4 py-2.5 text-sm text-white placeholder-white/30 focus:outline-none focus:border-purple-500/50 transition-colors"
              @keyup.enter="handleAddDepartment"
            />
            <button
              @click="handleAddDepartment"
              :disabled="isAddingDept"
              class="bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white font-medium px-5 py-2.5 rounded-xl text-sm transition-all shadow-lg shadow-purple-600/20 disabled:opacity-50"
            >
              {{ isAddingDept ? '處理中...' : '新增部門' }}
            </button>
          </div>

          <!-- Department Chips -->
          <div class="flex flex-wrap gap-2.5">
            <div v-if="departments.length === 0" class="text-xs text-white/40 py-2">
              目前尚無部門資料，請新增部門。
            </div>
            <div
              v-for="dept in departments"
              :key="dept.id"
              class="flex items-center gap-2 px-3.5 py-1.5 bg-white/5 border border-white/10 rounded-xl text-xs text-white/80 hover:border-purple-500/40 transition-colors"
            >
              <span>🏢 {{ dept.name }} <span class="text-white/40 font-mono">({{ dept.code || '未設定代號' }})</span></span>
              <button
                @click="handleDeleteDepartment(dept.id, dept.name)"
                class="text-white/40 hover:text-red-400 font-bold ml-1 transition-colors"
                title="刪除部門"
              >
                ✕
              </button>
            </div>
          </div>
        </section>

        <!-- Panel 2: 模擬使用者名冊管理 -->
        <section class="bg-[#111827]/70 border border-white/8 rounded-2xl p-6 backdrop-blur-xl shadow-xl">
          <div class="flex items-center justify-between mb-4 pb-3 border-b border-white/8">
            <div>
              <h3 class="text-lg font-bold text-white flex items-center gap-2">
                <span class="w-2 h-2 rounded-full bg-blue-500"></span>
                模擬使用者名冊 (Simulated User Roster)
              </h3>
              <p class="text-xs text-white/50 mt-0.5">供測試頁面（RAG / 向量搜尋）套用身分驗證權限隔離效果，非登入帳號</p>
            </div>
          </div>

          <!-- Alert Messages -->
          <div v-if="userError" class="mb-4 p-3 bg-red-500/10 border border-red-500/30 rounded-xl text-red-400 text-xs flex items-center gap-2">
            <span>⚠️</span> {{ userError }}
          </div>
          <div v-if="userSuccess" class="mb-4 p-3 bg-emerald-500/10 border border-emerald-500/30 rounded-xl text-emerald-400 text-xs flex items-center gap-2">
            <span>✅</span> {{ userSuccess }}
          </div>

          <!-- Add User Form -->
          <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6 bg-white/3 p-4 rounded-xl border border-white/5">
            <div>
              <label class="block text-xs font-medium text-white/60 mb-1.5">姓名</label>
              <input
                v-model="newUserName"
                type="text"
                placeholder="例如：王小明"
                class="w-full bg-[#1f2937]/60 border border-white/10 rounded-xl px-3.5 py-2 text-xs text-white focus:outline-none focus:border-blue-500/50"
              />
            </div>

            <div>
              <label class="block text-xs font-medium text-white/60 mb-1.5">所屬部門</label>
              <select
                v-model="selectedDept"
                class="w-full bg-[#1f2937] border border-white/10 rounded-xl px-3.5 py-2 text-xs text-white focus:outline-none focus:border-blue-500/50"
              >
                <option v-if="departments.length === 0" value="">-- 請先建立部門 --</option>
                <option v-for="d in departments" :key="d.id" :value="d.name">{{ d.name }}</option>
              </select>
            </div>

            <div>
              <label class="block text-xs font-medium text-white/60 mb-1.5">職級標籤</label>
              <select
                v-model="selectedJobTitle"
                class="w-full bg-[#1f2937] border border-white/10 rounded-xl px-3.5 py-2 text-xs text-white focus:outline-none focus:border-blue-500/50"
              >
                <option v-for="opt in jobTitleOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
              </select>
            </div>

            <div>
              <label class="block text-xs font-medium text-white/60 mb-1.5">
                {{ selectedJobTitle === '自訂' ? '機密等級 (1~10)' : '判定等級 (自動帶入)' }}
              </label>
              <div class="flex gap-2">
                <input
                  v-if="selectedJobTitle === '自訂'"
                  v-model.number="customLevel"
                  type="number"
                  min="1"
                  max="10"
                  class="w-full bg-[#1f2937]/60 border border-white/10 rounded-xl px-3.5 py-2 text-xs text-white focus:outline-none focus:border-blue-500/50"
                />
                <button
                  @click="handleAddUser"
                  :disabled="isAddingUser"
                  class="w-full bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white font-medium px-4 py-2 rounded-xl text-xs transition-all shadow-lg shadow-blue-600/20 disabled:opacity-50"
                >
                  {{ isAddingUser ? '新增中...' : '新增使用者' }}
                </button>
              </div>
            </div>
          </div>

          <!-- User Roster Table -->
          <div class="overflow-x-auto border border-white/8 rounded-xl">
            <table class="w-full text-left text-xs">
              <thead class="bg-[#1f2937]/50 text-white/60 uppercase text-[10px] tracking-wider border-b border-white/8">
                <tr>
                  <th class="px-4 py-3">姓名</th>
                  <th class="px-4 py-3">部門</th>
                  <th class="px-4 py-3">職級標籤</th>
                  <th class="px-4 py-3">權限等級 (1~10)</th>
                  <th class="px-4 py-3">建立時間</th>
                  <th class="px-4 py-3 text-right">操作</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-white/5">
                <tr v-if="users.length === 0">
                  <td colspan="6" class="px-4 py-6 text-center text-white/40">
                    目前名冊中無任何使用者，請於上方新增。
                  </td>
                </tr>
                <tr v-for="user in users" :key="user.id" class="hover:bg-white/3 transition-colors">
                  <td class="px-4 py-3 font-semibold text-white">{{ user.name }}</td>
                  <td class="px-4 py-3 text-white/70">
                    <span class="px-2 py-0.5 bg-white/5 rounded border border-white/10">{{ user.department }}</span>
                  </td>
                  <td class="px-4 py-3 text-white/70">{{ user.job_title }}</td>
                  <td class="px-4 py-3">
                    <span class="font-mono text-purple-400 font-bold">等級 {{ user.level }}</span>
                  </td>
                  <td class="px-4 py-3 text-white/40">{{ user.created_at }}</td>
                  <td class="px-4 py-3 text-right">
                    <button
                      @click="handleDeleteUser(user.id, user.name)"
                      class="text-red-400 hover:text-red-300 hover:underline text-xs"
                    >
                      刪除
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <!-- Panel 3: 外部 API 金鑰管理 -->
        <section class="bg-[#111827]/70 border border-white/8 rounded-2xl p-6 backdrop-blur-xl shadow-xl">
          <div class="flex items-center justify-between mb-4 pb-3 border-b border-white/8">
            <div>
              <h3 class="text-lg font-bold text-white flex items-center gap-2">
                <span class="w-2 h-2 rounded-full bg-amber-500"></span>
                外部 API 金鑰管理 (External API Keys)
              </h3>
              <p class="text-xs text-white/50 mt-0.5">供公司內網外部應用呼叫 /api/external/chat 時於 X-API-Key 標頭帶入</p>
            </div>
          </div>

          <!-- Alert Messages -->
          <div v-if="apiKeyError" class="mb-4 p-3 bg-red-500/10 border border-red-500/30 rounded-xl text-red-400 text-xs flex items-center gap-2">
            <span>⚠️</span> {{ apiKeyError }}
          </div>
          <div v-if="newlyCreatedKey" class="mb-4 p-3 bg-amber-500/10 border border-amber-500/30 rounded-xl text-amber-300 text-xs flex flex-col gap-1.5">
            <span>✅ 金鑰建立成功，請立即複製保存——關閉此提示後將無法再次取得完整金鑰：</span>
            <code class="block bg-black/30 rounded-lg px-3 py-2 font-mono text-[11px] text-amber-200 break-all select-all">{{ newlyCreatedKey }}</code>
          </div>

          <!-- Add Form -->
          <div class="flex gap-3 mb-6">
            <input
              v-model="newApiKeyName"
              type="text"
              placeholder="用途/系統名稱 (例如：HR 入口網站)"
              class="flex-1 bg-[#1f2937]/60 border border-white/10 rounded-xl px-4 py-2.5 text-sm text-white placeholder-white/30 focus:outline-none focus:border-amber-500/50 transition-colors"
              @keyup.enter="handleAddApiKey"
            />
            <button
              @click="handleAddApiKey"
              :disabled="isAddingApiKey"
              class="bg-gradient-to-r from-amber-600 to-orange-600 hover:from-amber-500 hover:to-orange-500 text-white font-medium px-5 py-2.5 rounded-xl text-sm transition-all shadow-lg shadow-amber-600/20 disabled:opacity-50"
            >
              {{ isAddingApiKey ? '建立中...' : '建立金鑰' }}
            </button>
          </div>

          <!-- API Key Table -->
          <div class="overflow-x-auto border border-white/8 rounded-xl">
            <table class="w-full text-left text-xs">
              <thead class="bg-[#1f2937]/50 text-white/60 uppercase text-[10px] tracking-wider border-b border-white/8">
                <tr>
                  <th class="px-4 py-3">名稱</th>
                  <th class="px-4 py-3">前綴</th>
                  <th class="px-4 py-3">狀態</th>
                  <th class="px-4 py-3">建立時間</th>
                  <th class="px-4 py-3">最後使用時間</th>
                  <th class="px-4 py-3 text-right">操作</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-white/5">
                <tr v-if="apiKeys.length === 0">
                  <td colspan="6" class="px-4 py-6 text-center text-white/40">
                    目前尚無任何外部 API 金鑰，請於上方建立。
                  </td>
                </tr>
                <tr v-for="key in apiKeys" :key="key.id" class="hover:bg-white/3 transition-colors">
                  <td class="px-4 py-3 font-semibold text-white">{{ key.name }}</td>
                  <td class="px-4 py-3 text-white/70 font-mono">{{ key.key_prefix }}...</td>
                  <td class="px-4 py-3">
                    <span :class="key.is_active ? 'text-emerald-400' : 'text-white/40'">{{ key.is_active ? '啟用中' : '已停用' }}</span>
                  </td>
                  <td class="px-4 py-3 text-white/40">{{ key.created_at }}</td>
                  <td class="px-4 py-3 text-white/40">{{ key.last_used_at || '尚未使用' }}</td>
                  <td class="px-4 py-3 text-right">
                    <button
                      @click="handleDeleteApiKey(key.id, key.name)"
                      class="text-red-400 hover:text-red-300 hover:underline text-xs"
                    >
                      刪除
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
  </div>
</template>
