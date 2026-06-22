<script setup>
import { ref } from 'vue'
import StreamRenderer from './StreamRenderer.vue'
import SourceChunks from './SourceChunks.vue'

const props = defineProps({
  message: {
    type: Object,
    required: true
  }
})

const emit = defineEmits(['dislike'])

const likeState = ref(null) // null | 'like' | 'dislike'

const handleLike = () => {
  if (likeState.value === 'like') {
    likeState.value = null
  } else {
    likeState.value = 'like'
    // Visual indicator or simple alert/event could go here
  }
}

const handleDislike = () => {
  if (likeState.value === 'dislike') {
    likeState.value = null
  } else {
    likeState.value = 'dislike'
    emit('dislike', props.message.id)
  }
}
</script>

<template>
  <div 
    class="flex gap-4 max-w-[85%] animate-fade-in"
    :class="message.role === 'user' ? 'self-end flex-row-reverse' : 'self-start'"
  >
    <!-- Avatar -->
    <div 
      class="w-8 h-8 rounded-lg flex items-center justify-center text-xs font-bold flex-shrink-0"
      :class="message.role === 'user' 
        ? 'bg-[#8b5cf6] text-white' 
        : 'bg-[#1f2937] border border-white/8 text-[#f3f4f6]'"
    >
      {{ message.role === 'user' ? 'ME' : 'AI' }}
    </div>

    <!-- Bubble content -->
    <div class="flex flex-col">
      <div 
        class="px-[18px] py-3.5 rounded-2xl text-sm"
        :class="message.role === 'user'
          ? 'bg-[#8b5cf6]/15 border border-[#8b5cf6]/30 text-white rounded-tr-none'
          : 'bg-[#111827] border border-white/8 text-[#f3f4f6] rounded-tl-none'"
      >
        <!-- Renders content using markdown renderer for assistant -->
        <StreamRenderer v-if="message.role === 'assistant'" :content="message.content" />
        <div v-else class="white-space-pre-wrap text-sm leading-relaxed">{{ message.content }}</div>

        <!-- Citation references -->
        <SourceChunks v-if="message.sources && message.sources.length > 0" :sources="message.sources" />

        <!-- Feedback buttons (only for assistant responses) -->
        <div v-if="message.role === 'assistant' && message.id !== 'welcome'" class="mt-2.5 flex gap-2">
          <!-- Like Button -->
          <button 
            @click="handleLike"
            class="w-7 h-7 border border-white/8 rounded-md flex items-center justify-center text-[#6b7280] hover:text-[#f3f4f6] hover:bg-white/5 hover:border-white/16 transition-all"
            :class="{ '!text-[#10b981] !bg-emerald-500/10 !border-emerald-500/30': likeState === 'like' }"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"></path>
            </svg>
          </button>
          
          <!-- Dislike Button -->
          <button 
            @click="handleDislike"
            class="w-7 h-7 border border-white/8 rounded-md flex items-center justify-center text-[#6b7280] hover:text-[#f3f4f6] hover:bg-white/5 hover:border-white/16 transition-all"
            :class="{ '!text-[#ef4444] !bg-rose-500/10 !border-rose-500/30': likeState === 'dislike' }"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3"></path>
            </svg>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}
.animate-fade-in {
  animation: fadeIn 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}
</style>
