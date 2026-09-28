import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from typing import Dict, List

DETECTION_IMPORT_ERROR = None
RECORDING_IMPORT_ERROR = None

try:
    from detectors.meeting_detector import check_active_calls
except Exception as exc:
    DETECTION_IMPORT_ERROR = str(exc)

    def check_active_calls():
        return False, False, False

try:
    from obs.controller import start_recording, stop_recording
    import obs.controller as obs_controller
except Exception as exc:
    RECORDING_IMPORT_ERROR = str(exc)
    obs_controller = None

    def start_recording(devices=None):
        raise RuntimeError(f"Recording backend unavailable: {RECORDING_IMPORT_ERROR}")

    def stop_recording():
        raise RuntimeError(f"Recording backend unavailable: {RECORDING_IMPORT_ERROR}")

IS_WINDOWS = sys.platform == "win32"
DEFAULT_MIC = 'Microphone (Audio Array AM-C1 Device)' if IS_WINDOWS else 'default'
DEFAULT_STEREO = 'Stereo Mix (Realtek(R) Audio)' if IS_WINDOWS else 'default.monitor'

parser = argparse.ArgumentParser()
parser.add_argument('--ffmpeg', default='ffmpeg', help='Path to ffmpeg executable')
parser.add_argument('--mic', default=DEFAULT_MIC)
parser.add_argument('--stereo', default=DEFAULT_STEREO)
args = parser.parse_args()

# Sync ffmpeg path to obs.controller if available
if obs_controller is not None:
    try:
        obs_controller.FFMPEG_PATH = args.ffmpeg
    except Exception:
        pass

state_lock = threading.Lock()
state = {
    'recording': False,
    'auto_record': True,
    'mic': False,
    'meet': False,
    'whatsapp': False,
    'call': False,
}

# Keep selected devices for auto-record
selected_devices = {
    'mic': args.mic,
    'stereo': args.stereo,
}

# On Linux, resolve default.monitor to a real .monitor if needed
if not IS_WINDOWS and obs_controller is not None:
    try:
        _devs = obs_controller.get_audio_devices()
        _real_stereos = [s for s in _devs.get('stereos', []) if '.monitor' in s]
        if _real_stereos:
            if selected_devices['stereo'] == DEFAULT_STEREO or selected_devices['stereo'] not in _devs.get('stereos', []):
                selected_devices['stereo'] = _real_stereos[0]
            if selected_devices['mic'] not in _devs.get('mics', []):
                # keep mic as is if default
                pass
    except Exception:
        pass
    # update env after resolution
    os.environ['MIC_DEVICE'] = selected_devices['mic']
    os.environ['STEREO_DEVICE'] = selected_devices['stereo']
else:
    os.environ['MIC_DEVICE'] = selected_devices['mic']
    os.environ['STEREO_DEVICE'] = selected_devices['stereo']

os.environ['FFMPEG_PATH'] = args.ffmpeg

running = True


def emit(message_type: str, data: Dict):
    payload = {'type': message_type, 'data': data}
    sys.stdout.write(json.dumps(payload) + '\n')
    sys.stdout.flush()


def emit_response(request_id: str, ok: bool, data=None, error: str = None):
    payload = {'type': 'response', 'requestId': request_id, 'ok': ok}
    if data is not None:
        payload['data'] = data
    if error:
        payload['error'] = error
    sys.stdout.write(json.dumps(payload) + '\n')
    sys.stdout.flush()


def update_audio_devices(devices: Dict):
    mic = devices.get('mic') if isinstance(devices, dict) else None
    stereo = devices.get('stereo') if isinstance(devices, dict) else None

    if mic:
        os.environ['MIC_DEVICE'] = mic
        selected_devices['mic'] = mic
    if stereo:
        os.environ['STEREO_DEVICE'] = stereo
        selected_devices['stereo'] = stereo


def list_audio_devices(ffmpeg_path: str) -> Dict[str, List[str]]:
    default_mic = os.environ.get('MIC_DEVICE', args.mic)
    default_stereo = os.environ.get('STEREO_DEVICE', args.stereo)

    # Prefer obs.controller enumeration (handles Windows + Linux)
    if obs_controller is not None:
        try:
            # sync ffmpeg path
            obs_controller.FFMPEG_PATH = ffmpeg_path
            data = obs_controller.get_audio_devices()
            # Ensure defaults are present (but don't insert invalid default.monitor on Linux)
            if default_mic not in data.get('mics', []):
                data.setdefault('mics', []).insert(0, default_mic)
            if default_stereo not in data.get('stereos', []):
                if not (not IS_WINDOWS and default_stereo == 'default.monitor' and data.get('stereos')):
                    data.setdefault('stereos', []).insert(0, default_stereo)
            return data
        except Exception:
            pass

    if sys.platform != 'win32':
        return {'mics': [default_mic], 'stereos': [default_stereo]}

    cmd = [ffmpeg_path, '-hide_banner', '-list_devices', 'true', '-f', 'dshow', '-i', 'dummy']
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )
        combined = f"{proc.stdout}\n{proc.stderr}"
        names = []
        for line in combined.splitlines():
            if '(audio)' not in line.lower():
                continue
            match = re.search(r'"([^"]+)"', line)
            if match:
                names.append(match.group(1).strip())

        # Preserve order while deduplicating.
        seen = set()
        unique = []
        for name in names:
            if name and name not in seen:
                seen.add(name)
                unique.append(name)

        mics = [n for n in unique if 'stereo mix' not in n.lower()]
        stereos = [n for n in unique if 'stereo mix' in n.lower()]

        if not mics and unique:
            mics = unique[:]
        if not stereos:
            stereos = [default_stereo]

        if default_mic not in mics:
            mics.insert(0, default_mic)
        if default_stereo not in stereos:
            stereos.insert(0, default_stereo)

        return {'mics': mics, 'stereos': stereos}
    except Exception:
        return {'mics': [default_mic], 'stereos': [default_stereo]}


def start_if_needed(trigger: str):
    with state_lock:
        if state['recording']:
            return
        devices = dict(selected_devices)
    # obs.controller.start_recording now expects dict; support both signatures
    try:
        start_recording(devices)
    except TypeError:
        # legacy no-arg signature
        start_recording()
    with state_lock:
        state['recording'] = True
    emit('status', {'message': f'Recording started ({trigger})', 'level': 'info'})


def stop_if_needed(trigger: str):
    with state_lock:
        if not state['recording']:
            return
    stop_recording()
    with state_lock:
        state['recording'] = False
    emit('status', {'message': f'Recording stopped ({trigger})', 'level': 'info'})


def detection_loop():
    last_snapshot = None

    while running:
        try:
            mic_active, meet_active, whatsapp_active = check_active_calls()

            with state_lock:
                state['mic'] = bool(mic_active)
                state['meet'] = bool(meet_active)
                state['whatsapp'] = bool(whatsapp_active)
                state['call'] = bool(meet_active or whatsapp_active)

                snapshot = {
                    'mic': state['mic'],
                    'meet': state['meet'],
                    'whatsapp': state['whatsapp'],
                    'recording': state['recording'],
                    'autoRecord': state['auto_record'],
                    'call': state['call'],
                }
                auto_record = state['auto_record']
                should_start = state['call'] and not state['recording']
                should_stop = (not state['call']) and state['recording']

            if auto_record and should_start:
                trigger = 'Google Meet' if meet_active else 'WhatsApp'
                start_if_needed(f'auto: {trigger}')
            if auto_record and should_stop:
                stop_if_needed('auto: no active call')

            with state_lock:
                snapshot['recording'] = state['recording']

            if snapshot != last_snapshot:
                emit('detection', snapshot)
                last_snapshot = snapshot

        except Exception as exc:
            emit('error', {'message': f'Detection loop error: {exc}'})

        time.sleep(3)


def command_loop():
    global running

    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue

        request_id = None
        try:
            message = json.loads(line)
            request_id = str(message.get('requestId', ''))
            action = message.get('action')

            if action == 'start_recording':
                update_audio_devices(message.get('devices') or {})
                start_if_needed('manual')
                emit_response(request_id, True)
                continue

            if action == 'stop_recording':
                stop_if_needed('manual')
                emit_response(request_id, True)
                continue

            if action == 'set_auto_record':
                enabled = bool(message.get('enabled', True))
                with state_lock:
                    state['auto_record'] = enabled
                    snapshot = {
                        'mic': state['mic'],
                        'meet': state['meet'],
                        'whatsapp': state['whatsapp'],
                        'recording': state['recording'],
                        'autoRecord': state['auto_record'],
                        'call': state['call'],
                    }
                emit('detection', snapshot)
                emit_response(request_id, True)
                continue

            if action == 'get_audio_devices':
                devices = list_audio_devices(args.ffmpeg)
                emit_response(request_id, True, devices)
                continue

            emit_response(request_id, False, error=f'Unknown action: {action}')
        except Exception as exc:
            emit_response(request_id or '', False, error=str(exc))

    running = False


def main():
    emit('status', {'message': 'Python monitoring started', 'level': 'info'})
    if DETECTION_IMPORT_ERROR:
        emit('error', {'message': f'Detector import error: {DETECTION_IMPORT_ERROR}'})
    if RECORDING_IMPORT_ERROR:
        emit('error', {'message': f'Recording import error: {RECORDING_IMPORT_ERROR}'})

    thread = threading.Thread(target=detection_loop, daemon=True)
    thread.start()

    command_loop()

    # stdin closed, shut down gracefully
    try:
        stop_if_needed('shutdown')
    except Exception:
        pass


if __name__ == '__main__':
    main()
