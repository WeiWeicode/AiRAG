<script setup>
import { ref, watch, computed } from 'vue'
import imageService from '../../services/imageService'

const props = defineProps({
  sources: {
    type: Array,
    required: true
  },
  contextSummary: {
    type: Object,
    default: null
  }
})

const textSources = computed(() => {
  return props.sources.filter(s => s.metadata?.chunk_type !== 'image')
})

// 圖片來源比照文字 Chunk 的列表樣式呈現（見文件引用區塊），Hover 時放大顯示圖片與描述，
// 並在列表右側直接提供下載 icon，取代先前小縮圖網格（縮圖太小看不清楚內容）的呈現方式。
const imageSources = computed(() => {
  // Collect direct image sources
  const directImages = props.sources.filter(s => s.metadata?.chunk_type === 'image')

  // Collect nested image chunks from text sources.
  // 這些圖片是靠 parent_id 撈出的「同段落兄弟節點」，並非各自被向量檢索獨立命中，
  // 本身沒有相似度分數——不可沿用宿主 source 的 score（會讓使用者誤以為每張圖都被
  // 獨立高度檢索命中），改標記 isSibling 讓樣板改顯示「同段落」而非假造的相似度數字。
  const nestedImages = []
  props.sources.forEach(s => {
    if (s.metadata?.image_chunks && Array.isArray(s.metadata.image_chunks)) {
      s.metadata.image_chunks.forEach(img => {
        nestedImages.push({
          chunk_id: img.chunk_id,
          content: img.content,
          metadata: {
            filename: img.metadata?.filename || s.metadata?.filename,
            page: img.metadata?.page || s.metadata?.page,
            chunk_type: 'image',
            image_filename: img.metadata?.image_filename,
            chunk_index: img.metadata?.chunk_index
          },
          isSibling: true,
          token_count: img.token_count || 0
        })
      })
    }
  })

  // Combine and deduplicate by image_filename to avoid rendering duplicates
  const combined = [...directImages, ...nestedImages]
  const seen = new Set()
  const unique = []
  for (const item of combined) {
    const filename = item.metadata?.image_filename
    if (filename && !seen.has(filename)) {
      seen.add(filename)
      unique.push(item)
    }
  }
  return unique
})

const imageUrls = ref({})
const imageLoadFailed = ref({})

const loadSourceImages = async () => {
  for (const source of imageSources.value) {
    const filename = source.metadata?.image_filename
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

watch(imageSources, () => {
  loadSourceImages()
}, { immediate: true })

const downloadImage = (filename) => {
  imageService.download(filename, filename)
}
</script>

<template>
  <div class="mt-3 pt-2.5 border-t border-dashed border-white/8 flex flex-col gap-2.5">

    <!-- Token 統計摘要：總計 Token 數與分批摘要（Map-Reduce）切分次數 -->
    <div
      v-if="contextSummary"
      class="text-[10px] text-[#9ca3af] bg-white/3 border border-white/8 rounded-lg px-3 py-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 select-none"
    >
      <span>總計 Token：<span class="text-[#a78bfa] font-semibold font-display">{{ contextSummary.total_tokens?.toLocaleString() ?? 0 }}</span></span>
      <span v-if="contextSummary.was_summarized">
        已觸發分批摘要（門檻 {{ contextSummary.threshold_tokens?.toLocaleString() }}）：切分
        <span class="text-[#a78bfa] font-semibold font-display">{{ contextSummary.batch_count }}</span> 次整理 /
        <span class="text-[#a78bfa] font-semibold font-display">{{ contextSummary.rounds }}</span> 輪思考
      </span>
      <span v-else>未超過門檻（{{ contextSummary.threshold_tokens?.toLocaleString() }}），未進行分批摘要</span>
    </div>

    <!-- 📄 參考文檔引用 (Chunks) -->
    <div v-if="textSources.length > 0" class="flex flex-col gap-1.5">
      <div class="text-[11px] font-semibold text-[#9ca3af] flex items-center gap-1.5 select-none">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="flex-shrink-0">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
          <polyline points="14 2 14 8 20 8"></polyline>
          <line x1="16" y1="13" x2="8" y2="13"></line>
          <line x1="16" y1="17" x2="8" y2="17"></line>
        </svg>
        參考文檔引用 (Chunks)
      </div>

      <div
        v-for="(source, idx) in textSources"
        :key="'text-' + idx"
        class="group relative bg-white/3 border border-white/8 px-3 py-1.5 rounded-lg flex items-center justify-between gap-4 text-xs hover:bg-white/8 hover:border-white/16 transition-all cursor-help"
      >
        <span class="truncate" :class="{ 'opacity-60': source.metadata?.included_in_ai_context === false }">
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
          <span 
            v-if="source.metadata?.included_in_ai_context === false"
            class="bg-rose-500/15 text-rose-300 font-semibold font-display px-1.5 py-0.5 rounded text-[10px]"
            title="此片段相似度低於 AI 總結門檻，已排除於總結脈絡外"
          >
            未採納
          </span>
          <span 
            v-else-if="source.metadata?.included_in_ai_context === true"
            class="bg-emerald-500/15 text-emerald-300 font-semibold font-display px-1.5 py-0.5 rounded text-[10px]"
          >
            已採納
          </span>
          <span 
            :class="source.metadata?.included_in_ai_context === false ? 'bg-white/5 text-slate-400' : 'bg-[#8b5cf6]/15 text-[#a78bfa]'"
            class="font-semibold font-display px-1.5 py-0.5 rounded text-[10px]"
          >
            Similarity: {{ ((source.semantic_score !== undefined ? source.semantic_score : (source.score !== undefined ? source.score : 0))).toFixed(2) }}
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

    <!-- 🖼️ 參考圖片引用 (Image Chunks) -->
    <div v-if="imageSources.length > 0" class="flex flex-col gap-1.5">
      <div class="text-[11px] font-semibold text-[#9ca3af] flex items-center gap-1.5 select-none">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="flex-shrink-0">
          <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
          <circle cx="8.5" cy="8.5" r="1.5"></circle>
          <polyline points="21 15 16 10 5 21"></polyline>
        </svg>
        參考圖片引用 (Image Chunks)
      </div>

      <div
        v-for="(source, idx) in imageSources"
        :key="'image-' + idx"
        class="group relative bg-white/3 border border-white/8 px-3 py-1.5 rounded-lg flex items-center justify-between gap-4 text-xs hover:bg-white/8 hover:border-white/16 transition-all cursor-help"
      >
        <span class="truncate" :class="{ 'opacity-60': source.metadata?.included_in_ai_context === false }">
          🖼️ [{{ source.metadata?.filename || '未知檔案' }}]
          段落: #{{ (source.chunk_index !== undefined && source.chunk_index !== null) ? source.chunk_index : (source.metadata?.chunk_index !== undefined && source.metadata?.chunk_index !== null ? source.metadata.chunk_index : '?') }}
        </span>
        <span class="flex items-center gap-1.5 flex-shrink-0">
          <span
            v-if="source.token_count"
            class="bg-white/8 text-[#9ca3af] font-semibold font-display px-1.5 py-0.5 rounded text-[10px]"
          >
            Tokens: {{ source.token_count }}
          </span>
          <span
            v-if="source.isSibling"
            class="bg-white/8 text-[#9ca3af] font-semibold font-display px-1.5 py-0.5 rounded text-[10px]"
            title="透過同一段落 (parent_id) 帶出，非查詢獨立命中，無相似度分數"
          >
            同段落
          </span>
          <span 
            v-else-if="source.metadata?.included_in_ai_context === false"
            class="bg-rose-500/15 text-rose-300 font-semibold font-display px-1.5 py-0.5 rounded text-[10px]"
          >
            未採納
          </span>
          <span 
            v-else-if="source.metadata?.included_in_ai_context === true"
            class="bg-emerald-500/15 text-emerald-300 font-semibold font-display px-1.5 py-0.5 rounded text-[10px]"
          >
            已採納
          </span>
          <span v-if="!source.isSibling" :class="source.metadata?.included_in_ai_context === false ? 'bg-white/5 text-slate-400' : 'bg-[#8b5cf6]/15 text-[#a78bfa]'" class="font-semibold font-display px-1.5 py-0.5 rounded text-[10px]">
            Similarity: {{ ((source.semantic_score !== undefined ? source.semantic_score : (source.score !== undefined ? source.score : 0))).toFixed(2) }}
          </span>
          <!-- 下載圖片 icon -->
          <button
            @click.stop="downloadImage(source.metadata.image_filename)"
            class="bg-white/8 hover:bg-[#8b5cf6] text-[#9ca3af] hover:text-white p-1 rounded transition-all flex items-center justify-center cursor-pointer"
            title="下載原圖"
          >
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="7 10 12 15 17 10"></polyline>
              <line x1="12" y1="15" x2="12" y2="3"></line>
            </svg>
          </button>
        </span>

        <!-- Tooltip Content Popup Wrapper：放大顯示圖片縮圖與描述，解決小縮圖看不清楚的問題 -->
        <div class="pointer-events-auto absolute left-4 bottom-full pb-2 w-96 scale-95 origin-bottom-left opacity-0 invisible group-hover:opacity-100 group-hover:visible group-hover:scale-100 transition-all duration-200 z-50">
          <!-- Styled Inner Box -->
          <div class="bg-[#0f172a]/95 border border-[#8b5cf6]/40 shadow-[0_10px_30px_rgba(0,0,0,0.6)] backdrop-blur-md rounded-xl p-3.5 text-[11px] text-[#e2e8f0] whitespace-pre-wrap leading-relaxed relative">
            <div class="text-[10px] font-bold text-[#a78bfa] border-b border-white/10 pb-1 mb-1.5 flex justify-between items-center">
              <span>🖼️ 圖片 Chunk 詳情</span>
              <span class="text-[9px] text-[#9ca3af] font-normal">段落 #{{ (source.chunk_index !== undefined && source.chunk_index !== null) ? source.chunk_index : (source.metadata?.chunk_index ?? '?') }}</span>
            </div>
            <!-- Image preview block（放大呈現，比原本的小縮圖網格更容易看清楚內容） -->
            <div class="mb-2 h-56 rounded-lg bg-black/40 flex items-center justify-center overflow-hidden border border-white/5 relative">
              <img
                v-if="imageUrls[source.metadata.image_filename]"
                :src="imageUrls[source.metadata.image_filename]"
                class="max-h-full max-w-full object-contain"
                alt="Retrieved source image"
              />
              <div v-else-if="imageLoadFailed[source.metadata.image_filename]" class="flex flex-col items-center gap-1 text-[#6b7280] text-[10px]">
                <svg class="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/>
                  <line x1="4" y1="4" x2="20" y2="20"/>
                </svg>
                圖片載入失敗
              </div>
              <svg v-else class="animate-spin h-6 w-6 text-[#6b7280]" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
            </div>
            <div class="font-mono text-left max-h-32 overflow-y-auto pr-1 select-all scrollbar-thin">
              {{ source.content || '無內容' }}
            </div>
            <!-- Arrow -->
            <div class="absolute top-full left-4 -mt-1 w-2.5 h-2.5 bg-[#0f172a] border-r border-b border-[#8b5cf6]/40 rotate-45"></div>
          </div>
        </div>
      </div>
    </div>

  </div>
</template>
