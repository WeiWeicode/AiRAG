<script setup>
import { ref, onMounted } from 'vue'
import { useParamsStore } from '../../stores/paramsStore'
import api from '../../services/api'

const paramsStore = useParamsStore()
const knowledgeBases = ref([])

const fetchKnowledgeBases = async () => {
  try {
    const response = await api.get('/api/knowledge-bases')
    if (response.data && response.data.items) {
      knowledgeBases.value = response.data.items
      // If current ID is invalid, fallback to the first available knowledge base
      const exists = knowledgeBases.value.some(kb => kb.id === paramsStore.knowledgeBaseId)
      if (!exists && knowledgeBases.value.length > 0) {
        paramsStore.knowledgeBaseId = knowledgeBases.value[0].id
      }
    }
  } catch (error) {
    console.error('無法取得知識庫列表，請檢查後端服務:', error)
  }
}

onMounted(() => {
  fetchKnowledgeBases()
})
</script>

<template>
  <div class="flex flex-col gap-2">
    <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">知識庫 (Knowledge Base)</label>
    <select 
      v-model="paramsStore.knowledgeBaseId" 
      :disabled="knowledgeBases.length === 0"
      class="bg-white/5 border border-white/8 rounded-lg text-white px-3.5 py-2.5 text-sm focus:outline-none focus:border-[#8b5cf6] focus:ring-2 focus:ring-[#8b5cf6]/15 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
    >
      <option v-if="knowledgeBases.length === 0" value="hr_docs" class="bg-[#111827] text-[#9ca3af]">
        -- 無可用知識庫 --
      </option>
      <option 
        v-for="kb in knowledgeBases" 
        :key="kb.id" 
        :value="kb.id"
        class="bg-[#111827] text-white"
      >
        {{ kb.name }}
      </option>
    </select>
  </div>
</template>
