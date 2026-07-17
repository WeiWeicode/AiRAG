<script setup>
import { useParamsStore } from '../../stores/paramsStore'

const paramsStore = useParamsStore()
</script>

<template>
  <div class="flex flex-col gap-5 bg-white/3 border border-white/8 rounded-2xl p-5 backdrop-blur-md">
    <div class="text-sm font-bold text-white border-b border-white/8 pb-2 tracking-wider">
      使用者身分與驗證 (External User & Auth)
    </div>

    <div class="flex flex-col gap-2">
      <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">API Key</label>
      <input
        v-model="paramsStore.externalApiKey"
        type="text"
        class="bg-white/5 border border-white/8 rounded-lg text-white px-3 py-2 text-xs font-mono focus:outline-none focus:border-[#8b5cf6] transition-all"
        placeholder="於「角色與權限設定」頁建立金鑰後貼上"
      />
      <p class="text-[10px] text-[#9ca3af] leading-relaxed">
        以 X-API-Key 標頭送出，此端點不使用登入 JWT。
      </p>
    </div>

    <div class="flex flex-col gap-3 pt-1 border-t border-white/5">
      <p class="text-[10px] text-[#9ca3af] leading-relaxed">
        以下 6 個欄位取代內部測試用的「模擬使用者」下拉選單，供外部應用傳入真實員工身分，決定機密文件的存取權限過濾結果。
      </p>
      <div class="grid grid-cols-2 gap-3">
        <div class="flex flex-col gap-1.5">
          <label class="text-[10px] font-semibold text-[#9ca3af] uppercase tracking-wider">工號 (employee_id)</label>
          <input v-model="paramsStore.externalEmployeeId" type="text" class="bg-white/5 border border-white/8 rounded-lg text-white px-3 py-2 text-xs focus:outline-none focus:border-[#8b5cf6]" placeholder="E00123" />
        </div>
        <div class="flex flex-col gap-1.5">
          <label class="text-[10px] font-semibold text-[#9ca3af] uppercase tracking-wider">姓名 (name)</label>
          <input v-model="paramsStore.externalEmployeeName" type="text" class="bg-white/5 border border-white/8 rounded-lg text-white px-3 py-2 text-xs focus:outline-none focus:border-[#8b5cf6]" placeholder="王小明" />
        </div>
        <div class="flex flex-col gap-1.5">
          <label class="text-[10px] font-semibold text-[#9ca3af] uppercase tracking-wider">部門代號 (department_code)</label>
          <input v-model="paramsStore.externalDepartmentCode" type="text" class="bg-white/5 border border-white/8 rounded-lg text-white px-3 py-2 text-xs focus:outline-none focus:border-[#8b5cf6]" placeholder="RD" />
        </div>
        <div class="flex flex-col gap-1.5">
          <label class="text-[10px] font-semibold text-[#9ca3af] uppercase tracking-wider">部門名稱 (department_name)</label>
          <input v-model="paramsStore.externalDepartmentName" type="text" class="bg-white/5 border border-white/8 rounded-lg text-white px-3 py-2 text-xs focus:outline-none focus:border-[#8b5cf6]" placeholder="研發部" />
        </div>
        <div class="flex flex-col gap-1.5">
          <label class="text-[10px] font-semibold text-[#9ca3af] uppercase tracking-wider">級職名稱 (job_title_name)</label>
          <input v-model="paramsStore.externalJobTitleName" type="text" class="bg-white/5 border border-white/8 rounded-lg text-white px-3 py-2 text-xs focus:outline-none focus:border-[#8b5cf6]" placeholder="經理" />
        </div>
        <div class="flex flex-col gap-1.5">
          <label class="text-[10px] font-semibold text-[#9ca3af] uppercase tracking-wider">級職等級 (job_title_level)</label>
          <input v-model.number="paramsStore.externalJobTitleLevel" type="number" min="1" max="10" class="bg-white/5 border border-white/8 rounded-lg text-white px-3 py-2 text-xs focus:outline-none focus:border-[#8b5cf6]" />
        </div>
      </div>
      <p class="text-[10px] text-[#9ca3af] leading-relaxed">
        部門比對採代號／名稱雙軌相容；級職等級由呼叫端直接信任帶入的數字，不會重新換算。
      </p>
    </div>
  </div>
</template>
