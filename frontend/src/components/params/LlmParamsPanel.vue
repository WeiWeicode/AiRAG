<script setup>
import { useParamsStore } from '../../stores/paramsStore'

const paramsStore = useParamsStore()
</script>

<template>
  <div class="flex flex-col gap-5 bg-white/3 border border-white/8 rounded-2xl p-5 backdrop-blur-md">
    <div class="text-sm font-bold text-white border-b border-white/8 pb-2 tracking-wider">
      生成模型設定 (Generation)
    </div>

    <!-- Model Selection -->
    <div class="flex flex-col gap-2">
      <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">模型 (LLM Model)</label>
      <select 
        v-model="paramsStore.model" 
        class="bg-white/5 border border-white/8 rounded-lg text-white px-3.5 py-2.5 text-sm focus:outline-none focus:border-[#8b5cf6] transition-all"
      >
        <option value="Qwen3.6-35B-A3B-FP8" class="bg-[#111827] text-white">Qwen3.6-35B-A3B-FP8 (vLLM)</option>
      </select>
    </div>

    <!-- Temperature Slider -->
    <div class="flex flex-col gap-2">
      <div class="flex justify-between items-center">
        <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">溫度參數 (Temperature)</label>
        <span class="text-xs font-bold text-[#a78bfa] font-display">{{ paramsStore.temperature }}</span>
      </div>
      <input 
        v-model.number="paramsStore.temperature" 
        type="range" 
        min="0" 
        max="1.5" 
        step="0.1" 
        class="w-full h-1 bg-white/10 rounded-lg appearance-none cursor-pointer accent-[#8b5cf6]"
      />
    </div>

    <!-- Max Tokens Slider -->
    <div class="flex flex-col gap-2">
      <div class="flex justify-between items-center">
        <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">最大 Token 數 (Max Tokens)</label>
        <span class="text-xs font-bold text-[#a78bfa] font-display">{{ paramsStore.maxTokens }}</span>
      </div>
      <input 
        v-model.number="paramsStore.maxTokens" 
        type="range" 
        min="256" 
        max="22768" 
        step="128" 
        class="w-full h-1 bg-white/10 rounded-lg appearance-none cursor-pointer accent-[#8b5cf6]"
      />
    </div>
  </div>
</template>
