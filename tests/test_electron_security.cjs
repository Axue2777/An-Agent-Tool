const test = require('node:test')
const assert = require('node:assert/strict')
const { createPolicy } = require('../electron/security.cjs')
const { validArtifactPath, validFilename } = require('../electron/local-files.cjs')
const { insideWorkspace } = require('../electron/workspace-paths.cjs')

const owner = {}
const origin = 'http://127.0.0.1:5173'
const { isTrusted, canCopy, externalLink } = createPolicy(origin, owner)

// 正向和反向检查：规则既要允许正常操作，也要拒绝危险输入。
test('允许当前来源', () => assert.equal(isTrusted(origin), true))
test('拒绝其他端口', () => assert.equal(isTrusted('http://127.0.0.1:5174'), false))
test('允许复制回答', () => assert.equal(canCopy(owner, 'clipboard-sanitized-write', origin), true))
test('拒绝读取剪贴板', () => assert.equal(canCopy(owner, 'clipboard-read', origin), false))
test('拒绝其他窗口', () => assert.equal(canCopy({}, 'clipboard-sanitized-write', origin), false))
test('允许普通网页', () => assert.equal(externalLink('https://example.com/').href, 'https://example.com/'))
test('拒绝危险协议', () => assert.equal(externalLink('javascript:alert(1)'), null))
test('拒绝携带凭证', () => assert.equal(externalLink('https://user:pass@example.com/'), null))
test('工作文件夹只允许内部文件', () => {
  assert.equal(insideWorkspace('D:\\AgentFiles', 'D:\\AgentFiles\\report.md'), true)
  assert.equal(insideWorkspace('D:\\AgentFiles', 'D:\\AgentFiles2\\report.md'), false)
  assert.equal(insideWorkspace('D:\\AgentFiles', 'D:\\outside.md'), false)
})
test('仅允许当前聊天成果的相对地址', () => {
  assert.equal(validArtifactPath('/chat/files/11111111-1111-4111-8111-111111111111/22222222-2222-4222-8222-222222222222'), true)
  assert.equal(validArtifactPath('https://example.com/secret'), false)
  assert.equal(validArtifactPath('/chat/files/../../secret'), false)
  assert.equal(validArtifactPath('/chat/files/11111111-1111-4111-8111-111111111111/22222222-2222-4222-8222-222222222222?x=1'), false)
})
test('另存文件名禁止路径和危险扩展名', () => {
  assert.equal(validFilename('学习计划.docx'), true)
  assert.equal(validFilename('report.pdf'), true)
  assert.equal(validFilename('../secret.pdf'), false)
  assert.equal(validFilename('installer.exe'), false)
})
