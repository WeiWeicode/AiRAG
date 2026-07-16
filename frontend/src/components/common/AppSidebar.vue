<script setup>
import { computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '../../stores/authStore'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const currentUser = computed(() => authStore.user || { username: 'John Doe', role: 'AI Engineer' })

const menuItems = [
  {
    path: '/rag-test',
    label: 'RAG 功能測試 (E2E)',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="w-[18px] h-[18px]"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>`
  },
  {
    path: '/retrieval-test',
    label: '向量搜尋測試 (Retrieval)',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="w-[18px] h-[18px]"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>`
  },
  {
    path: '/evaluation',
    label: '準確度評估 (Benchmarking)',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="w-[18px] h-[18px]"><line x1="18" y1="20" x2="18" y2="10"></line><line x1="12" y1="20" x2="12" y2="4"></line><line x1="6" y1="20" x2="6" y2="14"></line></svg>`
  },
  {
    path: '/prompt-test',
    label: 'Prompt / LLM 測試',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="w-[18px] h-[18px]"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>`
  },
  {
    path: '/embedding-test',
    label: '自訂資料向量化',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="w-[18px] h-[18px]"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path></svg>`
  },
  {
    path: '/feedback',
    label: '標註與人工回饋歷史',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="w-[18px] h-[18px]"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>`
  },
  {
    path: '/role-settings',
    label: '角色與權限設定',
    icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="w-[18px] h-[18px]"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg>`
  }
]

const handleLogout = () => {
  authStore.logout()
  router.push('/login')
}
</script>

<template>
  <aside class="w-[280px] bg-[#111827] border-r border-white/8 flex flex-col flex-shrink-0 z-10">
    <div class="h-[70px] flex items-center px-6 border-b border-white/8 cursor-pointer" @click="router.push('/dashboard')">
      <div class="w-7 h-7 bg-gradient-to-br from-[#8b5cf6] to-[#3b82f6] rounded-lg flex items-center justify-center font-extrabold text-white text-sm shadow-[0_0_15px_rgba(139,92,246,0.4)]">
        AR
      </div>
      <h1 class="ml-2.5 font-display text-lg font-bold tracking-wider bg-gradient-to-r from-[#a78bfa] to-[#3b82f6] bg-clip-text text-transparent">
        AiRAG Testbed
      </h1>
    </div>
    
    <nav class="flex-grow overflow-y-auto px-4 py-6 flex flex-col gap-2">
      <router-link
        v-for="item in menuItems"
        :key="item.path"
        :to="item.path"
        class="flex items-center px-4 py-3 text-[#9ca3af] hover:text-white hover:bg-white/3 border border-transparent hover:border-white/5 rounded-xl text-sm font-medium transition-all duration-200"
        active-class="!text-white bg-gradient-to-br from-[#8b5cf6]/15 to-[#3b82f6]/5 !border-[#8b5cf6]/30 shadow-[0_4px_20px_rgba(0,0,0,0.15)]"
      >
        <div v-html="item.icon" class="mr-3 transition-transform duration-200" :class="{ 'scale-105 text-[#a78bfa]': route.path === item.path }"></div>
        {{ item.label }}
      </router-link>
    </nav>
    
    <div class="p-6 border-t border-white/8 flex items-center justify-between gap-3">
      <div class="flex items-center gap-3">
        <div class="w-9 h-9 bg-[#1f2937] border border-white/8 rounded-full flex items-center justify-center font-semibold text-sm">
          {{ currentUser.username.substring(0, 2).toUpperCase() }}
        </div>
        <div class="flex flex-col">
          <span class="text-sm font-semibold text-[#f3f4f6]">{{ currentUser.username }}</span>
          <span class="text-xs text-[#6b7280]">{{ currentUser.role }}</span>
        </div>
      </div>
      <button 
        @click="handleLogout" 
        class="text-[#9ca3af] hover:text-red-400 p-1.5 rounded-lg hover:bg-white/5 transition-colors"
        title="登出"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="w-[18px] h-[18px]"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/></svg>
      </button>
    </div>
  </aside>
</template>
