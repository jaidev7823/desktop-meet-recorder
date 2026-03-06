const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');
const readline = require('readline');

let mainWindow = null;
let pythonProcess = null;
let nextRequestId = 1;
const pendingRequests = new Map();
let lastBackendError = '';

const fallbackDevices = {
  mics: ['Microphone (Audio Array AM-C1 Device)'],
  stereos: ['Stereo Mix (Realtek(R) Audio)'],
};

function getFFmpegPath() {
  const candidate = app.isPackaged
    ? path.join(process.resourcesPath, 'bin', 'ffmpeg.exe')
    : path.join(__dirname, 'resources', 'bin', 'ffmpeg.exe');

  return fs.existsSync(candidate) ? candidate : 'ffmpeg';
}

function getPythonScriptPath() {
  return app.isPackaged
    ? path.join(process.resourcesPath, 'main.py')
    : path.join(__dirname, 'main.py');
}

function getPythonCommand() {
  if (process.env.PYTHON_PATH) {
    return process.env.PYTHON_PATH;
  }
  return process.platform === 'win32' ? 'python' : 'python3';
}

function sendToRenderer(channel, payload) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send(channel, payload);
  }
}

function resolvePending(requestId, payload) {
  if (!requestId || !pendingRequests.has(requestId)) {
    return;
  }
  const { resolve, timeoutId } = pendingRequests.get(requestId);
  clearTimeout(timeoutId);
  pendingRequests.delete(requestId);
  resolve(payload);
}

function rejectAllPending(reason) {
  for (const [, value] of pendingRequests.entries()) {
    clearTimeout(value.timeoutId);
    value.reject(new Error(reason));
  }
  pendingRequests.clear();
}

function parsePythonMessage(rawLine) {
  const line = (rawLine || '').trim();
  if (!line) return;

  try {
    const message = JSON.parse(line);
    if (!message || typeof message !== 'object') return;

    if (message.type === 'detection') {
      sendToRenderer('detection-update', message.data || {});
      return;
    }

    if (message.type === 'status') {
      sendToRenderer('backend-status', message.data || {});
      return;
    }

    if (message.type === 'error') {
      sendToRenderer('backend-error', message.data || {});
      return;
    }

    if (message.type === 'response') {
      resolvePending(message.requestId, message);
      return;
    }
  } catch (_) {
    // Keep support for legacy plain-text backend logs.
    sendToRenderer('backend-status', { message: line, level: 'info' });
  }
}

function startPythonDetector() {
  if (pythonProcess && !pythonProcess.killed) {
    return;
  }

  const python = getPythonCommand();
  const scriptPath = getPythonScriptPath();
  const ffmpegPath = getFFmpegPath();

  pythonProcess = spawn(python, ['-u', scriptPath, '--ffmpeg', ffmpegPath], {
    stdio: ['pipe', 'pipe', 'pipe'],
  });

  const stdoutReader = readline.createInterface({ input: pythonProcess.stdout });
  stdoutReader.on('line', parsePythonMessage);

  const stderrReader = readline.createInterface({ input: pythonProcess.stderr });
  stderrReader.on('line', (line) => {
    lastBackendError = line;
    sendToRenderer('backend-error', { message: line });
    console.error('[Python Error]', line);
  });

  pythonProcess.on('error', (error) => {
    lastBackendError = error.message;
    sendToRenderer('backend-error', { message: `Failed to spawn Python: ${error.message}` });
  });

  pythonProcess.on('close', (code) => {
    rejectAllPending(`Python process exited with code ${code}`);
    sendToRenderer('backend-status', { message: `Python process exited with code ${code}`, level: 'warn' });
    pythonProcess = null;
  });
}

function sendCommandToPython(action, payload = {}, timeoutMs = 7000) {
  if (!pythonProcess || !pythonProcess.stdin || pythonProcess.killed) {
    startPythonDetector();
  }

  if (!pythonProcess || !pythonProcess.stdin || pythonProcess.killed) {
    const detail = lastBackendError ? ` Last backend error: ${lastBackendError}` : '';
    return Promise.reject(new Error(`Python backend is not running.${detail}`));
  }

  const requestId = String(nextRequestId++);
  const message = { requestId, action, ...payload };

  const promise = new Promise((resolve, reject) => {
    const timeoutId = setTimeout(() => {
      pendingRequests.delete(requestId);
      reject(new Error(`Timeout while waiting for backend response: ${action}`));
    }, timeoutMs);

    pendingRequests.set(requestId, { resolve, reject, timeoutId });
  });

  pythonProcess.stdin.write(`${JSON.stringify(message)}\n`);

  return promise;
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1080,
    height: 760,
    minWidth: 900,
    minHeight: 620,
    backgroundColor: '#0b1220',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.loadFile('index.html');
}

ipcMain.handle('start-recording', async (_, devices) => {
  const response = await sendCommandToPython('start_recording', { devices });
  if (response.ok === false) {
    throw new Error(response.error || 'Failed to start recording');
  }
  return true;
});

ipcMain.handle('stop-recording', async () => {
  const response = await sendCommandToPython('stop_recording');
  if (response.ok === false) {
    throw new Error(response.error || 'Failed to stop recording');
  }
  return true;
});

ipcMain.handle('set-auto-record', async (_, enabled) => {
  const response = await sendCommandToPython('set_auto_record', { enabled: !!enabled });
  if (response.ok === false) {
    throw new Error(response.error || 'Failed to set auto-record mode');
  }
  return true;
});

ipcMain.handle('get-audio-devices', async () => {
  try {
    const response = await sendCommandToPython('get_audio_devices', {}, 12000);
    if (response.ok && response.data) {
      return response.data;
    }
  } catch (_) {
    // Fall back if backend enumeration fails.
  }
  return fallbackDevices;
});

app.whenReady().then(() => {
  createWindow();
  startPythonDetector();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('before-quit', () => {
  if (pythonProcess) {
    try {
      pythonProcess.kill();
    } catch (_) {
      // no-op
    }
  }
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});
