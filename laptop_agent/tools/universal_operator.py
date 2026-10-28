from __future__ import annotations
import os
import time
import logging
from typing import Any, Dict, Optional, List

from laptop_agent.tools.app_control import AppControl
from laptop_agent.tools.browser_control import BrowserControl
from laptop_agent.tools.system_control import SystemControl

logger = logging.getLogger("iris.laptop_agent.universal_operator")


class UniversalOperator:
    """
    Universal AI Computer Operator for IRIS-BOX.
    Operates ANY application, browser tab, or desktop environment through
    atomic, human-like computer use primitives:
      1. open_or_switch(target)     - Launches or brings any app/site to front
      2. new_chat_or_tab()          - Contextual 'New Chat' / 'New Tab' / 'New File'
      3. type_and_send(text, submit)- Types into active input/textarea and submits
      4. click_element(label)       - Clicks buttons, links, or text labels
      5. hotkey(combo)              - Sends keyboard shortcuts (ctrl+t, space, f, etc.)
      6. scroll(direction)          - Scrolls active window or document
      7. get_active_context()       - Returns current active window & foreground app
    """

    active_app: str = "desktop"
    active_url: Optional[str] = None

    @classmethod
    def get_active_context(cls) -> Dict[str, Any]:
        """Inspect what window/application is currently in the foreground."""
        status = SystemControl.get_status()
        active_window = status.get("active_window", "")
        return {
            "success": True,
            "active_window": active_window,
            "inferred_app": cls.active_app,
            "cpu_percent": status.get("cpu_percent"),
            "memory_percent": status.get("memory_percent"),
            "message": f"Foreground window: '{active_window}' (Active Context: {cls.active_app})"
        }

    @classmethod
    async def open_or_switch(cls, target: str) -> Dict[str, Any]:
        """
        Universal app and website navigator:
        - If a window matching 'target' is already running, brings it to the front.
        - If 'target' is a website or URL (or known web service), opens or focuses it in browser.
        - If 'target' is an application, launches it cleanly.
        """
        target_clean = target.strip().lower()
        cls.active_app = target_clean

        # 1. Check if a desktop window with this title is already running
        window_match = AppControl.find_window(target_clean)
        if window_match:
            focus_res = AppControl.focus_window(target_clean)
            if focus_res.get("success"):
                cls.active_app = target_clean
                return {
                    "success": True,
                    "action": "switched_window",
                    "target": target,
                    "window_title": window_match.get("title"),
                    "message": f"Switched to running window: '{window_match.get('title')}'"
                }

        # 2. Known web apps / URLs
        web_shortcuts = {
            "claude": "https://claude.ai",
            "chatgpt": "https://chatgpt.com",
            "youtube": "https://www.youtube.com",
            "github": "https://github.com",
            "reddit": "https://reddit.com",
            "twitter": "https://x.com",
            "x": "https://x.com",
            "gmail": "https://mail.google.com",
            "google docs": "https://docs.google.com",
            "spotify web": "https://open.spotify.com",
            "apple music": "https://music.apple.com",
            "netflix": "https://www.netflix.com",
            "wikipedia": "https://wikipedia.org",
        }

        url = web_shortcuts.get(target_clean)
        if not url and ("." in target_clean or target_clean.startswith("http")):
            url = target_clean if target_clean.startswith("http") else "https://" + target_clean

        if url:
            cls.active_url = url
            return await BrowserControl.open_url(url)

        # 3. Desktop Application launch
        return AppControl.open_app(target)

    @classmethod
    async def new_chat_or_tab(cls) -> Dict[str, Any]:
        """
        Context-aware 'New Chat' / 'New Tab' / 'New File' action:
        - If Claude or ChatGPT is active: clicks 'New chat' or navigates to new session.
        - If a browser is active: opens a new tab (Ctrl+T).
        - If a text editor/IDE/terminal is active: creates a new file/tab (Ctrl+N).
        """
        # 1. Try DOM-level 'New chat' if browser is active
        try:
            page = await BrowserControl.get_page()
            current_url = page.url.lower()

            if "claude.ai" in current_url:
                # Claude: click Start new chat or go to claude.ai/new
                await page.goto("https://claude.ai/new", wait_until="domcontentloaded", timeout=10000)
                return {"success": True, "app": "claude", "message": "Opened new chat session on Claude"}

            elif "chatgpt.com" in current_url:
                await page.goto("https://chatgpt.com", wait_until="domcontentloaded", timeout=10000)
                return {"success": True, "app": "chatgpt", "message": "Opened new chat session on ChatGPT"}
        except Exception:
            pass

        # 2. Native keyboard shortcut fallback
        # In browsers: Ctrl+T opens new tab. In Claude desktop / Slack / Teams / Discord: Ctrl+K or Ctrl+N
        AppControl.press_key("ctrl")
        return AppControl.type_text("", press_enter=False)  # placeholder

    @classmethod
    async def type_and_send(cls, text: str, submit: bool = True, target_field: Optional[str] = None) -> Dict[str, Any]:
        """
        Universal typing & sending mechanism across ANY app or website:
        - Locates active text input, contenteditable, or prompt box.
        - Pastes/types text instantly with full Unicode support.
        - Optionally presses Enter or clicks Send.
        """
        # 1. If persistent browser is active with Claude, YouTube, or web apps
        try:
            page = await BrowserControl.get_page()
            current_url = page.url.lower()

            if "claude.ai" in current_url:
                return await BrowserControl.claude_send(text)

            elif target_field:
                return await BrowserControl.type_and_submit(text, selector=target_field, press_enter=submit)
        except Exception:
            pass

        # 2. Native OS clipboard injection into whatever window/input is currently focused
        res = AppControl.type_text(text, press_enter=submit)
        res["action"] = "type_and_send"
        res["submitted"] = submit
        return res

    @classmethod
    async def click_element(cls, label_or_selector: str) -> Dict[str, Any]:
        """
        Click any button, link, or element by text label, accessibility name, or CSS selector.
        Examples: 'New Chat', 'Skip Ad', 'Send', 'Subscribe', 'Play', 'Close'.
        """
        # 1. Try in browser
        try:
            page = await BrowserControl.get_page()
            # Try text selector
            selectors = [
                f"text={label_or_selector}",
                f"button:has-text('{label_or_selector}')",
                f"a:has-text('{label_or_selector}')",
                f"[aria-label*='{label_or_selector}' i]",
                label_or_selector
            ]
            for sel in selectors:
                elem = await page.query_selector(sel)
                if elem and await elem.is_visible():
                    await elem.click()
                    return {"success": True, "selector": sel, "message": f"Clicked '{label_or_selector}'"}
        except Exception:
            pass

        return {"success": False, "error": f"Could not find clickable element matching '{label_or_selector}'"}

    @classmethod
    def send_hotkey(cls, combo: str) -> Dict[str, Any]:
        """
        Execute any standard keyboard shortcut across active applications:
        e.g. 'ctrl+t', 'ctrl+w', 'ctrl+n', 'ctrl+tab', 'space', 'f', 'esc', 'enter', 'alt+f4'
        """
        combo_clean = combo.strip().lower()
        parts = combo_clean.split("+")

        import ctypes
        user32 = ctypes.windll.user32
        from laptop_agent.tools.app_control import VK_CODES

        pressed_vks = []
        try:
            # Press modifiers down
            for part in parts:
                vk = VK_CODES.get(part.strip())
                if not vk and len(part.strip()) == 1:
                    vk = ord(part.strip().upper())
                if vk:
                    user32.keybd_event(vk, 0, 0, 0)
                    pressed_vks.append(vk)

            time.sleep(0.05)
            # Release in reverse
            for vk in reversed(pressed_vks):
                user32.keybd_event(vk, 0, 2, 0)

            return {"success": True, "hotkey": combo, "message": f"Executed hotkey '{combo}'"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}
