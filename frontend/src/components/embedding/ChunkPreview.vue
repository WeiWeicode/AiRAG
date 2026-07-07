<script setup>
import { ref, watch } from 'vue'
import imageService from '../../services/imageService'

const props = defineProps({
  chunks: {
    type: Array,
    required: true
  }
})

const imageUrls = ref({})
const imageLoadFailed = ref({})

const loadChunkImages = async () => {
  for (const chunk of props.chunks) {
    if (chunk.metadata?.chunk_type === 'image') {
      const filename = chunk.metadata?.image_filename
      if (filename && !imageUrls.value[filename] && !imageLoadFailed.value[filename]) {
        try {
          const url = await imageService.fetchImageBlobUrl(filename)
          imageUrls.value[filename] = url
        } catch (err) {
          console.error('Failed to load image blob:', err)
          // 圖片端點需要 JWT，直接用 <img src="/api/..."> 一定會 401，不設無意義的 fallback 網址，
          // 改記錄載入失敗狀態讓畫面顯示明確的失敗佔位圖
          imageLoadFailed.value[filename] = true
        }
      }
    }
  }
}

watch(() => props.chunks, () => {
  loadChunkImages()
}, { immediate: true, deep: true })

const downloadImage = (filename) => {
  imageService.download(filename, filename)
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <div 
      v-for="chunk in chunks" 
      :key="chunk.index" 
      class="border border-white/8 rounded-xl p-4 bg-[#8b5cf6]/2 relative pt-6 hover:border-white/16 hover:bg-[#8b5cf6]/4 transition-all duration-200"
    >
      <!-- Chunk Index Tag -->
      <div class="absolute -top-2 left-3 text-[10px] font-bold bg-[#111827] text-[#a78bfa] border border-white/8 px-1.5 py-0.5 rounded flex items-center gap-1.5 select-none">
        <span>Chunk #{{ chunk.index + 1 }}</span>
        <span v-if="chunk.metadata?.chunk_type === 'image'" class="bg-purple-500/10 border border-purple-500/20 text-[#a78bfa] px-1 py-0.5 rounded text-[8px] font-bold">
          🖼️ 圖片段落
        </span>
      </div>
      
      <!-- Chunk Content (Image vs Text) -->
      <div v-if="chunk.metadata?.chunk_type === 'image'" class="flex flex-col sm:flex-row gap-4 items-start bg-black/20 p-3 rounded-lg border border-white/3">
        <div class="w-full sm:w-48 h-32 rounded-lg bg-black/40 flex items-center justify-center overflow-hidden border border-white/8 relative group flex-shrink-0">
          <img
            v-if="imageUrls[chunk.metadata.image_filename]"
            :src="imageUrls[chunk.metadata.image_filename]"
            class="max-h-full max-w-full object-contain"
            alt="Document Image"
          />
          <div v-else-if="imageLoadFailed[chunk.metadata.image_filename]" class="flex flex-col items-center gap-1 text-[#6b7280] text-[10px]">
            <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/>
              <line x1="4" y1="4" x2="20" y2="20"/>
            </svg>
            圖片載入失敗
          </div>
          <svg v-else class="animate-spin h-5 w-5 text-[#6b7280]" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
          <div v-if="imageUrls[chunk.metadata.image_filename]" class="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
            <button
              @click="downloadImage(chunk.metadata.image_filename)"
              class="p-2 bg-[#8b5cf6] hover:bg-[#a78bfa] rounded-full text-white transition-all shadow-lg cursor-pointer"
              title="下載原圖"
            >
              <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>
              </svg>
            </button>
          </div>
        </div>
        <div class="flex-grow flex flex-col gap-1.5 w-full">
          <span class="text-[10px] font-semibold text-[#a78bfa] uppercase tracking-wider select-none">圖片描述 (AI Generated Caption)</span>
          <p class="text-xs text-white leading-relaxed whitespace-pre-wrap">
            {{ chunk.content }}
          </p>
        </div>
      </div>
      
      <div v-else class="text-xs text-[#9ca3af] leading-relaxed whitespace-pre-wrap bg-black/20 p-3 rounded-lg border border-white/3">
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
