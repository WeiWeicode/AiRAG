<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import AppSidebar from './components/common/AppSidebar.vue'
import AppHeader from './components/common/AppHeader.vue'

const route = useRoute()
const isLoginPage = computed(() => route.path === '/login')
</script>

<template>
  <!-- Main layout for login page -->
  <div v-if="isLoginPage" class="h-screen w-screen bg-[#0b0f19] text-[#f3f4f6]">
    <router-view />
  </div>

  <!-- Standard layout with sidebar and header for authenticated views -->
  <div v-else class="flex h-screen w-screen bg-[#0b0f19] text-[#f3f4f6] overflow-hidden">
    <!-- Sidebar -->
    <AppSidebar />

    <!-- Main Workspace -->
    <div class="flex-grow flex flex-col min-w-0 h-full overflow-hidden">
      <!-- Header -->
      <AppHeader />

      <!-- Viewport content -->
      <main class="flex-grow overflow-hidden relative bg-[#0b0f19]">
        <router-view />
      </main>
    </div>
  </div>
</template>

<style>
/* CSS transitions or global adjustments if needed */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.25s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
