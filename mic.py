import subprocess
import json
import re


def detect_audio_devices(ffmpeg="ffmpeg"):
    try:
        result = subprocess.run(
            [ffmpeg, "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore"
        )

        lines = result.stderr.splitlines()

        devices = []
        for line in lines:
            m = re.search(r'"(.*?)"', line)
            if m:
                devices.append(m.group(1))

        microphones = []
        speakers = []

        for d in devices:
            name = d.lower()

            if "stereo mix" in name or "what u hear" in name or "loopback" in name:
                speakers.append(d)
            else:
                microphones.append(d)

        return {
            "microphones": microphones,
            "speakers": speakers
        }

    except Exception as e:
        return {
            "microphones": [],
            "speakers": [],
            "error": str(e)
        }


if __name__ == "__main__":
    devices = detect_audio_devices()
    print(json.dumps(devices, indent=2))