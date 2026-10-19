<script setup>
import { ref, onMounted, computed, watch, nextTick, onUnmounted } from 'vue'
import { Copy, Check, Square } from '@lucide/vue'
import { marked } from 'marked'
import { readChatStream } from './chat_stream'
import DOMPurify from 'dompurify'

const input = ref('')
const messages = ref([])
const loading = ref(false)
// 控制下一次发送是否允许联网搜索。
const webSearchEnabled = ref(true)
const error = ref('')
const conversationId = ref(null)
// 列表从后端读取，不再读取浏览器中的完整聊天内容。
const savedChats = ref([])
const sidebarOpen = ref(true)
const menuChatId = ref(null)
const progress = ref('')
const streamingText = ref('')
const messageList = ref(null)
const followLatest = ref(true)
// 当前任务编号和停止请求状态。
const activeTaskId = ref(null)
const stopping = ref(false)
// 标题跟随当前选中的会话。
const currentChatTitle = computed(() => {
  const chat = savedChats.value.find(item => item.id === conversationId.value)
  return chat?.title || 'Agent 聊天'
})

// 记录哪条消息刚复制成功，以及恢复图标的定时器。
const copiedMessage = ref(null)
let copyTimer = null

// 复制原始 Markdown，而不是页面转换后的 HTML。
async function copyMessage(message) {
  try {
    await navigator.clipboard.writeText(message.content)
    copiedMessage.value = message
    clearTimeout(copyTimer)
    copyTimer = setTimeout(() => {
      copiedMessage.value = null
    }, 1500)
  } catch {
    error.value = '复制失败，请检查浏览器的剪贴板权限。'
  }
}

// Markdown 转换后再清理 HTML，避免直接插入不可信内容。
function renderMarkdown(content) {
  return DOMPurify.sanitize(marked.parse(content || '', { async: false }))
}

// 用户向上查看历史时暂停自动滚动。
function handleMessageScroll() {
  const element = messageList.value
  if (!element) return
  const distance = element.scrollHeight - element.scrollTop - element.clientHeight
  followLatest.value = distance < 80
}

async function scrollToLatest() {
  await nextTick()
  const element = messageList.value
  if (element) element.scrollTop = element.scrollHeight
}

function resumeFollowing() {
  followLatest.value = true
  scrollToLatest()
}

watch(
  [messages, progress, loading, streamingText],
  () => {
    if (followLatest.value) scrollToLatest()
  },
  { deep: true },
)

function toggleChatMenu(id) {
  menuChatId.value = menuChatId.value === id ? null : id
}

// 历史接口统一检查 HTTP 状态，并解析 FastAPI 返回的错误详情。
async function requestJson(url, options = {}) {
  const response = await fetch(url, options)
  const data = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = typeof data?.detail === 'string'
      ? data.detail
      : JSON.stringify(data?.detail || data || '服务器未返回 JSON 详情')
    throw new Error(`请求失败：${response.status}，${detail}`)
  }
  if (data === null) throw new Error('接口未返回 JSON，请检查后端和 Vite 代理')
  return data
}

// 浏览器只保留选中的编号，不再写入完整消息。
function rememberSelectedChat() {
  try {
    if (conversationId.value) {
      localStorage.setItem('agent-selected-chat', conversationId.value)
    } else {
      localStorage.removeItem('agent-selected-chat')
    }
  } catch {
    error.value = '无法记住选中状态；数据库中的聊天不受影响。'
  }
}

// 当前选中的聊天始终放在列表最前面，其余保持后端顺序。
function putSelectedFirst() {
  const selected = savedChats.value.find(item => item.id === conversationId.value)
  if (!selected) return
  savedChats.value = [
    selected,
    ...savedChats.value.filter(item => item.id !== selected.id),
  ]
}

// 列表接口只取标题和编号；完整消息等点击时再加载。
async function loadHistory() {
  const data = await requestJson('/chat/history')
  savedChats.value = data.conversations
  putSelectedFirst()
}

// 把后端返回的会话详情应用到聊天区域。
function applyChat(chat) {
  conversationId.value = chat.id
  messages.value = chat.messages.map(message => ({ ...message }))
  input.value = ''
  streamingText.value = ''
  followLatest.value = true
  menuChatId.value = null
  error.value = ''
  putSelectedFirst()
  rememberSelectedChat()
}

// 创建成功后才切换页面，失败时保留当前聊天。
async function newChat() {
  if (loading.value) return false
  loading.value = true
  error.value = ''
  progress.value = '正在新建聊天…'
  try {
    const chat = await requestJson('/chat/history', { method: 'POST' })
    const { messages: unusedMessages, ...metadata } = chat
    savedChats.value = [metadata, ...savedChats.value]
    applyChat(chat)
    return true
  } catch (err) {
    error.value = err.message
    return false
  } finally {
    progress.value = ''
    loading.value = false
  }
}

// 点击历史时请求详情，不再从 localStorage 恢复消息。
async function openChat(chat) {
  if (loading.value) return
  loading.value = true
  error.value = ''
  progress.value = '正在读取聊天…'
  try {
    const detail = await requestJson(`/chat/history/${encodeURIComponent(chat.id)}`)
    applyChat(detail)
  } catch (err) {
    error.value = err.message
  } finally {
    progress.value = ''
    loading.value = false
  }
}

// PATCH 成功后再更新本地标题，避免页面改名但数据库没有改。
async function renameChat(chat) {
  if (loading.value) return
  menuChatId.value = null
  const title = window.prompt('输入新的聊天名称', chat.title)
  if (title === null || !title.trim()) return
  loading.value = true
  error.value = ''
  try {
    const result = await requestJson(`/chat/history/${encodeURIComponent(chat.id)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: title.trim().slice(0, 60) }),
    })
    chat.title = result.title
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

// 只删除数据库会话；现有后端仍保留磁盘上的 Markdown 和附件。
async function deleteChat(chat) {
  if (loading.value) return
  menuChatId.value = null
  if (!window.confirm(`删除聊天“${chat.title}”？Markdown 文件仍保留。`)) return
  loading.value = true
  error.value = ''
  try {
    await requestJson(`/chat/history/${encodeURIComponent(chat.id)}`, {
      method: 'DELETE',
    })
    savedChats.value = savedChats.value.filter(item => item.id !== chat.id)
    if (conversationId.value === chat.id) {
      conversationId.value = null
      messages.value = []
      input.value = ''
      streamingText.value = ''
      rememberSelectedChat()
    }
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

// Enter 发送，Shift+Enter 换行；中文输入法选字时不发送。
function handleComposerKeydown(event) {
  // 其他按键和 Shift+Enter 保留输入框原来的行为。
  if (event.key !== 'Enter' || event.shiftKey) return

  // 中文输入法按 Enter 确认文字时，不触发发送。
  if (event.isComposing || event.keyCode === 229) return

  // 阻止普通 Enter 在输入框中插入换行。
  event.preventDefault()

  // 按住 Enter 或正在等待回答时，不重复发送。
  if (event.repeat || loading.value) return

  // 复用现有发送函数，空消息仍由 send 拦截。
  send()
}


// 通知后端取消任务，仍等待事件流返回最终状态。
async function stopGeneration() {
  const id = activeTaskId.value
  if (!id || stopping.value) return
  stopping.value = true
  try {
    await requestJson(`/chat/tasks/${id}/cancel`, { method: 'POST' })
  } catch (err) {
    if (activeTaskId.value === id) {
      stopping.value = false
      error.value = `停止失败：${err.message}`
    }
  }
  stopping.value=false
  loading.value=false
  activeTaskId.value=null
}

// 发送仍走流式接口；消息入库由后端负责，前端不要重复保存。
async function send() {
  const text = input.value.trim()
  if (!text || loading.value) return
  if (!conversationId.value && !(await newChat())) return

  streamingText.value = ''
  followLatest.value = true
  messages.value.push({ role: 'user', content: text })
  input.value = ''
  loading.value = true
  progress.value = '正在连接 Agent…'
  error.value = ''
  activeTaskId.value = null

  try {
    const response = await fetch('/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        // 只提交本次问题；过去的对话由后端从数据库读取。
      messages: [{ role: 'user', content: text }],
        web_search: webSearchEnabled.value,
        conversation_id: conversationId.value,
      }),
    })
    if (!response.ok) {
      throw new Error(`请求失败：${response.status}，${await response.text()}`)
    }

    let completed = false
    const toolNames = {
      get_stock: '查询库存',
      read_attachment: '读取附件',
      save_report: '生成报告',
      search_web: '联网搜索',
    }


    // 此回调只同步更新页面，不在其中启动未等待的历史请求。
    await readChatStream(response, event => {
      const name = toolNames[event.name] || event.name
      if (event.type === 'start') {
        activeTaskId.value = event.task_id
        progress.value = '正在理解任务…'
        return
      }
      // 后端确认已经停止，显示固定回复并清除临时文字。
      if (event.type === 'cancelled') {
        messages.value.push({
          role: 'assistant', content: '对话内容被主动停止',
        })
        streamingText.value = ''
        completed = true // 主动停止也是正常结束，不能当作连接异常。
        return
      }
      // 停止等待期间冻结文字，但仍接收最终完成或错误通知。
      if (stopping.value && !['done', 'error'].includes(event.type)) return
      if (event.type === 'round_start') {
        streamingText.value = ''
        progress.value = '正在生成…'
      }
      if (event.type === 'text_delta') {
        streamingText.value += event.text
        progress.value = '正在生成…'
      }
      if (event.type === 'tool_start') {
        streamingText.value = ''
        progress.value = `正在${name}…`
      }
      if (event.type === 'tool_end') {
        progress.value = event.result?.error
          ? `${name}未成功，正在处理…`
          : `${name}完成，正在处理下一步…`
      }
      if (event.type === 'error') throw new Error(event.message)
      if (event.type === 'done') {
        const data = event.data
        conversationId.value = data.conversation_id
        messages.value.push({
          role: 'assistant',
          content: data.reply,
          tool_steps: data.tool_steps || [],
        })
        streamingText.value = ''
        rememberSelectedChat()
        completed = true
      }
    })
    if (!completed) throw new Error('连接提前结束，未收到最终结果')
  } catch (err) {
    error.value = err.message
  } finally {
    stopping.value = false
    // 列表刷新失败与聊天失败分开提示，也不自动重发用户消息。
    try {
      await loadHistory()
    } catch (err) {
      const warning = `历史列表刷新失败：${err.message}`
      error.value = error.value ? `${error.value}；${warning}` : warning
    }
    progress.value = ''
    loading.value = false
  }
}

// 上传前等待后端建立会话，防止附件写到空编号或错误会话下。
async function uploadAttachment(event) {
  const file = event.target.files?.[0]
  if (!file || loading.value) return
  const draft = input.value
  if (!conversationId.value) {
    const created = await newChat()
    if (!created) {
      event.target.value = ''
      return
    }
    // 新建会话会清空输入框，恢复上传前正在编写的问题。
    input.value = draft
  }
  const chatId = conversationId.value
  loading.value = true
  error.value = ''
  try {
    const formData = new FormData()
    formData.append('file', file)
    const response = await fetch(`/chat/upload/${encodeURIComponent(chatId)}`, {
      method: 'POST',
      body: formData,
    })
    if (!response.ok) throw new Error(`上传失败：${await response.text()}`)
    const data = await response.json()
    const attachment = `附件：${data.filename}\n附件编号：${data.file_id}`
    input.value = input.value.trim()
      ? `${input.value}\n\n${attachment}`
      : `请读取以下附件并总结重点。\n${attachment}`
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
    event.target.value = ''
  }
}

// 页面刷新后，先加载后端列表，再按浏览器记住的编号恢复详情。
onMounted(async () => {
  loading.value = true
  progress.value = '正在加载历史…'
  try {
    let selectedId = null
    try {
      selectedId = localStorage.getItem('agent-selected-chat')
    } catch {
      // 浏览器禁用本地存储时，仍可加载数据库列表。
    }
    await loadHistory()
    const selected = savedChats.value.find(chat => chat.id === selectedId)
    if (selected) {
      const detail = await requestJson(`/chat/history/${encodeURIComponent(selected.id)}`)
      applyChat(detail)
    } else {
      // 只移除失效的选中编号，不碰旧版 agent-chats 备份。
      rememberSelectedChat()
    }
  } catch (err) {
    error.value = `加载历史失败：${err.message}`
  } finally {
    progress.value = ''
    loading.value = false
  }
})

// 页面卸载时取消定时器，避免遗留任务。
onUnmounted(() => clearTimeout(copyTimer))


</script>

<template>
  <div class="workspace" :class="{ collapsed: !sidebarOpen }">
    // collapsed 是否折叠
    <aside v-if="sidebarOpen" class="sidebar">
      <header class="sidebar-header">
        <strong>Agent 工作台</strong>
        <button class="icon-button" @click="sidebarOpen = false"
          title="收起侧栏" aria-label="收起侧栏">‹</button>
      </header>
      <button
        class="sidebar-item new-chat-button"
        :disabled="loading"
        @click="newChat"
      >
        ＋ 新建聊天
      </button>
      <nav class="history" aria-label="历史聊天">
        <div v-for="chat in savedChats" :key="chat.id" class="history-entry">
          <!-- 当前会话添加 selected 类，显示选中背景。 -->
          <div
            class="history-row"
            :class="{ selected: conversationId === chat.id }"
          >
            <button class="sidebar-item history-title" :disabled="loading"
              @click="menuChatId = null; openChat(chat)" :title="chat.title">
              {{ chat.title }}
            </button>
            <button class="more-button" :class="{ visible: menuChatId === chat.id }"
              :disabled="loading" @click="toggleChatMenu(chat.id)"
              :aria-expanded="menuChatId === chat.id" aria-label="聊天选项" title="聊天选项">
              ⋯
            </button>
          </div>
          <div v-if="menuChatId === chat.id" class="chat-options">
            <button @click="renameChat(chat)" :disabled="loading">重命名</button>
            <button class="delete-option" @click="deleteChat(chat)" :disabled="loading">删除</button>
          </div>
        </div>
      </nav>
    </aside>

    <main class="chat-area">
      <header class="chat-header">
        <button v-if="!sidebarOpen" class="icon-button"
          @click="sidebarOpen = true" title="展开侧栏" aria-label="展开侧栏">›</button>
        <!-- 顶部标题与当前选中的聊天同步。 -->
        <span class="current-chat-title" :title="currentChatTitle">
          {{ currentChatTitle }}
        </span>
      </header>
      <!-- 获取消息容器，并监听用户是否主动向上浏览。 -->
      <section
        ref="messageList"
        class="message-list"
        aria-label="聊天消息"
        @scroll="handleMessageScroll"
      >
        <article v-for="(message, index) in messages" :key="index">
          <!-- 助手回答显示复制按钮，用户消息保持原样。 -->
          <div class="message-header">
            <strong>{{ message.role === 'user' ? '你' : '助手' }}</strong>
            <button v-if="message.role === 'assistant'"
              type="button" class="copy-button"
              :title="copiedMessage === message ? '已复制' : '复制回答'"
              :aria-label="copiedMessage === message ? '已复制' : '复制回答'"
              @click="copyMessage(message)">
              <component :is="copiedMessage === message ? Check : Copy" :size="16" />
            </button>
          </div>
          <!-- 展示 Markdown 正文；原始消息仍用于接口请求和记录保存。 -->
          <div class="markdown-body" v-html="renderMarkdown(message.content)"></div>
          <!-- 有工具调用时显示可展开的执行记录。 -->
          <details v-if="message.tool_steps?.length" class="tool-details">
            <summary>执行记录 · {{ message.tool_steps.length }} 次工具调用</summary>
            <section v-for="(step, index) in message.tool_steps" :key="index">
              <strong>{{ step.name }}</strong>
              <p>参数：{{ step.arguments }}</p>
              <pre>{{ JSON.stringify(step.result, null, 2) }}</pre>
              <!-- 直接使用报告工具返回的地址，不依赖助手正文中的链接。 -->
              <a
                v-if="step.name === 'save_report' && step.result?.download_url"
                class="report-download"
                :href="step.result.download_url"
              >
                下载 Markdown 报告
              </a>
            </section>
          </details>
        </article>
        <!-- 临时回答单独展示，避免未完成的内容混入下一次模型上下文。 -->
        <article v-if="streamingText" class="streaming-message">
          <strong>{{ loading ? '助手 · 生成中' : '助手 · 未完成' }}</strong>
          <div
            class="markdown-body"
            v-html="renderMarkdown(streamingText)"
          ></div>
        </article>
        <!-- 随后端事件更新状态；上传资料时使用默认提示。 -->
        <p v-if="loading" role="status">
          {{ stopping ? '正在停止生成…' : (progress || '正在上传并解析资料…') }}
        </p>
        <p v-if="error" class="error" role="alert">{{ error }}</p>
      </section>
      <!-- 用户离开底部时，提供恢复跟随的入口。 -->
      <div v-if="!followLatest" class="latest-bar">
        <button type="button" @click="resumeFollowing">
          ↓ 回到最新
        </button>
      </div>
      <!-- 等待任务期间禁止切换，避免与当前请求的实际设置不一致。 -->
      <div class="latest-bar">
        <label>
          <input v-model="webSearchEnabled" type="checkbox" :disabled="loading" />
          联网搜索
        </label>
      </div>
      <!-- 选择文件后自动上传；点击发送时，Agent 才开始分析。 -->
      <form class="composer" @submit.prevent="send">
        <label class="attachment-button" :class="{ disabled: loading }">
          上传资料
          <input
            class="attachment-input"
            type="file"
            accept=".txt,.md,.pdf,.docx,.png,.jpg,.jpeg"
            :disabled="loading"
            @change="uploadAttachment"
          />
        </label>

        <!-- 用多行输入框展示问题和附件编号。 -->
<!-- 监听键盘：Enter 发送，Shift+Enter 保留换行。 -->
        <textarea
          v-model="input"
          aria-label="消息"
          placeholder="输入问题，或上传资料…"
          rows="3"
          :disabled="loading"
          @keydown="handleComposerKeydown"
        ></textarea>

        <!-- 停止按钮不是提交按钮，不能再次触发 send。 -->
        <button v-if="activeTaskId" type="button" :disabled="stopping"
          @click="stopGeneration">
          停止
          <!-- <Square :size="18" /> -->
        </button>
        <button v-else :disabled="loading || !input.trim()">发送</button>
      </form>
    </main>
  </div>
</template>