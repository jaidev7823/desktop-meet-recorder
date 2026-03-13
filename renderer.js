let recording = false;
let autoRecord = true;
let timerInterval = null;
let elapsedSeconds = 0;

function el(id) {
  return document.getElementById(id);
}

function setBackendMessage(message, isError = false) {
  const target = el('backendMessage');
  target.textContent = `Backend: ${message}`;
  target.className = `text-sm font-mono ${isError ? 'text-red-400' : 'text-slate-400'}`;
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
  titleDot.className = `w-3 h-3 rounded-full ${recording ? 'bg-ok' : 'bg-slate-500'}`;

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
    startTimer();
  } else {
    stopTimer();
  }
  updateStatusUI();
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
}

async function toggleRecording() {
  if (!window.electronAPI) {
    setBackendMessage('Electron bridge not found', true);
    return;
  }

  const mic = el('micSelect').value;
  const stereo = el('stereoSelect').value;

  try {
    if (!recording) {
      await window.electronAPI.startRecording({ mic, stereo });
      syncRecordingState(true);
      setBackendMessage('Manual recording started');
    } else {
      await window.electronAPI.stopRecording();
      syncRecordingState(false);
      setBackendMessage('Manual recording stopped');
    }
  } catch (error) {
    setBackendMessage(error.message || 'Failed to change recording state', true);
  }
}

async function toggleAutoRecord() {
  autoRecord = !autoRecord;
  const button = el('autoToggle');
  button.textContent = autoRecord ? 'Enabled' : 'Disabled';
  button.className = `mt-3 inline-flex items-center px-3 py-2 rounded-lg border text-sm transition ${autoRecord ? 'border-ok bg-emerald-900/30 text-emerald-300' : 'border-line bg-slate-800 text-slate-300 hover:bg-slate-700'}`;

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
    button.className = `mt-3 inline-flex items-center px-3 py-2 rounded-lg border text-sm transition ${autoRecord ? 'border-ok bg-emerald-900/30 text-emerald-300' : 'border-line bg-slate-800 text-slate-300 hover:bg-slate-700'}`;
  }

  if (typeof data.recording === 'boolean') {
    syncRecordingState(data.recording);
  }
}

async function initializeRenderer() {
  el('recordBtn').addEventListener('click', toggleRecording);
  el('autoToggle').addEventListener('click', toggleAutoRecord);

  updateStatusUI();

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
  });

  window.electronAPI.onBackendError((status) => {
    setBackendMessage((status && status.message) || 'Unknown backend error', true);
  });

  try {
    const devices = await window.electronAPI.getAudioDevices();
    populateSelect('micSelect', devices.mics || []);
    populateSelect('stereoSelect', devices.stereos || []);
    setBackendMessage('Connected');
  } catch (error) {
    setBackendMessage(error.message || 'Failed to load devices', true);
  }
}

document.addEventListener('DOMContentLoaded', initializeRenderer);
