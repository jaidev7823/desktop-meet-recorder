const { app, BrowserWindow, ipcMain, shell, dialog } = require('electron');
const path = require('path');
const fs = require('fs');
const http = require('http');
const crypto = require('crypto');
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

    if (message.type === 'transcript') {
      sendToRenderer('transcript-update', message.data || {});
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
  const { outputDir } = loadRecordingConfig();
  fs.mkdirSync(outputDir, { recursive: true });

  pythonProcess = spawn(
    python,
    ['-u', scriptPath, '--ffmpeg', ffmpegPath, '--output-dir', outputDir],
    {
    stdio: ['pipe', 'pipe', 'pipe'],
    },
  );

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
  console.log('Requesting audio devices from Python backend...');
  try {
    const response = await sendCommandToPython('get_audio_devices', {}, 12000);

    if (response.ok && response.data) {

      let mics = Array.isArray(response.data.mics) ? response.data.mics : [];
      let stereos = Array.isArray(response.data.stereos) ? response.data.stereos : [];
      console.log('Raw devices from Python:', { mics, stereos });
      // remove invalid device identifiers
      const clean = (list) =>
        list
          .filter(Boolean)
          .filter((d) => typeof d === 'string')
          .filter((d) => !d.startsWith('@device'));

      mics = clean(mics);
      stereos = clean(stereos);

      // ensure at least one device exists
      if (mics.length === 0) {
        mics = fallbackDevices.mics;
      }

      if (stereos.length === 0) {
        stereos = fallbackDevices.stereos;
      }

      return { mics, stereos };
    }

  } catch (err) {
    console.error("Audio device detection failed:", err);
  }

  return fallbackDevices;
});

ipcMain.handle('select-output-directory', async () => {
  const current = loadRecordingConfig().outputDir;
  const result = await dialog.showOpenDialog(mainWindow, {
    title: 'Select recordings folder',
    defaultPath: current,
    properties: ['openDirectory', 'createDirectory'],
  });
  if (result.canceled || !result.filePaths || result.filePaths.length === 0) {
    return null;
  }
  return result.filePaths[0];
});

ipcMain.handle('set-output-directory', async (_, outputDir) => {
  const normalized = (outputDir || '').trim();
  if (!normalized) {
    return null;
  }
  fs.mkdirSync(normalized, { recursive: true });
  saveRecordingConfig({ outputDir: normalized });
  try {
    const response = await sendCommandToPython('set_output_directory', { outputDir: normalized });
    if (response.ok && response.data && response.data.outputDir) {
      return response.data.outputDir;
    }
  } catch (_) {
    // backend may not be ready yet
  }
  return normalized;
});

ipcMain.handle('get-output-directory', async () => {
  try {
    const response = await sendCommandToPython('get_output_directory');
    if (response.ok && response.data && response.data.outputDir) {
      return response.data.outputDir;
    }
  } catch (_) {
    // Fall back to local persisted config.
  }
  return loadRecordingConfig().outputDir;
});

ipcMain.handle('open-output-directory', async () => {
  const target = loadRecordingConfig().outputDir;
  fs.mkdirSync(target, { recursive: true });
  const error = await shell.openPath(target);
  return !error;
});

function getConfigPath() {
  return path.join(app.getPath('userData'), 'integrations.json');
}

function getRecordingConfigPath() {
  return path.join(app.getPath('userData'), 'recording-config.json');
}

function getDefaultOutputDir() {
  return path.join(app.getPath('documents'), 'BriefBridgeRecordings');
}

function loadRecordingConfig() {
  const configPath = getRecordingConfigPath();
  if (!fs.existsSync(configPath)) {
    return { outputDir: getDefaultOutputDir() };
  }
  try {
    const raw = fs.readFileSync(configPath, 'utf8');
    const data = JSON.parse(raw);
    return { outputDir: data.outputDir || getDefaultOutputDir() };
  } catch (_) {
    return { outputDir: getDefaultOutputDir() };
  }
}

function saveRecordingConfig(config) {
  const configPath = getRecordingConfigPath();
  fs.writeFileSync(configPath, JSON.stringify(config, null, 2), 'utf8');
}

function startNotionOAuthServer(expectedState, callbackPort = 8765, timeoutMs = 180000) {
  return new Promise((resolve, reject) => {
    const server = http.createServer();
    let settled = false;
    let timeoutId = null;
    let resolveCode;
    let rejectCode;

    const waitForCode = new Promise((innerResolve, innerReject) => {
      resolveCode = innerResolve;
      rejectCode = innerReject;
    });

    function cleanup() {
      if (timeoutId) {
        clearTimeout(timeoutId);
        timeoutId = null;
      }
      if (server.listening) {
        try {
          server.close();
        } catch (_) {
          // no-op
        }
      }
    }

    function completeError(message, res) {
      if (res && !res.headersSent) {
        res.writeHead(400, { 'Content-Type': 'text/plain' });
        res.end(`${message}. You can close this tab.`);
      }
      if (settled) return;
      settled = true;
      cleanup();
      rejectCode(new Error(message));
    }

    server.on('request', (req, res) => {
      const requestUrl = new URL(req.url || '/', 'http://127.0.0.1');
      if (requestUrl.pathname !== '/notion/oauth/callback') {
        res.writeHead(404, { 'Content-Type': 'text/plain' });
        res.end('Not found');
        return;
      }

      const code = requestUrl.searchParams.get('code');
      const state = requestUrl.searchParams.get('state');
      const error = requestUrl.searchParams.get('error');

      if (error) {
        completeError(`Notion OAuth error: ${error}`, res);
        return;
      }
      if (!code || state !== expectedState) {
        completeError('Invalid Notion OAuth callback state', res);
        return;
      }

      res.writeHead(200, { 'Content-Type': 'text/plain' });
      res.end('Notion connected. You can close this tab and return to the app.');
      if (settled) return;
      settled = true;
      cleanup();
      resolveCode({ code });
    });

    server.on('error', (error) => {
      if (settled) return;
      settled = true;
      cleanup();
      rejectCode(error);
      reject(error);
    });

    server.listen(callbackPort, '127.0.0.1', () => {
      const address = server.address();
      if (!address || typeof address !== 'object') {
        cleanup();
        reject(new Error('Failed to start local OAuth callback server'));
        return;
      }

      timeoutId = setTimeout(() => {
        if (settled) return;
        settled = true;
        cleanup();
        rejectCode(new Error('Notion OAuth callback timed out'));
      }, timeoutMs);

      resolve({
        port: address.port,
        waitForCode,
        close: cleanup,
      });
    });
  });
}

ipcMain.handle('save-integrations', async (_, settings) => {
  try {
    const response = await sendCommandToPython('save_integrations', { data: settings });
    if (response.ok === false) {
      throw new Error(response.error || 'Failed to save integrations');
    }
    return true;
  } catch (error) {
    console.error('Failed to save integrations:', error);
    return false;
  }
});

ipcMain.handle('load-integrations', async () => {
  try {
    const response = await sendCommandToPython('get_integrations');
    if (response.ok && response.data) {
      return response.data;
    }
  } catch (error) {
    console.error('Failed to load integrations:', error);
  }
  return null;
});

ipcMain.handle('connect-notion-oauth', async (_, data) => {
  const clientId = (data?.clientId || '').trim();
  const clientSecret = (data?.clientSecret || '').trim();
  const parentPageId = (data?.parentPageId || '').trim();
  if (!clientId || !clientSecret) {
    return { error: 'Notion OAuth client ID and client secret are required' };
  }

  const state = crypto.randomBytes(16).toString('hex');
  const callbackPort = Number(process.env.NOTION_OAUTH_CALLBACK_PORT || '8765');
  if (!Number.isInteger(callbackPort) || callbackPort < 1 || callbackPort > 65535) {
    return { error: 'Invalid NOTION_OAUTH_CALLBACK_PORT value' };
  }
  let oauthServer;
  let redirectUri;

  try {
    oauthServer = await startNotionOAuthServer(state, callbackPort);
    redirectUri = `http://127.0.0.1:${oauthServer.port}/notion/oauth/callback`;

    const authUrl = new URL('https://api.notion.com/v1/oauth/authorize');
    authUrl.searchParams.set('owner', 'user');
    authUrl.searchParams.set('client_id', clientId);
    authUrl.searchParams.set('redirect_uri', redirectUri);
    authUrl.searchParams.set('response_type', 'code');
    authUrl.searchParams.set('state', state);

    await shell.openExternal(authUrl.toString());
    const callbackPayload = await oauthServer.waitForCode;

    const response = await sendCommandToPython(
      'connect_notion_oauth',
      {
        data: {
          code: callbackPayload.code,
          clientId,
          clientSecret,
          redirectUri,
          parentPageId,
        },
      },
      45000,
    );

    if (!response.ok) {
      return { error: response.error || 'Failed to connect Notion OAuth' };
    }
    return response.data || { connected: true };
  } catch (error) {
    console.error('Failed to connect Notion OAuth:', error);
    return { error: error.message || 'Failed to connect Notion OAuth' };
  } finally {
    if (oauthServer && typeof oauthServer.close === 'function') {
      oauthServer.close();
    }
  }
});

ipcMain.handle('save-recording', async (_, data) => {
  try {
    const response = await sendCommandToPython('save_recording', { data });
    if (response.ok && response.data) {
      return response.data;
    }
    throw new Error(response.error || 'Failed to save recording');
  } catch (error) {
    console.error('Failed to save recording:', error);
    return null;
  }
});

ipcMain.handle('get-recordings', async (_, limit = 50) => {
  try {
    const response = await sendCommandToPython('get_recordings', { limit });
    if (response.ok && response.data) {
      return response.data.recordings;
    }
  } catch (error) {
    console.error('Failed to get recordings:', error);
  }
  return [];
});

ipcMain.handle('transcribe-audio', async (_, data) => {
  try {
    const response = await sendCommandToPython('transcribe_audio', { data }, 120000);
    if (response.ok && response.data) {
      return response.data;
    }
    throw new Error(response.error || 'Transcription failed');
  } catch (error) {
    console.error('Failed to transcribe audio:', error);
    return { error: error.message };
  }
});

ipcMain.handle('summarize-with-gemini', async (_, data) => {
  try {
    const response = await sendCommandToPython('summarize_with_gemini', { data }, 60000);
    if (response.ok && response.data) {
      return response.data;
    }
    throw new Error(response.error || 'Summary generation failed');
  } catch (error) {
    console.error('Failed to generate summary:', error);
    return { error: error.message };
  }
});

ipcMain.handle('chat-with-gemini', async (_, data) => {
  try {
    const response = await sendCommandToPython('chat_with_gemini', { data }, 60000);
    if (response.ok && response.data) {
      return response.data;
    }
    throw new Error(response.error || 'Chat failed');
  } catch (error) {
    console.error('Failed to chat with Gemini:', error);
    return { error: error.message };
  }
});

ipcMain.handle('create-notion-page', async (_, data) => {
  try {
    const response = await sendCommandToPython('create_notion_page', { data }, 30000);
    if (response.ok && response.data) {
      return response.data;
    }
    throw new Error(response.error || 'Failed to create Notion page');
  } catch (error) {
    console.error('Failed to create Notion page:', error);
    return { error: error.message };
  }
});

ipcMain.handle('process-recording', async (_, data) => {
  try {
    const response = await sendCommandToPython('process_recording', { data }, 300000);
    if (response.ok && response.data) {
      return response.data;
    }
    throw new Error(response.error || 'Processing failed');
  } catch (error) {
    console.error('Failed to process recording:', error);
    return { error: error.message };
  }
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
