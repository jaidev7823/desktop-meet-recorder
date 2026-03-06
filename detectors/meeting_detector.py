import win32gui
import win32process
import psutil
import winreg
import pygetwindow as gw

MIC_REG_PATH_PACKAGED = r"SOFTWARE\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"
MIC_REG_PATH_NON_PACKAGED = r"SOFTWARE\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone\NonPackaged"


def get_window_process_name(hwnd):
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        process = psutil.Process(pid)
        return process.name().lower()
    except Exception:
        return ""


def count_whatsapp_windows():
    """Count visible windows owned by the WhatsApp process."""
    whatsapp_windows = []

    def callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if not title:
            return
        proc_name = get_window_process_name(hwnd)
        if 'whatsapp' in proc_name:
            whatsapp_windows.append(title)

    win32gui.EnumWindows(callback, None)
    return len(whatsapp_windows)


def chrome_running():
    for proc in psutil.process_iter(['name']):
        if (proc.info['name'] or '').lower() == 'chrome.exe':
            return True
    return False


def meet_tab_open():
    for title in gw.getAllTitles():
        value = title.lower().strip()
        if 'google chrome' in value and 'meet' in value:
            return True
    return False


def check_registry_mic(registry_path):
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry_path)
        index = 0
        while True:
            try:
                subkey_name = winreg.EnumKey(key, index)
            except OSError:
                break

            try:
                subkey = winreg.OpenKey(key, subkey_name)
                last = winreg.QueryValueEx(subkey, 'LastUsedTimeStart')[0]
                stop = winreg.QueryValueEx(subkey, 'LastUsedTimeStop')[0]
                if last > stop:
                    return True
            except OSError:
                pass

            index += 1
    except OSError:
        pass
    return False


def mic_in_use():
    return check_registry_mic(MIC_REG_PATH_PACKAGED) or check_registry_mic(MIC_REG_PATH_NON_PACKAGED)


def check_active_calls():
    mic = mic_in_use()
    whatsapp_window_count = count_whatsapp_windows()

    meet_active = chrome_running() and meet_tab_open() and mic

    # PRIMARY: 2 windows = call is open (mic is secondary confirmation)
    # If windows drop to 1, call is over regardless of mic state.
    if whatsapp_window_count >= 2:
        whatsapp_active = mic
    else:
        whatsapp_active = False

    return mic, meet_active, whatsapp_active
