import time

from detectors.meeting_detector import meeting_active
from obs.controller import start_recording, stop_recording

recording = False


while True:

    call = meeting_active()

    if call and not recording:

        start_recording()
        recording = True
        print("OBS recording started")

    if not call and recording:

        stop_recording()
        recording = False
        print("OBS recording stopped")

    time.sleep(3)