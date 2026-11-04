
const { existsSync } = require('node:fs')
const { dirname, join } = require('node:path')
const { createServer } = require('node:net')
const { spawn, execFileSync } = require('node:child_process')
const { setTimeout: delay } = require('node:timers/promises')

// 让系统分配本机空闲端口；探测完成后释放给后端使用。
function choosePort() {
  return new Promise((resolve, reject) => {
    const server = createServer()
    server.once('error', reject)
    server.listen(0, '127.0.0.1', () => {
      const port = server.address().port
      server.close(error => error ? reject(error) : resolve(port))
    })
  })
}

// 只管理由本控制器创建的进程，不按程序名称批量结束进程。
function createBackend(executable, onUnexpectedExit) {
  let child = null
  let stopping = false
  let ready = false
  let failed = null
  let started = false

  function isRunning() {
    return child && child.pid && child.exitCode === null
      && child.signalCode === null
  }

  function stop() {
    stopping = true
    if (!isRunning()) return
    // Windows：按本次创建的 PID 清理后端及其子进程。
    const taskkill = join(process.env.SystemRoot || 'C:\\Windows',
      'System32', 'taskkill.exe')
    try {
      execFileSync(taskkill, ['/PID', String(child.pid), '/T', '/F'], {
        windowsHide: true, stdio: 'ignore', timeout: 5000,
      })
    } catch {
      console.error(`后端进程清理未确认完成，PID：${child.pid}`)
    }
  }

  async function start() {
    if (started) throw new Error('同一个后端控制器不能重复启动。')
    started = true
    if (!existsSync(executable)) {
      throw new Error(`找不到后端程序：${executable}`)
    }
    const port = await choosePort()
    if (stopping) throw new Error('启动已取消。')
    const address = `http://127.0.0.1:${port}`
    child = spawn(executable, ['--port', String(port)], {
      cwd: dirname(executable), windowsHide: true, stdio: 'inherit',
    })
    child.once('error', error => { failed = error })
    child.once('exit', (code, signal) => {
      failed = new Error(`后端已经退出，退出码：${code}，信号：${signal}`)
      if (ready && !stopping) onUnexpectedExit(failed)
    })
    console.log(`后端进程 PID：${child.pid}；计划地址：${address}`)

    // 进程创建不等于接口就绪；最多等待 45 秒。
    try {
      const deadline = Date.now() + 45000
      while (Date.now() < deadline) {
        if (stopping) throw new Error('启动已取消。')
        if (failed) throw failed
        if (!isRunning()) throw new Error('后端进程未运行。')
        let healthy = false
        try {
          const response = await fetch(`${address}/health`, {
            signal: AbortSignal.timeout(1000), redirect: 'error',
          })
          const data = await response.json()
          healthy = response.ok && data.status === 'ok'
            && data.service === 'agent-workspace'
        } catch {
          // 服务尚未就绪时继续等待；进程错误在下一轮明确报告。
        }
        if (failed) throw failed
        if (stopping) throw new Error('启动已取消。')
        if (healthy && isRunning()) {
          ready = true
          return address
        }
        await delay(300)
      }
      throw new Error('后端启动超时，请查看终端中的后端报错。')
    } catch (error) {
      stop()
      throw error
    }
  }

  return { start, stop }
}

module.exports = { createBackend }