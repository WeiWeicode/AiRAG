<script setup>
import { computed } from 'vue'

const props = defineProps({
  text: {
    type: String,
    default: ''
  }
})

const charCount = computed(() => props.text.length)
const estimatedTokens = computed(() => Math.round(props.text.length * 1.3))
</script>

<template>
  <div class="flex gap-4 text-xs text-[#6b7280]">
    <span>字元數: <strong class="text-[#9ca3af] font-display font-medium">{{ charCount }}</strong></span>
    <span>估算 Token 數: <strong class="text-[#a78bfa] font-display font-semibold">{{ estimatedTokens }}</strong></span>
  </div>
</template>
