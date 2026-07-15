<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { checkHealth } from '../../services/api'

const route = useRoute()
const isConnected = ref(true)

const pageTitle = computed(() => {
  const titles = {
    'Dashboard': '儀表板首頁',
    'RagTest': 'RAG 功能測試 (End-to-End Testing)',
    'RetrievalTest': '向量搜尋測試 (Retrieval Testing)',
    'Evaluation': '準確度評估 (Evaluation & Benchmarking)',
    'PromptTest': '自訂 Context 生成 (Prompt & Generation Testing)',
    'EmbeddingTest': '自訂資料向量化 (Embedding & Indexing)',
    'Feedback': '人工回饋與標註歷史 (Human Feedback)'
  }
  return titles[route.name] || 'AiRAG 內部測試平台'
})

const checkConnection = async () => {
  const health = await checkHealth()
  isConnected.value = health.status === 'healthy'
}

onMounted(() => {
  checkConnection()
  // Check every 30 seconds
  setInterval(checkConnection, 30000)
})
</script>

<template>
  <header class="h-[70px] border-b border-white/8 flex items-center justify-between px-8 bg-[#0b0f19]/50 backdrop-blur-md flex-shrink-0">
    <div class="text-lg font-semibold flex items-center gap-2">
      {{ pageTitle }}
    </div>
    <div class="flex items-center gap-4">
      <span 
        class="px-2.5 py-1 rounded-full text-xs font-medium flex items-center gap-1.5 border"
        :class="isConnected 
          ? 'bg-emerald-500/10 text-[#10b981] border-emerald-500/20' 
          : 'bg-rose-500/10 text-[#ef4444] border-rose-500/20'"
      >
        <span 
          class="w-1.5 h-1.5 rounded-full"
          :class="isConnected ? 'bg-emerald-500 shadow-[0_0_8px_#10b981]' : 'bg-rose-500 shadow-[0_0_8px_#ef4444]'"
        ></span>
        {{ isConnected ? 'vLLM / llama.cpp connected' : 'Backend disconnected' }}
      </span>
    </div>
  </header>
</template>
