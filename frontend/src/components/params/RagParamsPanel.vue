<script setup>
import { useParamsStore } from '../../stores/paramsStore'
import KnowledgeBaseSelector from '../common/KnowledgeBaseSelector.vue'

const paramsStore = useParamsStore()
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
        <option value="semantic_db_query" class="bg-[#111827] text-white">語義資料庫查詢法 (Semantic DB Query)</option>
      </select>
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
