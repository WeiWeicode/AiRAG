<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/authStore'

const router = useRouter()
const authStore = useAuthStore()

const username = ref('admin')
const password = ref('')
const error = ref('')
const isLoading = ref(false)

const handleLogin = async () => {
  if (!username.value || !password.value) {
    error.value = '請填寫帳號及密碼'
    return
  }

  error.value = ''
  isLoading.value = true
  try {
    const success = await authStore.login(username.value, password.value)
    if (success) {
      router.push('/dashboard')
    }
  } catch (err) {
    error.value = err.response?.data?.detail || '登入失敗，請檢查帳號密碼'
  } finally {
    isLoading.value = false
  }
}
</script>

<template>
  <div class="h-screen w-screen bg-[#0b0f19] flex items-center justify-center relative overflow-hidden">
    <!-- Glowing background accents -->
    <div class="absolute w-[500px] h-[500px] bg-[#8b5cf6]/10 rounded-full blur-[120px] top-[-100px] right-[-100px] pointer-events-none"></div>
    <div class="absolute w-[500px] h-[500px] bg-[#3b82f6]/5 rounded-full blur-[120px] bottom-[-100px] left-[-100px] pointer-events-none"></div>

    <!-- Login Card -->
    <div class="w-full max-w-[420px] bg-[#111827]/70 border border-white/8 rounded-2xl p-8 shadow-[0_4px_30px_rgba(0,0,0,0.3)] backdrop-blur-xl z-10 flex flex-col gap-6">
      <div class="flex flex-col items-center gap-2">
        <div class="w-12 h-12 bg-gradient-to-br from-[#8b5cf6] to-[#3b82f6] rounded-xl flex items-center justify-center font-extrabold text-white text-xl shadow-[0_0_20px_rgba(139,92,246,0.4)]">
          AR
        </div>
        <h1 class="text-xl font-bold bg-gradient-to-r from-[#a78bfa] to-[#3b82f6] bg-clip-text text-transparent font-display mt-2">
          AiRAG Testbed
        </h1>
        <span class="text-xs text-[#6b7280]">內部評估測試平台</span>
      </div>

      <!-- Error Message -->
      <div 
        v-if="error" 
        class="bg-rose-500/10 border border-rose-500/20 text-[#ef4444] px-4 py-3 rounded-lg text-xs font-semibold"
      >
        {{ error }}
      </div>

      <!-- Form -->
      <form @submit.prevent="handleLogin" class="flex flex-col gap-4">
        <div class="flex flex-col gap-2">
          <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">帳號 (Username)</label>
          <input 
            v-model="username"
            type="text" 
            class="bg-white/5 border border-white/8 rounded-lg text-white px-3.5 py-2.5 text-sm focus:outline-none focus:border-[#8b5cf6] focus:ring-2 focus:ring-[#8b5cf6]/15 transition-all"
            placeholder="輸入帳號..."
            autocomplete="username"
          />
        </div>

        <div class="flex flex-col gap-2">
          <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">密碼 (Password)</label>
          <input 
            v-model="password"
            type="password" 
            class="bg-white/5 border border-white/8 rounded-lg text-white px-3.5 py-2.5 text-sm focus:outline-none focus:border-[#8b5cf6] focus:ring-2 focus:ring-[#8b5cf6]/15 transition-all"
            placeholder="輸入密碼..."
            autocomplete="current-password"
          />
        </div>

        <button 
          type="submit"
          :disabled="isLoading"
          class="bg-[#8b5cf6] hover:bg-[#a78bfa] disabled:bg-purple-900/50 disabled:text-purple-300/50 hover:shadow-[0_4px_12px_rgba(139,92,246,0.3)] text-white font-semibold py-3 rounded-lg text-sm flex items-center justify-center gap-2 transition-all mt-2"
        >
          {{ isLoading ? '驗證中...' : '登入' }}
        </button>
      </form>
    </div>
  </div>
</template>
