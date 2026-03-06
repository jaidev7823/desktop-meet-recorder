const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electronAPI', {
  startRecording: (devices) => ipcRenderer.send('start-recording', devices),
  stopRecording: () => ipcRenderer.send('stop-recording'),
  setAutoRecord: (val) => ipcRenderer.send('set-auto-record', val),
  getAudioDevices: () => ipcRenderer.invoke('get-audio-devices'),
  onDetectionUpdate: (cb) => ipcRenderer.on('detection-update', (_, data) => cb(data))
})