import subprocess
import os
import sys
import json
import re
import shutil
from datetime import datetime

ffmpeg_process = None
stopping = False
current_output_file = None
current_segment_dir = None

FFMPEG_PATH = "ffmpeg"
OUTPUT_DIR = os.getcwd()

IS_WINDOWS = sys.platform == "win32"


# -----------------------------
# Utility
# -----------------------------

def send_response(request_id, ok=True, data=None, error=None):
    message = {
        "type": "response",
        "requestId": request_id,
        "ok": ok,
        "data": data,
        "error": error
    }
    print(json.dumps(message), flush=True)


def get_ffmpeg_path():
    return FFMPEG_PATH


def get_output_directory():
    return OUTPUT_DIR


def set_output_directory(path):
    global OUTPUT_DIR
    OUTPUT_DIR = os.path.abspath(path)
    os.makedirs(OUTPUT_DIR, exist_ok=True)


# -----------------------------
# Audio Device Detection
# -----------------------------

def _get_audio_devices_windows():
    try:
        result = subprocess.run(
            [FFMPEG_PATH, "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore"
        )
        lines = result.stderr.splitlines()
        devices = []
        for line in lines:
            match = re.search(r'"(.*?)"', line)
            if match:
                name = match.group(1)
                if name.startswith("@device"):
                    continue
                devices.append(name)
        microphones = []
        speakers = []
        for d in devices:
            lower = d.lower()
            if (
                "stereo mix" in lower
                or "what u hear" in lower
                or "loopback" in lower
            ):
                speakers.append(d)
            else:
                microphones.append(d)
        return {
            "mics": microphones,
            "stereos": speakers
        }
    except Exception as e:
        return {
            "mics": [],
            "stereos": [],
            "error": str(e)
        }


def _get_audio_devices_linux():
    mics = []
    stereos = []
    try:
        # Primary: pactl list short sources (PipeWire/Pulse)
        result = subprocess.run(
            ["pactl", "list", "short", "sources"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    name = parts[1]
                    lower = name.lower()
                    if ".monitor" in lower:
                        stereos.append(name)
                    else:
                        mics.append(name)
        # Fallback: arecord -l
        if not mics and shutil.which("arecord"):
            result2 = subprocess.run(
                ["arecord", "-l"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result2.returncode == 0:
                # Parse card/device lines
                for line in result2.stdout.splitlines():
                    if "card" in line.lower():
                        # e.g. card 0: Device [Audio Array...], device 0: USB Audio [USB Audio]
                        m = re.search(r"card\s+\d+:\s*([^\[]+)\[([^\]]+)\]", line)
                        if m:
                            mics.append(m.group(2).strip())
        # Ensure defaults
        if not mics:
            mics = ["default"]
        else:
            if "default" not in mics:
                mics.insert(0, "default")
        if not stereos:
            # Try to derive monitor from default sink
            try:
                info = subprocess.run(["pactl", "get-default-sink"], capture_output=True, text=True, timeout=3)
                if info.returncode == 0 and info.stdout.strip():
                    stereos = [info.stdout.strip() + ".monitor"]
                else:
                    info2 = subprocess.run(["pactl", "info"], capture_output=True, text=True, timeout=3)
                    m = re.search(r"Default Sink:\s*(\S+)", info2.stdout or "")
                    if m:
                        stereos = [m.group(1) + ".monitor"]
            except Exception:
                pass
            if not stereos:
                # fallback: use first available monitor name if any, else default
                stereos = ["default"]
        # Don't force default.monitor as first; keep real monitors first for validity
        # Ensure default is available as fallback last
        if "default" not in mics:
            # mics already has default at front, ok
            pass

        return {"mics": mics, "stereos": stereos}
    except Exception as e:
        return {"mics": ["default"], "stereos": ["default.monitor"], "error": str(e)}


def get_audio_devices():
    if IS_WINDOWS:
        return _get_audio_devices_windows()
    else:
        return _get_audio_devices_linux()


# -----------------------------
# Recording
# -----------------------------

def _build_output_file():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(OUTPUT_DIR, f"recording_{timestamp}.mp4")


def _build_segment_dir(output_file):
    base = os.path.splitext(os.path.basename(output_file))[0]
    path = os.path.join(OUTPUT_DIR, f"{base}_stt")
    os.makedirs(path, exist_ok=True)
    return path


def _get_linux_display():
    # Use DISPLAY env or fallback :0.0, works with XWayland on Wayland
    disp = os.environ.get("DISPLAY", ":0.0")
    # Validate ffmpeg can use it; if Wayland without XWayland, fallback to :0
    return disp


def start_recording(devices=None):
    global ffmpeg_process, current_output_file, current_segment_dir

    if devices is None:
        devices = {}

    mic = devices.get("mic")
    stereo = devices.get("stereo")

    # Allow defaults on Linux, require both on Windows
    if IS_WINDOWS:
        if not mic or not stereo:
            raise RuntimeError("Invalid audio devices (Windows requires mic and stereo)")
    else:
        if not mic:
            mic = "default"
        if not stereo:
            # Try to auto-detect monitor - prefer real .monitor
            audio = get_audio_devices()
            stereos = audio.get("stereos") or []
            stereo = None
            for s in stereos:
                if ".monitor" in s:
                    stereo = s
                    break
            if not stereo:
                stereo = stereos[0] if stereos else "default"

    ffmpeg = get_ffmpeg_path()
    output_file = _build_output_file()
    segment_dir = _build_segment_dir(output_file)
    segment_pattern = os.path.join(segment_dir, "chunk_%05d.wav")

    if IS_WINDOWS:
        cmd = [
            ffmpeg,
            "-f", "gdigrab",
            "-framerate", "30",
            "-i", "desktop",
            "-f", "dshow",
            "-i", f"audio={mic}",
            "-f", "dshow",
            "-i", f"audio={stereo}",
            "-filter_complex",
            "[1:a][2:a]amix=inputs=2:duration=longest, asplit=2 [aout1][aout2]",
            "-map", "0:v",
            "-map", "[aout1]",
            "-vcodec", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            "-acodec", "aac",
            "-y",
            output_file,
            "-map", "[aout2]",
            "-vn",
            "-ac", "1",
            "-ar", "16000",
            "-c:a", "pcm_s16le",
            "-f", "segment",
            "-segment_time", "20",
            segment_pattern
        ]
    else:
        display = _get_linux_display()
        # Linux: x11grab (XWayland) + pulse for mic + pulse for system monitor
        # Use pulse sources; if unavailable fallback to alsa
        cmd = [
            ffmpeg,
            "-f", "x11grab",
            "-framerate", "30",
            "-i", display,
            "-f", "pulse",
            "-i", mic,
            "-f", "pulse",
            "-i", stereo,
            "-filter_complex",
            "[1:a][2:a]amix=inputs=2:duration=longest, asplit=2 [aout1][aout2]",
            "-map", "0:v",
            "-map", "[aout1]",
            "-vcodec", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            "-acodec", "aac",
            "-y",
            output_file,
            "-map", "[aout2]",
            "-vn",
            "-ac", "1",
            "-ar", "16000",
            "-c:a", "pcm_s16le",
            "-f", "segment",
            "-segment_time", "20",
            segment_pattern
        ]

    # On Windows need CREATE_NEW_PROCESS_GROUP, on Linux no
    popen_kwargs = {
        "stdin": subprocess.PIPE,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if IS_WINDOWS:
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    ffmpeg_process = subprocess.Popen(cmd, **popen_kwargs)

    current_output_file = output_file
    current_segment_dir = segment_dir

    return {
        "filepath": output_file,
        "filename": os.path.basename(output_file),
        "segment_dir": segment_dir
    }


def stop_recording():
    global ffmpeg_process

    if not ffmpeg_process:
        return None

    try:
        ffmpeg_process.stdin.write(b"q\n")
        ffmpeg_process.stdin.flush()
        ffmpeg_process.wait(timeout=15)
    except Exception:
        try:
            ffmpeg_process.kill()
            ffmpeg_process.wait(timeout=5)
        except Exception:
            pass

    ffmpeg_process = None

    return {
        "filepath": current_output_file,
        "filename": os.path.basename(current_output_file) if current_output_file else None,
        "segment_dir": current_segment_dir
    }


# -----------------------------
# Electron IPC Loop
# -----------------------------

def handle_request(msg):
    action = msg.get("action")
    request_id = msg.get("requestId")

    try:

        if action == "get_audio_devices":
            data = get_audio_devices()
            send_response(request_id, True, data)

        elif action == "start_recording":
            devices = msg.get("devices", {})
            # support both {mic,stereo} and {mic_device,stereo_device} etc.
            if not isinstance(devices, dict):
                devices = {}
            # Normalize keys
            normalized = {
                "mic": devices.get("mic") or devices.get("mic_device") or devices.get("microphone"),
                "stereo": devices.get("stereo") or devices.get("stereo_device") or devices.get("speakers"),
            }
            data = start_recording(normalized)
            send_response(request_id, True, data)

        elif action == "stop_recording":
            data = stop_recording()
            send_response(request_id, True, data)

        elif action == "set_output_directory":
            set_output_directory(msg.get("outputDir"))
            send_response(request_id, True, {"outputDir": OUTPUT_DIR})

        elif action == "get_output_directory":
            send_response(request_id, True, {"outputDir": OUTPUT_DIR})

        else:
            send_response(request_id, False, error=f"Unknown action: {action}")

    except Exception as e:
        send_response(request_id, False, error=str(e))


# -----------------------------
# Startup
# -----------------------------

def parse_args():
    global FFMPEG_PATH, OUTPUT_DIR

    args = sys.argv

    if "--ffmpeg" in args:
        FFMPEG_PATH = args[args.index("--ffmpeg") + 1]

    if "--output-dir" in args:
        OUTPUT_DIR = args[args.index("--output-dir") + 1]


def main():
    parse_args()

    for line in sys.stdin:
        try:
            msg = json.loads(line)
            handle_request(msg)
        except Exception as e:
            print(json.dumps({
                "type": "error",
                "data": {"message": str(e)}
            }), flush=True)


if __name__ == "__main__":
    main()
