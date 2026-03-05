import time

from detectors.browser_detector import meeting_window_open
from detectors.mic_detector import mic_active
from obs.controller import start_recording, stop_recording

recording = False


def meeting_detected():

    meeting = meeting_window_open()
    mic = mic_active()

    print("meeting_window:", meeting, "mic:", mic)

    return meeting and mic


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