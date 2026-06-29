<script setup>
import { ref } from 'vue'
import ChunkingParams from '../components/params/ChunkingParams.vue'
import SingleIndexingTab from '../components/embedding/SingleIndexingTab.vue'
import BatchIndexingTab from '../components/embedding/BatchIndexingTab.vue'
import DatabaseIndexingTab from '../components/embedding/DatabaseIndexingTab.vue'
import VectorManagementTab from '../components/embedding/VectorManagementTab.vue'

// Tab state
const activeTab = ref('indexing') // indexing | batch_indexing | database_indexing | management
</script>

<template>
  <div class="flex-grow flex gap-6 p-6 overflow-hidden h-full min-h-0">
    <!-- Left Edit Area -->
    <div class="flex-grow flex flex-col gap-5 min-w-0 h-full overflow-y-auto pr-1">
      
      <!-- Tab selector -->
      <div class="flex gap-4 border-b border-white/8 pb-3 flex-shrink-0">
        <button 
          @click="activeTab = 'indexing'" 
          :class="[
            'text-sm font-semibold pb-1.5 border-b-2 transition-all',
            activeTab === 'indexing' ? 'text-[#a78bfa] border-[#8b5cf6]' : 'text-[#9ca3af] border-transparent hover:text-white'
          ]"
        >
          資料切分與向量化寫入
        </button>
        <button 
          @click="activeTab = 'batch_indexing'" 
          :class="[
            'text-sm font-semibold pb-1.5 border-b-2 transition-all',
            activeTab === 'batch_indexing' ? 'text-[#a78bfa] border-[#8b5cf6]' : 'text-[#9ca3af] border-transparent hover:text-white'
          ]"
        >
          自動分批寫入
        </button>
        <button 
          @click="activeTab = 'database_indexing'" 
          :class="[
            'text-sm font-semibold pb-1.5 border-b-2 transition-all',
            activeTab === 'database_indexing' ? 'text-[#a78bfa] border-[#8b5cf6]' : 'text-[#9ca3af] border-transparent hover:text-white'
          ]"
        >
          資料庫匯入向量化
        </button>
        <button 
          @click="activeTab = 'management'" 
          :class="[
            'text-sm font-semibold pb-1.5 border-b-2 transition-all',
            activeTab === 'management' ? 'text-[#a78bfa] border-[#8b5cf6]' : 'text-[#9ca3af] border-transparent hover:text-white'
          ]"
        >
          已向量化資料管理與刪除
        </button>
      </div>

      <!-- Tab Content Components -->
      <SingleIndexingTab v-if="activeTab === 'indexing'" />
      <BatchIndexingTab v-else-if="activeTab === 'batch_indexing'" />
      <DatabaseIndexingTab v-else-if="activeTab === 'database_indexing'" />
      <VectorManagementTab v-else-if="activeTab === 'management'" />
    </div>

    <!-- Right Side Config & Chunks Preview -->
    <div class="w-[320px] flex-shrink-0 flex flex-col gap-5 overflow-y-auto pr-1 h-full pb-6">
      <!-- Parameters -->
      <ChunkingParams />

      <!-- Containers for Teleport destination from subcomponents -->
      <div v-show="activeTab === 'indexing'" id="sidebar-single-indexing" class="flex-grow flex flex-col min-h-0"></div>
      <div v-show="activeTab === 'batch_indexing'" id="sidebar-batch-indexing" class="flex-grow flex flex-col min-h-0"></div>
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
