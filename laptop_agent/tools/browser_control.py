from __future__ import annotations
import os
import time
import logging
import urllib.parse
from typing import Any, Dict, Optional
from laptop_agent.tools.app_control import AppControl

logger = logging.getLogger("iris.laptop_agent.browser_control")


class BrowserControl:
    """
    Intelligent Browser Automation Controller:
    - Maintains a persistent interactive browser window (headed Chromium) with persistent profile.
    - Keeps logins (Claude, YouTube, Google, GitHub, etc.) intact without bot re-challenges.
    - Supports opening ANY URL, searching ANY engine, clicking elements, and typing into textareas.
    """

    _playwright = None
    _context = None
    _page = None
    _profile_dir: Optional[str] = None

    @classmethod
    async def get_page(cls, profile_dir: Optional[str] = None):
        """Get or initialize persistent interactive browser session."""
        if cls._page and not cls._page.is_closed():
            return cls._page

        from playwright.async_api import async_playwright

        if not cls._playwright:
            cls._playwright = await async_playwright().start()

        if not profile_dir:
            profile_dir = cls._profile_dir or os.path.expanduser("~/.iris_browser_profile")
        cls._profile_dir = profile_dir
        os.makedirs(profile_dir, exist_ok=True)

        logger.info(f"Launching persistent browser context at {profile_dir}...")
        cls._context = await cls._playwright.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=False,  # Visible interactive window on the user's laptop
            args=[
                "--start-maximized",
                "--no-default-browser-check",
                "--disable-blink-features=AutomationControlled",
            ],
            viewport=None,
        )

        pages = cls._context.pages
        cls._page = pages[0] if pages else await cls._context.new_page()
        return cls._page

    @classmethod
    async def open_url(cls, url: str) -> Dict[str, Any]:
        """Open any URL in the persistent browser."""
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url

        try:
            page = await cls.get_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            title = await page.title()
            return {
                "success": True,
                "url": url,
                "title": title,
                "message": f"Opened {url} ('{title}')"
            }
        except Exception as exc:
            logger.error(f"Failed to open URL {url}: {exc}")
            # Fallback to system default browser
            try:
                import webbrowser
                webbrowser.open(url)
                return {
                    "success": True,
                    "url": url,
                    "fallback": "default_browser",
                    "message": f"Opened {url} in system default browser"
                }
            except Exception as f_exc:
                return {"success": False, "error": f"{exc} | Fallback: {f_exc}"}

    @classmethod
    async def search_web(cls, query: str, engine: str = "google") -> Dict[str, Any]:
        """Search any web engine (google, youtube, duckduckgo, bing)."""
        engine_lower = engine.strip().lower()
        q_enc = urllib.parse.quote_plus(query)

        if "youtube" in engine_lower:
            url = f"https://www.youtube.com/results?search_query={q_enc}"
        elif "duck" in engine_lower:
            url = f"https://duckduckgo.com/?q={q_enc}"
        elif "bing" in engine_lower:
            url = f"https://www.bing.com/search?q={q_enc}"
        else:
            url = f"https://www.google.com/search?q={q_enc}"

        res = await cls.open_url(url)
        res["query"] = query
        res["engine"] = engine
        return res

    @classmethod
    async def youtube_search_and_play(cls, query: str, nth: int = 1, fullscreen: bool = False) -> Dict[str, Any]:
        """
        Specialized YouTube automation:
        1. Opens YouTube search results for query.
        2. Clicks the nth video.
        3. Optionally toggles fullscreen (presses 'f').
        """
        try:
            page = await cls.get_page()
            q_enc = urllib.parse.quote_plus(query)
            search_url = f"https://www.youtube.com/results?search_query={q_enc}"
            await page.goto(search_url, wait_until="domcontentloaded", timeout=15000)

            # Wait for video renderers
            selector = "ytd-video-renderer #video-title, ytd-rich-item-renderer #video-title"
            await page.wait_for_selector(selector, timeout=10000)

            videos = await page.query_selector_all(selector)
            if not videos:
                return {"success": False, "message": "No videos found in YouTube search results"}

            target_idx = max(0, min(nth - 1, len(videos) - 1))
            target_video = videos[target_idx]
            video_title = await target_video.get_attribute("title") or await target_video.inner_text()

            await target_video.click()
            time.sleep(1.0)

            if fullscreen:
                await page.keyboard.press("f")

            return {
                "success": True,
                "query": query,
                "played_nth": nth,
                "video_title": video_title.strip() if video_title else "video",
                "fullscreen": fullscreen,
                "message": f"Playing result #{nth}: '{video_title.strip() if video_title else 'video'}'"
            }
        except Exception as exc:
            logger.error(f"YouTube play failed: {exc}")
            # Fallback: search and focus
            await cls.search_web(query, engine="youtube")
            return {"success": False, "error": str(exc), "message": f"Opened YouTube search for '{query}'"}

    @classmethod
    async def claude_send(cls, prompt: str) -> Dict[str, Any]:
        """
        Specialized Claude automation:
        1. Opens or focuses claude.ai.
        2. Locates the message input (contenteditable, textarea, or ProseMirror).
        3. Types the prompt and sends it.
        """
        try:
            page = await cls.get_page()
            if "claude.ai" not in page.url:
                await page.goto("https://claude.ai", wait_until="domcontentloaded", timeout=15000)
                time.sleep(1.5)

            # Claude uses contenteditable ProseMirror div or textarea
            selectors = [
                "div.ProseMirror",
                "div[contenteditable='true']",
                "textarea[placeholder*='How can Claude help']",
                "textarea[placeholder*='Reply']",
                "textarea",
            ]

            input_elem = None
            for sel in selectors:
                try:
                    input_elem = await page.wait_for_selector(sel, timeout=3000)
                    if input_elem:
                        break
                except Exception:
                    continue

            if input_elem:
                await input_elem.click()
                await input_elem.fill(prompt)
                time.sleep(0.2)
                # Press Enter or click the Send button
                await page.keyboard.press("Enter")
                return {
                    "success": True,
                    "prompt": prompt,
                    "message": f"Successfully sent prompt to Claude: '{prompt}'"
                }
            else:
                # If selectors fail (e.g. login screen or different DOM), focus and use native paste + enter
                AppControl.focus_window("Claude")
                AppControl.type_text(prompt, press_enter=True)
                return {
                    "success": True,
                    "prompt": prompt,
                    "fallback": "native_input",
                    "message": f"Typed prompt to active Claude window: '{prompt}'"
                }
        except Exception as exc:
            logger.error(f"Claude automation error: {exc}")
            return {"success": False, "error": str(exc)}

    @classmethod
    async def type_and_submit(cls, text: str, selector: Optional[str] = None, press_enter: bool = True) -> Dict[str, Any]:
        """
        Type text into any website element or input and submit.
        Works across any web app (Google Docs, ChatGPT, Claude, GitHub, Reddit, etc.).
        """
        try:
            page = await cls.get_page()
            if selector:
                elem = await page.wait_for_selector(selector, timeout=5000)
                if elem:
                    await elem.click()
                    await elem.fill(text)
            else:
                # Type into currently active element
                await page.keyboard.type(text)

            if press_enter:
                time.sleep(0.1)
                await page.keyboard.press("Enter")

            return {
                "success": True,
                "text": text,
                "press_enter": press_enter,
                "message": f"Typed '{text}'" + (" and submitted" if press_enter else "")
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    @classmethod
    async def click_element(cls, selector: str) -> Dict[str, Any]:
        """Click any DOM selector on the active page."""
        try:
            page = await cls.get_page()
            await page.click(selector, timeout=5000)
            return {"success": True, "selector": selector, "message": f"Clicked selector '{selector}'"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    @classmethod
    async def toggle_fullscreen(cls) -> Dict[str, Any]:
        """Toggle video fullscreen / theater mode."""
        try:
            page = await cls.get_page()
            await page.keyboard.press("f")
            return {"success": True, "message": "Toggled fullscreen (pressed 'f')"}
        except Exception as exc:
            return AppControl.press_key("f")
