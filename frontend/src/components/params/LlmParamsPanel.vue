<script setup>
import { ref, onMounted } from 'vue'
import { useParamsStore } from '../../stores/paramsStore'
import modelService from '../../services/modelService'

const paramsStore = useParamsStore()

// 自動偵測本機 Ollama 已下載的對話模型（排除 embedding 模型）
const chatModels = ref([])
const defaultChatModel = ref('')
const isLoadingModels = ref(false)
const modelError = ref('')

const loadModels = async () => {
  isLoadingModels.value = true
  modelError.value = ''
  try {
    const { data } = await modelService.list()
    chatModels.value = data.models.filter(m => m.is_generation)
    defaultChatModel.value = data.default_chat_model
    // 尚未選擇或原選擇的模型已被移除時，改用後端預設模型
    if (!chatModels.value.some(m => m.name === paramsStore.model)) {
      paramsStore.model = data.default_chat_model
    }
  } catch (err) {
    modelError.value = err.response?.data?.detail || '無法取得模型清單'
  } finally {
    isLoadingModels.value = false
  }
}

const modelLabel = (m) => {
  const size = m.parameter_size || (m.size ? `${(m.size / 1e9).toFixed(1)}GB` : '')
  const notes = [size, m.name === defaultChatModel.value ? '預設' : ''].filter(Boolean)
  return notes.length ? `${m.name} (${notes.join('・')})` : m.name
}

onMounted(loadModels)
</script>

<template>
  <div class="flex flex-col gap-5 bg-white/3 border border-white/8 rounded-2xl p-5 backdrop-blur-md">
    <div class="text-sm font-bold text-white border-b border-white/8 pb-2 tracking-wider">
      生成模型設定 (Generation)
    </div>

    <!-- Model Selection -->
    <div class="flex flex-col gap-2">
      <div class="flex justify-between items-center">
        <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">模型 (Ollama 自動偵測)</label>
        <button
          type="button"
          @click="loadModels"
          :disabled="isLoadingModels"
          class="text-xs text-[#a78bfa] hover:text-white disabled:opacity-50 transition-colors"
        >
          {{ isLoadingModels ? '偵測中…' : '重新偵測' }}
        </button>
      </div>
      <select
        v-model="paramsStore.model"
        :disabled="isLoadingModels || chatModels.length === 0"
        class="bg-white/5 border border-white/8 rounded-lg text-white px-3.5 py-2.5 text-sm focus:outline-none focus:border-[#8b5cf6] transition-all disabled:opacity-60"
      >
        <option v-if="chatModels.length === 0" value="" class="bg-[#111827] text-white">
          {{ isLoadingModels ? '偵測中…' : '未偵測到可用模型' }}
        </option>
        <option v-for="m in chatModels" :key="m.name" :value="m.name" class="bg-[#111827] text-white">
          {{ modelLabel(m) }}
        </option>
      </select>
      <p v-if="modelError" class="text-xs text-[#ef4444]">{{ modelError }}</p>
    </div>

    <!-- Temperature Slider -->
    <div class="flex flex-col gap-2">
      <div class="flex justify-between items-center">
        <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">溫度參數 (Temperature)</label>
        <span class="text-xs font-bold text-[#a78bfa] font-display">{{ paramsStore.temperature }}</span>
      </div>
      <input 
        v-model.number="paramsStore.temperature" 
        type="range" 
        min="0" 
        max="1.5" 
        step="0.1" 
        class="w-full h-1 bg-white/10 rounded-lg appearance-none cursor-pointer accent-[#8b5cf6]"
      />
    </div>

    <!-- Max Tokens Slider -->
    <div class="flex flex-col gap-2">
      <div class="flex justify-between items-center">
        <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">最大 Token 數 (Max Tokens)</label>
        <span class="text-xs font-bold text-[#a78bfa] font-display">{{ paramsStore.maxTokens }}</span>
      </div>
      <input 
        v-model.number="paramsStore.maxTokens" 
        type="range" 
        min="256" 
        max="22768" 
        step="128" 
        class="w-full h-1 bg-white/10 rounded-lg appearance-none cursor-pointer accent-[#8b5cf6]"
      />
    </div>
  </div>
</template>
