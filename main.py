import time

from detectors.browser_detector import meeting_window_open
from detectors.mic_detector import mic_used_by_meeting_app
from obs.controller import start_recording, stop_recording

recording = False


def meeting_detected():

    mic = mic_used_by_meeting_app()
    meeting = meeting_window_open()

    print("mic:", mic, "meeting_window:", meeting)

    return mic and meeting


while True:

    call = meeting_detected()

    if call and not recording:
        start_recording()
        recording = True
        print("OBS recording started")

    if not call and recording:
        stop_recording()
        recording = False
        print("OBS recording stopped")

    time.sleep(3)