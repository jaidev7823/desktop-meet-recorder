import subprocess
import time
import signal
import sys
import os

ffmpeg_process = None
stopping = False

def start_recording():
    global ffmpeg_process
    output_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_recording.mp4")
    
    if os.path.exists(output_file):
        os.remove(output_file)

    cmd = [
        "ffmpeg",
        "-f", "gdigrab",
        "-framerate", "30",
        "-i", "desktop",
        "-f", "dshow",
        "-i", "audio=Microphone (Audio Array AM-C1 Device)",
        "-vcodec", "libx264",
        "-preset", "ultrafast",
        "-crf", "23",
        "-acodec", "aac",
        "-y",
        output_file
    ]
    
    print(f"Starting recording... saving to {output_file}")
    
    # Key: use PIPE for stdin, but keep stderr visible so we can see ffmpeg errors
    ffmpeg_process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=open("ffmpeg_log.txt", "w"),  # Log errors to file instead of hiding them
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
    )
    
    # Give FFmpeg 2 seconds to start and check it didn't immediately crash
    time.sleep(2)
    if ffmpeg_process.poll() is not None:
        print("FFmpeg failed to start! Check ffmpeg_log.txt for details")
        sys.exit(1)
    
    print("Recording started! Press Ctrl+C to stop and save.")

def stop_recording():
    global ffmpeg_process, stopping
    if stopping or not ffmpeg_process:
        return
    stopping = True
    
    print("\nStopping recording...")
    try:
        ffmpeg_process.stdin.write(b'q\n')
        ffmpeg_process.stdin.flush()
        ffmpeg_process.stdin.close()
        ffmpeg_process.wait(timeout=15)
        print("Recording saved!")
    except Exception as e:
        print(f"Force killing: {e}")
        ffmpeg_process.kill()
        ffmpeg_process.wait()
    finally:
        ffmpeg_process = None

def signal_handler(sig, frame):
    stop_recording()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

if __name__ == "__main__":
    start_recording()
    while True:
        time.sleep(1)