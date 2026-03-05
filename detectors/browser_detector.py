import pygetwindow as gw

KEYWORDS = [
    "zoom",
    "meet",
    "teams",
    "whatsapp",
]

def meeting_window_open():

    for title in gw.getAllTitles():
        t = title.lower()
        if not t.strip():
            continue

        for k in KEYWORDS:
            if k in t:
                return True

    return False