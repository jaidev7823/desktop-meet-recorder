import psutil
import pygetwindow as gw
import winreg


def chrome_running():

    for p in psutil.process_iter(['name']):
        if (p.info['name'] or "").lower() == "chrome.exe":
            return True

    return False

def meet_tab_open():

    for title in gw.getAllTitles():
        print(title)
        t = title.lower().strip()

        if not t:
            continue

        if "google chrome" not in t:
            continue

        if "meet" in t:
            return True

    return False


def mic_in_use():

    try:

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone\NonPackaged"
        )

        i = 0

        while True:

            subkey_name = winreg.EnumKey(key, i)
            subkey = winreg.OpenKey(key, subkey_name)

            try:
                last = winreg.QueryValueEx(subkey, "LastUsedTimeStart")[0]
                stop = winreg.QueryValueEx(subkey, "LastUsedTimeStop")[0]

                if last > stop:
                    return True

            except OSError:
                pass

            i += 1

    except OSError:
        pass

    return False


def meeting_active():

    return chrome_running() and meet_tab_open() and mic_in_use()