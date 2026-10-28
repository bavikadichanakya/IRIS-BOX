import asyncio
import os
import time
import logging
import urllib.parse
from typing import Any, Dict, Optional, List

from laptop_agent.tools.app_control import AppControl
from laptop_agent.tools.browser_control import BrowserControl

logger = logging.getLogger("iris.laptop_agent.media_control")


class MediaControl:
    """
    Intelligent Media & Entertainment Controller.
    Supports granular step-by-step actions (open -> search -> scroll -> select -> fullscreen -> skip ads)
    across YouTube, Spotify, Apple Music, and other streaming services.
    """

    # Track active media context for multi-turn conversational follow-ups
    active_service: str = "youtube"

    @classmethod
    async def open_service(cls, service: str = "youtube") -> Dict[str, Any]:
        """Open a streaming service (YouTube, Spotify, Apple Music, Netflix)."""
        service_clean = service.strip().lower()
        cls.active_service = service_clean

        if "spotify" in service_clean:
            # Check if desktop Spotify is installed, otherwise open web player
            res = AppControl.open_app("spotify")
            if not res.get("success"):
                return await BrowserControl.open_url("https://open.spotify.com")
            return res

        elif "apple" in service_clean:
            return await BrowserControl.open_url("https://music.apple.com")

        elif "netflix" in service_clean:
            return await BrowserControl.open_url("https://www.netflix.com")

        else:
            # Default to YouTube
            cls.active_service = "youtube"
            # If Chrome is already open with YouTube, focus it; otherwise open it
            focus_res = AppControl.focus_window("YouTube")
            if focus_res.get("success"):
                return focus_res
            return await BrowserControl.open_url("https://www.youtube.com")

    @classmethod
    async def search(cls, query: str, service: Optional[str] = None) -> Dict[str, Any]:
        """
        Search inside the active or specified media service.
        Supports YouTube, Spotify, Apple Music.
        """
        target_service = (service or cls.active_service or "youtube").lower()
        cls.active_service = target_service
        q_enc = urllib.parse.quote_plus(query)

        if "spotify" in target_service:
            # Try Spotify desktop URI protocol first
            try:
                import subprocess
                subprocess.Popen(["cmd", "/c", f"start spotify:search:{q_enc}"], shell=True)
                return {"success": True, "service": "spotify", "query": query, "message": f"Searching Spotify for '{query}'"}
            except Exception:
                return await BrowserControl.open_url(f"https://open.spotify.com/search/{q_enc}")

        elif "apple" in target_service:
            return await BrowserControl.open_url(f"https://music.apple.com/us/search?term={q_enc}")

        else:
            # YouTube search
            cls.active_service = "youtube"
            # 1. Try DOM-level search if persistent browser is open
            try:
                page = await BrowserControl.get_page()
                if "youtube.com" in page.url:
                    search_input = await page.wait_for_selector("input#search", timeout=3000)
                    if search_input:
                        await search_input.click()
                        await search_input.fill(query)
                        await page.keyboard.press("Enter")
                        return {
                            "success": True,
                            "service": "youtube",
                            "query": query,
                            "message": f"Searched YouTube for '{query}'"
                        }
            except Exception:
                pass

            # 2. Try focusing active YouTube Chrome window and using YouTube's native '/' shortcut
            focus_res = AppControl.focus_window("YouTube")
            if focus_res.get("success"):
                time.sleep(0.1)
                AppControl.press_key("/")  # YouTube's native hotkey to focus search bar
                time.sleep(0.1)
                AppControl.type_text(query, press_enter=True)
                return {
                    "success": True,
                    "service": "youtube",
                    "query": query,
                    "message": f"Searched active YouTube window for '{query}'"
                }

            # 3. Direct URL fallback
            return await BrowserControl.open_url(f"https://www.youtube.com/results?search_query={q_enc}")

    @classmethod
    async def play_video(cls, nth: int = 1) -> Dict[str, Any]:
        """Play the nth regular video from current search results."""
        # 1. Try DOM click via Playwright
        try:
            page = await BrowserControl.get_page()
            selector = "ytd-video-renderer #video-title, ytd-rich-item-renderer #video-title"
            videos = await page.query_selector_all(selector)
            if videos:
                idx = max(0, min(nth - 1, len(videos) - 1))
                title = await videos[idx].get_attribute("title") or await videos[idx].inner_text()
                await videos[idx].click()
                return {
                    "success": True,
                    "played_nth": nth,
                    "title": title.strip() if title else "video",
                    "message": f"Playing video #{nth}: '{title.strip() if title else 'video'}'"
                }
        except Exception:
            pass

        # 2. Fallback to native window focus + keyboard navigation
        AppControl.focus_window("YouTube")
        # In YouTube search results, Tab moves to the first result
        for _ in range(max(1, nth)):
            AppControl.press_key("tab")
            time.sleep(0.05)
        AppControl.press_key("enter")

        return {"success": True, "played_nth": nth, "message": f"Selected video #{nth}"}

    @classmethod
    async def play_short(cls, nth: int = 1) -> Dict[str, Any]:
        """Play the nth YouTube Short from the search results or Shorts shelf."""
        cls.active_service = "youtube"
        try:
            page = await BrowserControl.get_page()
            # YouTube Shorts cards selectors
            selectors = [
                "ytd-reel-item-renderer a",
                "ytd-reel-video-renderer",
                "grid-shelf-renderer a#thumbnail",
                "a[href*='/shorts/']"
            ]
            for sel in selectors:
                shorts = await page.query_selector_all(sel)
                if shorts:
                    idx = max(0, min(nth - 1, len(shorts) - 1))
                    await shorts[idx].click()
                    return {
                        "success": True,
                        "played_short_nth": nth,
                        "message": f"Playing YouTube Short #{nth}"
                    }
        except Exception:
            pass

        # Fallback: Navigate directly to /shorts
        AppControl.focus_window("YouTube")
        return await BrowserControl.open_url("https://www.youtube.com/shorts")

    @classmethod
    async def toggle_fullscreen(cls) -> Dict[str, Any]:
        """
        Toggle native video player fullscreen.
        Uses YouTube's official player fullscreen button or 'f' hotkey (NOT browser F11 zoom).
        """
        # 1. Try clicking YouTube's official .ytp-fullscreen-button via DOM
        try:
            page = await BrowserControl.get_page()
            fs_btn = await page.query_selector(".ytp-fullscreen-button")
            if fs_btn:
                await fs_btn.click()
                return {
                    "success": True,
                    "method": "ytp-fullscreen-button",
                    "message": "Activated YouTube native player fullscreen"
                }
        except Exception:
            pass

        # 2. Native Window Fallback: Focus YouTube window and send 'f'
        focus_res = AppControl.focus_window("YouTube")
        if not focus_res.get("success"):
            # Try focusing Chrome
            AppControl.focus_window("Chrome")

        time.sleep(0.1)
        # In YouTube, pressing 'f' triggers native video player fullscreen
        AppControl.press_key("f")

        return {
            "success": True,
            "method": "player_hotkey_f",
            "message": "Toggled native video fullscreen (pressed 'f')"
        }

    @classmethod
    async def toggle_theater_mode(cls) -> Dict[str, Any]:
        """Toggle YouTube theater mode (presses 't' or clicks .ytp-size-button)."""
        try:
            page = await BrowserControl.get_page()
            btn = await page.query_selector(".ytp-size-button")
            if btn:
                await btn.click()
                return {"success": True, "message": "Toggled theater mode"}
        except Exception:
            pass

        AppControl.focus_window("YouTube")
        AppControl.press_key("t")
        return {"success": True, "message": "Toggled theater mode (pressed 't')"}

    @classmethod
    async def skip_ad(cls) -> Dict[str, Any]:
        """
        Detect and click YouTube ad skip buttons.
        Works across all YouTube ad button classes (.ytp-skip-ad-button, .ytp-ad-skip-button-modern, etc.).
        """
        try:
            page = await BrowserControl.get_page()
            skip_selectors = [
                ".ytp-skip-ad-button",
                ".ytp-ad-skip-button-modern",
                ".ytp-ad-skip-button",
                "button.ytp-ad-skip-button-modern",
                ".videoAdUiSkipButton"
            ]
            for sel in skip_selectors:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    return {"success": True, "message": "Successfully clicked Skip Ad"}
        except Exception:
            pass

        # Try focusing window and pressing Tab + Enter on active ad button
        AppControl.focus_window("YouTube")
        return {"success": True, "message": "Attempted ad skip on active player"}

    @classmethod
    async def scroll(cls, direction: str = "down", amount: int = 600) -> Dict[str, Any]:
        """
        Smoothly scroll the active web page or application up or down.
        """
        direction_clean = direction.strip().lower()
        delta = amount if direction_clean in ("down", "bottom") else -amount

        # 1. Try DOM smooth scroll
        try:
            page = await BrowserControl.get_page()
            await page.evaluate(f"window.scrollBy({{top: {delta}, behavior: 'smooth'}})")
            return {"success": True, "direction": direction_clean, "amount": amount, "message": f"Scrolled {direction_clean}"}
        except Exception:
            pass

        # 2. Native Window Fallback (PageDown / PageUp)
        AppControl.focus_window("YouTube")
        key = "pagedown" if direction_clean in ("down", "bottom") else "pageup"
        AppControl.press_key(key)
        return {"success": True, "direction": direction_clean, "method": key, "message": f"Scrolled {direction_clean}"}

    @classmethod
    async def play_pause(cls) -> Dict[str, Any]:
        """Toggle play/pause on the active video/music player."""
        try:
            page = await BrowserControl.get_page()
            play_btn = await page.query_selector(".ytp-play-button")
            if play_btn:
                await play_btn.click()
                return {"success": True, "message": "Toggled play/pause"}
        except Exception:
            pass

        AppControl.focus_window("YouTube")
        AppControl.press_key("k")  # YouTube's reliable play/pause hotkey
        return {"success": True, "message": "Toggled play/pause (pressed 'k')"}

    @classmethod
    async def next_track(cls) -> Dict[str, Any]:
        """Skip to the next video or track."""
        AppControl.focus_window("YouTube")
        # Shift + N in YouTube plays next video
        import ctypes
        user32 = ctypes.windll.user32
        VK_SHIFT = 0x10
        VK_N = 0x4E
        user32.keybd_event(VK_SHIFT, 0, 0, 0)
        user32.keybd_event(VK_N, 0, 0, 0)
        time.sleep(0.05)
        user32.keybd_event(VK_N, 0, 2, 0)
        user32.keybd_event(VK_SHIFT, 0, 2, 0)
        return {"success": True, "message": "Skipped to next video"}

    @classmethod
    async def play_music_chain(
        cls,
        service: str = "youtube",
        query: str = "soothing songs",
        nth: int = 1,
        fullscreen: bool = True,
        is_short: bool = False
    ) -> Dict[str, Any]:
        """
        Execute an all-in-one compound command:
        Open service -> Search query -> Select video or short -> Enter native fullscreen.
        """
        logger.info(f"Executing compound media chain: {service} -> '{query}' -> #{nth} -> fs={fullscreen}")
        await cls.open_service(service)
        await asyncio.sleep(1.0)

        await cls.search(query, service=service)
        await asyncio.sleep(2.0)

        if is_short:
            await cls.play_short(nth=nth)
        else:
            await cls.play_video(nth=nth)

        await asyncio.sleep(1.5)

        # Check for ad and try to skip
        await cls.skip_ad()

        if fullscreen:
            await cls.toggle_fullscreen()

        return {
            "success": True,
            "service": service,
            "query": query,
            "nth": nth,
            "fullscreen": fullscreen,
            "message": f"Playing '{query}' on {service.capitalize()} in native fullscreen."
        }
