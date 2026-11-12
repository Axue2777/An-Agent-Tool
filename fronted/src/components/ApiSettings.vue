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
  zhipu_model: 'glm-4.7-flash', qwen_model: 'qwen-plus',
  openai_model: 'gpt-5-mini', gemini_model: 'gemini-3.8-flash',
  custom_model: 'custom-model',
  qwen_base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  custom_base_url: '', search_enabled: false, share_chat_key: false,
})
const keys = reactive({ deepseek_key: '', zhipu_key: '', qwen_key: '',
  openai_key: '', gemini_key: '', custom_key: '' })
const clearKeys = reactive({ deepseek_key: false, zhipu_key: false,
  qwen_key: false, openai_key: false, gemini_key: false, custom_key: false })
const keyLabels = {
  deepseek_key: 'DeepSeek', zhipu_key: '智谱标准 API', qwen_key: '千问（阿里云百炼）',
  openai_key: 'OpenAI', gemini_key: 'Gemini', custom_key: '自定义接口',
}
const activeKey = computed(() => `${form.provider}_key`)
const model = computed({
  get: () => form[`${form.provider}_model`],
  set: value => { form[`${form.provider}_model`] = value },
})
const modelExamples = {
  deepseek: ['deepseek-flash', 'deepseek-v4-pro'],
  zhipu: ['glm-4.7-flash'],
  qwen: ['qwen-plus'],
  openai: ['gpt-5-mini'],
  gemini: ['gemini-3.8-flash'],
  custom: [],
}
const dirty = computed(() => JSON.stringify(form) !== baseline.value
  || Object.values(keys).some(Boolean) || Object.values(clearKeys).some(Boolean))
const searchNote = computed(() => {
  if (form.provider !== 'zhipu') return '当前独立联网搜索工具只支持智谱模式；其他服务商仍可聊天和使用本地资料库。'
  if (!form.search_enabled) return '联网搜索已禁用，本轮仅使用聊天模型 API。'
  return '智谱聊天和智谱搜索使用同一把密钥，但仍调用两个不同接口，按各自规则计费。'
})

function changeProvider() {
  // 仅手动切换服务商时重置搜索，不覆盖从后端读回的设置。
  if (form.provider !== 'zhipu') form.search_enabled = false
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
    notice.value = '设置已保存到当前 Windows 用户的凭据中；重新打开软件无需重填。新配置从下一次发送开始生效。'
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
            <option value="qwen">千问（阿里云百炼）</option>
            <option value="zhipu">智谱标准 API</option>
            <option value="openai">OpenAI / GPT</option>
            <option value="gemini">Google Gemini</option>
            <option value="custom">自定义 OpenAI 兼容接口</option>
          </select>
        </label>
        <label>模型编号（可直接修改）
          <input v-model="model" required maxlength="80" autocomplete="off" list="model-suggestions" />
          <datalist id="model-suggestions">
            <option v-for="name in modelExamples[form.provider]" :key="name" :value="name" />
          </datalist>
        </label>
        <label v-if="form.provider === 'qwen'">千问 Base URL（须与密钥地域一致）
          <input v-model="form.qwen_base_url" type="url" required maxlength="512" autocomplete="off" />
        </label>
        <label v-if="form.provider === 'custom'">自定义 Base URL（HTTPS）
          <input v-model="form.custom_base_url" type="url" required maxlength="512" autocomplete="off"
            placeholder="https://你的服务商地址/v1" />
        </label>
        <label>
          {{ keyLabels[activeKey] }} API 密钥：{{ saved[`has_${activeKey}`] ? '已保存' : '未配置' }}
          <input v-model="keys[activeKey]" type="password" maxlength="256" autocomplete="new-password"
            :disabled="clearKeys[activeKey]" placeholder="留空保留原密钥" />
          <span class="api-check"><input v-model="clearKeys[activeKey]" type="checkbox" />清除已保存密钥</span>
        </label>
        <!-- 聊天使用其他服务商时，也能单独填写智谱识图和生图密钥。 -->
        <label v-if="form.provider !== 'zhipu'">
          智谱识图与生图密钥（可选）：{{ saved.has_zhipu_key ? '已保存' : '未配置' }}
          <input v-model="keys.zhipu_key" type="password" maxlength="256"
            autocomplete="new-password" :disabled="clearKeys.zhipu_key"
            placeholder="留空保留原智谱密钥" />
          <span class="api-check"><input v-model="clearKeys.zhipu_key" type="checkbox" />清除已保存智谱密钥</span>
        </label>
        <p class="api-note">已保存的密钥不会回显到输入框；关闭再打开软件时会自动使用。不同服务商的密钥和模型编号分别保留。</p>
        <p v-if="form.provider === 'custom'" class="api-note">自定义接口会接收你填写的密钥和聊天内容，请确认 Base URL 属于你信任的服务商。</p>
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
.api-open, .api-icon { display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px; flex: 0 0 36px; padding: 0; border: 0; border-radius: 12px; background: transparent; color: inherit; cursor: pointer; }
.api-open:hover, .api-icon:hover { background: #eae4ff; color: #574599; }
.api-dialog { box-sizing: border-box; width: 560px; max-width: calc(100% - 24px); max-height: calc(100dvh - 32px); margin: auto; padding: 20px; overflow: auto; border: 1px solid #c8b9ed; border-radius: 20px; background: #fffdfb; color: #354063; font-size: 14px; letter-spacing: 0; box-shadow: 0 20px 60px rgb(40 33 80 / 20%); }
.api-dialog::backdrop { background: rgb(0 0 0 / 40%); }
.api-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.api-heading h2 { margin: 0; font-size: 18px; }
.api-dialog fieldset { display: grid; gap: 12px; min-width: 0; margin: 0; padding: 12px 0; border: 0; border-top: 1px solid #e5e7eb; }
.api-dialog legend { padding: 0 8px 0 0; font-weight: 600; }
.api-dialog label { display: grid; gap: 6px; min-width: 0; }
.api-dialog input:not([type="checkbox"]), .api-dialog select { box-sizing: border-box; width: 100%; min-width: 0; height: 36px; padding: 6px 8px; border: 1px solid #c8c6e8; border-radius: 10px; background: #fcfbff; color: #354063; font: inherit; }
.api-dialog .api-check { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.api-dialog input[type="checkbox"] { width: 16px; height: 16px; margin: 0; flex: 0 0 16px; }
.api-note, .api-error { margin: 4px 0; line-height: 1.6; overflow-wrap: anywhere; }
.api-note { color: #515862; }
.api-error { color: #b42318; }
.api-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; margin-top: 16px; }
.api-actions button { display: inline-flex; align-items: center; gap: 6px; min-height: 36px; padding: 6px 10px; border: 1px solid #c8c6e8; border-radius: 10px; background: #f2edff; color: #354063; font: inherit; cursor: pointer; }
.api-dialog button:disabled, .api-open:disabled { opacity: .5; cursor: not-allowed; }
</style>
