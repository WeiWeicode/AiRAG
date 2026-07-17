<script setup>
import { useParamsStore } from '../../stores/paramsStore'

const paramsStore = useParamsStore()
</script>

<template>
  <div class="flex flex-col gap-5 bg-white/3 border border-white/8 rounded-2xl p-5 backdrop-blur-md">
    <div class="text-sm font-bold text-white border-b border-white/8 pb-2 tracking-wider">
      自訂總結提示詞 (Custom System Prompt)
    </div>

    <div class="flex flex-col gap-2">
      <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">System Prompt 覆蓋內容</label>
      <textarea
        v-model="paramsStore.customSystemPrompt"
        rows="6"
        class="bg-white/5 border border-white/8 rounded-lg text-white px-3 py-2 text-xs leading-relaxed focus:outline-none focus:border-[#8b5cf6] transition-all resize-y"
        placeholder="留空則使用系統預設總結提示詞"
      ></textarea>
      <p class="text-[10px] text-[#9ca3af] leading-relaxed">
        若有填寫，將完全取代預設的指示規則文字（含引用格式規則等）；檢索到的參考資料仍會由後端自動接續在此段文字之後。若未選擇知識庫，回答將直接依照這段文字生成，不會被強制接上「知識庫沒有相關資訊」的警語，可用於純 Prompt／LLM 行為測試。
      </p>
    </div>
  </div>
</template>
