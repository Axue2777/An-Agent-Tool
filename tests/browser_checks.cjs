// 使用真实 Vue 构建产物与本地模拟接口检查交互，不连接真实模型或聊天数据库。
const fs = require('node:fs')
const path = require('node:path')
const http = require('node:http')
const { pathToFileURL } = require('node:url')
const { randomUUID } = require('node:crypto')
const assert = require('node:assert/strict')
const root = path.resolve(__dirname, '..')
const artifacts = path.join(__dirname, '_artifacts')
const A = '11111111-1111-4111-8111-111111111111'
const B = '22222222-2222-4222-8222-222222222222'
let chats, mode, settingsProvider, requests, pending, server, browser
const checks = []
const runtimeErrors = []
const body = '# Vue 学习\n\n**重点内容**\n\n| 名称 | 说明 |\n| --- | --- |\n| computed | 缓存 |\n\n' +
  '<img src="data:," onerror="window.__unsafe=true"><script>window.__unsafe=true</script>\n\n[危险](javascript:alert(1))'
function reset() {
  chats = new Map([
    [A, { id: A, title: 'Vue 学习', messages: [{ role: 'user', content: '学习 Vue' }, {
      role: 'assistant', content: body, tool_steps: [{ name: 'search_web', arguments: '{}', duration_ms: 0, result: {
        sources: [
          { title: '官方文档', url: 'https://cn.vuejs.org/guide/' },
          { title: '重复', url: 'https://cn.vuejs.org/guide/' },
          { title: '危险', url: 'javascript:alert(1)' },
          { title: '凭证', url: 'https://user:pass@example.com/' },
        ],
      } }],
    }] }],
    [B, { id: B, title: '报告草稿', messages: [] }],
  ])
  mode = 'normal'
  settingsProvider = 'zhipu'
  requests = []
  pending = null
}
async function readBody(req) {
  const parts = []
  for await (const part of req) parts.push(part)
  return Buffer.concat(parts)
}
function json(res, data, status = 200) {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' })
  res.end(JSON.stringify(data))
}
function event(res, data) { res.write('data: ' + JSON.stringify(data) + '\n\n') }

// 本地服务只提供测试数据和静态页面；任何其他网络地址均由浏览器拦截。
async function handle(req, res) {
  const url = new URL(req.url, 'http://localhost')
  const parts = url.pathname.split('/').filter(Boolean)
  if (url.pathname === '/chat/settings' && req.method === 'GET') {
    res.writeHead(200, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify({
      revision: 'test-only', provider: settingsProvider,
      deepseek_model: 'deepseek-flash', zhipu_model: 'glm-4.7-flash',
      search_enabled: true, share_chat_key: settingsProvider === 'zhipu',
      chat_configured: true, search_configured: true,
      has_deepseek_key: true, has_zhipu_key: true, has_search_key: true,
    }))
    return
  }
  if (url.pathname === '/chat/history') {
    if (req.method === 'POST') {
      const settings = JSON.parse((await readBody(req)).toString() || '{}')
      const chat = { id: randomUUID(), title: settings.title || '新建聊天',
        persona: settings.persona || '', messages: [] }
      chats.set(chat.id, chat)
      return json(res, chat)
    }
    return json(res, { conversations: [...chats.values()].map(({ messages, ...chat }) => chat) })
  }
  if (parts[0] === 'chat' && parts[1] === 'history' && parts[3] === 'knowledge') {
    const chat = chats.get(parts[2])
    if (!chat) return json(res, { detail: '聊天不存在' }, 404)
    chat.knowledge ||= []
    if (req.method === 'POST' && parts.length === 4) {
      await readBody(req)
      const file = { id: randomUUID(), filename: 'stock.csv', kind: 'inventory' }
      chat.knowledge.push(file)
      return json(res, file, 201)
    }
    if (req.method === 'GET' && parts.length === 4) return json(res, { files: chat.knowledge })
    if (req.method === 'DELETE' && parts.length === 5) {
      chat.knowledge = chat.knowledge.filter(file => file.id !== parts[4])
      return json(res, { deleted: true })
    }
  }
  if (parts[0] === 'chat' && parts[1] === 'history') {
    const chat = chats.get(parts[2])
    if (!chat) return json(res, { detail: '不存在' }, 404)
    if (parts[3] === 'export') {
      res.writeHead(200, { 'Content-Type': 'text/markdown; charset=utf-8' })
      return res.end('# 测试聊天\n\n导出的 Markdown')
    }
    if (req.method === 'PATCH') {
      chat.title = JSON.parse((await readBody(req)).toString()).title
    }
    if (req.method === 'DELETE') chats.delete(chat.id)
    return json(res, chat)
  }
  if (url.pathname.startsWith('/chat/upload/')) {
    await readBody(req)
    return json(res, { filename: '资料.md', file_id: '33333333-3333-4333-8333-333333333333' })
  }
  if (url.pathname === '/chat/stream') {
    const payload = JSON.parse((await readBody(req)).toString())
    requests.push(payload)
    const chat = chats.get(payload.conversation_id)
    chat.messages.push(payload.messages[0])
    if (chat.title === '新建聊天') chat.title = payload.messages[0].content.slice(0, 30)
    res.writeHead(200, { 'Content-Type': 'text/event-stream; charset=utf-8', 'Cache-Control': 'no-cache' })
    event(res, { type: 'start', task_id: '44444444-4444-4444-8444-444444444444' })
    event(res, { type: 'round_start' })
    if (mode === 'broken') {
      event(res, { type: 'text_delta', text: '未完成片段' })
      return res.end()
    }
    if (mode === 'slow') {
      event(res, { type: 'text_delta', text: '正在处理' })
      pending = { res, chat }
      return
    }
    if (mode === 'tools') {
      event(res, { type: 'tool_start', name: 'save_report' })
      await new Promise(resolve => setTimeout(resolve, 500))
      event(res, { type: 'tool_end', name: 'save_report', result: { download_url: '/test/report.md' }, duration_ms: 100 })
      await new Promise(resolve => setTimeout(resolve, 500))
    }
    const reply = '测试回答：**已完成**'
    chat.messages.push({ role: 'assistant', content: reply })
    event(res, { type: 'text_delta', text: reply })
    event(res, { type: 'done', data: { conversation_id: chat.id, reply, tool_steps: [] } })
    return res.end()
  }
  if (url.pathname.endsWith('/cancel')) {
    json(res, { status: 'cancelling' }, 202)
    if (pending) {
      pending.chat.messages.push({ role: 'assistant', content: '对话内容被主动停止' })
      event(pending.res, { type: 'cancelled' })
      pending.res.end()
      pending = null
    }
    return
  }
  const name = url.pathname === '/' ? 'index.html' : decodeURIComponent(url.pathname.slice(1))
  const file = path.resolve(artifacts, 'frontend-dist', name)
  if (!file.startsWith(path.resolve(artifacts, 'frontend-dist') + path.sep)) return json(res, {}, 403)
  if (!fs.existsSync(file) || !fs.statSync(file).isFile()) return json(res, {}, 404)
  const ext = path.extname(file)
  res.writeHead(200, { 'Content-Type': ({ '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css' })[ext] || 'application/octet-stream' })
  fs.createReadStream(file).pipe(res)
}
async function check(name, fn) {
  try { await fn(); checks.push({ name, status: 'passed' }); console.log('PASS', name) }
  catch (error) { checks.push({ name, status: 'failed', error: error.message }); console.log('FAIL', name, error.message) }
}
async function pageFor(origin, viewport = { width: 1440, height: 900 }, provider = 'zhipu') {
  reset()
  settingsProvider = provider
  const context = await browser.newContext({ viewport, acceptDownloads: true })
  await context.addInitScript(({ id }) => {
    if (!localStorage.getItem('agent-selected-chat')) localStorage.setItem('agent-selected-chat', id)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: async text => { window.__copied = text } } })
  }, { id: A })
  await context.route('**/*', route => {
    const address = route.request().url()
    return address.startsWith(origin + '/') || address.startsWith('data:') || address.startsWith('blob:')
      ? route.continue() : route.abort()
  })
  const page = await context.newPage()
  page.on('pageerror', error => runtimeErrors.push(error.message))
  await page.goto(origin)
  await page.locator('.composer-editor').waitFor()
  await page.waitForFunction(() => !document.querySelector('.composer-editor').disabled)
  return { page, context }
}
async function done(page) {
  await page.waitForFunction(() => !document.querySelector('.composer-editor').disabled)
}
async function fixture(origin, fn, viewport, provider) {
  const { page, context } = await pageFor(origin, viewport, provider)
  try { await fn(page) } finally { await context.close(); if (pending) { pending.res.end(); pending = null } }
}
async function run() {
  fs.mkdirSync(artifacts, { recursive: true })
  const candidates = [
    process.env.AGENT_PLAYWRIGHT_PATH,
    'playwright',
    path.join(__dirname, '_browser_runtime', 'node_modules', 'playwright'),
    path.join(require('node:os').homedir(), '.cache', 'codex-runtimes', 'codex-primary-runtime', 'dependencies', 'node', 'node_modules', 'playwright'),
  ].filter(Boolean)
  let playwright
  for (const candidate of candidates) {
    try { playwright = require(candidate); break } catch {}
  }
  if (!playwright) throw new Error('未找到 Playwright，请配置 AGENT_PLAYWRIGHT_PATH；没有自动安装依赖。')
  const vite = await import(pathToFileURL(path.join(root, 'fronted/node_modules/vite/dist/node/index.js')).href)
  await vite.build({ root: path.join(root, 'fronted'), build: { outDir: path.join(artifacts, 'frontend-dist'), emptyOutDir: true }, logLevel: 'warn' })
  server = http.createServer((req, res) => handle(req, res).catch(error => { console.error(error); if (!res.headersSent) json(res, {}, 500); else res.end() }))
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  const origin = 'http://127.0.0.1:' + server.address().port
  browser = await playwright.chromium.launch({ channel: 'msedge', headless: true })
  await check('恢复选中聊天、标题同步、置顶高亮', () => fixture(origin, async page => {
    assert.equal(await page.locator('.current-chat-title').innerText(), 'Vue 学习')
    assert.equal(await page.locator('.history-row.selected').count(), 1)
    await page.getByRole('button', { name: '报告草稿', exact: true }).click()
    await done(page)
    assert.equal(await page.locator('.history-title').first().innerText(), '报告草稿')
    await page.reload(); await done(page)
    assert.equal(await page.locator('.current-chat-title').innerText(), '报告草稿')
  }))
  await check('各聊天草稿隔离、刷新恢复', () => fixture(origin, async page => {
    await page.getByRole('textbox', { name: '消息', exact: true }).fill('Vue 草稿')
    await page.getByRole('button', { name: '报告草稿', exact: true }).click(); await done(page)
    assert.equal(await page.locator('.composer-editor').inputValue(), '')
    await page.locator('.composer-editor').fill('报告草稿内容')
    await page.getByRole('button', { name: 'Vue 学习', exact: true }).click(); await done(page)
    assert.equal(await page.locator('.composer-editor').inputValue(), 'Vue 草稿')
    await page.reload(); await done(page)
    assert.equal(await page.locator('.composer-editor').inputValue(), 'Vue 草稿')
  }))
  await check('聊天标题筛选、空状态、清空恢复', () => fixture(origin, async page => {
    const search = page.getByRole('searchbox', { name: '搜索聊天标题' })
    await search.fill('vue')
    assert.equal(await page.locator('.history-title').count(), 1)
    await search.fill('不存在的标题')
    await page.getByText('没有匹配的聊天', { exact: true }).waitFor()
    await search.fill('')
    assert.equal(await page.locator('.history-title').count(), 2)
  }))
  await check('筛选期间新建聊天仍显示当前选中项', () => fixture(origin, async page => {
    await page.getByRole('searchbox').fill('Vue')
    await page.getByRole('button', { name: '＋ 新建聊天', exact: true }).click()
    await page.getByRole('button', { name: '开始聊天', exact: true }).click(); await done(page)
    assert.equal(await page.locator('.history-row.selected').count(), 1, '新聊天被旧搜索条件隐藏')
  }))
  await check('新聊天首次提问自动命名并保持置顶', () => fixture(origin, async page => {
    await page.getByRole('button', { name: '＋ 新建聊天', exact: true }).click()
    await page.getByRole('button', { name: '开始聊天', exact: true }).click(); await done(page)
    assert.equal(await page.locator('.current-chat-title').innerText(), '新建聊天')
    await page.locator('.composer-editor').fill('三天 Vue 学习计划')
    await page.getByRole('button', { name: '发送', exact: true }).click(); await done(page)
    assert.equal(await page.locator('.current-chat-title').innerText(), '三天 Vue 学习计划')
    assert.equal(await page.locator('.history-title').first().innerText(), '三天 Vue 学习计划')
  }))
  await check('自定义聊天名称和角色', () => fixture(origin, async page => {
    await page.getByRole('button', { name: '＋ 新建聊天', exact: true }).click()
    await page.getByLabel('聊天名称（可留空）').fill('店员助手')
    await page.getByLabel('角色与个性').fill('只根据资料库回答库存')
    await page.getByRole('button', { name: '开始聊天', exact: true }).click(); await done(page)
    assert.equal(await page.locator('.current-chat-title').innerText(), '店员助手')
    assert.equal(chats.get([...chats.keys()].at(-1)).persona, '只根据资料库回答库存')
  }))
  await check('新建聊天时上传资料并在资料库查看', () => fixture(origin, async page => {
    await page.getByRole('button', { name: '＋ 新建聊天', exact: true }).click()
    await page.getByLabel('资料库文件（可稍后上传）').setInputFiles({
      name: 'stock.csv', mimeType: 'text/csv', buffer: Buffer.from('product_name,stock\nmouse,2\n'),
    })
    await page.getByRole('button', { name: '开始聊天', exact: true }).click(); await done(page)
    await page.getByRole('button', { name: '资料库', exact: true }).click()
    await page.getByText('stock.csv · 库存表').waitFor()
  }))
  await check('聊天重命名、删除与草稿清理', () => fixture(origin, async page => {
    await page.locator('.history-entry').first().hover()
    await page.getByRole('button', { name: '聊天选项', exact: true }).first().click()
    page.once('dialog', dialog => dialog.accept('我的新标题'))
    await page.getByRole('button', { name: '重命名', exact: true }).click(); await done(page)
    assert.equal(await page.locator('.current-chat-title').innerText(), '我的新标题')
    await page.locator('.composer-editor').fill('待删除草稿')
    await page.locator('.history-entry').first().hover()
    await page.getByRole('button', { name: '聊天选项', exact: true }).first().click()
    page.once('dialog', dialog => dialog.accept())
    await page.getByRole('button', { name: '删除', exact: true }).click(); await done(page)
    assert.equal(await page.locator('.history-title').count(), 1)
    assert.equal(await page.evaluate(id => localStorage.getItem('agent-draft:' + id), A), null)
  }))
  await check('Enter 发送、Shift 换行、输入法确认不误发、联网开关', () => fixture(origin, async page => {
    const input = page.locator('.composer-editor')
    await input.fill('第一行'); await input.press('Shift+Enter')
    assert.equal(await input.inputValue(), '第一行\n')
    await input.dispatchEvent('keydown', { key: 'Enter', isComposing: true })
    assert.equal(requests.length, 0)
    await page.getByRole('button', { name: '联网搜索', exact: true }).click()
    await input.press('Enter'); await done(page)
    assert.equal(requests.length, 1)
    assert.equal(requests[0].web_search, false)
    assert.equal(requests[0].messages.length, 1)
    await page.getByText('测试回答：', { exact: false }).last().waitFor()
  }))
  await check('DeepSeek 模式不会发送联网搜索请求', async () => {
    await fixture(origin, async page => {
      const search = page.getByRole('button', { name: '联网搜索', exact: true })
      await page.waitForFunction(() => document.querySelector('.search-tool')?.disabled)
      assert.equal(await search.isDisabled(), true)
      await page.locator('.composer-editor').fill('只用 DeepSeek')
      await page.locator('.composer-editor').press('Enter'); await done(page)
      assert.equal(requests.at(-1).web_search, false)
    }, undefined, 'deepseek')
  })
  await check('主动停止固定回复、结束后恢复发送', () => fixture(origin, async page => {
    mode = 'slow'
    await page.locator('.composer-editor').fill('长任务')
    await page.getByRole('button', { name: '发送', exact: true }).click()
    await page.getByRole('button', { name: '停止', exact: true }).click()
    await done(page)
    await page.getByText('对话内容被主动停止', { exact: true }).waitFor()
    assert.equal(await page.getByRole('button', { name: '停止', exact: true }).count(), 0)
    mode = 'normal'
    await page.locator('.composer-editor').fill('再试一次')
    await page.getByRole('button', { name: '发送', exact: true }).click(); await done(page)
    assert.equal(requests.length, 2)
  }))
  await check('连接提前结束会报错、允许重新发送', () => fixture(origin, async page => {
    mode = 'broken'
    await page.locator('.composer-editor').fill('异常连接')
    await page.getByRole('button', { name: '发送', exact: true }).click(); await done(page)
    assert.match(await page.getByRole('alert').innerText(), /连接提前结束/)
    mode = 'normal'
    await page.locator('.composer-editor').fill('恢复')
    await page.getByRole('button', { name: '发送', exact: true }).click(); await done(page)
    assert.equal(await page.getByRole('alert').count(), 0)
  }))
  await check('实时工具进度与结束清理', () => fixture(origin, async page => {
    mode = 'tools'
    await page.locator('.composer-editor').fill('生成报告')
    await page.getByRole('button', { name: '发送', exact: true }).click()
    await page.getByRole('list', { name: '本轮工具进度' }).getByText('执行中', { exact: true }).waitFor()
    await page.getByRole('list', { name: '本轮工具进度' }).getByText('已完成', { exact: true }).waitFor()
    await done(page)
    assert.equal(await page.locator('.live-tool-list').count(), 0)
  }))
  await check('Markdown 渲染、安全清理、来源过滤去重', () => fixture(origin, async page => {
    assert.equal(await page.locator('.markdown-body table').count(), 1)
    assert.equal(await page.locator('.markdown-body script, .markdown-body [onerror], .markdown-body a[href^="javascript:"]').count(), 0)
    assert.equal(await page.evaluate(() => window.__unsafe), undefined)
    const links = page.getByRole('region', { name: '搜索来源' }).locator('a')
    assert.equal(await links.count(), 1)
    assert.equal(await links.first().getAttribute('rel'), 'noopener noreferrer')
  }))
  await check('复制原始 Markdown、导出 Markdown 下载', () => fixture(origin, async page => {
    await page.getByRole('button', { name: '复制回答', exact: true }).click()
    assert.equal(await page.evaluate(() => window.__copied), body)
    const download = page.waitForEvent('download')
    await page.getByRole('button', { name: '导出 Markdown', exact: true }).click()
    const file = await download
    assert.match(file.suggestedFilename(), /\.md$/)
    await file.saveAs(path.join(artifacts, 'exported-chat.md'))
    assert.match(fs.readFileSync(path.join(artifacts, 'exported-chat.md'), 'utf8'), /测试聊天/)
  }))
  await check('附件上传保留草稿并添加附件编号', () => fixture(origin, async page => {
    await page.locator('.composer-editor').fill('请分析此资料')
    await page.getByLabel('上传资料', { exact: true }).setInputFiles({ name: '资料.md', mimeType: 'text/markdown', buffer: Buffer.from('# 学习资料') })
    await page.waitForFunction(() => document.querySelector('.composer-editor').value.includes('附件编号'))
    assert.match(await page.locator('.composer-editor').inputValue(), /^请分析此资料/)
    assert.match(await page.locator('.composer-editor').inputValue(), /资料\.md/)
  }))
  for (const width of [1440, 768, 390, 320]) {
    await check('布局宽度 ' + width + '：对齐、无横向溢出、侧栏伸缩', () => fixture(origin, async page => {
      for (const collapsed of [false, true]) {
        if (collapsed) await page.getByRole('button', { name: '收起侧栏', exact: true }).click()
        const metrics = await page.evaluate(() => {
          const tools = document.querySelector('.composer-tools').getBoundingClientRect()
          const editor = document.querySelector('.composer-editor').getBoundingClientRect()
          return { overflow: document.documentElement.scrollWidth > innerWidth, tools: { y: tools.y, height: tools.height }, editor: { y: editor.y, height: editor.height } }
        })
        assert.equal(metrics.overflow, false)
        assert.ok(Math.abs(metrics.tools.height - metrics.editor.height) <= 1)
        assert.ok(Math.abs(metrics.tools.y - metrics.editor.y) <= 1)
        await page.screenshot({ path: path.join(artifacts, 'layout-' + width + (collapsed ? '-closed' : '-open') + '.png'), fullPage: true })
      }
      await page.getByRole('button', { name: '展开侧栏', exact: true }).click()
      assert.equal(await page.locator('.sidebar').count(), 1)
    }, { width, height: width < 500 ? 844 : 900 }))
  }
  await check('所有页面无未处理 JavaScript 异常', async () => assert.deepEqual(runtimeErrors, []))
}
;(async () => {
  let fatal
  try { await run() } catch (error) { fatal = error.stack; console.error(fatal) }
  finally {
    if (browser) await browser.close()
    if (server) { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)) }
    fs.mkdirSync(artifacts, { recursive: true })
    const status = fatal ? 'error' : checks.some(item => item.status === 'failed') ? 'failed' : 'passed'
    fs.writeFileSync(path.join(artifacts, 'browser-summary.json'), JSON.stringify({ status, checks, runtimeErrors, ...(fatal ? { message: fatal } : {}) }, null, 2))
    process.exitCode = status === 'passed' ? 0 : 1
  }
})()

