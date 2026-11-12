const { relative, isAbsolute, sep } = require('node:path')

// 只接受工作目录内的真实路径；拒绝上级目录和跨盘符路径。
function insideWorkspace(root, target) {
  const part = relative(root, target)
  return part !== '' && part !== '..' && !part.startsWith('..' + sep) && !isAbsolute(part)
}

module.exports = { insideWorkspace }
