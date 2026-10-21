// 检查分包、中文解码、错误传播和读取器释放，不请求真实后端。
import test from 'node:test'
import assert from 'node:assert/strict'
import { readChatStream } from '../fronted/src/chat_stream.js'

const encoder = new TextEncoder()
const line = (event) => 'data: ' + JSON.stringify(event) + '\n\n'
function response(parts) {
  return new Response(new ReadableStream({
    start(controller) {
      for (const part of parts) controller.enqueue(typeof part === 'string' ? encoder.encode(part) : part)
      controller.close()
    },
  }))
}
async function collect(parts) {
  const events = []
  await readChatStream(response(parts), (event) => events.push(event))
  return events
}
test('multiple events in one packet', async () => {
  const events = [{ type: 'text_delta', content: '你好' }, { type: 'done' }]
  assert.deepEqual(await collect([events.map(line).join('')]), events)
})
test('Chinese bytes split individually', async () => {
  const event = { type: 'text_delta', content: '你好，Vue 学习' }
  assert.deepEqual(await collect(Array.from(encoder.encode(line(event)), (byte) => new Uint8Array([byte]))), [event])
})
test('every possible split point', async () => {
  const event = { type: 'text_delta', content: '中文内容' }
  const bytes = encoder.encode(line(event))
  for (let i = 0; i <= bytes.length; i++) {
    assert.deepEqual(await collect([bytes.slice(0, i), bytes.slice(i)]), [event])
  }
})
test('heartbeats and other lines are ignored', async () => {
  assert.deepEqual(await collect([': ping\n\nid: 1\nevent: message\n' + line({ type: 'done' })]), [{ type: 'done' }])
})
test('CRLF and unterminated final line', async () => {
  assert.deepEqual(await collect(['data: {"type":"start"}\r\n\r\ndata: {"type":"done"}']), [{ type: 'start' }, { type: 'done' }])
})
test('empty stream', async () => assert.deepEqual(await collect([]), []))
test('missing body', async () => {
  await assert.rejects(readChatStream({ body: null }, () => {}), /响应流/)
})
test('malformed JSON releases reader', async () => {
  const result = response(['data: {bad}\n\n'])
  await assert.rejects(readChatStream(result, () => {}), SyntaxError)
  assert.equal(result.body.locked, false)
})
test('callback error cancels source and releases reader', async () => {
  let cancelled = false
  const body = new ReadableStream({
    start(controller) { controller.enqueue(encoder.encode(line({ type: 'done' }))) },
    cancel() { cancelled = true },
  })
  await assert.rejects(readChatStream(new Response(body), () => { throw new Error('callback failed') }), /callback failed/)
  assert.equal(cancelled, true)
  assert.equal(body.locked, false)
})
test('upstream stream error releases reader', async () => {
  const body = new ReadableStream({ start(controller) { controller.error(new Error('stream failed')) } })
  await assert.rejects(readChatStream(new Response(body), () => {}), /stream failed/)
  assert.equal(body.locked, false)
})
test('cleanup failure preserves original error', async () => {
  let released = false
  const original = new Error('original')
  const fake = { body: { getReader: () => ({
    read: async () => { throw original },
    cancel: async () => { throw new Error('cleanup') },
    releaseLock: () => { released = true },
  }) } }
  await assert.rejects(readChatStream(fake, () => {}), (error) => error === original)
  assert.equal(released, true)
})

