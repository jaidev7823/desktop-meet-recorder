import time
from detectors.mic_session_detector import meeting_active

while True:

    if meeting_active():
        print("Meeting detected")

    else:
        print("No meeting")

    time.sleep(2)