<script setup>
import { ref, onMounted, computed, watch, nextTick, onUnmounted } from 'vue'
import NewChatSetup from './components/NewChatSetup.vue'
import KnowledgePanel from './components/KnowledgePanel.vue'
import ApiSettings from './components/ApiSettings.vue'
import { Copy, Check, Square, Download, FolderOpen } from '@lucide/vue'
import { marked } from 'marked'
import { readChatStream } from './chat_stream'
import DOMPurify from 'dompurify'

const input = ref('')
const showNewChatSetup = ref(false)
const showKnowledgePanel = ref(false)
const showPersonaEditor = ref(false)
const personaDraft = ref('')
const currentPersona = ref('')
const assistantNameDraft = ref('助手')
const currentAssistantName = ref('助手')
const renameTarget = ref(null)
const renameDraft = ref('')
const pendingAttachmentIds = ref([])
const selectedFiles = ref({ attachments: [], knowledge: [] })
const fileNotice = ref('')
const thinkingEnabled = ref(false)
const currentProvider = ref('deepseek')
const currentModel = ref('deepseek-flash')
const imageAvailable = ref(false)
const desktopAvailable = Boolean(window.agentDesktop)
const workspaceFolder = ref('')
const messages = ref([])
const loading = ref(false)
// 控制下一次发送是否允许联网搜索。
const webSearchEnabled = ref(true)

// 后端总开关决定是否可用，原按钮控制本轮是否允许。
const searchAvailable = ref(false)
function applyApiSettings(settings) {
  currentProvider.value = settings.provider
  currentModel.value = settings[`${settings.provider}_model`] || ''
  imageAvailable.value = !!settings.has_zhipu_key
  if (settings.provider !== 'deepseek') thinkingEnabled.value = false
  searchAvailable.value = settings.provider === 'zhipu'
    && settings.search_enabled && settings.search_configured
  webSearchEnabled.value = searchAvailable.value
}

const error = ref('')
const conversationId = ref(null)
// 列表从后端读取，不再读取浏览器中的完整聊天内容。
const savedChats = ref([])
// 搜索只改变展示列表，不修改原始聊天记录。
const historyQuery = ref('')

const filteredChats = computed(() => {
  const keyword = historyQuery.value.trim().toLowerCase()
  if (!keyword) return savedChats.value
  return savedChats.value.filter(chat =>
    (chat.title || '').toLowerCase().includes(keyword),
  )
})
const sidebarOpen = ref(true)
const menuChatId = ref(null)
const progress = ref('')
const streamingText = ref('')
const streamingReasoning = ref('')
const messageList = ref(null)
const followLatest = ref(true)
// 当前任务编号和停止请求状态。
const activeTaskId = ref(null)
const stopping = ref(false)
const exporting = ref(false)
// 标题跟随当前选中的会话。
const currentChatTitle = computed(() => {
  const chat = savedChats.value.find(item => item.id === conversationId.value)
  return chat?.title || 'Agent 聊天'
})
// 顶部只显示真实用过的模型，另把当前选择的模型标成“下一轮”。
const modelUsages = computed(() => {
  const used = new Map()
  for (const message of messages.value) {
    if (message.role === 'assistant' && message.provider && message.model) {
      used.set(`${message.provider}/${message.model}`, `${message.provider} · ${message.model}`)
    }
    for (const step of message.tool_steps || []) {
      const result = step.result || {}
      if (result.provider && result.model) {
        used.set(`${result.provider}/${result.model}`, `${result.provider} · ${result.model}`)
      }
    }
  }
  return [...used.values()]
})
const allFiles = computed(() => [
  ...selectedFiles.value.attachments.map(file => ({ ...file, source: '附件' })),
  ...selectedFiles.value.knowledge.map(file => ({ ...file, source: '资料库' })),
])
const readFileIds = computed(() => {
  const ids = new Set()
  for (const message of messages.value) {
    for (const step of message.tool_steps || []) {
      if (step.name === 'read_attachment') {
        try { ids.add(JSON.parse(step.arguments).file_id) } catch { /* 旧记录格式不正确 */ }
      }
      if (step.name === 'search_knowledge') {
        for (const match of step.result?.matches || []) if (match.file_id) ids.add(match.file_id)
      }
      if (step.name === 'lookup_inventory' && step.result?.file_id) ids.add(step.result.file_id)
    }
    if (message.role === 'user' && message.content.startsWith('识图：')) {
      const match = message.content.match(/\(([0-9a-f-]{36})\)/i)
      if (match) ids.add(match[1])
    }
  }
  return ids
})
async function refreshFiles(id = conversationId.value) {
  if (!id) { selectedFiles.value = { attachments: [], knowledge: [] }; return }
  try {
    const data = await requestJson(`/chat/history/${encodeURIComponent(id)}/files`)
    if (conversationId.value === id) selectedFiles.value = data
  } catch (cause) {
    if (conversationId.value === id) error.value = `文件列表读取失败：${cause.message}`
  }
}

function openPersonaEditor() {
  personaDraft.value = currentPersona.value
  assistantNameDraft.value = currentAssistantName.value
  showPersonaEditor.value = true
}

async function savePersona() {
  if (!conversationId.value || loading.value) return
  loading.value = true
  try {
    const data = await requestJson(`/chat/history/${conversationId.value}/assistant`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ persona: personaDraft.value,
        assistant_name: assistantNameDraft.value.trim() }),
    })
    currentPersona.value = data.persona
    currentAssistantName.value = data.assistant_name
    showPersonaEditor.value = false
  } catch (cause) { error.value = cause.message }
  finally { loading.value = false }
}

async function inspectImage(file) {
  if (loading.value || !conversationId.value) return
  const question = window.prompt(`想了解“${file.filename}”的什么内容？`, '请描述这张图片的内容和重要细节。')
  if (!question?.trim()) return
  // 对话框明确告知图片名与接收方，取消时不会发生网络上传。
  if (!window.confirm(`将“${file.filename}”发送给智谱视觉 API 识图？`)) return
  loading.value = true
  progress.value = '正在使用智谱识图…'
  error.value = ''
  try {
    const data = await requestJson(`/chat/history/${conversationId.value}/analyze-image`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file_id: file.id, question: question.trim() }),
    })
    messages.value.push({ role: 'user', content: `识图：${file.filename}（${file.id}）\n${question.trim()}` })
    messages.value.push({ role: 'assistant', content: data.reply,
      provider: data.provider, model: data.model })
    await loadHistory()
  } catch (cause) { error.value = cause.message }
  finally { progress.value = ''; loading.value = false }
}
// 仅展示本轮实时进度，最终执行记录仍由后端保存。
const liveToolSteps = ref([])
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

// 下载服务器保存的记录，失败时在当前页面显示错误。
async function exportChat() {
  const id = conversationId.value
  if (!id || loading.value || exporting.value) return
  exporting.value = true
  error.value = ''
  try {
    const response = await fetch(`/chat/history/${id}/export`)
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      throw new Error(data?.detail || `导出失败：${response.status}`)
    }
    // Blob 是文件数据；临时地址供浏览器触发下载。
    const url = URL.createObjectURL(await response.blob())
    const link = document.createElement('a')
    link.href = url
    link.download = `chat-${id}.md`
    document.body.appendChild(link)
    link.click()
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (err) {
    error.value = err.message
  } finally {
    exporting.value = false
  }
}

// 仅桌面版可以调出系统“另存为”；网页仍保留普通下载链接。
async function saveArtifactToFolder(step) {
  if (!desktopAvailable) return
  const url = step.result?.download_url || step.result?.image_url
  const names = {
    save_report: 'report.md', save_presentation: 'presentation.pptx',
    generate_image: 'generated.png', save_document: 'document.docx',
    save_spreadsheet: 'spreadsheet.xlsx', save_pdf: 'document.pdf',
  }
  const filename = step.result?.filename || names[step.name] || 'file.txt'
  try {
    const result = await window.agentDesktop.saveArtifact(url, filename)
    if (!result.canceled) fileNotice.value = `已保存到你选择的位置：${result.filename}`
  } catch (cause) { error.value = `保存文件失败：${cause.message}` }
}

// 工作文件夹由系统目录选择器设置；路径只显示，不发送给聊天模型。
async function chooseWorkspace() {
  if (!desktopAvailable || loading.value) return
  try {
    const result = await window.agentDesktop.chooseWorkspace()
    if (!result.canceled) {
      workspaceFolder.value = result.folder
      fileNotice.value = `工作文件夹已设置：${result.folder}`
    }
  } catch (cause) { error.value = `设置工作文件夹失败：${cause.message}` }
}

async function readWorkspaceFile() {
  if (!desktopAvailable || loading.value) return false
  if (!workspaceFolder.value) { error.value = '请先设置工作文件夹'; return false }
  const draft = input.value
  if (!conversationId.value && !(await newChat())) return false
  input.value = draft
  loading.value = true
  error.value = ''
  try {
    const purpose = input.value.trim() || '阅读所选文件并回答后续问题'
    const result = await window.agentDesktop.readWorkspaceFile(
      conversationId.value, purpose, `${currentProvider.value} / ${currentModel.value}`)
    if (!result.canceled) {
      await refreshFiles()
      if (result.kind === 'image') {
        fileNotice.value = `已选中图片“${result.filename}”；请在文件框点击“识图”并单独确认。`
        return false
      }
      pendingAttachmentIds.value.push(result.file_id)
      fileNotice.value = `已读取工作文件夹中的“${result.filename}”；发送问题后模型才会使用。`
      return true
    }
    return false
  } catch (cause) { error.value = `读取工作文件失败：${cause.message}`; return false }
  finally { loading.value = false }
}

async function copyExistingFile() {
  if (!desktopAvailable) return
  try {
    const result = await window.agentDesktop.copyExistingFile()
    if (!result.canceled) fileNotice.value = `已复制到你选择的位置：${result.filename}`
  } catch (cause) { error.value = `复制文件失败：${cause.message}` }
}

// 对模型正文中的成果链接先检查是否真的存在，失败时留在聊天页。
async function openMessageLink(event) {
  const link = event.target.closest?.('a')
  if (!link) return
  let url
  try { url = new URL(link.href, location.href) }
  catch { event.preventDefault(); error.value = '链接地址无效'; return }
  if (url.origin !== location.origin) {
    if (!['https:', 'http:'].includes(url.protocol)) event.preventDefault()
    return
  }
  event.preventDefault()
  if (!/^\/chat\/files\/[0-9a-f-]{36}\/[0-9a-f-]{36}$/.test(url.pathname)) {
    error.value = '文件地址无效，生成可能未成功；请查看执行记录。'
    return
  }
  try {
    const response = await fetch(url.pathname)
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const blobUrl = URL.createObjectURL(await response.blob())
    const download = document.createElement('a')
    download.href = blobUrl
    download.download = response.headers.get('content-disposition')?.match(/filename="?([^";]+)/)?.[1] || '成果文件'
    document.body.appendChild(download)
    download.click()
    download.remove()
    setTimeout(() => URL.revokeObjectURL(blobUrl), 1000)
  } catch (cause) { error.value = `文件尚未生成：${cause.message}` }
}

async function removeDisplayedFile(file) {
  if (loading.value || !conversationId.value) return
  if (!window.confirm(`从当前聊天删除“${file.filename}”？`)) return
  loading.value = true
  try {
    const id = encodeURIComponent(conversationId.value)
    const route = file.source === '资料库' ? 'knowledge' : 'attachments'
    await requestJson(`/chat/history/${id}/${route}/${encodeURIComponent(file.id)}`,
      { method: 'DELETE' })
    pendingAttachmentIds.value = pendingAttachmentIds.value.filter(item => item !== file.id)
    await refreshFiles()
  } catch (cause) { error.value = cause.message }
  finally { loading.value = false }
}

function selectAttachmentForNextTurn(file) {
  if (loading.value || file.source !== '附件' || file.kind === 'image') return
  const purpose = input.value.trim() || '阅读并分析文件内容'
  if (!window.confirm(`允许模型在下一条消息中读取“${file.filename}”？\n用途：${purpose}`)) return
  if (!pendingAttachmentIds.value.includes(file.id)) pendingAttachmentIds.value.push(file.id)
  fileNotice.value = `已选择“${file.filename}”，发送下一条消息后模型才能读取。`
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
  [messages, progress, loading, streamingText, streamingReasoning],
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

// 从搜索工具结果中提取链接，并去重、过滤非 HTTP 地址。
function searchSources(message) {
  const sources = new Map()
  for (const step of message.tool_steps || []) {
    if (step.name !== 'search_web') continue
    const items = Array.isArray(step.result?.sources)
      ? step.result.sources : []
    for (const item of items) {
      try {
        const url = new URL(item.url)
        if (!['http:', 'https:'].includes(url.protocol)) continue
        if (url.username || url.password) continue
        if (!sources.has(url.href)) {
          sources.set(url.href, {
            url: url.href,
            title: item.title || url.hostname,
            domain: url.hostname,
          })
        }
      } catch {
        // 地址格式不合法时跳过，不影响其他来源。
      }
    }
  }
  return [...sources.values()]
}

// 每段聊天使用独立的存储键，避免草稿混到其他聊天。
function saveDraft(id, text) {
  if (!id) return
  try {
    const key = `agent-draft:${id}`
    if (text) localStorage.setItem(key, text)
    else localStorage.removeItem(key)
  } catch {
    error.value = '草稿保存失败，请检查浏览器存储空间或权限。'
  }
}

// 没有草稿时返回空字符串；读取失败不阻止打开聊天。
function readDraft(id) {
  try {
    return localStorage.getItem(`agent-draft:${id}`) || ''
  } catch {
    error.value = '草稿读取失败，聊天记录不受影响。'
    return ''
  }
}

// 输入变化时立即保存；清空输入框时同时删除草稿。
watch(input, text => {
  saveDraft(conversationId.value, text)
}, { flush: 'sync' })

// 把后端返回的会话详情应用到聊天区域。
function applyChat(chat) {
  conversationId.value = chat.id
  messages.value = chat.messages.map(message => ({ ...message }))
  currentPersona.value = chat.persona || ''
  currentAssistantName.value = chat.assistant_name || '助手'
  pendingAttachmentIds.value = []
  fileNotice.value = ''
  refreshFiles(chat.id)
  // 先清理旧错误，再读取当前会话的草稿。
  error.value = ''
  input.value = readDraft(chat.id)
  streamingText.value = ''
  streamingReasoning.value = ''
  followLatest.value = true
  menuChatId.value = null
  showKnowledgePanel.value = false
  putSelectedFirst()
  rememberSelectedChat()
}

// 创建成功后才切换页面，失败时保留当前聊天。
async function newChat(settings = {}) {
  if (loading.value) return false
  loading.value = true
  error.value = ''
  progress.value = '正在新建聊天…'
  try {
    const chat = await requestJson('/chat/history', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings),
    })
    const { messages: unusedMessages, ...metadata } = chat
    savedChats.value = [metadata, ...savedChats.value]
    // 创建成功后清空旧筛选，确保新会话在左侧可见并显示选中背景。
    historyQuery.value = ''
    applyChat(chat)
    return chat
  } catch (err) {
    error.value = err.message
    return false
  } finally {
    progress.value = ''
    loading.value = false
  }
}

// 先创建会话取得编号，再把所选资料上传到该会话。
async function createConfiguredChat({ title, persona, assistant_name, files }) {
  if (files.length && !window.confirm(`允许把所选的 ${files.length} 个文件加入新聊天资料库，供当前模型按需读取？`)) return
  const chat = await newChat({ title, persona, assistant_name })
  if (!chat) return
  showNewChatSetup.value = false
  if (!files.length) return
  loading.value = true
  error.value = ''
  try {
    for (const file of files) {
      const form = new FormData()
      form.append('file', file)
      const response = await fetch(`/chat/history/${chat.id}/knowledge`, {
        method: 'POST', body: form,
      })
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}))
        throw new Error(`${file.name}：${detail.detail || response.status}`)
      }
    }
  } catch (cause) {
    error.value = `部分资料上传失败：${cause.message}。可在资料库中重试。`
  } finally {
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
function renameChat(chat) {
  if (loading.value || !chat) return
  menuChatId.value = null
  renameTarget.value = chat
  renameDraft.value = chat.title
}

async function saveRename() {
  const chat = renameTarget.value
  const title = renameDraft.value.trim()
  if (!chat || loading.value || !title) return
  loading.value = true
  error.value = ''
  try {
    const result = await requestJson(`/chat/history/${encodeURIComponent(chat.id)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: title.slice(0, 60) }),
    })
    chat.title = result.title
    renameTarget.value = null
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
    // 后端删除成功后，才清除这段聊天的本地草稿。
    saveDraft(chat.id, '')
    savedChats.value = savedChats.value.filter(item => item.id !== chat.id)
    if (conversationId.value === chat.id) {
      conversationId.value = null
      messages.value = []
      selectedFiles.value = { attachments: [], knowledge: [] }
      currentPersona.value = ''
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


// 这里只请求停止，任务是否结束由后端事件流确认。
async function stopGeneration() {
  const id = activeTaskId.value
  if (!id || stopping.value) return
  stopping.value = true

  try {
    await requestJson(`/chat/tasks/${id}/cancel`, { method: 'POST' })
    // 请求被接受不等于任务已结束，此处不解除 loading。
  } catch (err) {
    // 只更新原任务，避免迟到的响应影响下一轮任务。
    if (activeTaskId.value === id) {
      stopping.value = false
      error.value = `停止失败：${err.message}`
    }
  }
}

// 发送仍走流式接口；消息入库由后端负责，前端不要重复保存。
async function send() {
  const text = input.value.trim() || (pendingAttachmentIds.value.length
    ? '请阅读我选中的文件并总结重点。' : '')
  if (!text || loading.value) return
  // 明确要求读取工作文件夹时，先选择并批准具体文件，再把编号交给模型。
  if (desktopAvailable && workspaceFolder.value && !pendingAttachmentIds.value.length
      && /(?:读取|打开|查看|分析).{0,60}工作文件夹|工作文件夹.{0,60}(?:读取|打开|查看|分析)/.test(text)) {
    if (!(await readWorkspaceFile())) return
  }
  if (!conversationId.value && !(await newChat())) return
  // 新问题开始时清除上一轮的临时进度。
  liveToolSteps.value = []
  streamingText.value = ''
  streamingReasoning.value = ''
  followLatest.value = true
  const userMessage = { role: 'user', content: text }
  messages.value.push(userMessage)
  input.value = ''
  loading.value = true
  progress.value = '正在连接 Agent…'
  error.value = ''
  activeTaskId.value = null
  // 每轮请求独立，不沿用上一轮的停止状态。
  stopping.value = false

  try {
    const response = await fetch('/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        // 只提交本次问题；过去的对话由后端从数据库读取。
      messages: [{ role: 'user', content: text }],
        web_search: searchAvailable.value && webSearchEnabled.value,
        thinking: currentProvider.value === 'deepseek' && thinkingEnabled.value,
        conversation_id: conversationId.value,
        attachment_ids: pendingAttachmentIds.value,
      }),
    })
    if (!response.ok) {
      throw new Error(`请求失败：${response.status}，${await response.text()}`)
    }

    let completed = false
    let finishedData = null
    const toolNames = {
      read_attachment: '读取附件',
      save_report: '生成报告',
      search_web: '联网搜索',
      lookup_inventory: '查询资料库库存',
      search_knowledge: '检索资料库',
      save_presentation: '制作 PPT',
      generate_image: 'AI 生图',
      save_document: '制作 Word',
      save_spreadsheet: '制作 Excel',
      save_pdf: '制作 PDF',
      save_text_file: '保存文件',
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
        streamingReasoning.value = ''
        completed = true // 主动停止也是正常结束，不能当作连接异常。
        return
      }
      // 停止等待期间冻结文字，但仍接收最终完成或错误通知。
      if (stopping.value && !['done', 'error'].includes(event.type)) return
      if (event.type === 'round_start') {
        streamingText.value = ''
        progress.value = '正在生成…'
      }
      if (event.type === 'reasoning_delta') {
        streamingReasoning.value += event.text
        progress.value = '正在思考…'
      }
      if (event.type === 'text_delta') {
        streamingText.value += event.text
        progress.value = '正在生成…'
      }
      if (event.type === 'tool_start') {
        // 同名工具可以多次执行，因此每次开始都新增一项。
        liveToolSteps.value.push({
          name: event.name, label: name, status: '执行中',
        })
        streamingText.value = ''
        progress.value = `正在${name}…`
      }
      if (event.type === 'tool_end') {
        // 当前后端串行执行工具，找到对应的未完成项更新状态。
        const step = liveToolSteps.value.find(
          item => item.name === event.name && item.status === '执行中',
        )
        if (step) step.status = event.result?.error ? '失败' : '已完成'
        progress.value = event.result?.error
          ? `${name}未成功，正在处理…`
          : `${name}完成，正在处理下一步…`
      }
      if (event.type === 'error') throw new Error(event.message)
      if (event.type === 'done') {
        const data = event.data
        finishedData = data
        conversationId.value = data.conversation_id
        messages.value.push({
          role: 'assistant',
          content: data.reply,
          tool_steps: data.tool_steps || [],
          reasoning: data.reasoning || streamingReasoning.value,
          provider: data.provider, model: data.model,
        })
        streamingText.value = ''
        streamingReasoning.value = ''
        if (!(data.tool_steps || []).some(step => step.result?.error)) pendingAttachmentIds.value = []
        rememberSelectedChat()
        completed = true
      }
    })
    if (!completed) throw new Error('连接提前结束，未收到最终结果')
    // 聊天完成后逐份请求用户确认，再把成果写进固定工作文件夹。
    if (desktopAvailable && workspaceFolder.value && finishedData) {
      for (const step of finishedData.tool_steps || []) {
        const url = step.result?.download_url || step.result?.image_url
        if (!url) continue
        const filename = step.result?.filename || '成果文件.md'
        try {
          const saved = await window.agentDesktop.saveToWorkspace(
            url, filename, `根据本轮问题生成：${text.slice(0, 120)}`)
          if (!saved.canceled) fileNotice.value = `成果已保存：${saved.path}`
        } catch (cause) { error.value = `保存工作文件失败：${cause.message}` }
      }
    }
  } catch (err) {
    error.value = err.message
    userMessage.failed = true
  } finally {
    // 成功、失败或取消，都在事件流处理结束后统一收尾。
    activeTaskId.value = null
    stopping.value = false
    progress.value = '正在刷新历史…'

    try {
      await loadHistory()
      await refreshFiles()
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
  const files = Array.from(event.target.files || [])
  if (!files.length || loading.value) return
  // 系统文件读取前明确征得用户同意，取消时不上传也不交给模型。
  if (!window.confirm(`允许读取并上传 ${files.map(file => file.name).join('、')} 到当前聊天？模型只会在你发送问题后按需读取。`)) {
    event.target.value = ''
    return
  }
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
  const uploaded = []
  const failed = []
  try {
    for (const file of files) {
      try {
        const formData = new FormData()
        formData.append('file', file)
        const response = await fetch(`/chat/upload/${encodeURIComponent(chatId)}`, {
          method: 'POST', body: formData,
        })
        if (!response.ok) {
          const detail = await response.json().catch(() => ({}))
          throw new Error(detail.detail || `HTTP ${response.status}`)
        }
        uploaded.push(await response.json())
      } catch (cause) { failed.push(`${file.name}：${cause.message}`) }
    }
    await refreshFiles(chatId)
    const documents = uploaded.filter(file => file.kind !== 'image')
    pendingAttachmentIds.value.push(...documents.map(file => file.file_id))
    if (documents.length) fileNotice.value = `已选择 ${documents.length} 个文件；文件显示在上方文件框，发送后模型才会读取。`
    const images = uploaded.filter(file => file.kind === 'image')
    if (images.length) fileNotice.value = `已上传 ${images.length} 张图片；在文件框点击“识图”才会发送给智谱。`
    if (failed.length) error.value = `部分文件上传失败：${failed.join('；')}`
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
  if (desktopAvailable) {
    try { workspaceFolder.value = (await window.agentDesktop.getWorkspace()).folder || '' }
    catch (cause) { error.value = `读取工作文件夹设置失败：${cause.message}` }
  }
})

// 页面卸载时取消定时器，避免遗留任务。
onUnmounted(() => clearTimeout(copyTimer))


</script>

<template>
  <div class="workspace" :class="{ collapsed: !sidebarOpen }">
    <!-- // collapsed 是否折叠 -->
    <Transition name="sidebar-slide">
    <aside v-if="sidebarOpen" class="sidebar">
      <header class="sidebar-header">
        <strong>Agent 工作台 <small>v0.1.2</small></strong>
        <button class="icon-button" @click="sidebarOpen = false"
          title="收起侧栏" aria-label="收起侧栏">‹</button>
      </header>
      <button
        class="sidebar-item new-chat-button"
        :disabled="loading"
        @click="showNewChatSetup = true"
      >
        ＋ 新建聊天
      </button>
      <!-- 搜索时关闭旧菜单，避免菜单残留在筛选结果中。 -->
      <input
        v-model="historyQuery"
        class="history-search"
        type="search"
        aria-label="搜索聊天标题"
        placeholder="搜索聊天标题"
        @input="menuChatId = null"
      />
      <nav class="history" aria-label="历史聊天">
        <!-- 区分没有聊天与没有匹配结果，不在加载期间显示。 -->
        <p v-if="!loading && !filteredChats.length" class="history-empty">
          {{ historyQuery.trim() ? '没有匹配的聊天' : '暂无聊天记录' }}
        </p>
        <div v-for="chat in filteredChats" :key="chat.id" class="history-entry">
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
    </Transition>

    <main class="chat-area">
      <header class="chat-header">
        <button v-if="!sidebarOpen" class="icon-button"
          @click="sidebarOpen = true" title="展开侧栏" aria-label="展开侧栏">›</button>
        <!-- 顶部标题与当前选中的聊天同步。 -->
        <span class="current-chat-title" :title="currentChatTitle">
          {{ currentChatTitle }}
        </span>
        <button type="button" class="assistant-edit" :disabled="loading || !conversationId"
          @click="renameChat(savedChats.find(chat => chat.id === conversationId))"
          title="重命名当前聊天">重命名</button>
        <button type="button" class="assistant-edit" :disabled="loading || !conversationId"
          @click="openPersonaEditor" aria-label="助手设定"
          title="调整当前聊天的助手设定">{{ currentAssistantName }}设定</button>
        <button v-if="desktopAvailable" type="button" class="assistant-edit copy-file-button"
          :disabled="loading" @click="copyExistingFile"
          aria-label="复制文件"
          title="先选择本机文件，再选择保存位置">复制文件</button>
        <button v-if="desktopAvailable" type="button" class="assistant-edit workspace-button"
          :disabled="loading" @click="chooseWorkspace" title="设置固定工作文件夹"
          aria-label="设置工作文件夹">工作文件夹</button>
        <ApiSettings :busy="loading" @updated="applyApiSettings" />
        <button type="button" class="icon-button" title="资料库" aria-label="资料库"
          :disabled="loading || !conversationId" @click="showKnowledgePanel = true">
          <FolderOpen :size="18" />
        </button>
        <NewChatSetup
          v-if="showNewChatSetup"
          :busy="loading"
          @cancel="showNewChatSetup = false"
          @create="createConfiguredChat"
        />
        <KnowledgePanel v-if="showKnowledgePanel && conversationId"
          :conversation-id="conversationId" @close="showKnowledgePanel = false"
          @changed="refreshFiles" />
        <!-- 生成期间禁止导出，避免下载到尚未写完的记录。 -->
        <button type="button" class="icon-button export-chat"
          :disabled="loading || exporting || !conversationId || !messages.length"
          title="导出 Markdown" aria-label="导出 Markdown" @click="exportChat">
          <Download :size="18" />
        </button>
      </header>
      <!-- 自定义重命名框不依赖浏览器 prompt，桌面版也能稳定输入。 -->
      <Teleport to="body">
        <div v-if="renameTarget" class="persona-backdrop">
          <section class="persona-panel" role="dialog" aria-modal="true" aria-label="重命名聊天">
            <h2>重命名聊天</h2>
            <form @submit.prevent="saveRename">
              <input v-model="renameDraft" maxlength="60" autofocus aria-label="新的聊天名称" />
              <div><button type="button" @click="renameTarget = null">取消</button>
                <button type="submit" :disabled="loading || !renameDraft.trim()">保存</button></div>
            </form>
          </section>
        </div>
      </Teleport>
      <!-- 模型和文件分开展示；历史模型是实际使用记录。 -->
      <div class="context-strip">
        <section class="context-card" aria-label="使用模型">
          <strong>✦ 模型</strong>
          <span>下一轮：{{ currentProvider }} · {{ currentModel }}</span>
          <small v-if="modelUsages.length">已使用：{{ modelUsages.join('、') }}</small>
        </section>
        <section class="context-card files-card" aria-label="本聊天文件">
          <strong>▣ 本聊天文件</strong>
          <small v-if="desktopAvailable">工作文件夹：{{ workspaceFolder || '未设置' }}</small>
          <button v-if="desktopAvailable" type="button" :disabled="loading || !workspaceFolder"
            @click="readWorkspaceFile">读取工作文件</button>
          <small>你选中的文件可供当前聊天模型读取；图片识图需单独确认。</small>
          <span v-if="!allFiles.length">暂无文件</span>
          <ul v-else>
            <li v-for="file in allFiles" :key="file.id">
              <span :title="file.filename">{{ file.filename }}</span>
              <small>{{ file.source }}{{ readFileIds.has(file.id) ? ' · 已读取' : '' }}{{ pendingAttachmentIds.includes(file.id) ? ' · 下轮可读取' : '' }}</small>
              <button v-if="file.source === '附件' && file.kind !== 'image'" type="button"
                :disabled="loading" @click="selectAttachmentForNextTurn(file)">下轮读取</button>
              <button v-if="file.kind === 'image'" type="button" :disabled="loading || !imageAvailable"
                :title="imageAvailable ? '将这张图片发送给智谱视觉 API' : '先在 API 设置中配置智谱密钥'"
                @click="inspectImage(file)">识图</button>
              <button type="button" :disabled="loading" @click="removeDisplayedFile(file)">删除</button>
            </li>
          </ul>
        </section>
      </div>
      <p v-if="fileNotice" class="file-notice" role="status">{{ fileNotice }}</p>
      <Teleport to="body">
      <div v-if="showPersonaEditor" class="persona-backdrop">
        <section class="persona-panel" role="dialog" aria-modal="true" aria-label="助手设定">
          <h2>当前聊天的助手</h2>
          <p>写下角色、语气或专业方向；保存后从下一条消息开始生效。</p>
          <label>助手名字<input v-model="assistantNameDraft" maxlength="30" aria-label="助手名字" /></label>
          <textarea v-model="personaDraft" maxlength="2000" aria-label="助手角色设定"
            placeholder="例如：你是一位耐心的 Vue 入门老师，每步都解释原因。"></textarea>
          <div><button type="button" :disabled="loading" @click="showPersonaEditor = false">取消</button>
            <button type="button" :disabled="loading || !assistantNameDraft.trim()" @click="savePersona">保存</button></div>
        </section>
      </div>
      </Teleport>
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
            <strong>{{ message.role === 'user' ? '你' : currentAssistantName }}</strong>
            <small v-if="message.failed" class="message-failed">本轮失败，不会加入后续对话</small>
            <button v-if="message.role === 'assistant'"
              type="button" class="copy-button"
              :title="copiedMessage === message ? '已复制' : '复制回答'"
              :aria-label="copiedMessage === message ? '已复制' : '复制回答'"
              @click="copyMessage(message)">
              <component :is="copiedMessage === message ? Check : Copy" :size="16" />
            </button>
          </div>
          <details v-if="message.reasoning" class="reasoning-panel" open>
            <summary>思考过程 · 点击收起或展开</summary>
            <div class="reasoning-text">{{ message.reasoning }}</div>
          </details>
          <!-- 展示 Markdown 正文；原始消息仍用于接口请求和记录保存。 -->
          <div class="markdown-body" v-html="renderMarkdown(message.content)" @click="openMessageLink"></div>
          <!-- 标题使用普通文本插值，外部链接在新标签页打开。 -->
          <section v-if="searchSources(message).length"
            class="search-sources" aria-label="搜索来源">
            <strong>搜索来源</strong>
            <ul>
              <li v-for="source in searchSources(message)" :key="source.url">
                <a :href="source.url" target="_blank" rel="noopener noreferrer">
                  {{ source.title }}
                </a>
                <small>{{ source.domain }}</small>
              </li>
            </ul>
          </section>
          <!-- 有工具调用时显示可展开的执行记录。 -->
          <details v-if="message.tool_steps?.length" class="tool-details">
            <summary>执行记录 · {{ message.tool_steps.length }} 次工具调用</summary>
            <section v-for="(step, index) in message.tool_steps" :key="index">
              <strong>{{ step.name }}</strong>
              <!-- 兼容旧记录：缺少耗时字段时不显示，0 毫秒仍然显示。 -->
              <small v-if="step.duration_ms != null" class="tool-duration">
                · {{ step.duration_ms }} ms
              </small>
              <p>参数：{{ step.arguments }}</p>
              <pre>{{ JSON.stringify(step.result, null, 2) }}</pre>
              <!-- 直接使用报告工具返回的地址，不依赖助手正文中的链接。 -->
              <a
                v-if="step.result?.download_url"
                class="report-download"
                :href="step.result.download_url" @click="openMessageLink"
              >
                下载 {{ step.result.filename || (step.name === 'save_presentation' ? 'PPTX' : '成果文件') }}
              </a>
              <a v-if="step.result?.image_url" class="report-download"
                :href="step.result.image_url" @click="openMessageLink">查看生成图片</a>
              <button v-if="desktopAvailable && (step.result?.download_url || step.result?.image_url)"
                type="button" class="report-download save-local"
                @click="saveArtifactToFolder(step)">另存到…</button>
            </section>
          </details>
        </article>
        <!-- 临时回答单独展示，避免未完成的内容混入下一次模型上下文。 -->
        <article v-if="streamingText" class="streaming-message">
          <strong>{{ currentAssistantName }} · {{ loading ? '生成中' : '未完成' }}</strong>
          <details v-if="streamingReasoning" class="reasoning-panel" open>
            <summary>思考过程 · 点击收起或展开</summary>
            <div class="reasoning-text">{{ streamingReasoning }}</div>
          </details>
          <div
            class="markdown-body"
            v-html="renderMarkdown(streamingText)"
            @click="openMessageLink"
          ></div>
        </article>
        <article v-else-if="streamingReasoning && loading" class="streaming-message">
          <details class="reasoning-panel" open>
            <summary>正在思考 · 点击收起或展开</summary>
            <div class="reasoning-text">{{ streamingReasoning }}</div>
          </details>
        </article>
        <!-- 仅在当前任务执行期间展示，结束后使用原有执行记录。 -->
        <ol v-if="loading && activeTaskId && liveToolSteps.length"
          class="live-tool-list" aria-label="本轮工具进度">
          <li v-for="(step, index) in liveToolSteps" :key="index">
            <span>{{ step.label }}</span>
            <span :class="{ 'tool-failed': step.status === '失败' }">
              {{ stopping && step.status === '执行中' ? '等待停止确认' : step.status }}
            </span>
          </li>
        </ol>
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

      <!-- 统一表单：点击发送或按 Enter 都复用 send。 -->
      <div class="composer-options">
        <label class="thinking-switch" :class="{ disabled: currentProvider !== 'deepseek' }">
          <input type="checkbox" v-model="thinkingEnabled"
            :disabled="loading || currentProvider !== 'deepseek'" />
          深度思考
        </label>
        <small v-if="currentProvider !== 'deepseek'">思考过程目前支持 DeepSeek</small>
      </div>
      <form class="bottom-composer" @submit.prevent="send">
        <!-- 左侧两行工具，总高度与输入框一致。 -->
        <div class="composer-tools">
          <!-- 普通按钮切换联网状态；type="button" 避免触发表单发送。 -->
          <button
            type="button"
            class="composer-tool search-tool"
            :disabled="loading || !searchAvailable"
            :aria-pressed="webSearchEnabled"
            :title="!searchAvailable ? '当前模式不可联网搜索' : webSearchEnabled ? '联网搜索已开启，点击关闭' : '联网搜索已关闭，点击开启'"
            @click="webSearchEnabled = !webSearchEnabled"
          >
            联网搜索
          </button>

          <label class="composer-tool upload-tool" :class="{ 'is-disabled': loading }">
            <span>上传资料</span>
            <input
              class="upload-picker"
              type="file" multiple
              accept=".txt,.md,.csv,.json,.py,.js,.ts,.vue,.html,.css,.xml,.yaml,.yml,.sql,.pdf,.docx,.xlsx,.pptx,.png,.jpg,.jpeg"
              :disabled="loading"
              aria-label="上传资料"
              @change="uploadAttachment"
            />
          </label>
        </div>

        <!-- 禁止手动拉伸，保持与左侧工具总高度对齐。 -->
        <textarea
          v-model="input"
          class="composer-editor"
          aria-label="消息"
          placeholder="输入问题，或上传资料…"
          :disabled="loading"
          @keydown="handleComposerKeydown"
        ></textarea>

        <button v-if="activeTaskId" class="composer-action" type="button"
          :disabled="stopping" @click="stopGeneration">
          {{ stopping ? '停止中…' : '停止' }}
        </button>
        <button v-else class="composer-action" type="submit"
          :disabled="loading || (!input.trim() && !pendingAttachmentIds.length)">
          发送
        </button>
      </form>
    </main>
  </div>
</template>
