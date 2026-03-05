import pygetwindow as gw


def meeting_tab_open():

    for title in gw.getAllTitles():

        t = title.lower()

        if "meet.google.com" in t:
            return True

        if "google meet" in t:
            return True

        if "zoom meeting" in t:
            return True

    return False