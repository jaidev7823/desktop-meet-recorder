const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  startRecording: (devices) => ipcRenderer.invoke('start-recording', devices),
  stopRecording: () => ipcRenderer.invoke('stop-recording'),
  setAutoRecord: (val) => ipcRenderer.invoke('set-auto-record', val),
  getAudioDevices: () => ipcRenderer.invoke('get-audio-devices'),
  saveIntegrations: (settings) => ipcRenderer.invoke('save-integrations', settings),
  loadIntegrations: () => ipcRenderer.invoke('load-integrations'),
  saveRecording: (data) => ipcRenderer.invoke('save-recording', data),
  getRecordings: (limit) => ipcRenderer.invoke('get-recordings', limit),
  onDetectionUpdate: (cb) => ipcRenderer.on('detection-update', (_, data) => cb(data)),
  onBackendStatus: (cb) => ipcRenderer.on('backend-status', (_, data) => cb(data)),
  onBackendError: (cb) => ipcRenderer.on('backend-error', (_, data) => cb(data)),
});
