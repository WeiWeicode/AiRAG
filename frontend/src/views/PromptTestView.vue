<script setup>
import { ref } from 'vue'
import LlmParamsPanel from '../components/params/LlmParamsPanel.vue'
import TokenCounter from '../components/embedding/TokenCounter.vue'
import api from '../services/api'

// Prompt inputs
const systemPrompt = ref('You are an expert AI Assistant. Refer to the provided Context to answer the user query accurately. If you don\'t know the answer, state that you do not know.')
const userPromptTemplate = ref('根據以下提供的參考資料回答問題：\n{context}\n\n使用者問題：{question}\n\n請以繁體中文回答：')
const manualContext = ref('【公司請假福利調整公告】\n自 2026 年起，全體正職員工之有薪病假額度自每年 3 日調整為每年 5 日，超出之病假以半薪計算。此外，員工生日當月可享有「生日假」1 日，須於當月使用完畢，不可遞延或折現。申請流程比照一般事假於 BPM 系統登錄即可。')
const testQuestion = ref('請問 2026 年病假的福利有什麼改變？另外生日假可以留到下個月請嗎？')

// Preview output state
const showPreview = ref(false)
const previewSystem = ref('')
const previewUser = ref('')
const previewTokens = ref(0)
const isPreviewLoading = ref(false)

// A/B test results state
const isGenerating = ref(false)
const abResults = ref([])

const handlePreview = async () => {
  if (!manualContext.value.trim() || !testQuestion.value.trim()) {
    alert('請填寫參考資料 (Context) 及測試問題 (Question)')
    return
  }

  showPreview.value = true
  isPreviewLoading.value = true
  
  try {
    const response = await api.post('/prompt/preview', {
      context: manualContext.value,
      question: testQuestion.value,
      system_prompt: systemPrompt.value,
      user_prompt_template: userPromptTemplate.value
    })
    
    previewSystem.value = response.data.rendered_system_prompt
    previewUser.value = response.data.rendered_user_prompt
    previewTokens.value = response.data.total_estimated_tokens
  } catch (error) {
    console.error('Backend preview API failed:', error)
    alert('預覽組合 Prompt 失敗，請檢查後端服務與連線')
    showPreview.value = false
  } finally {
    isPreviewLoading.value = false
  }
}

const handleABTest = async () => {
  if (!manualContext.value.trim() || !testQuestion.value.trim()) {
    alert('請填寫參考資料 (Context) 及測試問題 (Question)')
    return
  }

  isGenerating.value = true
  abResults.value = []
  
  try {
    const payload = {
      context: manualContext.value,
      question: testQuestion.value,
      variants: [
        {
          label: "Variant A (低溫度 - 0.1)",
          system_prompt: systemPrompt.value,
          user_prompt_template: userPromptTemplate.value,
          params: { temperature: 0.1, top_p: 0.9, max_tokens: 1024 }
        },
        {
          label: "Variant B (高溫度 - 0.9)",
          system_prompt: systemPrompt.value,
          user_prompt_template: userPromptTemplate.value,
          params: { temperature: 0.9, top_p: 0.9, max_tokens: 1024 }
        }
      ]
    }
    
    const response = await api.post('/prompt/ab-test', payload)
    abResults.value = response.data.results || []
  } catch (error) {
    console.error('Backend A/B test API failed:', error)
    alert('A/B 參數對照生成失敗，請檢查後端服務與連線')
  } finally {
    isGenerating.value = false
  }
}
</script>

<template>
  <div class="flex-grow flex gap-6 p-6 overflow-hidden h-full min-h-0">
    <!-- Left Main Prompt Panel -->
    <div class="flex-grow flex flex-col gap-5 min-w-0 h-full overflow-y-auto pr-1">
      <!-- Input Panel -->
      <div class="bg-[#111827]/70 border border-white/8 rounded-2xl p-6 backdrop-blur-md flex flex-col gap-4">
        <div class="text-sm font-bold text-white tracking-wider">Prompt 參數與 Context 注入測試</div>
        
        <!-- System Prompt -->
        <div class="flex flex-col gap-2">
          <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">系統設定 (System Prompt)</label>
          <textarea 
            v-model="systemPrompt" 
            rows="2"
            class="bg-white/5 border border-white/8 rounded-lg text-white p-3 text-xs font-mono focus:outline-none focus:border-[#8b5cf6] resize-y"
          ></textarea>
        </div>

        <!-- User Prompt Template -->
        <div class="flex flex-col gap-2">
          <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">使用者範本 (User Prompt Template)</label>
          <textarea 
            v-model="userPromptTemplate" 
            rows="2"
            class="bg-white/5 border border-white/8 rounded-lg text-white p-3 text-xs font-mono focus:outline-none focus:border-[#8b5cf6] resize-y"
          ></textarea>
        </div>

        <!-- Manual Context -->
        <div class="flex flex-col gap-2">
          <div class="flex justify-between items-center">
            <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">參考資料 (Context / RAG Chunks)</label>
            <TokenCounter :text="manualContext" />
          </div>
          <textarea 
            v-model="manualContext" 
            rows="4"
            class="bg-white/5 border border-white/8 rounded-lg text-white p-3.5 text-xs focus:outline-none focus:border-[#8b5cf6] resize-y"
            placeholder="請貼上測試用參考文本段落..."
          ></textarea>
        </div>

        <!-- Question -->
        <div class="flex flex-col gap-2">
          <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">測試問題 (User Query)</label>
          <input 
            v-model="testQuestion"
            type="text" 
            class="bg-white/5 border border-white/8 rounded-lg text-white px-3.5 py-2.5 text-xs focus:outline-none focus:border-[#8b5cf6]"
            placeholder="請輸入測試問題..."
          />
        </div>

        <!-- Actions -->
        <div class="flex gap-3 mt-2">
          <button 
            @click="handlePreview"
            :disabled="isGenerating || isPreviewLoading"
            class="px-5 py-2.5 border border-white/8 hover:border-white/16 text-xs text-[#f3f4f6] font-semibold rounded-lg bg-white/5 transition-all"
          >
            預覽組合 Prompt
          </button>
          <button 
            @click="handleABTest"
            :disabled="isGenerating || isPreviewLoading"
            class="px-5 py-2.5 bg-[#8b5cf6] hover:bg-[#a78bfa] hover:shadow-[0_4px_12px_rgba(139,92,246,0.3)] disabled:bg-purple-900/50 disabled:text-purple-300/50 text-xs text-white font-semibold rounded-lg transition-all flex items-center gap-1.5"
          >
            <svg v-if="isGenerating" class="animate-spin h-3.5 w-3.5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            {{ isGenerating ? '產生中...' : 'A/B 參數對照生成' }}
          </button>
        </div>
      </div>

      <!-- Preview Modal or Panel -->
      <div 
        v-if="showPreview" 
        class="bg-[#111827]/40 border border-white/8 rounded-2xl p-6 flex flex-col gap-4 relative animate-fade-in"
      >
        <button @click="showPreview = false" class="absolute top-4 right-4 text-[#6b7280] hover:text-white text-base">
          &times;
        </button>
        <div class="text-sm font-bold text-white tracking-wider flex items-center gap-2">
          組合 Prompt 預覽 
          <span class="text-[10px] font-bold px-1.5 py-0.5 rounded bg-[#8b5cf6]/10 text-[#a78bfa] font-display">Est. Tokens: {{ previewTokens }}</span>
        </div>
        
        <div v-if="isPreviewLoading" class="text-xs text-[#9ca3af] py-4">正在渲染中...</div>
        <div v-else class="flex flex-col gap-4 text-xs font-mono">
          <div class="flex flex-col gap-1.5">
            <span class="text-white font-bold">System Prompt:</span>
            <pre class="bg-black/30 p-3.5 rounded-lg border border-white/5 overflow-x-auto whitespace-pre-wrap leading-relaxed text-[#9ca3af]">{{ previewSystem }}</pre>
          </div>
          <div class="flex flex-col gap-1.5">
            <span class="text-white font-bold">User Prompt:</span>
            <pre class="bg-black/30 p-3.5 rounded-lg border border-white/5 overflow-x-auto whitespace-pre-wrap leading-relaxed text-[#9ca3af]">{{ previewUser }}</pre>
          </div>
        </div>
      </div>

      <!-- A/B Comparison Result Side-by-Side Grid -->
      <div v-if="abResults.length > 0" class="grid grid-cols-1 md:grid-cols-2 gap-6 animate-fade-in">
        <div 
          v-for="(res, idx) in abResults" 
          :key="idx" 
          class="bg-[#111827]/40 border border-white/8 rounded-2xl p-6 flex flex-col gap-4"
        >
          <div class="flex justify-between items-center border-b border-white/5 pb-2.5">
            <span class="text-sm font-bold text-white">{{ res.label }}</span>
            <span class="text-[10px] text-[#6b7280]">耗時: <strong class="text-white">{{ res.elapsed_ms }}</strong> ms</span>
          </div>
          <div class="text-xs text-[#9ca3af] leading-relaxed whitespace-pre-wrap bg-black/25 p-4 rounded-xl border border-white/3 min-h-[120px]">
            {{ res.answer }}
          </div>
          <div class="flex gap-4 text-[10px] text-[#6b7280]">
            <span>溫度: <strong class="text-white">{{ res.params.temperature }}</strong></span>
            <span>top_p: <strong class="text-white">{{ res.params.top_p || 0.9 }}</strong></span>
          </div>
        </div>
      </div>
    </div>

    <!-- Right Side Settings -->
    <div class="w-[320px] flex-shrink-0 flex flex-col gap-5 overflow-y-auto pr-1 h-full pb-6">
      <LlmParamsPanel />
    </div>
  </div>
</template>

<style scoped>
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}
.animate-fade-in {
  animation: fadeIn 0.35s cubic-bezier(0.4, 0, 0.2, 1);
}
</style>
