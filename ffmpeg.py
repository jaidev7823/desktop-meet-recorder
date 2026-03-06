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
        "-thread_queue_size", "512",        # prevent video buffer underrun
        "-i", "desktop",
        "-f", "dshow",
        "-thread_queue_size", "512",        # prevent audio buffer underrun
        "-i", "audio=Microphone (Audio Array AM-C1 Device)",
        "-f", "dshow",
        "-thread_queue_size", "512",
        "-i", "audio=Stereo Mix (Realtek(R) Audio)",
        "-filter_complex", "amix=inputs=2:duration=longest,volume=2.0,adelay=500|500",
        "-vcodec", "libx264",
        "-preset", "ultrafast",
        "-crf", "23",
        "-acodec", "aac",
        "-vsync", "1",                      # sync video to audio clock
        "-async", "1",                      # stretch/squeeze audio to match video
        "-y",
        output_file
    ]
    
    print(f"Starting recording... saving to {output_file}")
    ffmpeg_process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=open("ffmpeg_log.txt", "w"),
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
    )
    
    time.sleep(2)
    if ffmpeg_process.poll() is not None:
        print("FFmpeg failed! Check ffmpeg_log.txt")
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