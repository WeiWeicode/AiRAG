<script setup>
import { ref, watch } from 'vue'
import { useParamsStore } from '../../stores/paramsStore'
import KnowledgeBaseSelector from '../common/KnowledgeBaseSelector.vue'
import api from '../../services/api'

import userService from '../../services/userService'

const paramsStore = useParamsStore()

// 手動鎖定檔案：下拉選單選項來源，隨知識庫切換重新取得
const availableFilenames = ref([])
const simulatedUsers = ref([])

const loadUsers = async () => {
  try {
    const res = await userService.listUsers()
    simulatedUsers.value = res.data || []
    if (simulatedUsers.value.length > 0 && !paramsStore.simulatedUserId) {
      paramsStore.simulatedUserId = simulatedUsers.value[0].id
    }
  } catch (err) {
    console.error('Failed to fetch user roster:', err)
  }
}

watch(() => paramsStore.knowledgeBaseId, async (newKbId) => {
  if (!newKbId) {
    availableFilenames.value = []
    paramsStore.pinnedFilename = null
    return
  }
  try {
    const response = await api.get(`/api/knowledge-bases/${newKbId}/metadata`)
    availableFilenames.value = response.data?.filenames || []
    // 切換知識庫後，若原本鎖定的檔案不在新清單中，自動重置，避免無聲檢索 0 筆
    if (paramsStore.pinnedFilename && !availableFilenames.value.includes(paramsStore.pinnedFilename)) {
      paramsStore.pinnedFilename = null
    }
  } catch (err) {
    console.error('Failed to fetch filenames:', err)
    availableFilenames.value = []
    paramsStore.pinnedFilename = null
  }
}, { immediate: true })

loadUsers()
</script>

<template>
  <div class="flex flex-col gap-5 bg-white/3 border border-white/8 rounded-2xl p-5 backdrop-blur-md">
    <div class="text-sm font-bold text-white border-b border-white/8 pb-2 tracking-wider">
      檢索設定 (Retrieval)
    </div>

    <!-- Knowledge Base Selector -->
    <KnowledgeBaseSelector />

    <!-- Top-K Slider -->
    <div class="flex flex-col gap-2">
      <div class="flex justify-between items-center">
        <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">檢索數量 (Top-K)</label>
        <span class="text-xs font-bold text-[#a78bfa] font-display">{{ paramsStore.topK }}</span>
      </div>
      <input
        v-model.number="paramsStore.topK"
        type="range"
        min="1"
        max="50"
        class="w-full h-1 bg-white/10 rounded-lg appearance-none cursor-pointer accent-[#8b5cf6]"
      />
    </div>

    <!-- Score Threshold Slider -->
    <div class="flex flex-col gap-2">
      <div class="flex justify-between items-center">
        <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">相似度閾值 (Score Threshold)</label>
        <span class="text-xs font-bold text-[#a78bfa] font-display">{{ paramsStore.scoreThreshold.toFixed(2) }}</span>
      </div>
      <input 
        v-model.number="paramsStore.scoreThreshold" 
        type="range" 
        min="0" 
        max="1" 
        step="0.05" 
        class="w-full h-1 bg-white/10 rounded-lg appearance-none cursor-pointer accent-[#8b5cf6]"
      />
    </div>

    <!-- AI Summary Score Threshold Slider -->
    <div class="flex flex-col gap-2 pt-1 border-t border-white/5">
      <div class="flex justify-between items-center">
        <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider flex items-center gap-1">
          <span>AI 總結門檻 (AI Summary Threshold)</span>
        </label>
        <div class="flex items-center gap-2">
          <input 
            type="checkbox" 
            v-model="paramsStore.aiSummaryScoreThresholdEnabled" 
            class="rounded bg-white/10 border-white/20 text-[#8b5cf6] focus:ring-[#8b5cf6] h-3.5 w-3.5 cursor-pointer"
            title="開啟/關閉 AI 總結門檻過濾"
          />
          <span class="text-xs font-bold text-[#a78bfa] font-display">
            {{ paramsStore.aiSummaryScoreThresholdEnabled ? paramsStore.aiSummaryScoreThreshold.toFixed(2) : '關閉' }}
          </span>
        </div>
      </div>
      <input 
        v-model.number="paramsStore.aiSummaryScoreThreshold" 
        type="range" 
        min="0.00" 
        max="1.00" 
        step="0.05" 
        :disabled="!paramsStore.aiSummaryScoreThresholdEnabled"
        class="w-full h-1 bg-white/10 rounded-lg appearance-none cursor-pointer accent-[#8b5cf6] disabled:opacity-40"
      />
      <p class="text-[11px] text-slate-400 leading-normal">
        相似度低於此分數之片段將不放入 AI Context；全數低於門檻則自動跳過 AI 總結。
      </p>
    </div>

    <!-- Tags Filter -->
    <div class="flex flex-col gap-2">
      <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">標籤過濾篩選 (Filter Tags)</label>
      <input 
        v-model="paramsStore.filterTagsString" 
        type="text" 
        class="bg-white/5 border border-white/8 rounded-lg text-white px-3 py-2 text-xs focus:outline-none focus:border-[#8b5cf6] transition-all"
        placeholder="輸入篩選標籤，以英文逗號分隔"
      />
    </div>

    <!-- Search Mode Selector -->
    <div class="flex flex-col gap-2">
      <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">檢索模式 (Search Mode)</label>
      <select 
        v-model="paramsStore.searchMode" 
        class="bg-white/5 border border-white/8 rounded-lg text-white px-3.5 py-2.5 text-sm focus:outline-none focus:border-[#8b5cf6] transition-all"
      >
        <option value="vector" class="bg-[#111827] text-white">向量查詢 (Vector Search)</option>
        <option value="hybrid" class="bg-[#111827] text-white">混合查詢 (Hybrid Search)</option>
        <option value="semantic_hybrid" class="bg-[#111827] text-white">語義混合查詢 (Semantic Hybrid Search)</option>
        <option value="semantic_hybrid_feedback" class="bg-[#111827] text-white">語義混合回饋查詢法 (Semantic Hybrid + Feedback)</option>
        <option value="semantic_hybrid_attachment" class="bg-[#111827] text-white">語義混合附件查詢法 (Semantic Hybrid + Attachment)</option>
        <option value="KB_semantic_hybrid" class="bg-[#111827] text-white">集團知識庫語義混合查詢 (KB Semantic Hybrid)</option>
        <option value="KB_hybrid" class="bg-[#111827] text-white">集團知識庫混合查詢 (KB Hybrid)</option>
        <option value="semantic_db_query" class="bg-[#111827] text-white">語義資料庫查詢法 (Semantic DB Query)</option>
      </select>
    </div>

    <!-- Simulated User Access Control Section -->
    <div class="flex flex-col gap-2 pt-2 border-t border-white/5">
      <label class="flex items-center gap-2 text-xs font-semibold text-[#9ca3af] uppercase tracking-wider cursor-pointer">
        <input
          type="checkbox"
          v-model="paramsStore.simulatedUserEnabled"
          class="rounded bg-white/10 border-white/20 text-[#8b5cf6] focus:ring-[#8b5cf6] h-3.5 w-3.5 cursor-pointer"
        />
        <span>模擬使用者權限測試 (Simulate User)</span>
      </label>
      <div v-if="paramsStore.simulatedUserEnabled" class="flex flex-col gap-1.5 mt-1 animate-fade-in">
        <select
          v-model="paramsStore.simulatedUserId"
          class="bg-white/5 border border-white/8 rounded-lg text-white px-3 py-2 text-xs focus:outline-none focus:border-[#8b5cf6] transition-all"
        >
          <option v-if="simulatedUsers.length === 0" :value="null" class="bg-[#111827]">尚無使用者，請先新增</option>
          <option
            v-for="u in simulatedUsers"
            :key="u.id"
            :value="u.id"
            class="bg-[#111827] text-white"
          >
            👤 {{ u.name }} ({{ u.job_title }}/等級{{ u.level }}/{{ u.department }})
          </option>
        </select>
        <p class="text-[10px] text-[#9ca3af]">
          勾選後檢索將依該使用者的職級等級與部門自動排除無存取權限的機密文件。
        </p>
      </div>
    </div>

    <!-- Semantic Hybrid Attachment 專用參數：AI 讀取附件內容 -->
    <div v-if="paramsStore.searchMode === 'semantic_hybrid_attachment'" class="flex flex-col gap-3 border-t border-white/8 pt-4 animate-fade-in">
      <label class="flex items-center gap-2 text-xs text-white cursor-pointer select-none">
        <input
          type="checkbox"
          v-model="paramsStore.readAttachmentContent"
          class="rounded bg-white/5 border-white/10 text-[#8b5cf6] focus:ring-[#8b5cf6]/50 cursor-pointer"
        />
        AI 讀取附件內容 (AI Read Attachment Content)
      </label>
      <div class="text-[10px] text-[#9ca3af] leading-relaxed">
        勾選後，AI 將會在對話時讀取關聯附件的「描述與說明」併入上下文摘要，作為回答的依據。
      </div>
    </div>

    <!-- Context Summarize Threshold -->
    <div class="flex flex-col gap-2">
      <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">分批摘要門檻 (Context Summarize Threshold, tokens)</label>
      <input 
        v-model.number="paramsStore.contextSummarizeThreshold" 
        type="number" 
        min="1"
        class="bg-white/5 border border-white/8 rounded-lg text-white px-3 py-2 text-xs focus:outline-none focus:border-[#8b5cf6] transition-all"
        placeholder="預設 50000"
      />
      <div class="text-[10px] text-[#9ca3af] leading-relaxed">
        檢索內容 token 數超過此值時，會先分批摘要再送進主模型，避免超出模型上下文長度而回傳 400。
      </div>
    </div>

    <!-- 多輪對話指代消解：語義混合家族查詢法專用（自動指代消解 + 手動鎖定檔案）。
         KB_hybrid 已移除語義解析步驟，自動指代消解無作用故隱藏，但手動鎖定檔案仍有效因此保留。 -->
    <div v-if="['semantic_hybrid', 'semantic_hybrid_feedback', 'semantic_hybrid_attachment', 'KB_semantic_hybrid', 'KB_hybrid'].includes(paramsStore.searchMode)" class="flex flex-col gap-4 border-t border-white/8 pt-4 animate-fade-in">
      <div v-if="paramsStore.searchMode !== 'KB_hybrid'" class="flex flex-col gap-2">
        <label class="flex items-center gap-2 text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">
          <input type="checkbox" v-model="paramsStore.autoContextEnabled" class="accent-[#8b5cf6]" />
          自動指代消解（使用對話歷史）(Auto Reference Resolution)
        </label>
      </div>
      <div v-if="paramsStore.searchMode !== 'KB_hybrid'" class="flex flex-col gap-2" :class="{ 'opacity-40 pointer-events-none': !paramsStore.autoContextEnabled }">
        <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">指代消解歷史則數 (History Turns)</label>
        <input
          type="number" min="0"
          v-model.number="paramsStore.historyTurnCount"
          :disabled="!paramsStore.autoContextEnabled"
          placeholder="預設 3（後端設定值）"
          class="bg-white/5 border border-white/8 rounded-lg text-white px-3 py-2 text-xs focus:outline-none focus:border-[#8b5cf6] transition-all"
        />
      </div>
      <div class="flex flex-col gap-2">
        <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">手動鎖定檔案 (Pinned Filename)</label>
        <select v-model="paramsStore.pinnedFilename" class="bg-white/5 border border-white/8 rounded-lg text-white px-3 py-2 text-xs focus:outline-none focus:border-[#8b5cf6] transition-all">
          <option :value="null" class="bg-[#111827] text-white">不鎖定（由 AI 自動判斷）</option>
          <option v-for="fn in availableFilenames" :key="fn" :value="fn" class="bg-[#111827] text-white">{{ fn }}</option>
        </select>
      </div>
    </div>

    <!-- Semantic DB Query 專用參數：筆數/字數上限（可調整覆寫全域預設值） -->
    <div v-if="paramsStore.searchMode === 'semantic_db_query'" class="flex flex-col gap-3 border-t border-white/8 pt-4">
      <label class="flex items-center gap-2 text-xs text-[#9ca3af] cursor-pointer">
        <input
          type="checkbox"
          v-model="paramsStore.dbQueryAutoKb"
          class="rounded bg-white/5 border-white/10 text-[#8b5cf6] focus:ring-[#8b5cf6]/50 cursor-pointer"
        />
        不限定知識庫（讓 AI 自動掃描所有知識庫並判斷使用哪個查詢設定檔）
      </label>
      <div class="flex flex-col gap-1.5">
        <label class="text-[11px] text-[#9ca3af]">查詢筆數上限 (Max Rows)</label>
        <input
          v-model.number="paramsStore.dbQueryMaxRows"
          type="number"
          min="1"
          placeholder="預設 50"
          class="bg-white/5 border border-white/8 rounded-lg text-white px-3 py-2 text-xs focus:outline-none focus:border-[#8b5cf6]"
        />
      </div>
      <div class="flex flex-col gap-1.5">
        <label class="text-[11px] text-[#9ca3af]">結果字數上限 (Max Chars)</label>
        <input
          v-model.number="paramsStore.dbQueryMaxChars"
          type="number"
          min="1"
          placeholder="預設 4000"
          class="bg-white/5 border border-white/8 rounded-lg text-white px-3 py-2 text-xs focus:outline-none focus:border-[#8b5cf6]"
        />
      </div>
    </div>
  </div>
</template>
