const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('mnemoxDesktop', {
  checkForUpdates: () => ipcRenderer.invoke('desktop-updater:check'),
  getUpdateState: () => ipcRenderer.invoke('desktop-updater:get-state'),
  getUpdateSettings: () => ipcRenderer.invoke('desktop-updater:get-settings'),
  setUpdateSettings: (settings) => ipcRenderer.invoke('desktop-updater:set-settings', settings),
  downloadUpdate: () => ipcRenderer.invoke('desktop-updater:download'),
  quitAndInstall: () => ipcRenderer.invoke('desktop-updater:quit-and-install'),
  getSavedLogin: () => ipcRenderer.invoke('desktop-auth:get-saved-login'),
  saveLogin: (payload) => ipcRenderer.invoke('desktop-auth:save-login', payload),
  clearSavedLogin: () => ipcRenderer.invoke('desktop-auth:clear-saved-login'),
  getPreference: (key) => ipcRenderer.invoke('desktop-preferences:get', key),
  setPreference: (key, value) => ipcRenderer.invoke('desktop-preferences:set', key, value),
  setPomodoroReminder: (payload) => ipcRenderer.invoke('desktop-reminder:set', payload),
  clearPomodoroReminder: () => ipcRenderer.invoke('desktop-reminder:clear'),
  onUpdateState: (callback) => {
    const handler = (_event, payload) => callback(payload)
    ipcRenderer.on('desktop-updater:state', handler)
    return () => ipcRenderer.removeListener('desktop-updater:state', handler)
  },
  onReminderTriggered: (callback) => {
    const handler = (_event, payload) => callback(payload)
    ipcRenderer.on('desktop-reminder:triggered', handler)
    return () => ipcRenderer.removeListener('desktop-reminder:triggered', handler)
  },
})
