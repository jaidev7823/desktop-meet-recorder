import psutil

MEETING_APPS = [
    "zoom.exe",
    "teams.exe",
    "discord.exe",
    "slack.exe",
    "whatsapp.exe"
]

def meeting_process_running():
    for p in psutil.process_iter(['name']):
        name = (p.info['name'] or "").lower()
        if name in MEETING_APPS:
            return True
    return False