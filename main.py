import time

# Updated import to use the new function
from detectors.meeting_detector import check_active_calls
from obs.controller import start_recording, stop_recording

recording = False

print("Monitoring started. Waiting for active Google Meet or WhatsApp calls...")

while True:
    # Unpack the tuple returned by the updated detector
    meet_active, whatsapp_active = check_active_calls()
    
    # A call is happening if either Meet OR WhatsApp is active
    call = meet_active or whatsapp_active

    # Start recording if a call just started
    if call and not recording:
        start_recording()
        recording = True
        
        # Optional: Print exactly which call triggered the recording
        trigger = "Google Meet" if meet_active else "WhatsApp"
        print(f"OBS recording started (Triggered by: {trigger})")

    # Stop recording if all calls have ended
    if not call and recording:
        stop_recording()
        recording = False
        print("OBS recording stopped")

    time.sleep(3)