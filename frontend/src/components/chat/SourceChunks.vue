<script setup>
defineProps({
  sources: {
    type: Array,
    required: true
  },
  contextSummary: {
    type: Object,
    default: null
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

    <!-- Token 統計摘要：總計 Token 數與分批摘要（Map-Reduce）切分次數 -->
    <div
      v-if="contextSummary"
      class="text-[10px] text-[#9ca3af] bg-white/3 border border-white/8 rounded-lg px-3 py-1.5 flex flex-wrap items-center gap-x-3 gap-y-1"
    >
      <span>總計 Token：<span class="text-[#a78bfa] font-semibold font-display">{{ contextSummary.total_tokens?.toLocaleString() ?? 0 }}</span></span>
      <span v-if="contextSummary.was_summarized">
        已觸發分批摘要（門檻 {{ contextSummary.threshold_tokens?.toLocaleString() }}）：切分
        <span class="text-[#a78bfa] font-semibold font-display">{{ contextSummary.batch_count }}</span> 次整理 /
        <span class="text-[#a78bfa] font-semibold font-display">{{ contextSummary.rounds }}</span> 輪思考
      </span>
      <span v-else>未超過門檻（{{ contextSummary.threshold_tokens?.toLocaleString() }}），未進行分批摘要</span>
    </div>

    <div
      v-for="(source, idx) in sources" 
      :key="idx" 
      class="group relative bg-white/3 border border-white/8 px-3 py-1.5 rounded-lg flex items-center justify-between gap-4 text-xs hover:bg-white/8 hover:border-white/16 transition-all cursor-help"
    >
      <span class="truncate">
        [{{ source.file || source.metadata?.filename || '未知檔案' }}] 
        段落: #{{ (source.chunk_index !== undefined && source.chunk_index !== null) ? source.chunk_index : (source.metadata?.chunk_index !== undefined && source.metadata?.chunk_index !== null ? source.metadata.chunk_index : '?') }}
      </span>
      <span class="flex items-center gap-1.5 flex-shrink-0">
        <span
          v-if="source.token_count !== undefined"
          class="bg-white/8 text-[#9ca3af] font-semibold font-display px-1.5 py-0.5 rounded text-[10px]"
        >
          Tokens: {{ source.token_count }}
        </span>
        <span class="bg-[#8b5cf6]/15 text-[#a78bfa] font-semibold font-display px-1.5 py-0.5 rounded text-[10px]">
          Similarity: {{ (source.score !== undefined ? source.score : 0).toFixed(2) }}
        </span>
      </span>

      <!-- Tooltip Content Popup Wrapper (bridges gap with pb-2, allows hover persistence) -->
      <div class="pointer-events-auto absolute left-4 bottom-full pb-2 w-96 scale-95 origin-bottom-left opacity-0 invisible group-hover:opacity-100 group-hover:visible group-hover:scale-100 transition-all duration-200 z-50">
        <!-- Styled Inner Box -->
        <div class="bg-[#0f172a]/95 border border-[#8b5cf6]/40 shadow-[0_10px_30px_rgba(0,0,0,0.6)] backdrop-blur-md rounded-xl p-3.5 text-[11px] text-[#e2e8f0] whitespace-pre-wrap leading-relaxed relative">
          <div class="text-[10px] font-bold text-[#a78bfa] border-b border-white/10 pb-1 mb-1.5 flex justify-between items-center">
            <span>📄 Chunk 內容詳情</span>
            <span class="text-[9px] text-[#9ca3af] font-normal">段落 #{{ (source.chunk_index !== undefined && source.chunk_index !== null) ? source.chunk_index : (source.metadata?.chunk_index ?? '?') }}</span>
          </div>
          <div class="font-mono text-left max-h-48 overflow-y-auto pr-1 select-all scrollbar-thin">
            {{ source.content || '無內容' }}
          </div>
          <!-- Arrow -->
          <div class="absolute top-full left-4 -mt-1 w-2.5 h-2.5 bg-[#0f172a] border-r border-b border-[#8b5cf6]/40 rotate-45"></div>
        </div>
      </div>
    </div>
  </div>
</template>
