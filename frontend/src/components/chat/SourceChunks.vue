<script setup>
defineProps({
  sources: {
    type: Array,
    required: true
  }
})
</script>

<template>
  <div class="mt-3 pt-2.5 border-t border-dashed border-white/8 flex flex-col gap-2">
    <div class="text-[11px] font-semibold text-[#9ca3af] flex items-center gap-1.5">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="flex-shrink-0">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
        <polyline points="14 2 14 8 20 8"></polyline>
        <line x1="16" y1="13" x2="8" y2="13"></line>
        <line x1="16" y1="17" x2="8" y2="17"></line>
      </svg>
      參考文檔引用 (Chunks)
    </div>
    <div 
      v-for="(source, idx) in sources" 
      :key="idx" 
      class="bg-white/3 border border-white/8 px-3 py-1.5 rounded-lg flex items-center justify-between gap-4 text-xs hover:bg-white/8 hover:border-white/16 transition-all"
    >
      <span class="truncate">
        [{{ source.file || source.metadata?.filename || '未知檔案' }}] 
        頁碼: P.{{ source.page || source.metadata?.page || '?' }}
      </span>
      <span class="bg-[#8b5cf6]/15 text-[#a78bfa] font-semibold font-display px-1.5 py-0.5 rounded text-[10px] flex-shrink-0">
        Similarity: {{ (source.score !== undefined ? source.score : 0).toFixed(2) }}
      </span>
    </div>
  </div>
</template>
