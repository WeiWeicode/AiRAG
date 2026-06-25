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
        max="15" 
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
      </select>
    </div>
  </div>
</template>
