<script setup>
defineProps({
  chunks: {
    type: Array,
    required: true
  }
})
</script>

<template>
  <div class="flex flex-col gap-4">
    <div 
      v-for="chunk in chunks" 
      :key="chunk.index" 
      class="border border-white/8 rounded-xl p-4 bg-[#8b5cf6]/2 relative pt-6 hover:border-white/16 hover:bg-[#8b5cf6]/4 transition-all duration-200"
    >
      <!-- Chunk Index Tag -->
      <div class="absolute -top-2 left-3 text-[10px] font-bold bg-[#111827] text-[#a78bfa] border border-white/8 px-1.5 py-0.5 rounded">
        Chunk #{{ chunk.index + 1 }}
      </div>
      
      <!-- Chunk Content -->
      <div class="text-xs text-[#9ca3af] leading-relaxed whitespace-pre-wrap bg-black/20 p-3 rounded-lg border border-white/3">
        {{ chunk.content }}
      </div>

      <!-- Chunk Info Footer -->
      <div class="flex justify-end gap-3.5 text-[10px] text-[#6b7280] mt-2 pt-1.5 border-t border-white/3">
        <span>字數: {{ chunk.char_count || chunk.content.length }} 字</span>
        <span>估算 Tokens: {{ chunk.token_count || Math.round(chunk.content.length * 1.3) }}</span>
      </div>
    </div>
  </div>
</template>
