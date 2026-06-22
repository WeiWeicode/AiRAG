<script setup>
import { computed } from 'vue'

const props = defineProps({
  faithfulness: { type: Number, default: 0.0 },
  relevancy: { type: Number, default: 0.0 },
  precision: { type: Number, default: 0.0 },
  recall: { type: Number, default: 0.0 }
})

const chartData = computed(() => [
  { label: '忠實度', val: props.faithfulness, color: 'url(#grad-purple)' },
  { label: '相關性', val: props.relevancy, color: 'url(#grad-blue)' },
  { label: '精確率', val: props.precision, color: 'url(#grad-green)' },
  { label: '召回率', val: props.recall, color: 'url(#grad-orange)' }
])
</script>

<template>
  <div class="bg-white/3 border border-white/8 rounded-2xl p-6 backdrop-blur-md flex flex-col items-center">
    <div class="text-sm font-bold text-white mb-6 self-start tracking-wider">指標分析圖表 (RAGAS Chart)</div>
    
    <!-- SVG Chart Container -->
    <div class="w-full max-w-[500px] aspect-[16/9] relative">
      <svg viewBox="0 0 400 200" class="w-full h-full">
        <!-- Gradients Definitions -->
        <defs>
          <linearGradient id="grad-purple" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#8b5cf6" stop-opacity="0.8" />
            <stop offset="100%" stop-color="#8b5cf6" stop-opacity="0.1" />
          </linearGradient>
          <linearGradient id="grad-blue" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#3b82f6" stop-opacity="0.8" />
            <stop offset="100%" stop-color="#3b82f6" stop-opacity="0.1" />
          </linearGradient>
          <linearGradient id="grad-green" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#10b981" stop-opacity="0.8" />
            <stop offset="100%" stop-color="#10b981" stop-opacity="0.1" />
          </linearGradient>
          <linearGradient id="grad-orange" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#f59e0b" stop-opacity="0.8" />
            <stop offset="100%" stop-color="#f59e0b" stop-opacity="0.1" />
          </linearGradient>
        </defs>

        <!-- Grid Lines -->
        <line x1="40" y1="20" x2="380" y2="20" stroke="rgba(255,255,255,0.05)" stroke-width="1" />
        <line x1="40" y1="60" x2="380" y2="60" stroke="rgba(255,255,255,0.05)" stroke-width="1" />
        <line x1="40" y1="100" x2="380" y2="100" stroke="rgba(255,255,255,0.05)" stroke-width="1" />
        <line x1="40" y1="140" x2="380" y2="140" stroke="rgba(255,255,255,0.05)" stroke-width="1" />
        <line x1="40" y1="170" x2="380" y2="170" stroke="rgba(255,255,255,0.15)" stroke-width="1" />

        <!-- Y Axis Labels -->
        <text x="30" y="24" fill="#6b7280" font-size="10" text-anchor="end">1.0</text>
        <text x="30" y="64" fill="#6b7280" font-size="10" text-anchor="end">0.75</text>
        <text x="30" y="104" fill="#6b7280" font-size="10" text-anchor="end">0.5</text>
        <text x="30" y="144" fill="#6b7280" font-size="10" text-anchor="end">0.25</text>
        <text x="30" y="174" fill="#6b7280" font-size="10" text-anchor="end">0.0</text>

        <!-- Bars -->
        <g v-for="(item, idx) in chartData" :key="idx">
          <!-- Animated Bar Height -->
          <rect 
            :x="60 + idx * 80" 
            :y="170 - (item.val * 150)" 
            width="40" 
            :height="item.val * 150" 
            :fill="item.color" 
            rx="4"
            class="transition-all duration-500 ease-out"
          />
          <!-- Bar Outline -->
          <rect 
            :x="60 + idx * 80" 
            :y="170 - (item.val * 150)" 
            width="40" 
            :height="item.val * 150" 
            fill="none" 
            stroke-width="1.5"
            :stroke="idx === 0 ? '#8b5cf6' : idx === 1 ? '#3b82f6' : idx === 2 ? '#10b981' : '#f59e0b'"
            class="transition-all duration-500 ease-out"
          />
          <!-- Labels under bars -->
          <text 
            :x="80 + idx * 80" 
            y="188" 
            fill="#9ca3af" 
            font-size="10" 
            text-anchor="middle"
          >
            {{ item.label }}
          </text>
          <!-- Score numbers on top of bars -->
          <text 
            :x="80 + idx * 80" 
            :y="162 - (item.val * 150)" 
            fill="#ffffff" 
            font-size="11" 
            font-weight="bold"
            text-anchor="middle"
            class="transition-all duration-500 ease-out"
          >
            {{ item.val.toFixed(2) }}
          </text>
        </g>
      </svg>
    </div>
  </div>
</template>
