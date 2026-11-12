const { contextBridge, ipcRenderer } = require('electron')

// 每个方法只执行一项明确操作，不暴露通用文件系统或任意 IPC。
contextBridge.exposeInMainWorld('agentDesktop', {
  saveArtifact: (relativeUrl, filename) =>
    ipcRenderer.invoke('save-artifact', relativeUrl, filename),
  copyExistingFile: () => ipcRenderer.invoke('copy-existing-file'),
  getWorkspace: () => ipcRenderer.invoke('get-workspace'),
  chooseWorkspace: () => ipcRenderer.invoke('choose-workspace'),
  readWorkspaceFile: (conversationId, purpose, provider) =>
    ipcRenderer.invoke('read-workspace-file', conversationId, purpose, provider),
  saveToWorkspace: (relativeUrl, filename, purpose) =>
    ipcRenderer.invoke('save-to-workspace', relativeUrl, filename, purpose),
})
