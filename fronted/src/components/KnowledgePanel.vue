<script setup>
import { onMounted, ref, watch } from 'vue'

const props = defineProps({ conversationId: { type: String, required: true } })
const emit = defineEmits(['close'])
const files = ref([])
const busy = ref(false)
const error = ref('')
const picker = ref(null)

async function loadFiles() {
  if (!props.conversationId) return
  busy.value = true
  try {
    const response = await fetch(`/chat/history/${props.conversationId}/knowledge`)
    if (!response.ok) throw new Error(`读取资料失败：${response.status}`)
    files.value = (await response.json()).files
  } catch (cause) {
    error.value = cause.message
  } finally {
    busy.value = false
  }
}

async function upload(event) {
  const selected = Array.from(event.target.files || [])
  if (!selected.length) return
  busy.value = true
  error.value = ''
  try {
    for (const file of selected) {
      const form = new FormData()
      form.append('file', file)
      const response = await fetch(`/chat/history/${props.conversationId}/knowledge`, {
        method: 'POST', body: form,
      })
      if (!response.ok) {
        const data = await response.json().catch(() => ({}))
        throw new Error(`${file.name}：${data.detail || response.status}`)
      }
    }
  } catch (cause) {
    error.value = cause.message
  } finally {
    picker.value.value = ''
    busy.value = false
    await loadFiles()
  }
}

async function remove(file) {
  if (!window.confirm(`删除资料“${file.filename}”？`)) return
  busy.value = true
  error.value = ''
  try {
    const response = await fetch(
      `/chat/history/${props.conversationId}/knowledge/${file.id}`,
      { method: 'DELETE' },
    )
    if (!response.ok) throw new Error(`删除失败：${response.status}`)
  } catch (cause) {
    error.value = cause.message
  } finally {
    busy.value = false
    await loadFiles()
  }
}

watch(() => props.conversationId, loadFiles)
onMounted(loadFiles)
</script>

<template>
  <div class="knowledge-backdrop">
    <section class="knowledge-panel" role="dialog" aria-modal="true" aria-label="当前聊天的资料库">
      <header>
        <h2>资料库</h2>
        <button type="button" :disabled="busy" @click="emit('close')">关闭</button>
      </header>
      <input ref="picker" type="file" multiple :disabled="busy" @change="upload"
        accept=".txt,.md,.pdf,.docx,.csv" aria-label="添加资料" />
      <p v-if="error" role="alert">{{ error }}</p>
      <p v-if="!files.length">暂无资料</p>
      <ul v-else>
        <li v-for="file in files" :key="file.id">
          <span>{{ file.filename }} · {{ file.kind === 'inventory' ? '库存表' : '文档' }}</span>
          <button type="button" :disabled="busy" @click="remove(file)">删除</button>
        </li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.knowledge-backdrop { position: fixed; inset: 0; z-index: 100; display: grid; place-items: center; padding: 16px; background: rgb(0 0 0 / 40%); }
.knowledge-panel { box-sizing: border-box; width: min(560px, 100%); max-height: calc(100dvh - 32px); overflow: auto; padding: 20px; border: 1px solid #cbd5e1; border-radius: 8px; background: #fff; color: #20242b; }
.knowledge-panel header, .knowledge-panel li { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.knowledge-panel h2 { margin: 0 0 14px; font-size: 18px; }
.knowledge-panel ul { padding-left: 20px; }
.knowledge-panel li { padding: 8px 0; border-bottom: 1px solid #e5e7eb; }
.knowledge-panel input { max-width: 100%; }
</style>
