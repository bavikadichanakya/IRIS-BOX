from __future__ import annotations
import os
import sys
import time
import shutil
import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

try:
    import pyperclip
except ImportError:
    pyperclip = None

logger = logging.getLogger("iris.laptop_agent.app_control")

# Windows Virtual Key Codes
VK_CODES: Dict[str, int] = {
    "enter": 0x0D,
    "return": 0x0D,
    "esc": 0x1B,
    "escape": 0x1B,
    "tab": 0x09,
    "space": 0x20,
    "backspace": 0x08,
    "delete": 0x2E,
    "up": 0x26,
    "down": 0x28,
    "left": 0x27,
    "right": 0x29,
    "pageup": 0x21,
    "pagedown": 0x22,
    "home": 0x24,
    "end": 0x23,
    "f11": 0x7A,
    "f": 0x46,
    "volume_mute": 0xAD,
    "volume_down": 0xAE,
    "volume_up": 0xAF,
    "media_next": 0xB0,
    "media_prev": 0xB1,
    "media_stop": 0xB2,
    "media_play_pause": 0xB3,
    "control": 0x11,
    "ctrl": 0x11,
    "menu": 0x12,
    "alt": 0x12,
    "shift": 0x10,
    "v": 0x56,
}

# Windows SW_ constants
SW_HIDE = 0
SW_SHOWNORMAL = 1
SW_SHOWMINIMIZED = 2
SW_MAXIMIZE = 3
SW_SHOW = 5
SW_MINIMIZE = 6
SW_RESTORE = 9
WM_CLOSE = 0x0010


class AppControl:
    """
    Native Windows application discovery, process launching, window management,
    and simulated keyboard/clipboard automation.
    """

    KNOWN_APPS: Dict[str, str] = {
        "notepad": "notepad.exe",
        "calc": "calc.exe",
        "calculator": "calc.exe",
        "explorer": "explorer.exe",
        "files": "explorer.exe",
        "cmd": "cmd.exe",
        "command prompt": "cmd.exe",
        "powershell": "powershell.exe",
        "terminal": "wt.exe",
        "windows terminal": "wt.exe",
        "code": "code",
        "vscode": "code",
        "vs code": "code",
        "cursor": "cursor",
        "chrome": "chrome.exe",
        "google chrome": "chrome.exe",
        "browser": "chrome.exe",
        "edge": "msedge.exe",
        "msedge": "msedge.exe",
        "spotify": "spotify.exe",
    }

    @classmethod
    def open_app(cls, name: str, args: Optional[List[str]] = None) -> Dict[str, Any]:
        """Launch an application by friendly name, executable, or path detached from current process."""
        name_clean = name.strip().lower()
        exe = cls.KNOWN_APPS.get(name_clean, name)

        # Check in PATH
        resolved = shutil.which(exe)
        cmd = [resolved or exe]
        if args:
            cmd.extend(args)

        try:
            creationflags = 0
            if os.name == "nt":
                creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP

            proc = subprocess.Popen(
                cmd,
                creationflags=creationflags,
                close_fds=True,
                shell=(resolved is None)
            )
            return {
                "success": True,
                "app": name,
                "command": cmd,
                "pid": proc.pid,
                "message": f"Successfully launched {name} (PID: {proc.pid})"
            }
        except Exception as exc:
            logger.error(f"Failed to launch {name}: {exc}")
            return {
                "success": False,
                "app": name,
                "error": str(exc),
                "message": f"Could not launch application '{name}': {exc}"
            }

    @classmethod
    def list_windows(cls) -> List[Dict[str, Any]]:
        """Enumerate all visible desktop windows."""
        windows: List[Dict[str, Any]] = []
        if os.name != "nt":
            return windows

        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32

            WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

            def enum_cb(hwnd, lparam):
                if user32.IsWindowVisible(hwnd):
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buff = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, buff, length + 1)
                        title = buff.value.strip()
                        if title:
                            pid = wintypes.DWORD()
                            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                            windows.append({
                                "hwnd": hwnd,
                                "title": title,
                                "pid": pid.value,
                            })
                return True

            cb = WNDENUMPROC(enum_cb)
            hdesk = user32.OpenDesktopW("Default", 0, False, 0x0100)
            if hdesk:
                try:
                    user32.EnumDesktopWindows(hdesk, cb, 0)
                finally:
                    user32.CloseDesktop(hdesk)
            else:
                user32.EnumWindows(cb, 0)
        except Exception as exc:
            logger.warning(f"Error enumerating windows: {exc}")

        return windows

    @classmethod
    def find_window(cls, query: str) -> Optional[Dict[str, Any]]:
        """Find a window matching query substring in title."""
        query_lower = query.strip().lower()
        windows = cls.list_windows()
        for w in windows:
            if query_lower in w["title"].lower():
                return w
        return None

    @classmethod
    def focus_window(cls, query: str) -> Dict[str, Any]:
        """Bring target window to the foreground, bypassing Windows focus-stealing locks."""
        if os.name != "nt":
            return {"success": False, "error": "Only supported on Windows"}

        target = cls.find_window(query)
        if not target:
            return {"success": False, "message": f"No window found matching '{query}'"}

        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = target["hwnd"]

            # Unlock focus stealing via Alt key pulse
            user32.keybd_event(VK_CODES["alt"], 0, 0, 0)
            user32.keybd_event(VK_CODES["alt"], 0, 2, 0)

            user32.ShowWindow(hwnd, SW_RESTORE)
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.1)

            return {
                "success": True,
                "title": target["title"],
                "hwnd": hwnd,
                "message": f"Focused window '{target['title']}'"
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    @classmethod
    def close_window(cls, query: str) -> Dict[str, Any]:
        """Close window gracefully."""
        if os.name != "nt":
            return {"success": False, "error": "Only supported on Windows"}

        target = cls.find_window(query)
        if not target:
            return {"success": False, "message": f"No window found matching '{query}'"}

        try:
            import ctypes
            user32 = ctypes.windll.user32
            user32.PostMessageW(target["hwnd"], WM_CLOSE, 0, 0)
            return {"success": True, "message": f"Closed window '{target['title']}'"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    @classmethod
    def type_text(cls, text: str, press_enter: bool = False, delay: float = 0.05) -> Dict[str, Any]:
        """
        Type text into the currently active window or input element.
        Uses clipboard paste (Ctrl+V) for instant Unicode and special character support.
        """
        if os.name != "nt":
            return {"success": False, "error": "Only supported on Windows"}

        try:
            import ctypes
            user32 = ctypes.windll.user32

            if pyperclip:
                # Instant Unicode clipboard paste
                old_clipboard = ""
                try:
                    old_clipboard = pyperclip.paste()
                except Exception:
                    pass

                pyperclip.copy(text)
                time.sleep(0.05)

                # Press Ctrl + V
                user32.keybd_event(VK_CODES["ctrl"], 0, 0, 0)
                user32.keybd_event(VK_CODES["v"], 0, 0, 0)
                time.sleep(0.02)
                user32.keybd_event(VK_CODES["v"], 0, 2, 0)
                user32.keybd_event(VK_CODES["ctrl"], 0, 2, 0)

                time.sleep(delay)
            else:
                # Fallback to keybd_event per char
                for char in text:
                    vk = ctypes.windll.user32.VkKeyScanW(ord(char)) & 0xFF
                    if vk:
                        user32.keybd_event(vk, 0, 0, 0)
                        user32.keybd_event(vk, 0, 2, 0)
                    time.sleep(0.01)

            if press_enter:
                time.sleep(0.1)
                cls.press_key("enter")

            return {
                "success": True,
                "typed_length": len(text),
                "press_enter": press_enter,
                "message": f"Typed {len(text)} characters" + (" and pressed Enter" if press_enter else "")
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    @classmethod
    def press_key(cls, key: str) -> Dict[str, Any]:
        """Simulate pressing and releasing a key."""
        if os.name != "nt":
            return {"success": False, "error": "Only supported on Windows"}

        key_lower = key.strip().lower()
        vk = VK_CODES.get(key_lower)
        if not vk and len(key_lower) == 1:
            # Single character key
            vk = ord(key_lower.upper())

        if not vk:
            return {"success": False, "error": f"Unknown key '{key}'"}

        try:
            import ctypes
            user32 = ctypes.windll.user32
            user32.keybd_event(vk, 0, 0, 0)
            time.sleep(0.05)
            user32.keybd_event(vk, 0, 2, 0)
            return {"success": True, "key": key, "message": f"Pressed key '{key}'"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    @classmethod
    def control_volume(cls, action: str, steps: int = 2) -> Dict[str, Any]:
        """Adjust system volume (up, down, mute)."""
        action_clean = action.strip().lower()
        if action_clean in ("up", "raise", "increase"):
            key = "volume_up"
        elif action_clean in ("down", "lower", "decrease"):
            key = "volume_down"
        elif action_clean in ("mute", "toggle_mute"):
            key = "volume_mute"
            steps = 1
        else:
            return {"success": False, "error": f"Invalid volume action '{action}'. Use up, down, or mute."}

        for _ in range(max(1, steps)):
            cls.press_key(key)
            time.sleep(0.05)

        return {"success": True, "action": action_clean, "steps": steps, "message": f"Adjusted volume {action_clean}"}
