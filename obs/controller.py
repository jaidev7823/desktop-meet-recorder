import subprocess
import os
import sys
import json
import re
from datetime import datetime

ffmpeg_process = None
stopping = False
current_output_file = None
current_segment_dir = None

FFMPEG_PATH = "ffmpeg"
OUTPUT_DIR = os.getcwd()


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

def get_audio_devices():
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

                # ignore internal device IDs
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


def start_recording(devices):
    global ffmpeg_process, current_output_file, current_segment_dir

    mic = devices.get("mic")
    stereo = devices.get("stereo")

    if not mic or not stereo:
        raise RuntimeError("Invalid audio devices")

    ffmpeg = get_ffmpeg_path()

    output_file = _build_output_file()
    segment_dir = _build_segment_dir(output_file)
    segment_pattern = os.path.join(segment_dir, "chunk_%05d.wav")

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
        "[1:a][2:a]amix=inputs=2:duration=longest[aout]",

        "-map", "0:v",
        "-map", "[aout]",

        "-vcodec", "libx264",
        "-preset", "ultrafast",
        "-crf", "23",

        "-acodec", "aac",

        "-y",
        output_file,

        "-map", "[aout]",
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-c:a", "pcm_s16le",
        "-f", "segment",
        "-segment_time", "20",
        segment_pattern
    ]

    ffmpeg_process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

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
        ffmpeg_process.wait()
    except:
        ffmpeg_process.kill()

    ffmpeg_process = None

    return {
        "filepath": current_output_file,
        "filename": os.path.basename(current_output_file),
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
            data = start_recording(devices)
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