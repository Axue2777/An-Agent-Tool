// 渲染页面只能请求当前聊天中由后端生成的成果 URL。
const UUID = '[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}'
const ARTIFACT = new RegExp(`^/chat/files/${UUID}/${UUID}$`, 'i')
const EXTENSIONS = new Set(['md', 'txt', 'csv', 'json', 'py', 'js', 'ts', 'vue',
  'html', 'css', 'xml', 'yaml', 'yml', 'sql', 'docx', 'xlsx', 'pptx', 'pdf', 'png', 'jpg'])

function validArtifactPath(value) {
  return typeof value === 'string' && ARTIFACT.test(value)
}

function validFilename(value) {
  if (typeof value !== 'string' || !value.trim() || value.length > 120
      || value.includes('/') || value.includes('\\') || value.includes('..')
      || /[<>:"|?*\u0000-\u001f]/.test(value)) return false
  const extension = value.split('.').at(-1).toLowerCase()
  return EXTENSIONS.has(extension)
}

module.exports = { validArtifactPath, validFilename }
