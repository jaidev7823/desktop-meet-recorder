import subprocess
import os
import sys

ffmpeg_process = None
stopping = False

def get_ffmpeg_path():
    # Will be overridden by Electron passing --ffmpeg argument
    return os.environ.get("FFMPEG_PATH", "ffmpeg")

def get_audio_devices():
    mic = os.environ.get("MIC_DEVICE", "Microphone (Audio Array AM-C1 Device)")
    stereo = os.environ.get("STEREO_DEVICE", "Stereo Mix (Realtek(R) Audio)")
    return mic, stereo

def start_recording():
    global ffmpeg_process, stopping
    stopping = False

    mic, stereo = get_audio_devices()
    ffmpeg = get_ffmpeg_path()

    output_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "recording.mp4")
    output_file = os.path.abspath(output_file)

    if os.path.exists(output_file):
        os.remove(output_file)

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
        print("FFmpeg failed to start! Check ffmpeg_log.txt")
        ffmpeg_process = None

def stop_recording():
    global ffmpeg_process, stopping
    if stopping or not ffmpeg_process:
        return
    stopping = True
    print("Stopping FFmpeg recording...")
    try:
        ffmpeg_process.stdin.write(b'q\n')
        ffmpeg_process.stdin.flush()
        ffmpeg_process.stdin.close()
        ffmpeg_process.wait(timeout=15)
        print("Recording saved!")
    except Exception as e:
        print(f"Force killing FFmpeg: {e}")
        ffmpeg_process.kill()
        ffmpeg_process.wait()
    finally:
        ffmpeg_process = None
        stopping = False