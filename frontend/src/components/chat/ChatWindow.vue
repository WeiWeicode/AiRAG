<script setup>
import { ref, watch, nextTick, onMounted } from 'vue'
import { useChatStore } from '../../stores/chatStore'
import MessageBubble from './MessageBubble.vue'
import FeedbackPanel from './FeedbackPanel.vue'

const chatStore = useChatStore()

const inputMessage = ref('')
const messageContainer = ref(null)

// Feedback Modal State
const isFeedbackOpen = ref(false)
const selectedMessageId = ref('')
const selectedQuery = ref('')
const selectedContent = ref('')

const handleSend = async () => {
  const query = inputMessage.value.trim()
  if (!query || chatStore.isLoading) return
  
  inputMessage.value = ''
  await chatStore.sendQuestion(query)
}

const handleCtrlEnter = (e) => {
  if (e.ctrlKey) {
    handleSend()
  }
}

// Open Feedback modal when dislike is clicked
const openFeedbackModal = (messageId) => {
  const msgIndex = chatStore.messages.findIndex(m => m.id === messageId)
  if (msgIndex !== -1) {
    const assistantMsg = chatStore.messages[msgIndex]
    // The query corresponds to the user message immediately preceding the assistant message
    const userMsg = msgIndex > 0 ? chatStore.messages[msgIndex - 1] : null
    
    selectedMessageId.value = messageId
    selectedQuery.value = userMsg ? userMsg.content : ''
    selectedContent.value = assistantMsg.content
    
    isFeedbackOpen.value = true
  }
}

const scrollToBottom = () => {
  if (messageContainer.value) {
    messageContainer.value.scrollTop = messageContainer.value.scrollHeight
  }
}

// Auto scroll on new messages
watch(() => chatStore.messages, () => {
  nextTick(() => {
    scrollToBottom()
  })
}, { deep: true })

onMounted(() => {
  scrollToBottom()
})
</script>

<template>
  <div class="flex-grow flex flex-col bg-[#111827]/40 border border-white/8 rounded-2xl overflow-hidden relative">
    <!-- Messages Box -->
    <div 
      ref="messageContainer"
      class="flex-grow p-6 overflow-y-auto flex flex-col gap-5"
    >
      <MessageBubble 
        v-for="msg in chatStore.messages" 
        :key="msg.id" 
        :message="msg"
        @dislike="openFeedbackModal"
      />
    </div>

    <!-- Input Area -->
    <div class="p-5 bg-[#111827]/60 border-t border-white/8 flex gap-3 flex-shrink-0">
      <div class="flex-grow relative">
        <input 
          v-model="inputMessage"
          type="text" 
          class="w-full bg-[#111827] border border-white/10 rounded-xl text-white px-4 py-3.5 pr-20 text-sm focus:outline-none focus:border-[#8b5cf6] focus:ring-2 focus:ring-[#8b5cf6]/15 transition-all"
          placeholder="輸入問題... (例如: 公司請假規定為何？)"
          @keydown.enter="handleCtrlEnter"
          :disabled="chatStore.isLoading"
          autocomplete="off"
        />
        <div class="absolute right-3.5 top-1/2 -translate-y-1/2 flex gap-1">
          <span class="bg-white/8 border border-white/8 px-1.5 py-0.5 rounded text-[10px] text-[#9ca3af]">Ctrl+Enter</span>
        </div>
      </div>
      <button 
        @click="handleSend"
        :disabled="chatStore.isLoading || !inputMessage.trim()"
        class="bg-[#8b5cf6] hover:bg-[#a78bfa] disabled:bg-purple-900/50 disabled:text-purple-300/50 hover:shadow-[0_4px_12px_rgba(139,92,246,0.3)] text-white font-semibold px-5 py-3 rounded-xl text-sm flex items-center justify-center gap-2 transition-all flex-shrink-0"
      >
        <span>{{ chatStore.isLoading ? '傳送中...' : '發送' }}</span>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="flex-shrink-0">
          <line x1="22" y1="2" x2="11" y2="13"></line>
          <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
        </svg>
      </button>
    </div>

    <!-- Feedback Modal -->
    <FeedbackPanel 
      :is-open="isFeedbackOpen"
      :message-id="selectedMessageId"
      :query="selectedQuery"
      :content="selectedContent"
      @close="isFeedbackOpen = false"
      @saved="isFeedbackOpen = false"
    />
  </div>
</template>
