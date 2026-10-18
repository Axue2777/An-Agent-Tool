<!-- 我们将把默认页面改成聊天页面 -->
<script setup>
import { ref, onMounted, computed, watch, nextTick } from 'vue'
import { marked } from 'marked'
import { readChatStream } from './chat_stream'
import DOMPurify from 'dompurify'

// 将消息中的 Markdown 转为经过清理的 HTML。
function renderMarkdown(content) {
  return DOMPurify.sanitize(marked.parse(content || '', { async: false }))
}
const input = ref('')       // 输入框内容
const messages = ref([])    // 页面上显示的消息
const loading = ref(false) // 是否正在等待回答
const error = ref('')       // 请求失败时的提示
const conversationId = ref(null)
const savedChats = ref(readSavedChats())
const sidebarOpen = ref(true)
const menuChatId = ref(null)
// 显示当前任务阶段，上传时未设置则沿用默认等待提示。
const progress = ref('')
// 仅用于展示本轮正在生成的文字，不混入正式聊天历史。
const streamingText = ref('')
// 保存消息区域元素，以及是否自动跟随最新内容。
const messageList = ref(null)
const followLatest = ref(true)
// 根据当前会话编号读取标题；未选择聊天时显示默认名称。
const currentChatTitle = computed(() => {
  const chat = savedChats.value.find(
    item => item.id === conversationId.value
  )
  return chat?.title || 'Agent 聊天'
})

// 用户距离底部不足 80 像素时，继续自动跟随。
function handleMessageScroll() {
  const element = messageList.value
  if (!element) return
  const distance = element.scrollHeight - element.scrollTop - element.clientHeight
  followLatest.value = distance < 80
}

// 等待 Vue 更新页面尺寸后，再滚动到底部。
async function scrollToLatest() {
  await nextTick()
  const element = messageList.value
  if (element) element.scrollTop = element.scrollHeight
}

// 用户主动点击按钮时，恢复自动跟随。
function resumeFollowing() {
  followLatest.value = true
  scrollToLatest()
}

// 消息、执行进度或等待状态变化时，按用户当前选择滚动。
watch(
    // 文字逐步增长时，也按用户选择跟随最新内容。
  [messages, progress, loading, streamingText],
  () => {
    if (followLatest.value) scrollToLatest()
  },
  { deep: true },
)

function toggleChatMenu(id) {
  menuChatId.value = menuChatId.value === id ? null : id
}

function persistChats() {
  try {
    localStorage.setItem('agent-chats', JSON.stringify(savedChats.value))
  } catch {
    error.value = '历史记录保存失败。'
  }
}

function renameChat(chat) {
  menuChatId.value = null
  const title = window.prompt('输入新的聊天名称', chat.title)
  if (title === null || !title.trim()) return
  chat.title = title.trim().slice(0, 60)
  persistChats()
}

function deleteChat(chat) {
  menuChatId.value = null
  if (!window.confirm(`删除聊天“${chat.title}”？Markdown 文件仍保留。`)) return
  savedChats.value = savedChats.value.filter(item => item.id !== chat.id)
  if (conversationId.value === chat.id) {
    conversationId.value = null
    messages.value = []
    input.value = ''
    error.value = ''
  }
  persistChats()
  rememberSelectedChat()
}

function readSavedChats() {
  try {
    return JSON.parse(localStorage.getItem('agent-chats') || '[]')
  } catch {
    return []
  }
}

function saveCurrentChat() {
  // 新聊天即使没有消息，也要保留在历史列表中。
  if (!conversationId.value) return 
  if (!conversationId.value || messages.value.length === 0) return
  const existing = savedChats.value.find(item => item.id === conversationId.value)
  const chat = {
    id: conversationId.value,
    // 保留已设置的名称，空会话使用默认标题。
    title: existing?.title ?? (messages.value[0]?.content.slice(0, 20) || '新建聊天'),
    messages: messages.value.map(message => ({ ...message })),
  }
  const others = savedChats.value.filter(item => item.id !== chat.id)
  savedChats.value = [chat, ...others]

  try {
    localStorage.setItem('agent-chats', JSON.stringify(savedChats.value))
  } catch {
    error.value = '浏览器历史保存失败，后端 Markdown 记录仍保留。'
  }
}

// 打开历史聊天，并将选中的会话置顶、保存排序。
function openChat(chat) {
  if (loading.value) return
  // 切换会话后，默认定位到这段聊天的最新消息。
  followLatest.value = true
  // 切换聊天时移除未完成的临时内容。
  streamingText.value = ''
  // 切换前保存当前聊天。
  saveCurrentChat()

  // 按编号找到最新记录，避免使用保存前的旧对象。
  const selected = savedChats.value.find(item => item.id === chat.id)
  if (!selected) return

  // 恢复会话编号和消息，继续写入原来的 Markdown 文件。
  conversationId.value = selected.id
  messages.value = selected.messages.map(message => ({ ...message }))
  input.value = ''
  error.value = ''
  menuChatId.value = null

  // 将选中的聊天放在最前面，其余聊天保持原有顺序。
  savedChats.value = [
    selected,
    ...savedChats.value.filter(item => item.id !== selected.id),
  ]

  // 保存列表顺序和选中状态，刷新后仍然有效。
  persistChats()
  rememberSelectedChat()
}
async function send() {
  const text = input.value.trim()
  if (!text || loading.value) return

  // 首次发送时先建立会话。
  if (!conversationId.value) newChat()

  // 新请求清空上一轮临时文字，并恢复自动滚动。
  streamingText.value = ''
  followLatest.value = true

  // 从这里开始，保留你原来的发送逻辑。
  messages.value.push({ role: 'user', content: text })
  saveCurrentChat()
  input.value = ''
  loading.value = true
  progress.value = '正在连接 Agent…'
  error.value = ''

  // 后面的 try、fetch 等代码保持原样。

  try {
    const response = await fetch('/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        // 展示用的执行步骤不重复发送给模型。
        messages: messages.value.map(({ role, content }) => ({ role, content })),
        conversation_id: conversationId.value,
      }),
    })
    if (!response.ok) {
      const detail = await response.text()
      throw new Error(`请求失败：${response.status}，详情：${detail}`)
  }
    // 分别处理进度、最终结果和错误，不能再用 response.json()。
    let completed = false
    const toolNames = {
      get_stock: '查询库存',
      read_attachment: '读取附件',
      save_report: '生成报告',
      // 联网搜索继续使用现有的工具开始、结束事件。
      search_web: '联网搜索',
    }
    await readChatStream(response, event => {
      const name = toolNames[event.name] || event.name
            // 每轮模型请求开始时，清空上一轮的临时说明。
      if (event.type === 'round_start') {
        streamingText.value = ''
        progress.value = '正在生成…'
      }

      // 收到文字片段后，追加到页面上的临时回答。
      if (event.type === 'text_delta') {
        streamingText.value += event.text
        progress.value = '正在生成…'
      }

      // 开始执行工具时，清除中间说明，继续显示工具进度。
      if (event.type === 'tool_start') {
        streamingText.value = ''
      }
      if (event.type === 'start') progress.value = '正在理解任务…'
      if (event.type === 'tool_start') progress.value = `正在${name}…`
      if (event.type === 'tool_end') {
        progress.value = event.result?.error
          ? `${name}未成功，正在处理…`
          : `${name}完成，正在处理下一步…`
      }
      if (event.type === 'error') throw new Error(event.message)
      if (event.type === 'done') {
        // 最终结果继续使用原来的结构，保存历史和执行记录。
        const data = event.data
        conversationId.value = data.conversation_id
        messages.value.push({
          role: 'assistant',
          content: data.reply,
          tool_steps: data.tool_steps || [],
        })

        // 完整回答已经显示，清除临时副本，防止出现两份。
        streamingText.value = ''

        saveCurrentChat()
        rememberSelectedChat()
        completed = true
      }
    })
    if (!completed) throw new Error('连接提前结束，未收到最终结果')
  } catch (err) {
    error.value = err.message
  } finally {
    progress.value=''
    loading.value = false // 成功或失败都恢复发送按钮
  }
  rememberSelectedChat()
}

// 创建独立会话，并立即保存到左侧历史列表。
function newChat() {
  if (loading.value) return
  // 切换会话后，默认定位到这段聊天的最新消息。
  followLatest.value = true
  // 切换聊天时移除未完成的临时内容。
  streamingText.value = ''
  saveCurrentChat()
  conversationId.value = crypto.randomUUID()
  messages.value = []
  input.value = ''
  error.value = ''
  menuChatId.value = null
  saveCurrentChat()
  rememberSelectedChat()
}

// 保存当前选中的会话编号，供刷新页面后恢复。
function rememberSelectedChat() {
  try {
    if (conversationId.value) {
      localStorage.setItem('agent-selected-chat', conversationId.value)
    } else {
      localStorage.removeItem('agent-selected-chat')
    }
  } catch {
    error.value = '当前聊天的选择状态保存失败。'
  }
}

// 页面加载后，从已有历史中恢复上次选中的聊天。
onMounted(() => {
  try {
    const id = localStorage.getItem('agent-selected-chat')
    const chat = savedChats.value.find(item => item.id === id)
    if (!chat) {
      localStorage.removeItem('agent-selected-chat')
      return
    }
    conversationId.value = chat.id
    messages.value = chat.messages.map(message => ({ ...message }))
  } catch {
    error.value = '恢复上次聊天失败。'
  }
})

// 上传文本资料，并把附件编号填入输入框，供 Agent 读取。
async function uploadAttachment(event) {
  const file = event.target.files?.[0]
  if (!file || loading.value) return

  // 没有当前会话时，先创建，确保附件归属正确。
  if (!conversationId.value) newChat()
  const chatId = conversationId.value
  loading.value = true
  error.value = ''

  try {
    // FormData 用于发送文件，由浏览器自动设置请求格式。
    const formData = new FormData()
    formData.append('file', file)

    const response = await fetch(`/chat/upload/${chatId}`, {
      method: 'POST',
      body: formData,
    })
    if (!response.ok) {
      throw new Error(`上传失败：${await response.text()}`)
    }

    const data = await response.json()

    // 将附件信息加入草稿，保留用户已经输入的问题。
    const attachment = `附件：${data.filename}\n附件编号：${data.file_id}`
    input.value = input.value.trim()
      ? `${input.value}\n\n${attachment}`
      : `请读取以下附件并总结重点。\n${attachment}`
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
    event.target.value = '' // 允许再次选择同一个文件。
  }
}
</script>

<template>
  <div class="workspace" :class="{ collapsed: !sidebarOpen }">
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
          <strong>{{ message.role === 'user' ? '你' : '助手' }}</strong>
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
          {{ progress || '正在上传并解析资料…' }}
        </p>
        <p v-if="error" class="error" role="alert">{{ error }}</p>
      </section>
      <!-- 用户离开底部时，提供恢复跟随的入口。 -->
      <div v-if="!followLatest" class="latest-bar">
        <button type="button" @click="resumeFollowing">
          ↓ 回到最新
        </button>
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
        <textarea
          v-model="input"
          aria-label="消息"
          placeholder="输入问题，或上传资料…"
          rows="3"
          :disabled="loading"
        ></textarea>

        <button :disabled="loading || !input.trim()">发送</button>
      </form>
    </main>
  </div>
</template>