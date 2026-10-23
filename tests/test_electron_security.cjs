const test = require('node:test')
const assert = require('node:assert/strict')
const { createPolicy } = require('../electron/security.cjs')

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