import subprocess
import os
import sys
from datetime import datetime

ffmpeg_process = None
stopping = False
current_output_file = None

def _tail_ffmpeg_log(max_lines: int = 12):
    try:
        with open("ffmpeg_log.txt", "r", encoding="utf-8", errors="ignore") as f:
            lines = [line.strip() for line in f.readlines() if line.strip()]
        if not lines:
            return ""
        return " | ".join(lines[-max_lines:])
    except Exception:
        return ""

def get_ffmpeg_path():
    # Will be overridden by Electron passing --ffmpeg argument
    return os.environ.get("FFMPEG_PATH", "ffmpeg")

def get_audio_devices():
    mic = os.environ.get("MIC_DEVICE", "Microphone (Audio Array AM-C1 Device)")
    stereo = os.environ.get("STEREO_DEVICE", "Stereo Mix (Realtek(R) Audio)")
    return mic, stereo

def get_output_directory():
    output_dir = os.environ.get("OUTPUT_DIR", "").strip()
    if output_dir:
        return os.path.abspath(output_dir)
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

def set_output_directory(output_dir: str):
    if not output_dir:
        return
    os.environ["OUTPUT_DIR"] = os.path.abspath(output_dir)

def _build_output_file():
    output_dir = get_output_directory()
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"recording_{timestamp}.mp4"
    return os.path.join(output_dir, filename)

def start_recording():
    global ffmpeg_process, stopping, current_output_file
    stopping = False

    mic, stereo = get_audio_devices()
    ffmpeg = get_ffmpeg_path()
    output_file = _build_output_file()
    current_output_file = output_file

    cmd = [
        ffmpeg,
        "-f", "gdigrab",
        "-framerate", "30",
        "-thread_queue_size", "512",
        "-i", "desktop",
        "-f", "dshow",
        "-thread_queue_size", "512",
        "-i", f"audio={mic}",
        "-f", "dshow",
        "-thread_queue_size", "512",
        "-i", f"audio={stereo}",
        "-filter_complex", "[1:a]volume=1.0[mic];[2:a]volume=3.0[sys];[mic][sys]amix=inputs=2:duration=longest:normalize=0",
        "-vcodec", "libx264",
        "-preset", "ultrafast",
        "-crf", "23",
        "-acodec", "aac",
        "-vsync", "1",
        "-async", "1",
        "-y",
        output_file
    ]

    print(f"Starting FFmpeg recording -> {output_file}")
    ffmpeg_process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=open("ffmpeg_log.txt", "w"),
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
    )

    import time
    time.sleep(2)
    if ffmpeg_process.poll() is not None:
        detail = _tail_ffmpeg_log()
        print("FFmpeg failed to start! Check ffmpeg_log.txt")
        ffmpeg_process = None
        current_output_file = None
        if detail:
            raise RuntimeError(f"FFmpeg failed to start: {detail}")
        raise RuntimeError("FFmpeg failed to start")
    return output_file

def stop_recording():
    global ffmpeg_process, stopping, current_output_file
    if stopping or not ffmpeg_process:
        return None
    stopping = True
    print("Stopping FFmpeg recording...")
    try:
        ffmpeg_process.stdin.write(b'q\n')
        ffmpeg_process.stdin.flush()
        ffmpeg_process.stdin.close()
        ffmpeg_process.wait(timeout=15)
        print("Recording saved!")
        if current_output_file and os.path.exists(current_output_file):
            return {
                "filepath": os.path.abspath(current_output_file),
                "filename": os.path.basename(current_output_file),
                "duration": 0,
            }
        return None
    except Exception as e:
        print(f"Force killing FFmpeg: {e}")
        ffmpeg_process.kill()
        ffmpeg_process.wait()
        return None
    finally:
        ffmpeg_process = None
        stopping = False
        current_output_file = None
