const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('mnemoxDesktop', {
  checkForUpdates: () => ipcRenderer.invoke('desktop-updater:check'),
  getUpdateState: () => ipcRenderer.invoke('desktop-updater:get-state'),
  getUpdateSettings: () => ipcRenderer.invoke('desktop-updater:get-settings'),
  setUpdateSettings: (settings) => ipcRenderer.invoke('desktop-updater:set-settings', settings),
  downloadUpdate: () => ipcRenderer.invoke('desktop-updater:download'),
  quitAndInstall: () => ipcRenderer.invoke('desktop-updater:quit-and-install'),
  onUpdateState: (callback) => {
    const handler = (_event, payload) => callback(payload)
    ipcRenderer.on('desktop-updater:state', handler)
    return () => ipcRenderer.removeListener('desktop-updater:state', handler)
  },
})
