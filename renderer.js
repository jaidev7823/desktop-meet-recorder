let recording = false;
let autoRecord = true;
let timerInterval = null;
let elapsedSeconds = 0;
let liveTranscriptText = '';

let integrations = {
  notion: {
    enabled: false,
    accessToken: '',
    workspaceId: '',
    workspaceName: '',
    parentPageId: '',
  },
  gemini: { enabled: false, apiKey: '' },
  whisper: { mode: 'local', apiKey: '' }
};

let activePage = 'recording';

function el(id) {
  return document.getElementById(id);
}

function setBackendMessage(message, isError = false) {
  const target = el('backendMessage');
  target.textContent = `Backend: ${message}`;
  target.className = `text-xs font-mono ${isError ? 'text-red-400' : 'text-slate-400'}`;
}

function setIntegrationStatus(message, isError = false) {
  const target = el('integrationSaveStatus');
  if (!target) return;
  target.textContent = message;
  target.className = `text-sm ${isError ? 'text-red-400' : 'text-slate-400'}`;
}

function setDetectionCard(id, active, label) {
  const card = el(id);
  card.classList.toggle('border-ok', active);
  card.classList.toggle('border-line', !active);
  card.innerHTML = `${label}: <span class="${active ? 'text-emerald-400' : 'text-slate-400'}">${active ? 'Yes' : 'No'}</span>`;
}

function updateStatusUI() {
  const statusIndicator = el('statusIndicator');
  const titleDot = el('titleDot');
  const statusLabel = el('statusLabel');
  const statusText = el('statusText');
  const recordBtn = el('recordBtn');
  const ffmpegStatus = el('ffmpegStatus');

  statusIndicator.className = `w-3 h-3 rounded-full ${recording ? 'bg-ok shadow-[0_0_0_6px_rgba(34,197,94,0.2)]' : 'bg-slate-500'}`;
  titleDot.className = `w-2.5 h-2.5 rounded-full ${recording ? 'bg-ok' : 'bg-slate-500'}`;

  if (recording) {
    statusLabel.textContent = 'Recording in progress';
    statusText.textContent = 'Recording';
    recordBtn.textContent = 'Stop Recording';
    recordBtn.className = 'rounded-xl bg-danger hover:bg-red-500 text-white font-semibold px-5 py-3 transition';
    ffmpegStatus.textContent = 'ffmpeg recording';
  } else {
    statusLabel.textContent = 'Waiting for call';
    statusText.textContent = 'Idle';
    recordBtn.textContent = 'Start Recording';
    recordBtn.className = 'rounded-xl bg-calm hover:bg-sky-400 text-slate-900 font-semibold px-5 py-3 transition';
    ffmpegStatus.textContent = 'ffmpeg ready';
  }
}

function startTimer() {
  if (timerInterval) return;

  elapsedSeconds = 0;
  timerInterval = setInterval(() => {
    elapsedSeconds += 1;
    const h = String(Math.floor(elapsedSeconds / 3600)).padStart(2, '0');
    const m = String(Math.floor((elapsedSeconds % 3600) / 60)).padStart(2, '0');
    const s = String(elapsedSeconds % 60).padStart(2, '0');
    el('timer').textContent = `${h}:${m}:${s}`;
  }, 1000);
}

function stopTimer() {
  if (timerInterval) {
    clearInterval(timerInterval);
    timerInterval = null;
  }
  elapsedSeconds = 0;
  el('timer').textContent = '00:00:00';
}

function syncRecordingState(isRecording) {
  if (recording === isRecording) {
    return;
  }

  recording = isRecording;
  if (recording) {
    liveTranscriptText = '';
    updateLiveTranscript({ fullText: '', latestText: '', segmentCount: 0, status: 'starting' });
    startTimer();
  } else {
    stopTimer();
  }
  if (!recording && !liveTranscriptText.trim()) {
    updateLiveTranscript({ fullText: '', latestText: '', segmentCount: 0, status: 'idle' });
  }
  updateStatusUI();
}

function updateLiveTranscript(data = {}) {
  const transcriptNode = el('liveTranscript');
  const metaNode = el('liveTranscriptMeta');
  liveTranscriptText = (data.fullText || '').trim();
  transcriptNode.textContent = liveTranscriptText || 'Transcript will appear here during recording.';

  const pieces = [];
  if (typeof data.segmentCount === 'number') {
    pieces.push(`${data.segmentCount} chunks`);
  }
  if (data.status) {
    pieces.push(data.status);
  }
  metaNode.textContent = pieces.join(' | ') || 'Waiting for segments';
}

function populateSelect(id, items) {
  const select = el(id);
  select.innerHTML = '';

  if (!Array.isArray(items) || items.length === 0) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = 'No devices found';
    select.appendChild(opt);
    return;
  }

  for (const name of items) {
    const opt = document.createElement('option');
    opt.value = name;
    opt.textContent = name;
    select.appendChild(opt);
  }

  select.selectedIndex = 0;
}

function selectedDeviceValue(id) {
  const select = el(id);
  const value = (select.value || '').trim();
  if (!value || value === 'Loading...' || value === 'No devices found') {
    return '';
  }
  return value;
}

async function toggleRecording() {
  if (!window.electronAPI) {
    setBackendMessage('Electron bridge not found', true);
    return;
  }

  const mic = selectedDeviceValue('micSelect');
  const stereo = selectedDeviceValue('stereoSelect');

  try {
    if (!recording) {
      if (!mic) {
        setBackendMessage('Select a valid microphone before starting', true);
        return;
      }
      if (!stereo) {
        setBackendMessage('Select a valid system audio input before starting', true);
        return;
      }
      await window.electronAPI.startRecording({ mic, stereo });
      syncRecordingState(true);
      setBackendMessage('Manual recording started');
    } else {
      await window.electronAPI.stopRecording();
      syncRecordingState(false);
      setBackendMessage('Manual recording stopped');
      await loadRecordings();
    }
  } catch (error) {
    setBackendMessage(error.message || 'Failed to change recording state', true);
  }
}

function setOutputDirectoryUI(pathValue) {
  const target = el('outputDirPath');
  target.textContent = pathValue || 'Not configured';
}

async function initializeOutputDirectory() {
  if (!window.electronAPI) {
    setOutputDirectoryUI('Unavailable in preview mode');
    return;
  }
  try {
    const current = await window.electronAPI.getOutputDirectory();
    setOutputDirectoryUI(current || 'Not configured');
  } catch (error) {
    setOutputDirectoryUI('Could not load output folder');
    setBackendMessage(error.message || 'Failed to load output folder', true);
  }
}

async function chooseOutputDirectory() {
  if (!window.electronAPI) return;
  try {
    const selected = await window.electronAPI.selectOutputDirectory();
    if (!selected) return;
    const resolved = await window.electronAPI.setOutputDirectory(selected);
    if (resolved) {
      setOutputDirectoryUI(resolved);
      setBackendMessage('Recording folder updated');
    }
  } catch (error) {
    setBackendMessage(error.message || 'Failed to set recording folder', true);
  }
}

async function openOutputDirectory() {
  if (!window.electronAPI) return;
  try {
    const ok = await window.electronAPI.openOutputDirectory();
    if (!ok) {
      setBackendMessage('Could not open recording folder', true);
    }
  } catch (error) {
    setBackendMessage(error.message || 'Could not open recording folder', true);
  }
}

async function toggleAutoRecord() {
  autoRecord = !autoRecord;
  const button = el('autoToggle');
  button.textContent = autoRecord ? 'Enabled' : 'Disabled';
  button.className = `mt-2 inline-flex items-center px-3 py-2 rounded-lg border text-sm transition ${autoRecord ? 'border-ok bg-emerald-900/30 text-emerald-300' : 'border-line bg-slate-800 text-slate-300 hover:bg-slate-700'}`;

  if (!window.electronAPI) {
    return;
  }

  try {
    await window.electronAPI.setAutoRecord(autoRecord);
    setBackendMessage(`Auto-record ${autoRecord ? 'enabled' : 'disabled'}`);
  } catch (error) {
    setBackendMessage(error.message || 'Failed to update auto-record', true);
  }
}

function applyDetectionState(data) {
  setDetectionCard('detectMic', !!data.mic, 'Mic Active');
  setDetectionCard('detectMeet', !!data.meet, 'Google Meet');
  setDetectionCard('detectWhatsApp', !!data.whatsapp, 'WhatsApp');

  if (typeof data.autoRecord === 'boolean' && data.autoRecord !== autoRecord) {
    autoRecord = data.autoRecord;
    const button = el('autoToggle');
    button.textContent = autoRecord ? 'Enabled' : 'Disabled';
    button.className = `mt-2 inline-flex items-center px-3 py-2 rounded-lg border text-sm transition ${autoRecord ? 'border-ok bg-emerald-900/30 text-emerald-300' : 'border-line bg-slate-800 text-slate-300 hover:bg-slate-700'}`;
  }

  if (typeof data.recording === 'boolean') {
    syncRecordingState(data.recording);
  }
}

function updateToggle(id, enabled) {
  const btn = el(id);
  if (enabled) {
    btn.className = 'w-10 h-5 rounded-full bg-emerald-600 relative transition';
    btn.innerHTML = '<span class="absolute right-0.5 top-0.5 w-4 h-4 rounded-full bg-white transition"></span>';
  } else {
    btn.className = 'w-10 h-5 rounded-full bg-slate-700 relative transition';
    btn.innerHTML = '<span class="absolute left-0.5 top-0.5 w-4 h-4 rounded-full bg-slate-400 transition"></span>';
  }
}

function toggleIntegration(name) {
  integrations[name].enabled = !integrations[name].enabled;
  updateToggle(`${name}Toggle`, integrations[name].enabled);
  setIntegrationStatus('Unsaved changes');
}

function updateNotionConnectionInfo() {
  const target = el('notionConnectionInfo');
  if (!target) return;

  if (!integrations.notion.accessToken) {
    target.textContent = 'Not connected';
    target.className = 'mt-2 text-xs text-amber-300';
    return;
  }

  const workspaceLabel = integrations.notion.workspaceName || integrations.notion.workspaceId || 'Connected workspace';
  target.textContent = `Connected: ${workspaceLabel}`;
  target.className = 'mt-2 text-xs text-emerald-300';
}

function collectIntegrationSettings() {
  return {
    notion: {
      enabled: integrations.notion.enabled,
      accessToken: integrations.notion.accessToken,
      workspaceId: integrations.notion.workspaceId,
      parentPageId: el('notionParentPageId').value.trim(),
    },
    gemini: { enabled: integrations.gemini.enabled, apiKey: el('geminiKey').value.trim() },
    whisper: { mode: el('whisperMode').value, apiKey: el('whisperKey').value.trim() }
  };
}

async function saveIntegrations() {
  const settings = collectIntegrationSettings();

  if (!window.electronAPI) {
    setIntegrationStatus('Electron bridge not available', true);
    return false;
  }

  try {
    const ok = await window.electronAPI.saveIntegrations(settings);
    if (!ok) {
      throw new Error('Backend save returned false');
    }
    setIntegrationStatus('Integration settings saved to database');
    return true;
  } catch (e) {
    setIntegrationStatus(`Save failed: ${e.message || 'Unknown error'}`, true);
    return false;
  }
}

async function connectNotionOAuth() {
  if (!window.electronAPI) {
    setIntegrationStatus('Electron bridge not available', true);
    return;
  }

  const clientId = el('notionClientId').value.trim();
  const clientSecret = el('notionClientSecret').value.trim();
  const parentPageId = el('notionParentPageId').value.trim();

  if (!clientId || !clientSecret) {
    setIntegrationStatus('Enter Notion OAuth client ID and client secret', true);
    return;
  }

  setIntegrationStatus('Opening Notion authorization in browser...');
  const response = await window.electronAPI.connectNotionOAuth({
    clientId,
    clientSecret,
    parentPageId,
  });

  if (!response || response.error) {
    setIntegrationStatus(response?.error || 'Failed to connect Notion OAuth', true);
    return;
  }

  integrations.notion.accessToken = response.accessToken || '';
  integrations.notion.workspaceName = response.workspaceName || '';
  integrations.notion.workspaceId = response.workspaceId || '';
  if (response.parentPageId) {
    integrations.notion.parentPageId = response.parentPageId;
    el('notionParentPageId').value = response.parentPageId;
  }
  integrations.notion.enabled = true;
  updateToggle('notionToggle', true);
  updateNotionConnectionInfo();
  setIntegrationStatus('Notion connected. Click Save Integrations to persist enable/disable state.');
}

async function loadIntegrations() {
  if (!window.electronAPI) return;

  try {
    const settings = await window.electronAPI.loadIntegrations();
    if (!settings) return;

    const hasNested = settings.notion || settings.gemini || settings.whisper;

    if (hasNested) {
      integrations.notion.enabled = !!settings.notion?.enabled;
      integrations.gemini.enabled = !!settings.gemini?.enabled;
      integrations.whisper.mode = settings.whisper?.mode || 'local';
      integrations.notion.accessToken = settings.notion?.accessToken || '';
      integrations.notion.workspaceId = settings.notion?.workspaceId || '';
      integrations.notion.workspaceName = settings.notion?.workspaceName || '';
      integrations.notion.parentPageId = settings.notion?.parentPageId || '';

      el('notionParentPageId').value = settings.notion?.parentPageId || '';
      el('geminiKey').value = settings.gemini?.apiKey || '';
      el('whisperMode').value = settings.whisper?.mode || 'local';
      el('whisperKey').value = settings.whisper?.apiKey || '';
    } else {
      integrations.notion.enabled = Boolean(Number(settings.notion_enabled || 0));
      integrations.gemini.enabled = Boolean(Number(settings.gemini_enabled || 0));
      integrations.whisper.mode = settings.whisper_mode || 'local';
      integrations.notion.accessToken = settings.notion_api_key || '';
      integrations.notion.workspaceId = settings.notion_id || '';
      integrations.notion.parentPageId = settings.notion_parent_page_id || '';

      el('notionParentPageId').value = settings.notion_parent_page_id || '';
      el('geminiKey').value = settings.gemini_api_key || '';
      el('whisperMode').value = settings.whisper_mode || 'local';
      el('whisperKey').value = settings.whisper_api_key || '';
    }

    updateToggle('notionToggle', integrations.notion.enabled);
    updateToggle('geminiToggle', integrations.gemini.enabled);
    updateNotionConnectionInfo();
    setIntegrationStatus('Loaded saved integration settings');
  } catch (e) {
    setIntegrationStatus(`Could not load settings: ${e.message || 'Unknown error'}`, true);
  }
}

function setActivePage(page) {
  activePage = page;

  const pages = {
    recording: el('pageRecording'),
    integrations: el('pageIntegrations'),
    ai: el('pageAI')
  };

  const nav = {
    recording: el('navRecording'),
    integrations: el('navIntegrations'),
    ai: el('navAI')
  };

  Object.entries(pages).forEach(([key, node]) => {
    node.classList.toggle('hidden', key !== activePage);
  });

  Object.entries(nav).forEach(([key, node]) => {
    if (key === activePage) {
      node.className = 'w-full text-left px-3 py-2 rounded-lg text-sm border border-line bg-slate-800/80 text-slate-100';
    } else {
      node.className = 'w-full text-left px-3 py-2 rounded-lg text-sm border border-line bg-transparent text-slate-300 hover:bg-slate-800/60 transition';
    }
  });
}

async function loadRecordings() {
  if (!window.electronAPI) return;

  try {
    const recordings = await window.electronAPI.getRecordings(20);
    const list = el('recordingsList');

    if (!recordings || recordings.length === 0) {
      list.innerHTML = '<p class="text-sm text-slate-400">No recordings yet</p>';
      return;
    }

    list.innerHTML = recordings.map((rec) => `
      <div class="flex items-center justify-between px-3 py-2 rounded-lg border border-line bg-ink/40">
        <div>
          <p class="text-sm font-medium">${rec.filename || 'Recording'}</p>
          <p class="text-xs text-slate-400">${new Date(rec.created_at).toLocaleString()}</p>
        </div>
        <span class="text-xs text-slate-400">${rec.duration_seconds || 0}s</span>
      </div>
    `).join('');
  } catch (e) {
    console.log('Could not load recordings:', e);
  }
}

function addChatMessage(role, content) {
  const container = el('chatMessages');
  const div = document.createElement('div');
  div.className = role === 'user' ? 'text-slate-200' : 'text-slate-400';
  div.textContent = `${role === 'user' ? 'You' : 'Assistant'}: ${content}`;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

async function sendChatMessage() {
  const input = el('chatInput');
  const message = input.value.trim();
  if (!message) return;

  addChatMessage('user', message);
  input.value = '';

  if (!window.electronAPI) {
    addChatMessage('assistant', 'Electron bridge not available');
    return;
  }

  try {
    const response = await window.electronAPI.chatWithGemini({ message });
    if (response && response.response) {
      addChatMessage('assistant', response.response);
    } else {
      addChatMessage('assistant', response?.error || 'Failed to get response');
    }
  } catch (e) {
    addChatMessage('assistant', `Error: ${e.message || 'Unknown error'}`);
  }
}

async function processRecording(recordingId, audioPath, notionParentPageId = null) {
  if (!window.electronAPI) return null;

  try {
    const result = await window.electronAPI.processRecording({
      recordingId,
      audioPath,
      notionParentPageId,
    });
    return result;
  } catch (e) {
    console.error('Failed to process recording:', e);
    return null;
  }
}

async function initializeRenderer() {
  el('recordBtn').addEventListener('click', toggleRecording);
  el('autoToggle').addEventListener('click', toggleAutoRecord);
  el('chooseOutputDirBtn').addEventListener('click', chooseOutputDirectory);
  el('openOutputDirBtn').addEventListener('click', openOutputDirectory);

  el('navRecording').addEventListener('click', () => setActivePage('recording'));
  el('navIntegrations').addEventListener('click', () => setActivePage('integrations'));
  el('navAI').addEventListener('click', () => setActivePage('ai'));

  el('notionToggle').addEventListener('click', () => toggleIntegration('notion'));
  el('geminiToggle').addEventListener('click', () => toggleIntegration('gemini'));
  el('notionConnectBtn').addEventListener('click', connectNotionOAuth);
  el('saveIntegrationsBtn').addEventListener('click', saveIntegrations);

  el('whisperMode').addEventListener('change', () => setIntegrationStatus('Unsaved changes'));
  el('notionClientId').addEventListener('input', () => setIntegrationStatus('Unsaved changes'));
  el('notionClientSecret').addEventListener('input', () => setIntegrationStatus('Unsaved changes'));
  el('notionParentPageId').addEventListener('input', () => setIntegrationStatus('Unsaved changes'));
  el('geminiKey').addEventListener('input', () => setIntegrationStatus('Unsaved changes'));
  el('whisperKey').addEventListener('input', () => setIntegrationStatus('Unsaved changes'));

  el('chatSend').addEventListener('click', sendChatMessage);
  el('chatInput').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') sendChatMessage();
  });

  setActivePage('recording');
  updateStatusUI();

  await loadIntegrations();
  await loadRecordings();

  if (!window.electronAPI) {
    setBackendMessage('Running in preview mode');
    populateSelect('micSelect', ['Microphone (Preview)']);
    populateSelect('stereoSelect', ['Stereo Mix (Preview)']);
    return;
  }

  window.electronAPI.onDetectionUpdate((state) => {
    applyDetectionState(state || {});
  });

  window.electronAPI.onBackendStatus((status) => {
    if (status && status.message) {
      setBackendMessage(status.message, status.level === 'error');
    }
    if (status && status.savedRecording) {
      loadRecordings();
    }
  });

  window.electronAPI.onBackendError((status) => {
    setBackendMessage((status && status.message) || 'Unknown backend error', true);
  });

  window.electronAPI.onTranscriptUpdate((payload) => {
    updateLiveTranscript(payload || {});
  });

  try {
    const devices = await window.electronAPI.getAudioDevices();
    console.log('Audio devices loaded:', devices);
    console.log('Microphones:', devices.mics);
    populateSelect('micSelect', devices.mics || []);
    populateSelect('stereoSelect', devices.stereos || []);
    setBackendMessage('Connected');
  } catch (error) {
    setBackendMessage(error.message || 'Failed to load devices', true);
  }

  await initializeOutputDirectory();
}

document.addEventListener('DOMContentLoaded', initializeRenderer);

const whisperMode = document.getElementById("whisperMode");
const whisperKey = document.getElementById("whisperKey");
const whisperUrl = document.getElementById("whisperUrl");

function updateWhisperInputs() {
  if (whisperMode.value === "local") {
    whisperUrl.classList.remove("hidden");
    whisperKey.classList.add("hidden");
  } else {
    whisperKey.classList.remove("hidden");
    whisperUrl.classList.add("hidden");
  }
}

whisperMode.addEventListener("change", updateWhisperInputs);

// run once on load
updateWhisperInputs();
