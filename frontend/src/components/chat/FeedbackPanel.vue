<script setup>
import { ref, watch } from 'vue'
import { useFeedbackStore } from '../../stores/feedbackStore'

const props = defineProps({
  isOpen: {
    type: Boolean,
    required: true
  },
  messageId: {
    type: String,
    required: true
  },
  query: {
    type: String,
    default: ''
  },
  content: {
    type: String,
    default: ''
  }
})

const emit = defineEmits(['close', 'saved'])
const feedbackStore = useFeedbackStore()

const isSubmitting = ref(false)
const selectedErrorTags = ref(new Set())
const groundTruth = ref('')
const note = ref('')

const errorTags = [
  { value: 'hallucination', label: '幻覺 (Hallucination)' },
  { value: 'incomplete', label: '資訊不完整' },
  { value: 'wrong_source', label: '引用來源錯誤' },
  { value: 'format_issue', label: '格式問題' },
  { value: 'other', label: '其他問題' }
]

const toggleTag = (tag) => {
  if (selectedErrorTags.value.has(tag)) {
    selectedErrorTags.value.delete(tag)
  } else {
    selectedErrorTags.value.add(tag)
  }
}

// Reset state when opening/closing
watch(() => props.isOpen, (newVal) => {
  if (newVal) {
    selectedErrorTags.value.clear()
    groundTruth.value = ''
    note.value = ''
  }
})

const handleSave = async () => {
  if (!groundTruth.value.trim()) {
    alert('請提供正確的人工解答內容（Ground Truth）')
    return
  }

  isSubmitting.value = true
  try {
    // Get the first error type, or join them if multiples, or fallback
    const errorTypes = Array.from(selectedErrorTags.value)
    const error_type = errorTypes[0] || 'other'
    
    await feedbackStore.submitFeedback({
      chat_message_id: props.messageId,
      is_correct: false,
      correct_answer: groundTruth.value.trim(),
      error_type,
      note: note.value.trim() || `多選標記: ${errorTypes.join(', ')}`,
      question: props.query,
      ai_answer: props.content
    })
    
    emit('saved')
    emit('close')
  } catch (error) {
    console.error('Failed to submit feedback:', error)
    alert('儲存回饋失敗，請稍後再試。')
  } finally {
    isSubmitting.value = false
  }
}
</script>

<template>
  <div 
    v-if="isOpen" 
    class="fixed inset-0 bg-black/60 backdrop-blur-[4px] z-50 flex items-center justify-center p-4"
  >
    <div class="w-full max-w-[500px] bg-[#111827] border border-white/8 rounded-2xl shadow-[0_10px_40px_rgba(0,0,0,0.5)] overflow-hidden flex flex-col max-h-[90vh]">
      <!-- Header -->
      <div class="px-6 py-5 border-b border-white/8 flex items-center justify-between">
        <h3 class="font-semibold text-[#f3f4f6]">人工作答與錯誤標註 (Feedback Annotation)</h3>
        <button @click="emit('close')" class="text-[#6b7280] hover:text-[#f3f4f6] text-xl font-medium focus:outline-none">
          &times;
        </button>
      </div>

      <!-- Body -->
      <div class="p-6 flex flex-col gap-5 overflow-y-auto">
        <div class="flex flex-col gap-2">
          <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">使用者問題</label>
          <div class="bg-black/25 text-[#9ca3af] text-sm p-3.5 rounded-lg border border-white/3 font-medium">
            {{ query || '-' }}
          </div>
        </div>

        <div class="flex flex-col gap-2">
          <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">AI 回答內容</label>
          <div class="bg-black/25 text-[#9ca3af] text-sm p-3.5 rounded-lg border border-white/3 max-h-[120px] overflow-y-auto font-medium">
            {{ content || '-' }}
          </div>
        </div>

        <div class="flex flex-col gap-2">
          <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">標註錯誤分類 (可多選)</label>
          <div class="flex flex-wrap gap-2 mt-1.5">
            <button 
              v-for="tag in errorTags" 
              :key="tag.value"
              @click="toggleTag(tag.value)"
              class="px-3.5 py-2 rounded-lg text-xs font-medium border transition-all"
              :class="selectedErrorTags.has(tag.value)
                ? 'bg-[#8b5cf6]/15 border-[#8b5cf6] text-[#a78bfa]'
                : 'bg-white/4 border-white/8 text-[#9ca3af] hover:border-white/16 hover:text-white'"
            >
              {{ tag.label }}
            </button>
          </div>
        </div>

        <div class="flex flex-col gap-2">
          <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">正確預期答案 (Ground Truth)</label>
          <textarea 
            v-model="groundTruth" 
            rows="3"
            class="bg-white/5 border border-white/8 rounded-lg text-white p-3.5 text-sm focus:outline-none focus:border-[#8b5cf6] focus:ring-2 focus:ring-[#8b5cf6]/15 transition-all resize-y"
            placeholder="在此輸入正確的人工解答內容，將作為系統調優指標的評估標準..."
          ></textarea>
        </div>

        <div class="flex flex-col gap-2">
          <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">備註說明 (選填)</label>
          <input 
            v-model="note" 
            type="text"
            class="bg-white/5 border border-white/8 rounded-lg text-white px-3.5 py-2.5 text-sm focus:outline-none focus:border-[#8b5cf6] focus:ring-2 focus:ring-[#8b5cf6]/15 transition-all"
            placeholder="輸入其他需要備註的資訊..."
          />
        </div>
      </div>

      <!-- Footer -->
      <div class="px-6 py-4 border-t border-white/8 bg-black/10 flex justify-end gap-3 flex-shrink-0">
        <button 
          @click="emit('close')" 
          class="px-5 py-2.5 border border-white/8 bg-white/8 hover:bg-white/12 text-sm text-[#f3f4f6] font-semibold rounded-lg transition-all"
        >
          取消
        </button>
        <button 
          @click="handleSave" 
          :disabled="isSubmitting"
          class="px-5 py-2.5 bg-[#8b5cf6] hover:bg-[#a78bfa] hover:shadow-[0_4px_12px_rgba(139,92,246,0.3)] disabled:bg-purple-900 disabled:text-purple-300 text-sm text-white font-semibold rounded-lg transition-all"
        >
          {{ isSubmitting ? '儲存中...' : '儲存回饋' }}
        </button>
      </div>
    </div>
  </div>
</template>
