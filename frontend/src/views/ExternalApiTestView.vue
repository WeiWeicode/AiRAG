<script setup>
import ChatWindow from '../components/chat/ChatWindow.vue'
import RagParamsPanel from '../components/params/RagParamsPanel.vue'
import LlmParamsPanel from '../components/params/LlmParamsPanel.vue'
import CustomSystemPromptPanel from '../components/params/CustomSystemPromptPanel.vue'
import ExternalUserInfoPanel from '../components/params/ExternalUserInfoPanel.vue'
import ApiJsonPreviewPanel from '../components/params/ApiJsonPreviewPanel.vue'
import { useExternalChatStore } from '../stores/externalChatStore'

const externalChatStore = useExternalChatStore()
</script>

<template>
  <div class="flex-grow flex gap-6 p-6 overflow-hidden h-full min-h-0">
    <!-- Chat window on the left -->
    <div class="flex-grow flex flex-col min-w-0 h-full">
      <ChatWindow :store="externalChatStore" />
    </div>

    <!-- Parameter side panel on the right -->
    <div class="w-[380px] flex-shrink-0 flex flex-col gap-5 overflow-y-auto pr-1 h-full pb-6">
      <RagParamsPanel />
      <LlmParamsPanel />
      <CustomSystemPromptPanel />
      <ExternalUserInfoPanel />
      <ApiJsonPreviewPanel />
    </div>
  </div>
</template>
