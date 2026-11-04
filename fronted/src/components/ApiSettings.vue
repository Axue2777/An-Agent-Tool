<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Settings2, X, Save, PlugZap } from '@lucide/vue'

const props = defineProps({ busy: Boolean })
const emit = defineEmits(['updated'])
const panel = ref(null)
const working = ref(false)
const loaded = ref(false)
const notice = ref('')
const failure = ref('')
const baseline = ref('')
const saved = ref({})
const form = reactive({
  revision: 'initial', provider: 'deepseek', deepseek_model: 'deepseek-flash',
  zhipu_model: 'glm-4.7-flash', search_enabled: false, share_chat_key: false,
})
const keys = reactive({ deepseek_key: '', zhipu_key: '' })
const clearKeys = reactive({ deepseek_key: false, zhipu_key: false })
const keyLabels = {
  deepseek_key: 'DeepSeek 聊天密钥', zhipu_key: '智谱标准 API 聊天密钥',
}
const keyFlags = {
  deepseek_key: 'has_deepseek_key', zhipu_key: 'has_zhipu_key',
}
const activeKey = computed(() => form.provider === 'deepseek' ? 'deepseek_key' : 'zhipu_key')
const model = computed({
  get: () => form.provider === 'deepseek' ? form.deepseek_model : form.zhipu_model,
  set: value => {
    if (form.provider === 'deepseek') form.deepseek_model = value
    else form.zhipu_model = value
  },
})
const dirty = computed(() => JSON.stringify(form) !== baseline.value
  || Object.values(keys).some(Boolean) || Object.values(clearKeys).some(Boolean))
const searchNote = computed(() => {
  if (form.provider === 'deepseek') return 'DeepSeek 模式仅用于聊天，不提供联网搜索。'
  if (!form.search_enabled) return '联网搜索已禁用，本轮仅使用聊天模型 API。'
  return '智谱聊天和智谱搜索使用同一把密钥，但仍调用两个不同接口，按各自规则计费。'
})

function changeProvider() {
  // 仅手动切换服务商时重置搜索，不覆盖从后端读回的设置。
  form.search_enabled = false
  form.share_chat_key = form.provider === 'zhipu'
}

// Secrets exist in these inputs only while editing, never in localStorage.
function wipeInputs() {
  for (const name of Object.keys(keys)) {
    keys[name] = ''
    clearKeys[name] = false
  }
}

async function request(path, options = {}) {
  const response = await fetch(path, { ...options, cache: 'no-store' })
  const data = await response.json().catch(() => null)
  if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : `请求失败：${response.status}`)
  return data
}

function apply(data) {
  saved.value = data
  for (const name of Object.keys(form)) form[name] = data[name]
  baseline.value = JSON.stringify(form)
  loaded.value = true
  wipeInputs()
  emit('updated', data)
}

async function refresh() {
  working.value = true
  failure.value = ''
  try {
    apply(await request('/chat/settings'))
  } catch (error) {
    loaded.value = false
    failure.value = error.message
  } finally {
    working.value = false
  }
}

async function open() {
  if (props.busy || working.value) return
  notice.value = ''
  wipeInputs()
  panel.value.showModal()
  await refresh()
}

function close() {
  if (!working.value) panel.value.close()
}

async function save() {
  if (working.value || props.busy || !loaded.value) return
  working.value = true
  failure.value = ''
  notice.value = ''
  const payload = { ...form }
  for (const name of Object.keys(keys)) {
    payload[name] = clearKeys[name] ? '' : keys[name].trim() || null
  }
  try {
    apply(await request('/chat/settings', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }))
    notice.value = '设置已保存。新配置从下一次发送开始生效，尚未验证接口可用性。'
  } catch (error) {
    failure.value = error.message
  } finally {
    working.value = false
  }
}

async function test(kind) {
  if (dirty.value) {
    failure.value = '请先保存设置，再测试连接。'
    return
  }
  if (!window.confirm('这会发送一次真实 API 请求，可能消耗额度或产生费用。继续吗？')) return
  working.value = true
  failure.value = ''
  notice.value = ''
  try {
    const data = await request('/chat/settings/test', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind }),
    })
    notice.value = data.message
  } catch (error) {
    failure.value = error.message
  } finally {
    working.value = false
  }
}

onMounted(async () => {
  await refresh()
  if (loaded.value && !saved.value.chat_configured) panel.value.showModal()
})
</script>

<template>
  <button type="button" class="api-open" title="API 设置" aria-label="API 设置"
    :disabled="busy || working" @click="open"><Settings2 :size="18" /></button>
  <dialog ref="panel" class="api-dialog" aria-labelledby="api-heading"
    @close="wipeInputs" @cancel="working && $event.preventDefault()">
    <form @submit.prevent="save">
      <header class="api-heading">
        <h2 id="api-heading">API 设置</h2>
        <button type="button" class="api-icon" title="关闭" aria-label="关闭"
          :disabled="working" @click="close"><X :size="18" /></button>
      </header>
      <fieldset :disabled="working || busy || !loaded">
        <legend>聊天模型</legend>
        <label>服务商
          <select v-model="form.provider" @change="changeProvider">
            <option value="deepseek">DeepSeek</option>
            <option value="zhipu">智谱标准 API</option>
          </select>
        </label>
        <label>模型编号<input v-model="model" required maxlength="80" autocomplete="off" /></label>
        <label>
          {{ keyLabels[activeKey] }}：{{ saved[keyFlags[activeKey]] ? '已配置' : '未配置' }}
          <input v-model="keys[activeKey]" type="password" maxlength="256" autocomplete="new-password"
            :disabled="clearKeys[activeKey]" placeholder="留空保留原密钥" />
          <span class="api-check"><input v-model="clearKeys[activeKey]" type="checkbox" />清除已保存密钥</span>
        </label>
      </fieldset>
      <fieldset :disabled="working || busy || !loaded">
        <legend>联网搜索</legend>
        <label class="api-check"><input v-model="form.search_enabled" type="checkbox"
          :disabled="form.provider !== 'zhipu'" />允许联网搜索</label>
        <p class="api-note">{{ searchNote }}</p>
        <p v-if="form.provider === 'zhipu'" class="api-note">智谱须使用有对应接口权限的标准 API 密钥；编程套餐密钥不保证通用。开启搜索不代表每轮都会调用，实际执行见聊天工具记录。</p>
      </fieldset>
      <p v-if="failure" class="api-error" role="alert">{{ failure }}</p>
      <p v-if="notice" class="api-note" role="status">{{ notice }}</p>
      <footer class="api-actions">
        <button type="button" :disabled="working || busy || !loaded" @click="test('chat')"><PlugZap :size="16" />测试聊天</button>
        <button type="button" :disabled="working || busy || !loaded || form.provider !== 'zhipu' || !form.search_enabled" @click="test('search')"><PlugZap :size="16" />测试搜索</button>
        <button type="submit" :disabled="working || busy || !loaded"><Save :size="16" />{{ working ? '处理中…' : '保存' }}</button>
      </footer>
    </form>
  </dialog>
</template>

<style scoped>
.api-open, .api-icon { display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px; flex: 0 0 36px; padding: 0; border: 0; border-radius: 6px; background: transparent; color: inherit; cursor: pointer; }
.api-open:hover, .api-icon:hover { background: #e5e7eb; color: #111827; }
.api-dialog { box-sizing: border-box; width: 560px; max-width: calc(100% - 24px); max-height: calc(100dvh - 32px); margin: auto; padding: 20px; overflow: auto; border: 1px solid #cbd5e1; border-radius: 8px; background: #fff; color: #20242b; font-size: 14px; letter-spacing: 0; }
.api-dialog::backdrop { background: rgb(0 0 0 / 40%); }
.api-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.api-heading h2 { margin: 0; font-size: 18px; }
.api-dialog fieldset { display: grid; gap: 12px; min-width: 0; margin: 0; padding: 12px 0; border: 0; border-top: 1px solid #e5e7eb; }
.api-dialog legend { padding: 0 8px 0 0; font-weight: 600; }
.api-dialog label { display: grid; gap: 6px; min-width: 0; }
.api-dialog input:not([type="checkbox"]), .api-dialog select { box-sizing: border-box; width: 100%; min-width: 0; height: 36px; padding: 6px 8px; border: 1px solid #b8bec7; border-radius: 4px; background: #fff; color: #20242b; font: inherit; }
.api-dialog .api-check { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.api-dialog input[type="checkbox"] { width: 16px; height: 16px; margin: 0; flex: 0 0 16px; }
.api-note, .api-error { margin: 4px 0; line-height: 1.6; overflow-wrap: anywhere; }
.api-note { color: #515862; }
.api-error { color: #b42318; }
.api-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; margin-top: 16px; }
.api-actions button { display: inline-flex; align-items: center; gap: 6px; min-height: 36px; padding: 6px 10px; border: 1px solid #b8bec7; border-radius: 4px; background: #f5f6f8; color: #20242b; font: inherit; cursor: pointer; }
.api-dialog button:disabled, .api-open:disabled { opacity: .5; cursor: not-allowed; }
</style>
