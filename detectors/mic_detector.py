from pycaw.pycaw import AudioUtilities
import psutil

MEETING_APPS = [
    "chrome.exe",
    "zoom.exe",
    "teams.exe",
    "whatsapp.exe",
    "discord.exe"
]


def mic_used_by_meeting_app():

    sessions = AudioUtilities.GetAllSessions()

    for session in sessions:

        if not session.Process:
            continue

        name = session.Process.name().lower()

        if name in MEETING_APPS:
            return True

    return False