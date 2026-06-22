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
  </div>
</template>
