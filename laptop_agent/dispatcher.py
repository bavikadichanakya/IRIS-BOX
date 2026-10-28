from __future__ import annotations
import asyncio
import json
import time
import logging
from typing import Any, Dict, Optional

from laptop_agent.tools.app_control import AppControl
from laptop_agent.tools.browser_control import BrowserControl
from laptop_agent.tools.system_control import SystemControl
from laptop_agent.tools.media_control import MediaControl
from laptop_agent.tools.universal_operator import UniversalOperator

logger = logging.getLogger("iris.laptop_agent.dispatcher")


def redact_sensitive_args(args: Dict[str, Any]) -> Dict[str, Any]:
    """Redacts tokens, passwords, and sensitive keys from log output."""
    sensitive_keys = {"token", "password", "key", "secret", "auth", "credential", "auth_token"}
    safe = {}
    for k, v in args.items():
        if any(s in str(k).lower() for s in sensitive_keys):
            safe[k] = "[REDACTED]"
        elif isinstance(v, str) and (v.startswith("cfm_") or v.startswith("stk_")):
            safe[k] = f"{v[:6]}...[REDACTED]"
        else:
            safe[k] = v
    return safe


class ToolDispatcher:
    """
    Central command dispatcher for the laptop agent.
    Normalizes incoming JSON requests, routes to the corresponding tool handler,
    enforces fail-fast compound execution, and returns standardized execution receipts.
    """

    def __init__(self, device_name: str = "laptop1"):
        self.device_name = device_name

    async def dispatch(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Process an incoming tool call payload."""
        start_time = time.perf_counter()

        # Check target device filter
        target_device = payload.get("device")
        if target_device and target_device != "*" and target_device != self.device_name:
            return {
                "success": False,
                "ignored": True,
                "reason": f"Payload targeted for '{target_device}', but this agent is '{self.device_name}'"
            }

        # Check for batch / compound multi-step action chain
        if "actions" in payload and isinstance(payload["actions"], list):
            step_results = []
            continue_on_error = bool(payload.get("continue_on_error", False))
            for idx, step in enumerate(payload["actions"]):
                step["device"] = self.device_name
                step_res = await self.dispatch(step)
                step_results.append(step_res)
                
                # Fail-fast by default to prevent state desynchronization
                if not step_res.get("success", False) and not continue_on_error:
                    logger.warning(
                        f"[{self.device_name}] Compound action step {idx + 1} ('{step.get('tool')}') failed. "
                        f"Aborting subsequent {len(payload['actions']) - idx - 1} steps."
                    )
                    for remaining in payload["actions"][idx + 1:]:
                        step_results.append({
                            "success": False,
                            "skipped": True,
                            "tool": remaining.get("tool", "unknown"),
                            "reason": f"Aborted: preceding step '{step.get('tool')}' failed",
                            "device": self.device_name,
                        })
                    break
                await asyncio.sleep(0.3)

            return {
                "success": all(r.get("success", False) for r in step_results if not r.get("skipped")),
                "device": self.device_name,
                "tool": "batch_actions",
                "steps_count": len(step_results),
                "results": step_results,
                "duration_ms": round((time.perf_counter() - start_time) * 1000.0, 2)
            }

        tool_name = (payload.get("tool") or payload.get("action") or "").strip().lower()
        args = payload.get("args") or payload.get("arguments") or {}

        # If payload itself has parameters directly at the root
        if not args and any(k for k in payload if k not in ("device", "tool", "action", "id", "type")):
            args = {k: v for k, v in payload.items() if k not in ("device", "tool", "action", "id", "type")}

        logger.info(f"[{self.device_name}] Dispatching tool '{tool_name}' with args {redact_sensitive_args(args)}")

        try:
            # 0. Universal Operator Primitives (Works on ANY app or website)
            if tool_name in ("open_or_switch", "open", "switch_to", "focus"):
                target = args.get("target") or args.get("app") or args.get("name") or args.get("url") or ""
                result = await UniversalOperator.open_or_switch(target)

            elif tool_name in ("new_chat", "new_tab", "new_window", "new_file"):
                result = await UniversalOperator.new_chat_or_tab()

            elif tool_name in ("type_and_send", "send_message", "prompt"):
                text = args.get("text") or args.get("prompt") or ""
                submit = bool(args.get("submit", True))
                target_field = args.get("target_field") or args.get("selector")
                result = await UniversalOperator.type_and_send(text, submit=submit, target_field=target_field)

            elif tool_name in ("click_label", "click_text", "click_button"):
                label = args.get("label") or args.get("text") or args.get("name") or ""
                result = await UniversalOperator.click_element(label)

            elif tool_name in ("hotkey", "shortcut", "send_keys"):
                combo = args.get("combo") or args.get("key") or args.get("shortcut") or ""
                result = UniversalOperator.send_hotkey(combo)

            elif tool_name in ("get_active_context", "active_context", "where_am_i"):
                result = UniversalOperator.get_active_context()

            # 1. Media & Streaming Control (Step-by-step or compound)
            elif tool_name in ("open_youtube", "open_spotify", "open_apple_music", "open_service"):
                service = "youtube"
                if "spotify" in tool_name:
                    service = "spotify"
                elif "apple" in tool_name:
                    service = "apple_music"
                else:
                    service = args.get("service") or "youtube"
                result = await MediaControl.open_service(service)

            elif tool_name in ("search_youtube", "search_media", "search_music"):
                query = args.get("query") or args.get("text") or ""
                service = args.get("service")
                result = await MediaControl.search(query, service=service)

            elif tool_name in ("play_video", "play_nth"):
                nth = int(args.get("nth") or args.get("n") or 1)
                result = await MediaControl.play_video(nth=nth)

            elif tool_name in ("play_short", "play_shorts"):
                nth = int(args.get("nth") or args.get("n") or 1)
                result = await MediaControl.play_short(nth=nth)

            elif tool_name in ("fullscreen", "video_fullscreen", "toggle_fullscreen"):
                result = await MediaControl.toggle_fullscreen()

            elif tool_name in ("theater_mode", "toggle_theater_mode"):
                result = await MediaControl.toggle_theater_mode()

            elif tool_name in ("skip_ad", "skip_ads"):
                result = await MediaControl.skip_ad()

            elif tool_name in ("scroll", "scroll_down", "scroll_up"):
                direction = "up" if "up" in tool_name else args.get("direction", "down")
                amount = int(args.get("amount", 600))
                result = await MediaControl.scroll(direction=direction, amount=amount)

            elif tool_name in ("play_pause", "toggle_play"):
                result = await MediaControl.play_pause()

            elif tool_name in ("next_track", "next_video", "skip_track"):
                result = await MediaControl.next_track()

            elif tool_name in ("play_music", "play_song", "play_music_chain"):
                service = args.get("service") or "youtube"
                query = args.get("query") or args.get("song") or "soothing songs"
                nth = int(args.get("nth") or 1)
                fullscreen = bool(args.get("fullscreen", True))
                is_short = bool(args.get("is_short", False))
                result = await MediaControl.play_music_chain(
                    service=service, query=query, nth=nth, fullscreen=fullscreen, is_short=is_short
                )

            # 2. Application & Window Automation
            elif tool_name in ("open_app", "launch_app", "start_app"):
                name = args.get("name") or args.get("app") or ""
                app_args = args.get("args")
                result = AppControl.open_app(name, app_args)

            elif tool_name in ("focus_window", "switch_window", "bring_to_front"):
                query = args.get("query") or args.get("window") or args.get("title") or ""
                result = AppControl.focus_window(query)

            elif tool_name in ("close_window", "kill_window"):
                query = args.get("query") or args.get("window") or args.get("title") or ""
                result = AppControl.close_window(query)

            elif tool_name in ("type_text", "type", "keyboard_type"):
                text = args.get("text") or args.get("input_text") or ""
                press_enter = bool(args.get("press_enter", False))
                result = AppControl.type_text(text, press_enter=press_enter)

            elif tool_name in ("press_key", "key", "hotkey"):
                key = args.get("key") or ""
                result = AppControl.press_key(key)

            elif tool_name in ("volume", "control_volume", "set_volume"):
                action = args.get("action") or args.get("direction") or "up"
                steps = int(args.get("steps", 2))
                result = AppControl.control_volume(action, steps)

            elif tool_name in ("list_windows", "get_windows"):
                windows = AppControl.list_windows()
                result = {"success": True, "count": len(windows), "windows": windows}

            # 3. Web Browser Automation
            elif tool_name in ("browser_open", "open_url", "goto", "navigate"):
                url = args.get("url") or args.get("destination") or ""
                result = await BrowserControl.open_url(url)

            elif tool_name in ("browser_search", "web_search", "search"):
                query = args.get("query") or args.get("text") or ""
                engine = args.get("engine") or "google"
                result = await BrowserControl.search_web(query, engine)

            elif tool_name in ("youtube_play", "youtube_search"):
                query = args.get("query") or ""
                nth = int(args.get("nth") or args.get("n") or 1)
                fullscreen = bool(args.get("fullscreen", False))
                result = await BrowserControl.youtube_search_and_play(query, nth=nth, fullscreen=fullscreen)

            elif tool_name in ("claude_send", "open_claude", "claude_prompt"):
                prompt = args.get("prompt") or args.get("text") or ""
                result = await BrowserControl.claude_send(prompt)

            elif tool_name in ("browser_type", "type_and_submit"):
                text = args.get("text") or ""
                selector = args.get("selector")
                press_enter = bool(args.get("press_enter", True))
                result = await BrowserControl.type_and_submit(text, selector=selector, press_enter=press_enter)

            elif tool_name in ("click_element", "click"):
                selector = args.get("selector") or ""
                result = await BrowserControl.click_element(selector)

            # 4. System Observability & Shell Commands
            elif tool_name in ("system_status", "status", "metrics"):
                result = SystemControl.get_status()

            elif tool_name in ("run_command", "shell", "terminal", "exec"):
                cmd = args.get("command") or args.get("cmd") or ""
                timeout = float(args.get("timeout", 15.0))
                result = SystemControl.run_command(cmd, timeout)

            else:
                result = {
                    "success": False,
                    "error": f"Unknown tool '{tool_name}'",
                    "available_tools": [
                        "open_youtube", "open_spotify", "open_apple_music", "search_youtube",
                        "play_video", "play_short", "fullscreen", "theater_mode", "skip_ad",
                        "scroll", "play_pause", "next_track", "play_music", "open_app",
                        "focus_window", "close_window", "type_text", "press_key", "volume",
                        "browser_open", "browser_search", "claude_send", "system_status"
                    ]
                }

        except Exception as exc:
            logger.error(f"Error handling tool '{tool_name}': {exc}", exc_info=True)
            result = {"success": False, "error": str(exc)}

        duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        result["device"] = self.device_name
        result["tool"] = tool_name
        result["duration_ms"] = duration_ms
        return result
