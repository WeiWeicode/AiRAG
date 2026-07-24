<script setup>
import { ref, computed } from 'vue'
import { useParamsStore } from '../../stores/paramsStore'
import { useExternalChatStore, buildExternalChatPayload } from '../../stores/externalChatStore'

const paramsStore = useParamsStore()
const externalChatStore = useExternalChatStore()

const endpointUrl = computed(() => `${import.meta.env.VITE_API_BASE_URL || '/api'}/external/chat`)

// 對話紀錄示範沿用本頁實際的外部對話 store（排除歡迎訊息），讓預覽盡量貼近目前畫面上的真實對話狀態；
// question 欄位因為要即時反映輸入框「尚未送出」的草稿文字，牽涉到跨元件狀態，這裡先以固定範例文字呈現，
// 實際送出時仍是即時依當下輸入框內容組出 payload（見 externalChatStore.js sendQuestion）
const chatHistoryForPreview = computed(() =>
  externalChatStore.messages
    .filter(m => m.id !== 'welcome' && m.content)
    .map(m => ({ role: m.role, content: m.content }))
)

const previewPayload = computed(() => buildExternalChatPayload(paramsStore, {
  question: '<請輸入問題，實際值以下方對話框送出時的文字為準>',
  chatHistory: chatHistoryForPreview.value,
  selectedDbProfileId: undefined
}))

const jsonPreview = computed(() => JSON.stringify(previewPayload.value, null, 2))

const copied = ref(false)
const copyJson = async () => {
  try {
    await navigator.clipboard.writeText(jsonPreview.value)
    copied.value = true
    setTimeout(() => { copied.value = false }, 1500)
  } catch (err) {
    console.error('複製失敗:', err)
  }
}

const fieldDocs = [
  { field: 'question', desc: '使用者提問文字（必填）' },
  { field: 'knowledge_base_id', desc: '要檢索的知識庫 ID；留空則不執行檢索，直接以 params.custom_system_prompt（若有填寫）進行純 LLM 對話' },
  { field: 'chat_history', desc: '對話歷史陣列，格式為 [{ role: "user"|"assistant", content: "..." }, ...]，供多輪對話與指代消解使用' },
  { field: 'selected_db_profile_id', desc: '僅 search_type 為 semantic_db_query 且需二次選定候選查詢設定檔時才帶入' },
  { field: 'params.search_type', desc: '檢索模式：vector / hybrid / semantic_hybrid / semantic_hybrid_feedback / semantic_hybrid_attachment / KB_semantic_hybrid / semantic_db_query' },
  { field: 'params.top_k', desc: '檢索筆數上限' },
  { field: 'params.score_threshold', desc: '檢索相似度最低門檻，低於此分數的片段不會被檢索回傳' },
  { field: 'params.ai_summary_score_threshold', desc: 'AI 總結門檻，低於此分數的片段不會納入 AI 總結上下文（但仍會出現在 sources）' },
  { field: 'params.filter_tags', desc: '標籤過濾陣列，未帶或空陣列代表不過濾' },
  { field: 'params.custom_system_prompt', desc: '自訂總結提示詞：有填寫時完全取代預設的指示規則文字，檢索到的參考資料仍會由後端自動接續在後面；未帶或空白則使用系統預設模板' },
  { field: 'params.temperature / max_tokens', desc: '生成模型參數' },
  { field: 'params.pinned_filename', desc: '手動鎖定檔案，僅語義混合家族查詢法有效，null 代表不鎖定' },
  { field: 'params.external_user', desc: '必填，取代內部測試用的 simulated_user_id：帶入實際員工身分，供機密文件存取權限過濾使用' },
  { field: 'params.external_user.employee_id / name', desc: '工號、姓名，僅供稽核紀錄與排除說明文字顯示，不影響過濾判斷' },
  { field: 'params.external_user.department_code', desc: '部門代號，用於機密文件的部門限制比對（與既有部門名稱雙軌相容）' },
  { field: 'params.external_user.department_name', desc: '部門名稱，僅供排除說明文字顯示' },
  { field: 'params.external_user.job_title_name', desc: '級職名稱，僅供排除說明文字顯示' },
  { field: 'params.external_user.job_title_level', desc: '級職等級（1~10，數字越小權限越高），由呼叫端直接信任帶入，不會重新換算，用於機密等級比對' }
]
</script>

<template>
  <div class="flex flex-col gap-4 bg-white/3 border border-white/8 rounded-2xl p-5 backdrop-blur-md">
    <div class="text-sm font-bold text-white border-b border-white/8 pb-2 tracking-wider">
      API 預覽 (API Preview)
    </div>

    <p class="text-[11px] text-[#9ca3af] leading-relaxed">
      以下內容依左側目前的參數設定即時組成，未來可直接提供給外部應用開發者作為串接參考。
    </p>

    <div class="flex flex-col gap-1.5">
      <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">端點</label>
      <div class="bg-white/5 border border-white/8 rounded-lg px-3 py-2 text-xs text-[#a78bfa] font-mono break-all">
        POST {{ endpointUrl }}
      </div>
      <p class="text-[10px] text-[#9ca3af]">
        Headers: <span class="font-mono">Content-Type: application/json</span>、<span class="font-mono">X-API-Key: &lt;your-api-key&gt;</span>
        （於「角色與權限設定」頁建立金鑰；此端點不使用登入 JWT，改以 X-API-Key 驗證呼叫端系統身分）
      </p>
    </div>

    <div class="flex flex-col gap-1.5">
      <div class="flex justify-between items-center">
        <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">Request Body</label>
        <button
          @click="copyJson"
          class="text-[10px] px-2 py-1 rounded-md bg-[#8b5cf6]/15 hover:bg-[#8b5cf6]/25 border border-[#8b5cf6]/30 text-[#a78bfa] transition-all"
        >
          {{ copied ? '已複製' : '複製 JSON' }}
        </button>
      </div>
      <pre class="bg-[#0b0f19] border border-white/8 rounded-lg p-3 text-[11px] text-[#e5e7eb] font-mono overflow-auto max-h-80 whitespace-pre">{{ jsonPreview }}</pre>
    </div>

    <div class="flex flex-col gap-2 border-t border-white/5 pt-3">
      <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">欄位說明</label>
      <div class="flex flex-col gap-2">
        <div v-for="item in fieldDocs" :key="item.field" class="text-[10px] leading-relaxed">
          <span class="text-[#a78bfa] font-mono">{{ item.field }}</span>
          <span class="text-[#9ca3af]"> — {{ item.desc }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
