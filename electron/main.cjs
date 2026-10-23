const { app, BrowserWindow, dialog, shell } = require('electron')
const { createPolicy } = require('./security.cjs')

// Electron 准备完成后，才能创建窗口。
app.whenReady().then(async () => {
  const address = process.env.AGENT_FRONTEND_URL
  if (!address) throw new Error('请先设置 AGENT_FRONTEND_URL 为前端地址。')

  // 开发版只允许连接本机，避免误加载外部网站。
  const target = new URL(address)
  if (target.protocol !== 'http:' || target.hostname !== '127.0.0.1'
      || target.username || target.password) {
    throw new Error('开发地址必须是 http://127.0.0.1:端口')
  }

  const win = new BrowserWindow({
    title: 'Agent 工作台',
    width: 1200,
    height: 800,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
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

  // 只处理普通网页链接，并让用户确认目标地址。
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
    return { action: 'deny' } // 不在 Electron 内创建陌生页面窗口。
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
  dialog.showErrorBox('桌面窗口启动失败', error.message)
  app.quit()
})

// 当前以 Windows 为目标：关闭全部窗口后退出桌面程序。
app.on('window-all-closed', () => app.quit())