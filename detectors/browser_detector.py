import pygetwindow as gw

KEYWORDS = [
    "zoom meeting",
    "google meet",
    "microsoft teams",
    "whatsapp",
    "discord",
]

def meeting_window_open():

    for title in gw.getAllTitles():

        t = title.lower().strip()

        if not t:
            continue

        for k in KEYWORDS:
            if k in t:
                return True

    return False