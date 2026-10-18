// 读取当前后端的 SSE：每个 data 行包含一个完整的 JSON 事件。
export async function readChatStream(response, onEvent) {
  if (!response.body) throw new Error('浏览器未提供响应流')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  // 忽略空行和心跳，只处理后端发送的数据事件。
  function handleLine(line) {
    if (line.startsWith('data:')) {
      onEvent(JSON.parse(line.slice(5).trim()))
    }
  }

  try {
    while (true) {
      const { value, done } = await reader.read()
      // 流式解码，避免中文字符被拆开后乱码。
      buffer += decoder.decode(value, { stream: !done })
      const lines = buffer.split('\n')
      buffer = lines.pop()
      for (const line of lines) handleLine(line.trimEnd())
      if (done) {
        if (buffer.trim()) handleLine(buffer.trimEnd())
        break
      }
    }
  } finally {
    // 结束或处理失败时释放读取器。
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}