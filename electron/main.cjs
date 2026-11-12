
const { app, BrowserWindow, dialog, shell, ipcMain } = require('electron')
const { join, basename, resolve, extname } = require('node:path')
const { writeFile, copyFile, readFile, realpath, stat, mkdir, access } = require('node:fs/promises')
const { constants } = require('node:fs')
const { createPolicy } = require('./security.cjs')
const { createBackend } = require('./backend.cjs')
const { validArtifactPath, validFilename } = require('./local-files.cjs')
const { insideWorkspace } = require('./workspace-paths.cjs')

let backend = null
let quitting = false

// 正常退出时清理本窗口自行启动的后端；外接开发服务不归它管理。
app.on('before-quit', () => {
  quitting = true
  backend?.stop()
})

app.whenReady().then(async () => {
  // 保留 dev.py 的外接开发模式；没有开发地址时自动启动 exe。
  let address = app.isPackaged ? null : process.env.AGENT_FRONTEND_URL
  if (!address) {
    const executable = app.isPackaged
      ? join(process.resourcesPath, 'backend', 'agent-backend.exe')
      : join(__dirname, '..', 'dist', 'agent-backend', 'agent-backend.exe')
    backend = createBackend(executable, error => {
      if (quitting) return
      dialog.showErrorBox('后端停止运行', error.message)
      app.quit()
    })
    address = await backend.start()
  }

  // 页面只允许使用本机 HTTP 地址，不加载任意远程站点。
  const target = new URL(address)
  if (target.protocol !== 'http:' || target.hostname !== '127.0.0.1'
      || target.username || target.password) {
    throw new Error('桌面地址必须是 http://127.0.0.1:端口')
  }

  const win = new BrowserWindow({
    title: 'Agent 工作台', width: 1200, height: 800,
    webPreferences: {
      nodeIntegration: false, contextIsolation: true, sandbox: true,
      preload: join(__dirname, 'preload.cjs'),
    },
  })

  const { isTrusted, canCopy, externalLink } =
    createPolicy(target.origin, win.webContents)

  function requireCurrentWindow(event) {
    if (event.sender !== win.webContents || !isTrusted(event.sender.getURL())) {
      throw new Error('仅当前工作台窗口可操作本地文件')
    }
  }

  const workspaceConfig = join(app.getPath('userData'), 'workspace.json')
  async function workspaceRoot() {
    try {
      const saved = JSON.parse(await readFile(workspaceConfig, 'utf8'))
      const root = await realpath(saved.folder)
      if (!(await stat(root)).isDirectory()) throw new Error('工作文件夹不是目录')
      return root
    } catch { return null }
  }
  function checkedPurpose(value) {
    if (typeof value !== 'string' || !value.trim() || value.length > 300) {
      throw new Error('请先写明读取或保存文件的用途')
    }
    return value.trim()
  }
  async function artifactBytes(relativeUrl) {
    const response = await fetch(target.origin + relativeUrl, { redirect: 'error' })
    if (!response.ok) throw new Error(`读取成果失败：HTTP ${response.status}`)
    const reader = response.body.getReader()
    const chunks = []
    let size = 0
    try {
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        size += value.length
        if (size > 30 * 1024 * 1024) throw new Error('成果超过 30 MB')
        chunks.push(Buffer.from(value))
      }
    } finally { reader.releaseLock() }
    return Buffer.concat(chunks)
  }

  ipcMain.handle('get-workspace', async event => {
    requireCurrentWindow(event)
    return { folder: await workspaceRoot() }
  })
  ipcMain.handle('choose-workspace', async event => {
    requireCurrentWindow(event)
    const choice = await dialog.showOpenDialog(win, {
      title: '选择 Agent 工作文件夹', properties: ['openDirectory'],
      defaultPath: (await workspaceRoot()) || app.getPath('documents'),
    })
    if (choice.canceled || !choice.filePaths.length) return { canceled: true }
    const folder = await realpath(choice.filePaths[0])
    if (!(await stat(folder)).isDirectory()) throw new Error('请选择文件夹')
    await mkdir(app.getPath('userData'), { recursive: true })
    await writeFile(workspaceConfig, JSON.stringify({ folder }), 'utf8')
    return { canceled: false, folder }
  })

  // 只从用户指定的工作目录选择文件；每次读取前显示名称、用途和接收方。
  ipcMain.handle('read-workspace-file', async (event, conversationId, purpose, provider) => {
    requireCurrentWindow(event)
    const root = await workspaceRoot()
    if (!root) throw new Error('请先设置工作文件夹')
    if (typeof conversationId !== 'string' || !/^[0-9a-f-]{36}$/i.test(conversationId)) {
      throw new Error('当前聊天编号无效')
    }
    const reason = checkedPurpose(purpose)
    const choice = await dialog.showOpenDialog(win, {
      title: '选择要让 Agent 读取的文件', defaultPath: root,
      properties: ['openFile'],
    })
    if (choice.canceled || !choice.filePaths.length) return { canceled: true }
    const filePath = await realpath(choice.filePaths[0])
    if (!insideWorkspace(root, filePath)) throw new Error('只能读取工作文件夹内的文件')
    if (!(await stat(filePath)).isFile() || (await stat(filePath)).size > 10 * 1024 * 1024) {
      throw new Error('只能读取不超过 10 MB 的普通文件')
    }
    const name = basename(filePath)
    const approval = await dialog.showMessageBox(win, {
      type: 'question', buttons: ['取消', '允许读取'], defaultId: 0, cancelId: 0,
      message: `允许读取“${name}”？`,
      detail: `位置：${filePath}\n用途：${reason}\n接收方：${String(provider || '当前聊天模型').slice(0, 60)}`,
    })
    if (approval.response !== 1) return { canceled: true }
    const form = new FormData()
    form.append('file', new Blob([await readFile(filePath)]), name)
    const response = await fetch(`${target.origin}/chat/upload/${conversationId}`, {
      method: 'POST', body: form, redirect: 'error',
    })
    const result = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(`文件解析失败：${result.detail || response.status}`)
    return { canceled: false, ...result }
  })

  // 生成物只写入已设定的工作文件夹；每一份文件都要单独确认。
  ipcMain.handle('save-to-workspace', async (event, relativeUrl, filename, purpose) => {
    requireCurrentWindow(event)
    const root = await workspaceRoot()
    if (!root) throw new Error('请先设置工作文件夹')
    if (!validArtifactPath(relativeUrl) || !validFilename(filename)) {
      throw new Error('成果地址或文件名无效')
    }
    const reason = checkedPurpose(purpose)
    const extension = extname(filename)
    const stem = filename.slice(0, -extension.length || undefined)
    let destination = join(root, filename)
    for (let number = 2; number < 100; number++) {
      try { await access(destination); destination = join(root, `${stem} (${number})${extension}`) }
      catch { break }
    }
    const approval = await dialog.showMessageBox(win, {
      type: 'question', buttons: ['取消', '保存文件'], defaultId: 0, cancelId: 0,
      message: `将生成结果保存为“${basename(destination)}”？`,
      detail: `目标：${destination}\n用途：${reason}`,
    })
    if (approval.response !== 1) return { canceled: true }
    await writeFile(destination, await artifactBytes(relativeUrl), { flag: 'wx' })
    return { canceled: false, path: destination }
  })

  // 成果始终从本机聊天接口读取；目标文件由系统“另存为”窗口选定。
  ipcMain.handle('save-artifact', async (event, relativeUrl, filename) => {
    requireCurrentWindow(event)
    if (!validArtifactPath(relativeUrl) || !validFilename(filename)) {
      throw new Error('成果地址或文件名无效')
    }
    const response = await fetch(target.origin + relativeUrl, { redirect: 'error' })
    if (!response.ok) throw new Error(`读取成果失败：HTTP ${response.status}`)
    const reader = response.body.getReader()
    const chunks = []
    let size = 0
    try {
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        size += value.length
        if (size > 30 * 1024 * 1024) throw new Error('成果超过 30 MB')
        chunks.push(Buffer.from(value))
      }
    } finally { reader.releaseLock() }
    const choice = await dialog.showSaveDialog(win, {
      title: '将成果保存到指定位置',
      defaultPath: join(app.getPath('downloads'), filename),
    })
    if (choice.canceled || !choice.filePath) return { canceled: true }
    await writeFile(choice.filePath, Buffer.concat(chunks))
    return { canceled: false, filename: basename(choice.filePath) }
  })

  // 用户先选择现有文件，再选择新位置；只复制，不让模型指定任意路径。
  ipcMain.handle('copy-existing-file', async event => {
    requireCurrentWindow(event)
    const source = await dialog.showOpenDialog(win, {
      title: '选择要复制的文件', properties: ['openFile'],
    })
    if (source.canceled || !source.filePaths.length) return { canceled: true }
    const destination = await dialog.showSaveDialog(win, {
      title: '选择目标目录和文件名', defaultPath: basename(source.filePaths[0]),
    })
    if (destination.canceled || !destination.filePath) return { canceled: true }
    if (resolve(source.filePaths[0]).toLowerCase() === resolve(destination.filePath).toLowerCase()) {
      throw new Error('目标位置与原文件相同')
    }
    await copyFile(source.filePaths[0], destination.filePath, constants.COPYFILE_EXCL)
    return { canceled: false, filename: basename(destination.filePath) }
  })
  win.webContents.session.setPermissionCheckHandler(
    (contents, permission, origin) => canCopy(contents, permission, origin),
  )
  win.webContents.session.setPermissionRequestHandler(
    (contents, permission, reply, details) =>
      reply(canCopy(contents, permission, details.requestingUrl)),
  )

  // 外部网页仅在用户确认后交给系统浏览器打开。
  function openLink(address) {
    const link = externalLink(address)
    if (!link || !isTrusted(win.webContents.getURL())) return
    const choice = dialog.showMessageBoxSync(win, {
      type: 'question', buttons: ['取消', '打开浏览器'],
      defaultId: 0, cancelId: 0,
      message: '是否使用系统浏览器打开？', detail: link.href,
    })
    if (choice === 1) {
      shell.openExternal(link.href).catch(() =>
        dialog.showErrorBox('打开失败', '无法打开系统浏览器。'))
    }
  }

  win.webContents.setWindowOpenHandler(({ url }) => {
    openLink(url)
    return { action: 'deny' }
  })
  win.webContents.on('will-navigate', event => {
    if (!isTrusted(event.url)) {
      event.preventDefault()
      openLink(event.url)
    }
  })
  win.webContents.on('will-redirect', event => {
    if (!isTrusted(event.url)) event.preventDefault()
  })
  await win.loadURL(target.href)
}).catch(error => {
  quitting = true
  backend?.stop()
  dialog.showErrorBox('桌面窗口启动失败', error.message)
  // app.exit 不触发 before-quit，因此上面先显式清理后端。
  app.exit(1)
})

// 当前面向 Windows：关闭全部窗口后退出。
app.on('window-all-closed', () => app.quit())
