import sounddevice as sd
import numpy as np


def mic_active():

    data = sd.rec(8000, samplerate=8000, channels=1)
    sd.wait()

    level = abs(data).mean()

    return level > 0.01