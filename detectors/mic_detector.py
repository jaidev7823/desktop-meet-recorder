import sounddevice as sd
import numpy as np
import json

with open("config.json") as f:
    CONFIG = json.load(f)

DEVICE_ID = CONFIG["mic_device"]

SAMPLE_RATE = 16000
DURATION = 0.5
THRESHOLD = 0.0007


def mic_active():

    audio = sd.rec(
        int(DURATION * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        device=DEVICE_ID,
        dtype="float32"
    )

    sd.wait()

    level = np.sqrt(np.mean(audio**2))

    return level > THRESHOLD