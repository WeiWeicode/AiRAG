<script setup>
import { ref } from 'vue'
import StreamRenderer from './StreamRenderer.vue'
import SourceChunks from './SourceChunks.vue'
import attachmentService from '../../services/attachmentService'

const props = defineProps({
  message: {
    type: Object,
    required: true
  }
})

const emit = defineEmits(['dislike', 'select-db-profile'])

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

const isThinkingExpanded = ref(true)
const toggleThinking = () => {
  isThinkingExpanded.value = !isThinkingExpanded.value
}

const downloadAttachment = async (id, filename) => {
  try {
    await attachmentService.download(id, filename)
  } catch (error) {
    console.error('下載附件失敗:', error)
    alert('下載附件失敗，請確認後端連線。')
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
        <!-- RAG Steps Process (for semantic_hybrid / step-enabled RAG) -->
        <div v-if="message.steps && message.steps.length > 0" class="mb-4 flex flex-col gap-2">
          <div class="text-[10px] text-white/40 font-semibold uppercase tracking-wider mb-1">語義混合查詢分析步驟</div>
          
          <div 
            v-for="step in message.steps" 
            :key="step.key" 
            class="border border-white/10 rounded-xl bg-white/3 overflow-hidden transition-all"
            :class="{ 'border-purple-500/20 bg-purple-500/2': step.status === 'running' }"
          >
            <!-- Step Header -->
            <button 
              @click="step.expanded = !step.expanded"
              class="w-full flex items-center justify-between px-4 py-2.5 text-xs text-white/70 hover:text-white hover:bg-white/5 transition-all focus:outline-none"
            >
              <div class="flex items-center gap-2.5">
                <!-- Status icon -->
                <span v-if="step.status === 'pending'" class="w-3.5 h-3.5 rounded-full border border-white/20 flex-shrink-0"></span>
                <svg v-else-if="step.status === 'running'" class="animate-spin h-3.5 w-3.5 text-purple-400 flex-shrink-0" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                <svg v-else-if="step.status === 'success'" class="h-3.5 w-3.5 text-emerald-400 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
                <svg v-else-if="step.status === 'failed'" class="h-3.5 w-3.5 text-red-400 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18"></line>
                  <line x1="6" y1="6" x2="18" y2="18"></line>
                </svg>
                <span class="font-semibold">{{ step.name }}</span>
                <span v-if="step.status === 'running'" class="text-[9px] bg-purple-500/20 text-purple-300 px-1.5 py-0.5 rounded font-normal animate-pulse">執行中</span>
              </div>
              
              <!-- Chevron -->
              <svg 
                class="w-3.5 h-3.5 transition-transform duration-200 text-white/40" 
                :class="{ 'rotate-180': step.expanded }"
                viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
              >
                <polyline points="6 9 12 15 18 9"></polyline>
              </svg>
            </button>
            
            <!-- Step Content -->
            <div 
              v-show="step.expanded"
              class="px-4 pb-3.5 pt-1.5 border-t border-white/5 text-xs text-white/60 whitespace-pre-wrap font-mono leading-relaxed max-h-[300px] overflow-y-auto bg-[#0a0f1d]/50"
            >
              {{ step.content || '尚無詳細資訊...' }}
            </div>
          </div>
        </div>

        <!-- 語義資料庫查詢法：候選查詢設定檔選取 -->
        <div v-if="message.awaitingProfileSelection && message.dbQueryCandidates?.length" class="mb-4 flex flex-col gap-2">
          <div class="text-[10px] text-white/40 font-semibold uppercase tracking-wider mb-1">找到以下候選查詢設定檔，請選擇其中一個以繼續查詢</div>
          <button
            v-for="c in message.dbQueryCandidates"
            :key="c.profile_id"
            @click="emit('select-db-profile', message.id, c.profile_id)"
            class="text-left border border-white/10 hover:border-purple-500/40 rounded-xl bg-white/3 hover:bg-white/5 px-4 py-2.5 transition-all"
          >
            <div class="flex justify-between items-center">
              <span class="text-xs font-semibold text-white">{{ c.name }}</span>
              <span class="text-[10px] text-emerald-400 font-display">Score: {{ c.score.toFixed(4) }}</span>
            </div>
            <div class="text-[11px] text-white/50 mt-0.5">表格: {{ c.table_name }}｜{{ c.table_purpose }}</div>
          </button>
        </div>

        <!-- Thinking Process Accordion (Fallback，只在沒有結構化 steps 列表時顯示，避免與 steps 內的「思考中」步驟重複) -->
        <div v-if="!(message.steps && message.steps.length > 0) && (message.thinking || message.isThinking)" class="mb-3 border border-white/10 rounded-xl bg-white/5 overflow-hidden">
          <button 
            @click="toggleThinking"
            class="w-full flex items-center justify-between px-4 py-2.5 text-xs text-white/60 hover:text-white/90 hover:bg-white/5 transition-all focus:outline-none"
          >
            <div class="flex items-center gap-2">
              <!-- Loading spinner or check icon -->
              <svg v-if="message.isThinking" class="animate-spin h-3.5 w-3.5 text-purple-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              <svg v-else class="h-3.5 w-3.5 text-emerald-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="20 6 9 17 4 12"></polyline>
              </svg>
              <span>{{ message.isThinking ? '思考中...' : '已完成思考' }}</span>
            </div>
            <!-- Chevron -->
            <svg 
              class="w-3.5 h-3.5 transition-transform duration-200" 
              :class="{ 'rotate-180': isThinkingExpanded }"
              viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
            >
              <polyline points="6 9 12 15 18 9"></polyline>
            </svg>
          </button>
          
          <!-- Collapsible Content -->
          <div 
            v-show="isThinkingExpanded"
            class="px-4 pb-3 pt-1 border-t border-white/5 text-xs text-white/50 whitespace-pre-wrap font-mono leading-relaxed max-h-[250px] overflow-y-auto"
          >
            {{ message.thinking || '正在整理思緒...' }}
          </div>
        </div>

        <!-- Renders content using markdown renderer for assistant -->
        <StreamRenderer v-if="message.role === 'assistant'" :content="message.content" />
        <div v-else class="white-space-pre-wrap text-sm leading-relaxed">{{ message.content }}</div>

        <!-- Citation references -->
        <SourceChunks v-if="message.sources && message.sources.length > 0" :sources="message.sources" :context-summary="message.contextSummary" />

        <!-- Attachment references -->
        <div v-if="message.attachments && message.attachments.length > 0" class="mt-4 flex flex-col gap-2">
          <div class="text-[11px] font-bold text-[#a78bfa] uppercase tracking-wider flex items-center gap-1.5 select-none">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"></path>
            </svg>
            相關參考附件 ({{ message.attachments.length }})
          </div>
          <div class="flex flex-col gap-2">
            <div 
              v-for="att in message.attachments" 
              :key="att.id"
              class="bg-white/3 border border-white/8 rounded-xl p-3 hover:bg-white/5 hover:border-white/12 transition-all flex justify-between items-center gap-4"
            >
              <div class="flex flex-col gap-1 min-w-0">
                <span class="text-xs font-semibold text-white truncate" :title="att.original_filename">
                  📂 {{ att.original_filename }}
                </span>
                <p v-if="att.description" class="text-[11px] text-[#9ca3af] leading-relaxed whitespace-pre-wrap">
                  {{ att.description }}
                </p>
              </div>
              <button 
                @click="downloadAttachment(att.id, att.original_filename)"
                class="flex-shrink-0 bg-[#8b5cf6] hover:bg-[#a78bfa] text-white p-1.5 rounded-lg transition-all flex items-center justify-center cursor-pointer"
                title="下載附件"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                  <polyline points="7 10 12 15 17 10"></polyline>
                  <line x1="12" y1="15" x2="12" y2="3"></line>
                </svg>
              </button>
            </div>
          </div>
        </div>

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
