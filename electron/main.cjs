
const { app, BrowserWindow, dialog, shell } = require('electron')
const { join } = require('node:path')
const { createPolicy } = require('./security.cjs')
const { createBackend } = require('./backend.cjs')

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
    },
  })

  const { isTrusted, canCopy, externalLink } =
    createPolicy(target.origin, win.webContents)
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
