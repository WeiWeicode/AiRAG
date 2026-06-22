<script setup>
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'
// Import highlight.js styles if required, but we can also style code blocks via Tailwind

const props = defineProps({
  content: {
    type: String,
    required: true
  }
})

const md = new MarkdownIt({
  html: false,
  linkify: true,
  typographer: true,
  highlight: (str, lang) => {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return `<pre class="hljs bg-black/20 p-3 rounded-lg overflow-x-auto my-2 font-mono text-xs"><code>${
          hljs.highlight(str, { language: lang, ignoreIllegals: true }).value
        }</code></pre>`
      } catch (__) {}
    }
    return `<pre class="hljs bg-black/20 p-3 rounded-lg overflow-x-auto my-2 font-mono text-xs"><code>${md.utils.escapeHtml(str)}</code></pre>`
  }
})

const renderedHtml = computed(() => {
  return md.render(props.content || '')
})
</script>

<template>
  <div class="prose prose-invert max-w-none text-sm leading-relaxed" v-html="renderedHtml"></div>
</template>

<style scoped>
:deep(p) {
  margin-bottom: 0.75rem;
}
:deep(p:last-child) {
  margin-bottom: 0;
}
:deep(ul), :deep(ol) {
  margin-top: 0.5rem;
  margin-bottom: 0.75rem;
  padding-left: 1.25rem;
}
:deep(ul) {
  list-style-type: disc;
}
:deep(ol) {
  list-style-type: decimal;
}
:deep(li) {
  margin-bottom: 0.25rem;
}
:deep(code) {
  background-color: rgba(255, 255, 255, 0.08);
  padding: 0.125rem 0.25rem;
  border-radius: 0.25rem;
  font-family: monospace;
  font-size: 0.9em;
}
:deep(pre code) {
  background-color: transparent;
  padding: 0;
  border-radius: 0;
  font-size: 1em;
}
</style>
