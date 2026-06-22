<script setup>
defineProps({
  faithfulness: {
    type: Number,
    default: 0.0
  },
  relevancy: {
    type: Number,
    default: 0.0
  },
  precision: {
    type: Number,
    default: 0.0
  },
  recall: {
    type: Number,
    default: 0.0
  }
})
</script>

<template>
  <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
    <!-- Faithfulness -->
    <div class="bg-white/3 border border-white/8 rounded-xl p-5 relative overflow-hidden flex flex-col items-center">
      <div class="absolute left-0 top-0 w-1 h-full bg-[#8b5cf6]"></div>
      <span class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">Faithfulness (忠實度)</span>
      <span class="text-2xl font-bold font-display mt-2 text-white">{{ faithfulness.toFixed(2) }}</span>
      <span class="text-[10px] text-[#6b7280] mt-1 text-center">回答基於檢索內容，無幻覺</span>
    </div>

    <!-- Answer Relevancy -->
    <div class="bg-white/3 border border-white/8 rounded-xl p-5 relative overflow-hidden flex flex-col items-center">
      <div class="absolute left-0 top-0 w-1 h-full bg-[#3b82f6]"></div>
      <span class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">Answer Relevancy (相關性)</span>
      <span class="text-2xl font-bold font-display mt-2 text-white">{{ relevancy.toFixed(2) }}</span>
      <span class="text-[10px] text-[#6b7280] mt-1 text-center">解答切合問題之精確度</span>
    </div>

    <!-- Context Precision -->
    <div class="bg-white/3 border border-white/8 rounded-xl p-5 relative overflow-hidden flex flex-col items-center">
      <div class="absolute left-0 top-0 w-1 h-full bg-[#10b981]"></div>
      <span class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">Context Precision (精確率)</span>
      <span class="text-2xl font-bold font-display mt-2 text-white">{{ precision.toFixed(2) }}</span>
      <span class="text-[10px] text-[#6b7280] mt-1 text-center">檢索出的 Context 是否精確</span>
    </div>

    <!-- Context Recall -->
    <div class="bg-white/3 border border-white/8 rounded-xl p-5 relative overflow-hidden flex flex-col items-center">
      <div class="absolute left-0 top-0 w-1 h-full bg-[#f59e0b]"></div>
      <span class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">Context Recall (召回率)</span>
      <span class="text-2xl font-bold font-display mt-2 text-white">{{ recall.toFixed(2) }}</span>
      <span class="text-[10px] text-[#6b7280] mt-1 text-center">檢索到的資訊是否完整</span>
    </div>
  </div>
</template>
