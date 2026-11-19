"""Everything that touches the operating system: apps, websites, media keys."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import webbrowser
from difflib import get_close_matches
from pathlib import Path
from typing import Dict, Optional

IS_WINDOWS = os.name == "nt"

# Spoken name -> (command / URI to launch, process name used to close it)
APPS: Dict[str, tuple[str, str]] = {
    "chrome": ("chrome", "chrome.exe"),
    "google chrome": ("chrome", "chrome.exe"),
    "firefox": ("firefox", "firefox.exe"),
    "edge": ("msedge", "msedge.exe"),
    "microsoft edge": ("msedge", "msedge.exe"),
    "brave": ("brave", "brave.exe"),
    "notepad": ("notepad", "notepad.exe"),
    "calculator": ("calc", "CalculatorApp.exe"),
    "paint": ("mspaint", "mspaint.exe"),
    "file explorer": ("explorer", "explorer.exe"),
    "explorer": ("explorer", "explorer.exe"),
    "files": ("explorer", "explorer.exe"),
    "task manager": ("taskmgr", "Taskmgr.exe"),
    "control panel": ("control", "control.exe"),
    "settings": ("ms-settings:", "SystemSettings.exe"),
    "terminal": ("wt", "WindowsTerminal.exe"),
    "command prompt": ("cmd", "cmd.exe"),
    "cmd": ("cmd", "cmd.exe"),
    "powershell": ("powershell", "powershell.exe"),
    "vs code": ("code", "Code.exe"),
    "vscode": ("code", "Code.exe"),
    "visual studio code": ("code", "Code.exe"),
    "spotify": ("spotify:", "Spotify.exe"),
    "discord": ("discord:", "Discord.exe"),
    "steam": ("steam:", "steam.exe"),
    "whatsapp": ("whatsapp:", "WhatsApp.exe"),
    "teams": ("msteams:", "ms-teams.exe"),
    "zoom": ("zoommtg:", "Zoom.exe"),
    "vlc": ("vlc", "vlc.exe"),
    "word": ("winword", "WINWORD.EXE"),
    "excel": ("excel", "EXCEL.EXE"),
    "powerpoint": ("powerpnt", "POWERPNT.EXE"),
    "outlook": ("outlook", "OUTLOOK.EXE"),
    "camera": ("microsoft.windows.camera:", "WindowsCamera.exe"),
    "store": ("ms-windows-store:", "WinStore.App.exe"),
    "riot client": (r"C:\Riot Games\Riot Client\RiotClientServices.exe", "RiotClientServices.exe"),
}

WEBSITES: Dict[str, str] = {
    "youtube": "https://www.youtube.com",
    "gmail": "https://mail.google.com",
    "google": "https://www.google.com",
    "google drive": "https://drive.google.com",
    "drive": "https://drive.google.com",
    "google calendar": "https://calendar.google.com",
    "calendar": "https://calendar.google.com",
    "maps": "https://maps.google.com",
    "google maps": "https://maps.google.com",
    "netflix": "https://www.netflix.com",
    "instagram": "https://www.instagram.com",
    "facebook": "https://www.facebook.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "reddit": "https://www.reddit.com",
    "github": "https://github.com",
    "linkedin": "https://www.linkedin.com",
    "amazon": "https://www.amazon.com",
    "chatgpt": "https://chatgpt.com",
    "claude": "https://claude.ai",
    "wikipedia": "https://www.wikipedia.org",
    "youtube music": "https://music.youtube.com",
    "whatsapp web": "https://web.whatsapp.com",
}

FOLDERS = {
    "documents": "Documents",
    "downloads": "Downloads",
    "desktop": "Desktop",
    "pictures": "Pictures",
    "photos": "Pictures",
    "music": "Music",
    "videos": "Videos",
}

# "open bluetooth settings" -> ms-settings:bluetooth
SETTINGS_PAGES = {
    "wifi": "network-wifi", "wi-fi": "network-wifi", "network": "network", "internet": "network",
    "bluetooth": "bluetooth", "devices": "bluetooth", "display": "display", "screen": "display",
    "brightness": "display", "night light": "nightlight", "sound": "sound", "audio": "sound",
    "volume": "sound", "battery": "batterysaver", "power": "powersleep", "sleep": "powersleep",
    "notifications": "notifications", "focus": "quiethours", "do not disturb": "quiethours",
    "storage": "storagesense", "apps": "appsfeatures", "installed apps": "appsfeatures",
    "default apps": "defaultapps", "startup apps": "startupapps", "startup": "startupapps",
    "update": "windowsupdate", "windows update": "windowsupdate", "updates": "windowsupdate",
    "privacy": "privacy", "camera": "privacy-webcam", "microphone": "privacy-microphone",
    "location": "privacy-location", "personalization": "personalization", "background": "personalization-background",
    "wallpaper": "personalization-background", "colors": "colors", "theme": "themes", "themes": "themes",
    "dark mode": "colors", "lock screen": "lockscreen", "taskbar": "taskbar", "mouse": "mousetouchpad",
    "touchpad": "devices-touchpad", "keyboard": "keyboard", "printer": "printers", "printers": "printers",
    "language": "regionlanguage", "time": "dateandtime", "date": "dateandtime", "accounts": "yourinfo",
    "account": "yourinfo", "sign in": "signinoptions", "password": "signinoptions", "vpn": "network-vpn",
    "hotspot": "network-mobilehotspot", "airplane mode": "network-airplanemode", "about": "about",
    "system": "display", "accessibility": "easeofaccess", "multitasking": "multitasking",
    "clipboard": "clipboard", "gaming": "gaming-gamebar", "game mode": "gaming-gamemode",
    "recovery": "recovery", "troubleshoot": "troubleshoot", "activation": "activation",
}

# Windows virtual-key codes for media keys.
_VK = {
    "play_pause": 0xB3,
    "next": 0xB0,
    "previous": 0xB1,
    "stop": 0xB2,
    "volume_up": 0xAF,
    "volume_down": 0xAE,
    "mute": 0xAD,
}
_PLAYERCTL = {"play_pause": "play-pause", "next": "next", "previous": "previous", "stop": "stop"}


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


class System:
    """Real implementation. Tests swap in a fake with the same methods."""

    def __init__(self) -> None:
        self._start_menu: Optional[Dict[str, Path]] = None

    # ----- websites & folders -------------------------------------------------
    def open_url(self, url: str) -> bool:
        return webbrowser.open(url)

    def website_for(self, name: str) -> Optional[str]:
        name = name.lower().strip()
        if name in WEBSITES:
            return WEBSITES[name]
        if re.fullmatch(r"[\w-]+(\.[\w-]+)+(/\S*)?", name):
            return name if name.startswith("http") else f"https://{name}"
        return None

    def open_folder(self, name: str) -> bool:
        folder = FOLDERS.get(name.lower().strip())
        if not folder:
            return False
        return self._start(str(Path.home() / folder))

    # ----- apps ---------------------------------------------------------------
    def _start(self, target: str) -> bool:
        try:
            if IS_WINDOWS:
                os.startfile(target)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", target])
            else:
                subprocess.Popen(["xdg-open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError:
            return False

    def _start_menu_apps(self) -> Dict[str, Path]:
        """Shortcuts from the Start Menu: covers almost every installed app."""
        if self._start_menu is not None:
            return self._start_menu
        apps: Dict[str, Path] = {}
        roots = [
            Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
            Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "Microsoft/Windows/Start Menu/Programs",
        ] if IS_WINDOWS else [Path("/usr/share/applications"), Path.home() / ".local/share/applications"]
        for root in roots:
            if not root.is_dir():
                continue
            for path in root.rglob("*"):
                if path.suffix.lower() in {".lnk", ".url", ".desktop"}:
                    apps.setdefault(_key(path.stem), path)
        self._start_menu = apps
        return apps

    def find_app(self, name: str) -> Optional[str]:
        key = _key(name)
        apps = self._start_menu_apps()
        if key in apps:
            return str(apps[key])
        for app_key, path in apps.items():
            if key and (app_key.startswith(key) or key in app_key):
                return str(path)
        match = get_close_matches(key, list(apps), n=1, cutoff=0.8)
        return str(apps[match[0]]) if match else None

    def open_app(self, name: str) -> bool:
        name = name.lower().strip()
        known = APPS.get(name)
        if known:
            target = known[0]
            if target.endswith(":") or Path(target).is_file():
                if self._start(target):
                    return True
            elif shutil.which(target):
                subprocess.Popen([shutil.which(target)])  # type: ignore[list-item]
                return True
        shortcut = self.find_app(name)
        if shortcut:
            return self._start(shortcut)
        if known and IS_WINDOWS:  # Let Windows resolve App Paths (e.g. chrome, winword).
            return subprocess.call(["cmd", "/c", "start", "", known[0]], shell=False) == 0
        return False

    def close_app(self, name: str) -> bool:
        name = name.lower().strip()
        process = APPS.get(name, (None, f"{name.replace(' ', '')}.exe"))[1]
        if IS_WINDOWS:
            result = subprocess.run(["taskkill", "/IM", process, "/F"], capture_output=True)
            return result.returncode == 0
        result = subprocess.run(["pkill", "-f", process.removesuffix(".exe")], capture_output=True)
        return result.returncode == 0

    # ----- media --------------------------------------------------------------
    def media(self, action: str, repeat: int = 1) -> bool:
        if IS_WINDOWS:
            import ctypes

            user32 = ctypes.windll.user32  # type: ignore[attr-defined]
            for _ in range(repeat):
                user32.keybd_event(_VK[action], 0, 0, 0)
                user32.keybd_event(_VK[action], 0, 2, 0)  # key up
            return True
        if action in _PLAYERCTL and shutil.which("playerctl"):
            return subprocess.call(["playerctl", _PLAYERCTL[action]]) == 0
        if action.startswith("volume") or action == "mute":
            if shutil.which("pactl"):
                arg = {"volume_up": "+5%", "volume_down": "-5%"}.get(action)
                cmd = ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"] if arg is None else [
                    "pactl", "set-sink-volume", "@DEFAULT_SINK@", arg
                ]
                for _ in range(repeat):
                    subprocess.call(cmd)
                return True
        return False

    # ----- settings ---------------------------------------------------------
    def open_settings(self, page: str = "") -> bool:
        key = page.lower().strip()
        uri = SETTINGS_PAGES.get(key)
        if uri is None:
            match = get_close_matches(key, list(SETTINGS_PAGES), n=1, cutoff=0.75)
            uri = SETTINGS_PAGES[match[0]] if match else ""
        return self._start(f"ms-settings:{uri}")

    def set_dark_mode(self, dark: bool) -> bool:
        if not IS_WINDOWS:
            return False
        import winreg

        path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as key:
            for name in ("AppsUseLightTheme", "SystemUsesLightTheme"):
                winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, 0 if dark else 1)
        return True

    def get_brightness(self) -> Optional[int]:
        out = self.powershell("(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness).CurrentBrightness")
        try:
            return int(out.split()[0])
        except (ValueError, IndexError):
            return None

    def set_brightness(self, percent: int) -> bool:
        percent = max(0, min(100, int(percent)))
        out = self.powershell(
            "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods)"
            f" | Invoke-CimMethod -MethodName WmiSetBrightness -Arguments @{{Timeout=1;Brightness={percent}}}"
        )
        return "error" not in out.lower()

    def power(self, action: str) -> bool:
        commands = {
            "shutdown": ["shutdown", "/s", "/t", "5"],
            "restart": ["shutdown", "/r", "/t", "5"],
            "sign out": ["shutdown", "/l"],
            "sleep": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
        }
        if not IS_WINDOWS or action not in commands:
            return False
        return subprocess.call(commands[action]) == 0

    def screenshot(self) -> bool:
        return self._start("ms-screenclip:") if IS_WINDOWS else False

    def powershell(self, command: str, timeout: int = 60) -> str:
        shell = ["powershell", "-NoProfile", "-Command", command] if IS_WINDOWS else ["bash", "-lc", command]
        try:
            result = subprocess.run(shell, capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError as exc:
            return f"Error: {exc}"
        except subprocess.TimeoutExpired:
            return "Error: the command timed out."
        output = (result.stdout + ("\n" + result.stderr if result.stderr else "")).strip()
        return output[:4000] or f"(finished with exit code {result.returncode})"

    def lock(self) -> bool:
        if IS_WINDOWS:
            import ctypes

            return bool(ctypes.windll.user32.LockWorkStation())  # type: ignore[attr-defined]
        return subprocess.call(["loginctl", "lock-session"]) == 0
