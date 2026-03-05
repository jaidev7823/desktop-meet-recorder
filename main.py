import time

from obs.controller import start_recording, stop_recording
from detectors.mic_detector import mic_active
from detectors.process_detector import meeting_process_running
from detectors.browser_detector import meeting_tab_open

recording = False


def on_call():

    if not mic_active():
        return False

    if meeting_process_running():
        return True

    if meeting_tab_open():
        return True

    return False


while True:

    call = on_call()

    if call and not recording:
        start_recording()
        recording = True

    if not call and recording:
        stop_recording()
        recording = False

    time.sleep(5)