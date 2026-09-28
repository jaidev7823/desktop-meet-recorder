import sys
import psutil
import subprocess
import shutil

IS_WINDOWS = sys.platform == "win32"

MIC_REG_PATH_PACKAGED = r"SOFTWARE\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"
MIC_REG_PATH_NON_PACKAGED = r"SOFTWARE\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone\NonPackaged"

if IS_WINDOWS:
    import win32gui
    import win32process
    import winreg
    import pygetwindow as gw

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
        try:
            for title in gw.getAllTitles():
                value = title.lower().strip()
                if 'google chrome' in value and 'meet' in value:
                    return True
        except Exception:
            pass
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

else:
    # ---------------- Linux / Wayland helpers ----------------
    def _run(cmd):
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        except Exception:
            return None

    def _pactl_mic_in_use():
        # pactl list short source-outputs -> non-empty means mic is capturing
        for cmd in (["pactl", "list", "short", "source-outputs"], ["pactl", "list", "source-outputs"]):
            proc = _run(cmd)
            if proc and proc.returncode == 0:
                out = (proc.stdout or "").strip()
                if out:
                    # short format: each line is an active capture
                    # verbose format: contains Source Output #<n>
                    if "Source Output" in out or len(out.splitlines()) > 0 and any(line.strip() for line in out.splitlines()):
                        # double check: for short, any non-empty line means active
                        lines = [l for l in out.splitlines() if l.strip()]
                        if lines:
                            # filter header noise
                            if "Source Output" in out:
                                return True
                            # short: if any line has tab separated fields, it's active
                            return True
                else:
                    # empty -> check next cmd? short empty means no capture
                    if cmd[2] == "short":
                        # confirm with verbose as well
                        continue
                    return False
        # fallback: check pw-cli
        proc = _run(["pw-cli", "list-objects"])
        if proc and proc.returncode == 0 and "PipeWire:Interface:Client" in proc.stdout:
            # overly broad, ignore
            pass
        return False

    def _pactl_chrome_holding_mic():
        proc = _run(["pactl", "list", "source-outputs"])
        if not proc or proc.returncode != 0:
            return False
        out = (proc.stdout or "").lower()
        # chrome / chromium / brave / firefox as application.process.binary
        for key in ("chrome", "chromium", "brave", "firefox", "google chrome"):
            if key in out:
                return True
        return False

    def get_window_process_name(hwnd):  # stub for compat
        return ""

    def count_whatsapp_windows():
        # Prefer window titles via xdotool if available (X11/XWayland)
        titles = _linux_get_window_titles()
        count = sum(1 for t in titles if "whatsapp" in t.lower())
        if count > 0:
            return count
        # fallback: process-based
        whatsapp_procs = 0
        for proc in psutil.process_iter(['name']):
            name = (proc.info['name'] or '').lower()
            if 'whatsapp' in name:
                whatsapp_procs += 1
        # Check Chrome holding mic with whatsapp-like usage? Can't distinguish, so if whatsapp process exists and mic active, count as 1
        # To match Windows logic (>=2 means call), on Linux use 1 + mic as active
        if whatsapp_procs > 0:
            return 2  # pretend 2 so check_active_calls returns whatsapp_active = mic
        # Also check Chrome title fallback for web.whatsapp.com via wmctrl/xdotool already handled
        return 0

    def _linux_get_window_titles():
        titles = []
        # Try xdotool (X11/XWayland)
        if shutil.which("xdotool"):
            try:
                proc = _run(["xdotool", "search", "--onlyvisible", "--name", ".*"])
                if proc and proc.returncode == 0:
                    ids = [l.strip() for l in proc.stdout.splitlines() if l.strip()]
                    for wid in ids[:20]:  # limit
                        p2 = _run(["xdotool", "getwindowname", wid])
                        if p2 and p2.returncode == 0 and p2.stdout.strip():
                            titles.append(p2.stdout.strip())
            except Exception:
                pass
        # Try wmctrl
        if not titles and shutil.which("wmctrl"):
            proc = _run(["wmctrl", "-l"])
            if proc and proc.returncode == 0:
                for line in proc.stdout.splitlines():
                    parts = line.split(None, 3)
                    if len(parts) == 4:
                        titles.append(parts[3])
        # Try hyprctl (Hyprland)
        if not titles and shutil.which("hyprctl"):
            proc = _run(["hyprctl", "clients", "-j"])
            if proc and proc.returncode == 0:
                try:
                    import json
                    clients = json.loads(proc.stdout)
                    for c in clients:
                        t = c.get("title") or c.get("initialTitle") or ""
                        if t:
                            titles.append(t)
                except Exception:
                    pass
        # Try swaymsg
        if not titles and shutil.which("swaymsg"):
            proc = _run(["swaymsg", "-t", "get_tree"])
            if proc and proc.returncode == 0:
                try:
                    import json
                    def collect(node):
                        if isinstance(node, dict):
                            if "name" in node and node.get("type") == "con":
                                titles.append(str(node["name"]))
                            for v in node.values():
                                collect(v)
                        elif isinstance(node, list):
                            for item in node:
                                collect(item)
                    collect(json.loads(proc.stdout))
                except Exception:
                    pass
        return titles

    def chrome_running():
        candidates = ("chrome", "chromium", "chromium-browser", "google-chrome", "brave", "firefox")
        for proc in psutil.process_iter(['name']):
            name = (proc.info['name'] or '').lower()
            for cand in candidates:
                if cand in name:
                    return True
        return False

    def meet_tab_open():
        titles = _linux_get_window_titles()
        if titles:
            for title in titles:
                low = title.lower()
                if "meet" in low:
                    return True
            return False
        # Wayland: titles not available via xdotool, fallback to heuristic
        # If chrome is using mic, likely Meet/Jitsi/Zoom tab. Let mic+chrome be the signal.
        # Check if chrome is holding mic via pactl
        if _pactl_chrome_holding_mic():
            return True
        # As last resort, check cmdline for meet.google.com
        try:
            for proc in psutil.process_iter(['name', 'cmdline']):
                cmdline = " ".join(proc.info.get('cmdline') or []).lower()
                if "meet.google.com" in cmdline or "zoom.us" in cmdline:
                    return True
        except Exception:
            pass
        return False

    def mic_in_use():
        return _pactl_mic_in_use()


def check_active_calls():
    mic = mic_in_use()
    whatsapp_window_count = count_whatsapp_windows()

    if IS_WINDOWS:
        meet_active = chrome_running() and meet_tab_open() and mic
        if whatsapp_window_count >= 2:
            whatsapp_active = mic
        else:
            whatsapp_active = False
    else:
        # Linux: titles unreliable on Wayland, use process+mic heuristic
        chrome = chrome_running()
        meet_open = meet_tab_open()
        # If we have titles, require them; if not, meet_tab_open already falls back to pactl chrome check
        meet_active = chrome and meet_open and mic

        # WhatsApp: native or web. Use count heuristic
        if whatsapp_window_count >= 1:
            whatsapp_active = mic
        else:
            whatsapp_active = False

    return mic, meet_active, whatsapp_active
