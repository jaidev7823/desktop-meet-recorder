import win32gui
import win32process
import psutil
import time

def get_window_process_name(hwnd):
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        process = psutil.Process(pid)
        return process.name().lower()
    except:
        return ""

def monitor_whatsapp_calls():
    print("Monitoring started... (DEBUG MODE - showing all WhatsApp process windows)")
    was_calling = False

    while True:
        whatsapp_windows = []

        def callback(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd)
            if not title:
                return
            
            proc_name = get_window_process_name(hwnd)
            # Catch ANY window owned by whatsapp process
            if "whatsapp" in proc_name:
                whatsapp_windows.append({"title": title, "proc": proc_name})

        win32gui.EnumWindows(callback, None)

        print(f"--- All WhatsApp windows ({len(whatsapp_windows)}) ---")
        for w in whatsapp_windows:
            print(f"  [{w['proc']}] '{w['title']}'")

        time.sleep(2)

if __name__ == "__main__":
    monitor_whatsapp_calls()