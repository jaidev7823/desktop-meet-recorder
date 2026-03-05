import psutil
import pygetwindow as gw
import winreg

# Base path for Packaged apps (like WhatsApp Desktop)
MIC_REG_PATH_PACKAGED = r"SOFTWARE\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"
# Path for Non-Packaged apps (like Chrome)
MIC_REG_PATH_NON_PACKAGED = r"SOFTWARE\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone\NonPackaged"

def chrome_running():
    for p in psutil.process_iter(['name']):
        name = (p.info['name'] or "").lower()
        if name == "chrome.exe":
            return True
    return False

def whatsapp_app_running():
    for p in psutil.process_iter(['name']):
        name = (p.info['name'] or "").lower()
        if name == "whatsapp.exe":
            return True
    return False

def meet_tab_open():
    for title in gw.getAllTitles():
        t = title.lower().strip()
        if not t: continue
        if "google chrome" in t and "meet" in t:
            return True
    return False

def whatsapp_web_open():
    for title in gw.getAllTitles():
        t = title.lower().strip()
        if not t: continue
        # Checks if WhatsApp is in the title alongside common browsers
        if "whatsapp" in t and any(browser in t for browser in ["chrome", "edge", "firefox", "brave"]):
            return True
    return False

def check_registry_mic(registry_path):
    """Helper function to check a specific registry path for mic activity."""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry_path)
        i = 0
        while True:
            try:
                subkey_name = winreg.EnumKey(key, i)
            except OSError:
                break
            
            try:
                subkey = winreg.OpenKey(key, subkey_name)
                last = winreg.QueryValueEx(subkey, "LastUsedTimeStart")[0]
                stop = winreg.QueryValueEx(subkey, "LastUsedTimeStop")[0]
                
                # If the start time is greater than the stop time, the mic is currently active
                if last > stop:
                    return True
            except OSError:
                pass
            
            i += 1
    except OSError:
        pass
    
    return False

def mic_in_use():
    # Check both packaged apps (WhatsApp Desktop) and non-packaged apps (Chrome)
    return check_registry_mic(MIC_REG_PATH_PACKAGED) or check_registry_mic(MIC_REG_PATH_NON_PACKAGED)

def check_active_calls():
    # Evaluate base states
    mic = mic_in_use()
    
    # Meet Logic
    meet_active = chrome_running() and meet_tab_open() and mic
    
    # WhatsApp Logic (Triggered if either the Desktop App OR the Web version is running while mic is active)
    whatsapp_active = (whatsapp_app_running() or whatsapp_web_open()) and mic

    print(f"Mic Active: {mic}")
    print(f"Google Meet Call: {meet_active}")
    print(f"WhatsApp Call: {whatsapp_active}")

    return meet_active, whatsapp_active

if __name__ == "__main__":
    check_active_calls()