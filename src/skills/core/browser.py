import logging
import time
from typing import Any, Dict, Optional

from src.models.schemas import BrowserAction
from src.security.policy import is_url_allowed
from src.skills.base import BaseSkill, SkillExecutionResult, SkillHealthResult, SkillManifest
from src.tools.capability import PermissionLevel

logger = logging.getLogger("iris.skills.browser")


class BrowserAutomationSkill(BaseSkill):
    """
    Core skill executing SSRF-restricted browser automation tasks via Playwright.
    """

    def __init__(self, headless: bool = True):
        self.headless = headless
        manifest = SkillManifest(
            name="BrowserAutomationSkill",
            version="1.0.0",
            description="Automate web browser interactions with SSRF defense and headless Chromium.",
            category="browser",
            permission_level=PermissionLevel.PROTECTED,
            requires_network=True,  # Interacts with web URLs
            timeout_seconds=30.0,
            parameters_schema=BrowserAction.model_json_schema(),
            supported_platforms=["windows", "linux", "darwin"],
        )
        super().__init__(manifest)

    async def check_health(self) -> SkillHealthResult:
        """Check if Playwright runtime is installed."""
        try:
            import playwright
            return SkillHealthResult(
                skill_name=self.name,
                healthy=True,
                message="Playwright browser engine is ready",
                details={"headless": self.headless}
            )
        except ImportError:
            return SkillHealthResult(
                skill_name=self.name,
                healthy=False,
                message="Playwright package is not installed",
                details={"install_hint": "pip install playwright && playwright install chromium"}
            )

    async def execute(
        self,
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> SkillExecutionResult:
        start_time = time.perf_counter()
        url = params.get("url", "")
        action = params.get("action", "goto")
        selector = params.get("selector")
        input_text = params.get("input_text")
        timeout_ms = params.get("timeout_ms", 10000)

        # 1. SSRF Restriction
        if url:
            allowed, reason = is_url_allowed(url)
            if not allowed:
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                return SkillExecutionResult(
                    success=False,
                    skill_name=self.name,
                    error=f"SSRF_BLOCKED: {reason}",
                    duration_ms=duration_ms
                )

        # 2. Check Playwright
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return SkillExecutionResult(
                success=False,
                skill_name=self.name,
                error="Playwright is not installed or headless browser binary is missing.",
                duration_ms=duration_ms
            )

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=self.headless)
                page = await browser.new_page()
                output = {"action_performed": action, "url": url}

                if action in ("goto", "navigate"):
                    if not url:
                        await browser.close()
                        return SkillExecutionResult(
                            success=False,
                            skill_name=self.name,
                            error="URL is required for navigate action.",
                            duration_ms=(time.perf_counter() - start_time) * 1000.0
                        )
                    await page.goto(url, timeout=timeout_ms)
                    output["title"] = await page.title()
                elif action == "click":
                    if url:
                        await page.goto(url, timeout=timeout_ms)
                    if not selector:
                        await browser.close()
                        return SkillExecutionResult(
                            success=False,
                            skill_name=self.name,
                            error="Selector is required for click action.",
                            duration_ms=(time.perf_counter() - start_time) * 1000.0
                        )
                    await page.click(selector, timeout=timeout_ms)
                    output["clicked_selector"] = selector
                elif action == "type_text":
                    if url:
                        await page.goto(url, timeout=timeout_ms)
                    if not selector:
                        await browser.close()
                        return SkillExecutionResult(
                            success=False,
                            skill_name=self.name,
                            error="Selector is required for type_text action.",
                            duration_ms=(time.perf_counter() - start_time) * 1000.0
                        )
                    await page.fill(selector, input_text or "", timeout=timeout_ms)
                    output["filled_selector"] = selector
                elif action in ("extract", "extract_text"):
                    if url:
                        await page.goto(url, timeout=timeout_ms)
                    if selector:
                        output["text"] = await page.inner_text(selector, timeout=timeout_ms)
                    else:
                        output["text"] = await page.inner_text("body", timeout=timeout_ms)
                elif action == "screenshot":
                    if url:
                        await page.goto(url, timeout=timeout_ms)
                    screenshot_bytes = await page.screenshot()
                    output["screenshot_bytes_len"] = len(screenshot_bytes)

                await browser.close()
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                return SkillExecutionResult(
                    success=True,
                    skill_name=self.name,
                    output=output,
                    duration_ms=duration_ms
                )
        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return SkillExecutionResult(
                success=False,
                skill_name=self.name,
                error=f"Browser action failed: {exc}",
                duration_ms=duration_ms
            )
