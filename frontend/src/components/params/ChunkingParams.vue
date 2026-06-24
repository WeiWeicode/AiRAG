<script setup>
import { useParamsStore } from '../../stores/paramsStore'
import KnowledgeBaseSelector from '../common/KnowledgeBaseSelector.vue'

const paramsStore = useParamsStore()
</script>

<template>
  <div class="flex flex-col gap-5 bg-white/3 border border-white/8 rounded-2xl p-5 backdrop-blur-md">
    <div class="text-sm font-bold text-white border-b border-white/8 pb-2 tracking-wider">
      Chunking 參數調優
    </div>

    <!-- Target Knowledge Base -->
    <KnowledgeBaseSelector />

    <!-- Chunk Size Slider -->
    <div class="flex flex-col gap-2">
      <div class="flex justify-between items-center">
        <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">Chunk Size (Token/字元)</label>
        <span class="text-xs font-bold text-[#a78bfa] font-display">{{ paramsStore.chunkSize }}</span>
      </div>
      <input 
        v-model.number="paramsStore.chunkSize" 
        type="range" 
        min="128" 
        max="1024" 
        step="64"
        class="w-full h-1 bg-white/10 rounded-lg appearance-none cursor-pointer accent-[#8b5cf6]"
      />
    </div>

    <!-- Overlap Size Slider -->
    <div class="flex flex-col gap-2">
      <div class="flex justify-between items-center">
        <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">Overlap Size</label>
        <span class="text-xs font-bold text-[#a78bfa] font-display">{{ paramsStore.chunkOverlap }}</span>
      </div>
      <input 
        v-model.number="paramsStore.chunkOverlap" 
        type="range" 
        min="0" 
        max="200" 
        step="10"
        class="w-full h-1 bg-white/10 rounded-lg appearance-none cursor-pointer accent-[#8b5cf6]"
      />
    </div>

    <!-- Separator Input -->
    <div class="flex flex-col gap-2">
      <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">切分符號 (Separator)</label>
      <input 
        v-model="paramsStore.separator"
        type="text" 
        class="bg-white/5 border border-white/8 rounded-lg text-white px-3.5 py-2.5 text-sm focus:outline-none focus:border-[#8b5cf6] font-mono"
        placeholder="例如: \n\n"
      />
    </div>

    <!-- Structure Text Option -->
    <div class="flex items-center gap-2.5 pt-1 border-t border-white/5 mt-1">
      <input 
        v-model="paramsStore.enableStructuring" 
        type="checkbox" 
        id="enableStructuring"
        class="w-4 h-4 rounded bg-white/5 border border-white/12 text-[#8b5cf6] focus:ring-[#8b5cf6]/50 cursor-pointer accent-[#8b5cf6]"
      />
      <label for="enableStructuring" class="text-xs font-semibold text-[#9ca3af] cursor-pointer select-none">
        啟用文字結構化 (Structure Text)
      </label>
    </div>
  </div>
</template>
