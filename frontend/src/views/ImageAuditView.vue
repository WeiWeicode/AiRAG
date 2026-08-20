<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import imageAuditService from '../services/imageAuditService'
import imageService from '../services/imageService'

const PAGE_SIZE_OPTIONS = [20, 50, 100, 200]
const THUMB_CONCURRENCY = 6

const report = ref(null)
const isLoading = ref(false)
const errorMessage = ref('')
const successMessage = ref('')

const activeTab = ref('orphan')   // orphan | missing | matched
const page = ref(1)
const pageSize = ref(PAGE_SIZE_OPTIONS[0])
const showRecent = ref(false)     // 是否放行「近期檔案」讓使用者勾選
const selectedFilenames = ref([])
const expandedFilenames = ref([])

// 縮圖以 blob URL 載入：圖片端點需要 JWT，<img src> 直接指過去會 401
const thumbUrls = ref({})         // filename -> blob URL；載入失敗記為 'error'

const showDeleteModal = ref(false)
const deleteMode = ref('selected')   // selected | all
const confirmInput = ref('')
const isDeleting = ref(false)

const summary = computed(() => report.value?.summary || {})
const scanErrors = computed(() => report.value?.errors || [])
const hasScanError = computed(() => scanErrors.value.length > 0)

const orphanFiles = computed(() => report.value?.orphan_files || [])
const missingFiles = computed(() => report.value?.missing_files || [])
const matchedFiles = computed(() => report.value?.matched_files || [])

const currentList = computed(() => {
  if (activeTab.value === 'orphan') return orphanFiles.value
  if (activeTab.value === 'missing') return missingFiles.value
  return matchedFiles.value
})

const totalPages = computed(() => Math.max(1, Math.ceil(currentList.value.length / pageSize.value)))
const pagedList = computed(() =>
  currentList.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value)
)

const isSelectable = (item) => !item.is_recent || showRecent.value
const selectablePagedItems = computed(() => pagedList.value.filter(isSelectable))
const isAllPageSelected = computed(() =>
  selectablePagedItems.value.length > 0 &&
  selectablePagedItems.value.every((item) => selectedFilenames.value.includes(item.image_filename))
)

// 一鍵清除的實際對象：近期檔案要勾了「允許勾選近期檔案」才會一起刪
const deletableOrphanCount = computed(() => orphanFiles.value.filter(isSelectable).length)

const deleteTargetCount = computed(() =>
  deleteMode.value === 'all' ? deletableOrphanCount.value : selectedFilenames.value.length
)

const recentProtectHours = computed(() => {
  const seconds = report.value?.recent_protect_seconds || 0
  return Math.round((seconds / 3600) * 10) / 10
})

const formatSize = (bytes) => {
  if (bytes === null || bytes === undefined) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

const formatTime = (value) => (value ? new Date(value).toLocaleString() : '-')

const revokeAllThumbs = () => {
  thumbLoadToken++
  Object.values(thumbUrls.value).forEach((url) => {
    if (url && url !== 'error') window.URL.revokeObjectURL(url)
  })
  thumbUrls.value = {}
}

let thumbLoadToken = 0

const loadThumbsForCurrentPage = async () => {
  // 遺失檔在磁碟上不存在，載了必然 404，直接跳過
  if (activeTab.value === 'missing') return

  const token = ++thumbLoadToken
  const pending = pagedList.value
    .map((item) => item.image_filename)
    .filter((filename) => !thumbUrls.value[filename])

  // 每頁可到 200 筆，逐張 await 會慢到無法用，改成小批並行；換頁後 token 失效即停止
  for (let i = 0; i < pending.length; i += THUMB_CONCURRENCY) {
    if (token !== thumbLoadToken) return
    const batch = pending.slice(i, i + THUMB_CONCURRENCY)
    const results = await Promise.all(
      batch.map(async (filename) => {
        try {
          return [filename, await imageService.fetchImageBlobUrl(filename)]
        } catch (err) {
          return [filename, 'error']
        }
      })
    )
    if (token !== thumbLoadToken) {
      results.forEach(([, url]) => {
        if (url && url !== 'error') window.URL.revokeObjectURL(url)
      })
      return
    }
    thumbUrls.value = { ...thumbUrls.value, ...Object.fromEntries(results) }
  }
}

const loadReport = async (refresh = false) => {
  isLoading.value = true
  errorMessage.value = ''
  try {
    const res = await imageAuditService.scan(refresh)
    report.value = res.data
    selectedFilenames.value = []
    expandedFilenames.value = []
    page.value = 1
    revokeAllThumbs()
    await loadThumbsForCurrentPage()
  } catch (err) {
    console.error('圖片稽核掃描失敗:', err)
    errorMessage.value = err.response?.data?.detail || '圖片稽核掃描失敗'
  } finally {
    isLoading.value = false
  }
}

const switchTab = (tab) => {
  activeTab.value = tab
  page.value = 1
}

const toggleSelect = (item) => {
  if (!isSelectable(item)) return
  const filename = item.image_filename
  const index = selectedFilenames.value.indexOf(filename)
  if (index >= 0) {
    selectedFilenames.value.splice(index, 1)
  } else {
    selectedFilenames.value.push(filename)
  }
}

const toggleSelectAllOnPage = () => {
  if (isAllPageSelected.value) {
    const pageNames = selectablePagedItems.value.map((item) => item.image_filename)
    selectedFilenames.value = selectedFilenames.value.filter((name) => !pageNames.includes(name))
  } else {
    selectablePagedItems.value.forEach((item) => {
      if (!selectedFilenames.value.includes(item.image_filename)) {
        selectedFilenames.value.push(item.image_filename)
      }
    })
  }
}

const toggleExpand = (filename) => {
  const index = expandedFilenames.value.indexOf(filename)
  if (index >= 0) {
    expandedFilenames.value.splice(index, 1)
  } else {
    expandedFilenames.value.push(filename)
  }
}

const copyText = async (text) => {
  try {
    await navigator.clipboard.writeText(text)
    successMessage.value = `已複製：${text}`
  } catch (err) {
    errorMessage.value = '複製失敗，請手動選取'
  }
}

const openDeleteModal = (mode = 'selected') => {
  deleteMode.value = mode
  confirmInput.value = ''
  showDeleteModal.value = true
}

const closeDeleteModal = () => {
  showDeleteModal.value = false
  confirmInput.value = ''
}

const handleCleanupConfirm = async () => {
  if (confirmInput.value !== 'DELETE' || deleteTargetCount.value === 0) return

  isDeleting.value = true
  errorMessage.value = ''
  successMessage.value = ''
  try {
    const res = deleteMode.value === 'all'
      ? await imageAuditService.cleanupAll(showRecent.value)
      : await imageAuditService.cleanup([...selectedFilenames.value], showRecent.value)
    const data = res.data
    const messages = [data.message]
    if (data.skipped?.length) {
      const stillReferenced = data.skipped.filter((s) => s.reason === 'still_referenced').length
      const verifyFailed = data.skipped.filter((s) => s.reason === 'verify_failed').length
      const recent = data.skipped.filter((s) => s.reason === 'recent_file').length
      if (stillReferenced) messages.push(`其中 ${stillReferenced} 筆在確認期間被重新引用，已跳過`)
      if (verifyFailed) messages.push(`其中 ${verifyFailed} 筆因無法查詢 Qdrant 複驗，已跳過`)
      if (recent) messages.push(`其中 ${recent} 筆為近期檔案（可能是進行中的任務），已跳過`)
    }
    if (data.failed?.length) {
      messages.push(`失敗：${data.failed.map((f) => `${f.filename} (${f.error})`).join('、')}`)
    }
    successMessage.value = messages.join('；')
    closeDeleteModal()
    await loadReport(true)
  } catch (err) {
    console.error('清理孤兒圖檔失敗:', err)
    errorMessage.value = err.response?.data?.detail || '清理孤兒圖檔失敗'
  } finally {
    isDeleting.value = false
  }
}

watch([page, activeTab], () => {
  loadThumbsForCurrentPage()
})

watch(pageSize, () => {
  page.value = 1
  loadThumbsForCurrentPage()
})

watch(showRecent, (allowed) => {
  if (!allowed) {
    const recentNames = orphanFiles.value.filter((item) => item.is_recent).map((item) => item.image_filename)
    selectedFilenames.value = selectedFilenames.value.filter((name) => !recentNames.includes(name))
  }
})

onMounted(() => {
  loadReport(false)
})

onUnmounted(() => {
  revokeAllThumbs()
})
</script>

<template>
  <div class="flex-grow overflow-y-auto p-8 flex flex-col gap-8 h-full">
    <!-- Header -->
    <div class="flex justify-between items-start gap-4">
      <div class="flex flex-col gap-2">
        <h1 class="text-2xl font-bold text-white tracking-wide">圖片檔案稽核 (Image File Audit)</h1>
        <p class="text-sm text-[#9ca3af]">
          比對 Qdrant 全部 Collection 的圖片段落與地端 FileAttachments/image 資料夾，找出孤兒檔與遺失檔。
        </p>
        <p v-if="report" class="text-xs text-[#6b7280] font-mono">
          掃描時間：{{ formatTime(report.scanned_at) }} ・ 目錄：{{ report.image_dir }}
        </p>
      </div>
      <button
        @click="loadReport(true)"
        :disabled="isLoading"
        class="flex-shrink-0 bg-[#8b5cf6] hover:bg-[#a78bfa] disabled:bg-purple-900/50 disabled:text-purple-300/50 text-white font-semibold py-2.5 px-4 rounded-lg text-sm transition-all shadow-[0_0_15px_rgba(139,92,246,0.3)]"
      >
        <span v-if="isLoading">掃描中...</span>
        <span v-else>重新掃描</span>
      </button>
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

    <!-- 掃描錯誤：有 Collection 掃不到就不能判定孤兒，清理功能一律停用 -->
    <div v-if="hasScanError" class="bg-amber-500/10 border border-amber-500/25 text-amber-200 px-4 py-3 rounded-xl text-sm flex flex-col gap-2">
      <span class="font-semibold">⚠️ 部分 Collection 掃描失敗，孤兒判定不完整，已停用清理功能。</span>
      <ul class="list-disc list-inside text-xs text-amber-300/80 font-mono">
        <li v-for="(item, idx) in scanErrors" :key="idx">{{ item.collection }}：{{ item.error }}</li>
      </ul>
    </div>

    <!-- Summary Cards -->
    <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
      <div class="bg-[#111827]/70 border border-white/8 rounded-2xl p-5 backdrop-blur-md flex flex-col gap-1">
        <span class="text-xs font-semibold text-[#6b7280] uppercase tracking-wider">磁碟檔案</span>
        <span class="text-2xl font-bold text-white font-display">{{ summary.disk_file_count ?? '-' }}</span>
        <span class="text-xs text-[#6b7280]">image 資料夾內的實體檔</span>
      </div>
      <div
        class="bg-[#111827]/70 border border-white/8 rounded-2xl p-5 backdrop-blur-md flex flex-col gap-1"
        title="同一張圖可能被多個段落引用，因此檔名數與段落數不會相等"
      >
        <span class="text-xs font-semibold text-[#6b7280] uppercase tracking-wider">向量引用</span>
        <span class="text-2xl font-bold text-white font-display">
          {{ summary.referenced_filename_count ?? '-' }}
          <span class="text-sm text-[#9ca3af] font-normal">檔名 / {{ summary.image_point_count ?? '-' }} 段落</span>
        </span>
        <span class="text-xs text-[#6b7280]">跨 {{ summary.collection_count ?? '-' }} 個 Collection</span>
      </div>
      <div class="bg-[#111827]/70 border border-amber-500/20 rounded-2xl p-5 backdrop-blur-md flex flex-col gap-1">
        <span class="text-xs font-semibold text-amber-500/80 uppercase tracking-wider">孤兒檔</span>
        <span class="text-2xl font-bold text-amber-300 font-display">{{ summary.orphan_file_count ?? '-' }}</span>
        <span class="text-xs text-[#6b7280]">
          磁碟有、無任何向量引用
          <template v-if="summary.orphan_recent_count">（近期 {{ summary.orphan_recent_count }}）</template>
        </span>
      </div>
      <div class="bg-[#111827]/70 border border-rose-500/20 rounded-2xl p-5 backdrop-blur-md flex flex-col gap-1">
        <span class="text-xs font-semibold text-rose-500/80 uppercase tracking-wider">遺失檔</span>
        <span class="text-2xl font-bold text-rose-300 font-display">{{ summary.missing_file_count ?? '-' }}</span>
        <span class="text-xs text-[#6b7280]">向量有引用、磁碟無檔</span>
      </div>
    </div>

    <!-- Main Panel -->
    <div class="bg-[#111827]/70 border border-white/8 rounded-2xl p-6 backdrop-blur-md flex flex-col gap-5">
      <!-- Tabs -->
      <div class="flex gap-2 border-b border-white/5 pb-3">
        <button
          @click="switchTab('orphan')"
          :class="activeTab === 'orphan' ? 'bg-amber-500/15 text-amber-300 border-amber-500/30' : 'text-[#9ca3af] border-transparent hover:bg-white/5'"
          class="px-4 py-2 rounded-lg text-sm font-semibold border transition-all"
        >
          孤兒檔 ({{ orphanFiles.length }})
        </button>
        <button
          @click="switchTab('missing')"
          :class="activeTab === 'missing' ? 'bg-rose-500/15 text-rose-300 border-rose-500/30' : 'text-[#9ca3af] border-transparent hover:bg-white/5'"
          class="px-4 py-2 rounded-lg text-sm font-semibold border transition-all"
        >
          遺失檔 ({{ missingFiles.length }})
        </button>
        <button
          @click="switchTab('matched')"
          :class="activeTab === 'matched' ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' : 'text-[#9ca3af] border-transparent hover:bg-white/5'"
          class="px-4 py-2 rounded-lg text-sm font-semibold border transition-all"
        >
          正常 ({{ matchedFiles.length }})
        </button>
      </div>

      <div v-if="isLoading" class="py-12 text-center text-[#9ca3af] text-sm">掃描中...</div>

      <!-- 孤兒檔 -->
      <template v-else-if="activeTab === 'orphan'">
        <div class="flex flex-wrap justify-between items-center gap-3">
          <div class="flex items-center gap-4">
            <label class="flex items-center gap-2 text-sm text-[#9ca3af] cursor-pointer">
              <input
                type="checkbox"
                :checked="isAllPageSelected"
                :disabled="selectablePagedItems.length === 0"
                @change="toggleSelectAllOnPage"
                class="accent-[#8b5cf6] w-4 h-4"
              />
              本頁全選
            </label>
            <span class="text-xs text-[#6b7280]">已選 {{ selectedFilenames.length }} 筆</span>
            <label class="flex items-center gap-2 text-xs text-[#9ca3af] cursor-pointer" :title="`mtime 在最近 ${recentProtectHours} 小時內的檔案，可能是進行中的向量化任務產物`">
              <input type="checkbox" v-model="showRecent" class="accent-amber-500 w-4 h-4" />
              允許勾選近期檔案（最近 {{ recentProtectHours }} 小時）
            </label>
          </div>
          <div class="flex items-center gap-3">
            <button
              @click="openDeleteModal('selected')"
              :disabled="selectedFilenames.length === 0 || hasScanError"
              class="bg-rose-600 hover:bg-rose-500 disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold py-2 px-4 rounded-lg text-sm transition-all"
              :title="hasScanError ? '掃描有 Collection 失敗，無法確認孤兒狀態' : ''"
            >
              刪除選取的實體檔
            </button>
            <button
              @click="openDeleteModal('all')"
              :disabled="deletableOrphanCount === 0 || hasScanError"
              class="bg-rose-900/60 border border-rose-500/40 hover:bg-rose-800/70 disabled:opacity-40 disabled:cursor-not-allowed text-rose-200 font-semibold py-2 px-4 rounded-lg text-sm transition-all"
              :title="hasScanError ? '掃描有 Collection 失敗，無法確認孤兒狀態' : '刪除全部孤兒檔（後端會重新複驗一次）'"
            >
              一鍵清除全部 ({{ deletableOrphanCount }})
            </button>
          </div>
        </div>

        <div class="overflow-x-auto">
          <table class="w-full text-left text-sm text-[#9ca3af]">
            <thead>
              <tr class="border-b border-white/8 text-xs uppercase tracking-wider text-[#6b7280]">
                <th class="pb-3 w-10"></th>
                <th class="pb-3 w-20 font-medium">預覽</th>
                <th class="pb-3 font-medium">檔名</th>
                <th class="pb-3 text-right font-medium">大小</th>
                <th class="pb-3 text-right font-medium">最後修改</th>
                <th class="pb-3 text-center font-medium">狀態</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-white/4">
              <tr v-if="pagedList.length === 0" class="text-[#6b7280] text-center">
                <td colspan="6" class="py-8">沒有孤兒檔，兩邊資料一致</td>
              </tr>
              <tr v-for="item in pagedList" :key="item.image_filename" class="hover:bg-white/1 transition-all">
                <td class="py-3">
                  <input
                    type="checkbox"
                    :checked="selectedFilenames.includes(item.image_filename)"
                    :disabled="!isSelectable(item)"
                    @change="toggleSelect(item)"
                    class="accent-[#8b5cf6] w-4 h-4 disabled:opacity-30"
                  />
                </td>
                <td class="py-3">
                  <img
                    v-if="thumbUrls[item.image_filename] && thumbUrls[item.image_filename] !== 'error'"
                    :src="thumbUrls[item.image_filename]"
                    class="w-14 h-14 object-cover rounded-lg border border-white/10"
                  />
                  <div v-else class="w-14 h-14 rounded-lg bg-white/5 border border-white/8 flex items-center justify-center text-[10px] text-[#6b7280]">
                    {{ thumbUrls[item.image_filename] === 'error' ? '讀取失敗' : '載入中' }}
                  </div>
                </td>
                <td class="py-3 font-mono text-xs text-white break-all">{{ item.image_filename }}</td>
                <td class="py-3 text-right text-xs font-mono">{{ formatSize(item.size) }}</td>
                <td class="py-3 text-right text-xs font-mono text-[#6b7280]">{{ formatTime(item.modified_at) }}</td>
                <td class="py-3 text-center">
                  <span v-if="item.is_recent" class="text-[11px] px-2 py-1 rounded-md bg-amber-500/15 text-amber-300 border border-amber-500/25">
                    近期檔案・建議稍後確認
                  </span>
                  <span v-else class="text-[11px] px-2 py-1 rounded-md bg-white/5 text-[#9ca3af]">可刪除</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>

      <!-- 遺失檔 -->
      <template v-else-if="activeTab === 'missing'">
        <p class="text-xs text-[#6b7280]">
          這些圖片仍被 Qdrant 段落引用，但磁碟上已不存在：前端縮圖會 404，且無法用「重新產生圖片描述」修復。
          處理方式為重新向量該來源文件，或刪除對應的 point。
        </p>
        <div class="overflow-x-auto">
          <table class="w-full text-left text-sm text-[#9ca3af]">
            <thead>
              <tr class="border-b border-white/8 text-xs uppercase tracking-wider text-[#6b7280]">
                <th class="pb-3 font-medium">檔名</th>
                <th class="pb-3 font-medium">來源文件</th>
                <th class="pb-3 font-medium">知識庫</th>
                <th class="pb-3 text-center font-medium">頁次</th>
                <th class="pb-3 font-medium">Point ID</th>
                <th class="pb-3 text-center font-medium">描述失敗</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-white/4">
              <tr v-if="pagedList.length === 0" class="text-[#6b7280] text-center">
                <td colspan="6" class="py-8">沒有遺失檔，向量引用的圖片都還在磁碟上</td>
              </tr>
              <template v-for="item in pagedList" :key="item.image_filename">
                <tr v-for="(ref, idx) in item.references" :key="ref.point_id" class="hover:bg-white/1 transition-all">
                  <td class="py-3 font-mono text-xs text-rose-300 break-all">
                    {{ idx === 0 ? item.image_filename : '' }}
                  </td>
                  <td class="py-3 text-xs text-white">{{ ref.filename || '-' }}</td>
                  <td class="py-3 text-xs">
                    {{ ref.kb_name || '（無對應知識庫紀錄）' }}
                    <span class="block text-[10px] text-[#6b7280] font-mono">{{ ref.collection }}</span>
                  </td>
                  <td class="py-3 text-center text-xs font-mono">{{ ref.page ?? '-' }}</td>
                  <td class="py-3">
                    <button
                      @click="copyText(ref.point_id)"
                      class="text-[11px] font-mono text-purple-300 hover:text-purple-200 hover:bg-white/5 px-2 py-1 rounded-md transition-all"
                      title="複製 Point ID"
                    >
                      {{ ref.point_id.slice(0, 8) }}… 複製
                    </button>
                  </td>
                  <td class="py-3 text-center">
                    <span v-if="ref.caption_failed" class="text-[11px] px-2 py-1 rounded-md bg-rose-500/15 text-rose-300">是</span>
                    <span v-else class="text-[11px] text-[#6b7280]">否</span>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
      </template>

      <!-- 正常 -->
      <template v-else>
        <div class="overflow-x-auto">
          <table class="w-full text-left text-sm text-[#9ca3af]">
            <thead>
              <tr class="border-b border-white/8 text-xs uppercase tracking-wider text-[#6b7280]">
                <th class="pb-3 w-20 font-medium">預覽</th>
                <th class="pb-3 font-medium">檔名</th>
                <th class="pb-3 text-right font-medium">大小</th>
                <th class="pb-3 text-center font-medium">引用段落</th>
                <th class="pb-3 font-medium">來源文件</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-white/4">
              <tr v-if="pagedList.length === 0" class="text-[#6b7280] text-center">
                <td colspan="5" class="py-8">尚無圖片段落</td>
              </tr>
              <template v-for="item in pagedList" :key="item.image_filename">
                <tr class="hover:bg-white/1 transition-all">
                  <td class="py-3">
                    <img
                      v-if="thumbUrls[item.image_filename] && thumbUrls[item.image_filename] !== 'error'"
                      :src="thumbUrls[item.image_filename]"
                      class="w-14 h-14 object-cover rounded-lg border border-white/10"
                    />
                    <div v-else class="w-14 h-14 rounded-lg bg-white/5 border border-white/8 flex items-center justify-center text-[10px] text-[#6b7280]">
                      {{ thumbUrls[item.image_filename] === 'error' ? '讀取失敗' : '載入中' }}
                    </div>
                  </td>
                  <td class="py-3 font-mono text-xs text-white break-all">{{ item.image_filename }}</td>
                  <td class="py-3 text-right text-xs font-mono">{{ formatSize(item.size) }}</td>
                  <td class="py-3 text-center font-mono text-xs text-emerald-300">{{ item.reference_count }}</td>
                  <td class="py-3 text-xs">
                    {{ item.references[0]?.filename || '-' }}
                    <button
                      v-if="item.reference_count > 1"
                      @click="toggleExpand(item.image_filename)"
                      class="ml-2 text-[11px] text-purple-300 hover:text-purple-200"
                    >
                      {{ expandedFilenames.includes(item.image_filename) ? '收合' : `展開全部 ${item.reference_count} 筆` }}
                    </button>
                  </td>
                </tr>
                <tr v-if="expandedFilenames.includes(item.image_filename)" class="bg-white/2">
                  <td colspan="5" class="py-3 px-4">
                    <ul class="flex flex-col gap-1 text-[11px] font-mono text-[#9ca3af]">
                      <li v-for="ref in item.references" :key="ref.point_id">
                        {{ ref.kb_name || '（無對應知識庫紀錄）' }} ・ {{ ref.filename || '-' }} ・ 第 {{ ref.page ?? '-' }} 頁 ・ {{ ref.point_id }}
                      </li>
                    </ul>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
      </template>

      <!-- Pagination -->
      <div v-if="!isLoading && currentList.length > 0" class="flex flex-wrap justify-between items-center gap-3 pt-2 border-t border-white/5">
        <label class="flex items-center gap-2 text-xs text-[#6b7280]">
          每頁顯示
          <select
            v-model.number="pageSize"
            class="bg-white/5 border border-white/10 rounded-lg text-[#9ca3af] px-2 py-1.5 text-xs focus:outline-none focus:border-[#8b5cf6] transition-all"
          >
            <option v-for="size in PAGE_SIZE_OPTIONS" :key="size" :value="size">{{ size }}</option>
          </select>
          筆・共 {{ currentList.length }} 筆
        </label>
        <div class="flex items-center gap-3">
          <button
            @click="page = 1"
            :disabled="page === 1"
            class="px-3 py-1.5 rounded-lg text-xs text-[#9ca3af] bg-white/5 hover:bg-white/10 disabled:opacity-30 transition-all"
          >
            第一頁
          </button>
          <button
            @click="page = Math.max(1, page - 1)"
            :disabled="page === 1"
            class="px-3 py-1.5 rounded-lg text-xs text-[#9ca3af] bg-white/5 hover:bg-white/10 disabled:opacity-30 transition-all"
          >
            上一頁
          </button>
          <span class="text-xs text-[#6b7280] font-mono">{{ page }} / {{ totalPages }}</span>
          <button
            @click="page = Math.min(totalPages, page + 1)"
            :disabled="page === totalPages"
            class="px-3 py-1.5 rounded-lg text-xs text-[#9ca3af] bg-white/5 hover:bg-white/10 disabled:opacity-30 transition-all"
          >
            下一頁
          </button>
          <button
            @click="page = totalPages"
            :disabled="page === totalPages"
            class="px-3 py-1.5 rounded-lg text-xs text-[#9ca3af] bg-white/5 hover:bg-white/10 disabled:opacity-30 transition-all"
          >
            最後一頁
          </button>
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
          <h3 class="text-base font-bold text-white">
            {{ deleteMode === 'all' ? '二次確認：一鍵清除全部孤兒檔' : '二次確認：刪除實體圖檔' }}
          </h3>
        </div>

        <div class="flex flex-col gap-3 text-sm text-[#9ca3af]">
          <p class="text-rose-300 font-medium">
            ⚠️ 即將從磁碟永久刪除 {{ deleteTargetCount }} 個檔案，無法復原。
            刪除前後端會再次複驗仍無向量引用，仍被引用者會自動跳過。
          </p>
          <p v-if="deleteMode === 'all'" class="text-xs text-amber-300/90">
            一鍵清除的對象是「後端複驗當下仍無任何向量引用」的全部孤兒檔，不限於本頁或已勾選的項目。
            {{ showRecent
              ? `包含最近 ${recentProtectHours} 小時內的近期檔案（可能是進行中的向量化任務產物）。`
              : `不含最近 ${recentProtectHours} 小時內的近期檔案。` }}
            檔案數量多時可能需要數十秒，請勿關閉頁面。
          </p>
          <ul v-else class="flex flex-col gap-1 text-xs font-mono text-white bg-white/5 rounded-lg p-3 max-h-40 overflow-y-auto">
            <li v-for="filename in selectedFilenames.slice(0, 10)" :key="filename">{{ filename }}</li>
            <li v-if="selectedFilenames.length > 10" class="text-[#6b7280]">…等 {{ selectedFilenames.length }} 筆</li>
          </ul>
          <p>
            請輸入 <strong class="text-white select-all font-mono">DELETE</strong> 以確認：
          </p>
          <input
            v-model="confirmInput"
            type="text"
            placeholder="DELETE"
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
            @click="handleCleanupConfirm"
            :disabled="confirmInput !== 'DELETE' || isDeleting || deleteTargetCount === 0"
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
