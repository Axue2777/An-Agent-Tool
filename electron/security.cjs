// 规则不依赖 Electron，因此可以单独测试。
function createPolicy(origin, owner) {
  const isTrusted = address => {
    try {
      const url = new URL(address)
      return url.origin === origin && !url.username && !url.password
    } catch { return false }
  }
  const canCopy = (contents, permission, address) =>
    contents === owner && permission === 'clipboard-sanitized-write' && isTrusted(address)

  const externalLink = address => {
    try {
      const url = new URL(address)
      return ['http:', 'https:'].includes(url.protocol) &&
        !url.username && !url.password ? url : null
    } catch { return null }
  }
  return { isTrusted, canCopy, externalLink }
}
module.exports = { createPolicy }