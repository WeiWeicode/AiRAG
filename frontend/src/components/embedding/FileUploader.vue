<script setup>
import { ref, computed } from 'vue'
import embeddingService from '../../services/embeddingService'

const props = defineProps({
  extractImages: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['upload-success', 'upload-error'])

const isDragActive = ref(false)
const fileInput = ref(null)
const isUploading = ref(false)

const uploadingText = computed(() => {
  return props.extractImages
    ? '正在解析文件並辨識圖片中，圖片數量較多或內容複雜時可能需要較長時間，請耐心等候...'
    : '正在上傳並解析文件...'
})

const triggerFileInput = () => {
  if (!isUploading.value) {
    fileInput.value.click()
  }
}

const handleDragOver = (e) => {
  e.preventDefault()
  if (!isUploading.value) {
    isDragActive.value = true
  }
}

const handleDragLeave = () => {
  isDragActive.value = false
}

const handleDrop = async (e) => {
  e.preventDefault()
  isDragActive.value = false
  if (isUploading.value) return

  const file = e.dataTransfer.files[0]
  if (file) {
    await uploadFile(file)
  }
}

const handleFileSelect = async (e) => {
  const file = e.target.files[0]
  if (file) {
    await uploadFile(file)
  }
}

const uploadFile = async (file) => {
  isUploading.value = true
  try {
    const data = await embeddingService.uploadFile(file, props.extractImages)
    emit('upload-success', data)
  } catch (error) {
    console.error('File upload failed:', error)
    emit('upload-error', error)
  } finally {
    isUploading.value = false
  }
}
</script>

<template>
  <div class="flex flex-col gap-2">
    <label class="text-xs font-semibold text-[#9ca3af] uppercase tracking-wider">文件上傳</label>

    <!-- Hidden file input -->
    <input
      ref="fileInput"
      type="file"
      class="hidden"
      accept=".pdf,.docx,.txt,.md"
      @change="handleFileSelect"
    />

    <!-- Dropzone UI -->
    <div
      @click="triggerFileInput"
      @dragover="handleDragOver"
      @dragleave="handleDragLeave"
      @drop="handleDrop"
      class="border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all duration-200"
      :class="[
        isDragActive
          ? 'border-[#8b5cf6] bg-[#8b5cf6]/10 text-white'
          : 'border-white/8 bg-white/1 text-[#9ca3af] hover:border-white/16 hover:bg-white/3',
        isUploading ? 'opacity-80 cursor-not-allowed' : ''
      ]"
    >
      <!-- 上傳/解析中：轉動的 spinner，讓使用者能明確分辨畫面正在執行、不是卡住 -->
      <svg
        v-if="isUploading"
        class="animate-spin mx-auto mb-3 h-9 w-9 text-[#8b5cf6]"
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
      >
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
      </svg>
      <svg
        v-else
        width="36"
        height="36"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
        class="mx-auto mb-3 text-[#6b7280]"
      >
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/>
      </svg>
      <div class="text-xs font-semibold">
        {{ isUploading ? uploadingText : '拖曳文件至此或點擊上傳' }}
      </div>
      <div class="text-[10px] text-[#6b7280] mt-1">支援 PDF, DOCX, TXT, MD 格式</div>
    </div>
  </div>
</template>
