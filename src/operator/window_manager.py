from __future__ import annotations
import os
import logging
from typing import Any, Dict, List, Optional, Union

from src.operator.desktop import DesktopEnvironment

logger = logging.getLogger("iris.operator.window_manager")

# Windows SW_ constants
SW_HIDE = 0
SW_SHOWNORMAL = 1
SW_SHOWMINIMIZED = 2
SW_MAXIMIZE = 3
SW_SHOWNOACTIVATE = 4
SW_SHOW = 5
SW_MINIMIZE = 6
SW_RESTORE = 9

# Windows Messages
WM_CLOSE = 0x0010
VK_MENU = 0x12
KEYEVENTF_KEYUP = 0x0002


class WindowManager:
    """
    Native Window State Controller for IRIS AI Computer Operator:
    - Window discovery by partial title or process name substring.
    - Reliable foreground window focus switching bypassing Windows focus-stealing locks.
    - Window state manipulation (maximize, minimize, restore).
    - Safe graceful window closing with system process blacklist protection.
    """

    @staticmethod
    def find_window(query: Union[str, int]) -> Optional[Dict[str, Any]]:
        """
        Locate an active desktop window by title, process name, or HWND.
        Returns window dictionary {hwnd, title, pid, process_name} or None.
        """
        windows = DesktopEnvironment.get_visible_windows()
        if not windows:
            return None

        # 1. Direct HWND lookup
        if isinstance(query, int):
            for w in windows:
                if w["hwnd"] == query:
                    return w
            return None

        query_str = str(query).strip()
        if not query_str:
            return None

        # Check if query string is integer HWND
        if query_str.isdigit():
            hwnd_int = int(query_str)
            for w in windows:
                if w["hwnd"] == hwnd_int:
                    return w

        query_lower = query_str.lower()

        # Priority 1: Exact case-insensitive match on title
        for w in windows:
            if w["title"].lower() == query_lower:
                return w

        # Priority 2: Exact case-insensitive match on process_name (with or without .exe)
        for w in windows:
            pname = w["process_name"].lower()
            if pname == query_lower or pname.removesuffix(".exe") == query_lower:
                return w

        # Priority 3: Title starts with query
        for w in windows:
            if w["title"].lower().startswith(query_lower):
                return w

        # Priority 4: Query is substring of title
        for w in windows:
            if query_lower in w["title"].lower():
                return w

        # Priority 5: Query is substring of process_name
        for w in windows:
            if query_lower in w["process_name"].lower():
                return w

        # Priority 6: All words in query appear in title
        query_words = query_lower.split()
        if len(query_words) > 1:
            for w in windows:
                title_lower = w["title"].lower()
                if all(word in title_lower for word in query_words):
                    return w

        return None

    @classmethod
    def focus_window(cls, query_or_hwnd: Union[str, int]) -> bool:
        """
        Brings target window to the foreground, restoring it if minimized.
        Uses Alt key simulation and thread attachment to overcome Windows OS focus-stealing locks.
        """
        if os.name != "nt":
            logger.debug("Window focus is only supported on Windows.")
            return False

        try:
            import ctypes
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
        except Exception as e:
            logger.error(f"Failed to load user32/kernel32: {e}")
            return False

        # Resolve HWND
        hwnd: Optional[int] = None
        if isinstance(query_or_hwnd, int):
            hwnd = query_or_hwnd
        else:
            matched = cls.find_window(query_or_hwnd)
            if matched:
                hwnd = matched["hwnd"]

        if not hwnd or not user32.IsWindow(hwnd):
            logger.warning(f"Window handle for '{query_or_hwnd}' is invalid or not found.")
            return False

        try:
            # 1. Restore if minimized
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, SW_RESTORE)

            # 2. Bypass Windows Focus Lock via Alt keystroke simulation & thread input attachment
            curr_thread = kernel32.GetCurrentThreadId()
            fg_hwnd = user32.GetForegroundWindow()
            fg_thread = user32.GetWindowThreadProcessId(fg_hwnd, None) if fg_hwnd else 0

            # Simulate Alt keypress to grant foreground permission
            user32.keybd_event(VK_MENU, 0, 0, 0)
            user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)

            attached = False
            if fg_thread != 0 and fg_thread != curr_thread:
                attached = bool(user32.AttachThreadInput(curr_thread, fg_thread, True))

            try:
                user32.BringWindowToTop(hwnd)
                user32.ShowWindow(hwnd, SW_SHOW)
                res = user32.SetForegroundWindow(hwnd)
            finally:
                if attached:
                    user32.AttachThreadInput(curr_thread, fg_thread, False)

            return bool(res)
        except Exception as exc:
            logger.error(f"Error focusing window {hwnd}: {exc}", exc_info=True)
            return False

    @classmethod
    def set_window_state(cls, query_or_hwnd: Union[str, int], state: str) -> bool:
        """
        Change target window state: 'maximize', 'minimize', or 'restore'.
        """
        if os.name != "nt":
            logger.debug("Window state control is only supported on Windows.")
            return False

        try:
            import ctypes
            user32 = ctypes.windll.user32
        except Exception as e:
            logger.error(f"Failed to load user32: {e}")
            return False

        state_norm = state.lower().strip()
        cmd_map = {
            "maximize": SW_MAXIMIZE,
            "maximized": SW_MAXIMIZE,
            "max": SW_MAXIMIZE,
            "minimize": SW_MINIMIZE,
            "minimized": SW_MINIMIZE,
            "min": SW_MINIMIZE,
            "restore": SW_RESTORE,
            "restored": SW_RESTORE,
            "normal": SW_RESTORE,
        }

        cmd = cmd_map.get(state_norm)
        if cmd is None:
            raise ValueError(f"Invalid window state '{state}'. Expected: maximize, minimize, restore.")

        # Resolve HWND
        hwnd: Optional[int] = None
        if isinstance(query_or_hwnd, int):
            hwnd = query_or_hwnd
        else:
            matched = cls.find_window(query_or_hwnd)
            if matched:
                hwnd = matched["hwnd"]

        if not hwnd or not user32.IsWindow(hwnd):
            logger.warning(f"Window '{query_or_hwnd}' not found.")
            return False

        try:
            user32.ShowWindow(hwnd, cmd)
            if cmd in (SW_MAXIMIZE, SW_RESTORE):
                cls.focus_window(hwnd)
            return True
        except Exception as exc:
            logger.error(f"Failed to set window state for {hwnd}: {exc}", exc_info=True)
            return False

    @classmethod
    def close_window(cls, query_or_hwnd: Union[str, int]) -> bool:
        """
        Gracefully request target window to close by posting WM_CLOSE.
        Strictly enforces system blacklist protection (PID 0, PID 4, explorer.exe, and active IRIS process).
        """
        matched = cls.find_window(query_or_hwnd)
        if not matched:
            raise LookupError(f"Window matching '{query_or_hwnd}' not found.")

        hwnd = matched["hwnd"]
        pid = matched["pid"]
        proc_name = (matched.get("process_name") or "").lower()
        base_name = proc_name.removesuffix(".exe")

        # 1. System blacklist safety verification
        if pid <= 4:
            raise PermissionError(
                f"SECURITY_DENIED: Cannot close window belonging to core system process (PID {pid})."
            )

        if pid == os.getpid():
            raise PermissionError(
                f"SECURITY_DENIED: Cannot close window belonging to the active IRIS runtime process (PID {pid})."
            )

        if (
            proc_name in DesktopEnvironment.PROTECTED_SYSTEM_PROCESSES
            or base_name in DesktopEnvironment.PROTECTED_SYSTEM_PROCESSES
        ):
            raise PermissionError(
                f"SECURITY_DENIED: Cannot close window belonging to protected system process '{proc_name}' (PID {pid})."
            )

        if os.name != "nt":
            logger.debug("Window close message posting only supported on Windows.")
            return False

        try:
            import ctypes
            user32 = ctypes.windll.user32
            # PostMessageW is non-blocking and prompts application to cleanly exit
            res = user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            logger.info(f"Posted WM_CLOSE to window {hwnd} ('{matched.get('title')}', PID {pid})")
            return bool(res)
        except Exception as exc:
            logger.error(f"Error posting WM_CLOSE to window {hwnd}: {exc}", exc_info=True)
            raise RuntimeError(f"Failed to close window {hwnd}: {exc}")
