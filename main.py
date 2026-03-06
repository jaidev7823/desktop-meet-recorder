import time
import argparse
import os

parser = argparse.ArgumentParser()
parser.add_argument('--ffmpeg', default='ffmpeg', help='Path to ffmpeg executable')
parser.add_argument('--mic', default='Microphone (Audio Array AM-C1 Device)')
parser.add_argument('--stereo', default='Stereo Mix (Realtek(R) Audio)')
args = parser.parse_args()

# Pass paths to controller via environment variables
os.environ["FFMPEG_PATH"] = args.ffmpeg
os.environ["MIC_DEVICE"] = args.mic
os.environ["STEREO_DEVICE"] = args.stereo

from detectors.meeting_detector import check_active_calls
from obs.controller import start_recording, stop_recording

recording = False
print("Monitoring started. Waiting for active Google Meet or WhatsApp calls...")

while True:
    meet_active, whatsapp_active = check_active_calls()
    call = meet_active or whatsapp_active

    if call and not recording:
        start_recording()
        recording = True
        trigger = "Google Meet" if meet_active else "WhatsApp"
        print(f"Recording started (Triggered by: {trigger})")

    if not call and recording:
        stop_recording()
        recording = False
        print("Recording stopped")

    time.sleep(3)