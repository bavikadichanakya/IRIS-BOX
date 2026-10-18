from __future__ import annotations
import os
import psutil
import pytest
from starlette.testclient import TestClient

from src.models.schemas import WindowAutomationAction
from src.operator.app_launcher import AppLauncher
from src.operator.desktop import DesktopEnvironment
from src.operator.window_manager import WindowManager
from src.operator.summarizer import OperatorSummarizer
from src.security import auth_manager
from src.server.app import app
from src.skills.core.window_skill import WindowAutomationSkill
from src.skills.registry import SkillRegistry
from src.tools.capability import PermissionLevel
from src.tools.registry import ToolRegistry, WindowAutomationTool


def test_app_launcher_discovery_and_fuzzy_matching():
    """Verify application discovery and alias resolution (notepad, calc, browser, code)."""
    known_apps = AppLauncher.list_known_apps()
    assert isinstance(known_apps, dict)
    assert len(known_apps) > 5

    # 1. Direct standard utilities
    notepad_bin = AppLauncher.find_app("notepad")
    assert notepad_bin is not None
    assert "notepad" in notepad_bin.lower()

    calc_bin = AppLauncher.find_app("calc")
    assert calc_bin is not None

    # 2. Alias resolution
    browser_bin = AppLauncher.find_app("browser")
    assert browser_bin is not None
    assert any(b in browser_bin.lower() for b in ("chrome", "msedge", "edge", "browser"))

    # 3. Fuzzy substring matching
    chrome_bin = AppLauncher.find_app("google chrome")
    assert chrome_bin is not None

    # 4. Unknown fake app returns None
    assert AppLauncher.find_app("fake_non_existent_app_xyz_99") is None


def test_window_manager_finding_logic():
    """Verify WindowManager locates active windows by HWND, partial title, and process name."""
    windows = DesktopEnvironment.get_visible_windows()
    if not windows:
        pytest.skip("No visible desktop windows found in current session.")

    first_win = windows[0]
    hwnd = first_win["hwnd"]
    title = first_win["title"]
    pname = first_win["process_name"]

    # 1. Match by HWND (int and string)
    assert WindowManager.find_window(hwnd) is not None
    assert WindowManager.find_window(str(hwnd)) is not None

    # 2. Match by exact title
    assert WindowManager.find_window(title) is not None

    # 3. Match by partial title substring
    if len(title) > 4:
        substring = title[:4]
        assert WindowManager.find_window(substring) is not None

    # 4. Match by process name (e.g. without .exe)
    clean_pname = pname.removesuffix(".exe")
    assert WindowManager.find_window(clean_pname) is not None


def test_window_manager_state_control():
    """Verify window state validation and safe window manipulation."""
    # Invalid state should raise ValueError
    with pytest.raises(ValueError):
        WindowManager.set_window_state(123456, "invalid_state_xyz")

    # Non-existent HWND returns False safely
    assert WindowManager.focus_window(99999999) is False
    assert WindowManager.set_window_state(99999999, "maximize") is False


def test_close_window_blacklist_safety_boundary():
    """Verify close_window strictly rejects closing protected core OS processes."""
    # 1. Direct protected system process (find explorer window if active)
    explorer_win = None
    for w in DesktopEnvironment.get_visible_windows():
        if "explorer" in w["process_name"].lower():
            explorer_win = w
            break

    if explorer_win:
        with pytest.raises(PermissionError) as exc_exp:
            WindowManager.close_window(explorer_win["hwnd"])
        assert "SECURITY_DENIED" in str(exc_exp.value)

    # 2. Close window for non-existent window raises LookupError
    with pytest.raises(LookupError):
        WindowManager.close_window(99999999)


def test_window_summarizer_voice_output():
    """Verify concise natural voice confirmations for window automation actions."""
    # 1. App Launch
    launch_ok = OperatorSummarizer.summarize_app_launch("spotify", True)
    assert launch_ok == "Launched Spotify."

    launch_fail = OperatorSummarizer.summarize_app_launch("nonexistent", False)
    assert "Could not find application matching" in launch_fail

    # 2. Window Focus
    focus_ok = OperatorSummarizer.summarize_window_focus("code", True, "Visual Studio Code")
    assert focus_ok == "Switched to Visual Studio Code."

    focus_fail = OperatorSummarizer.summarize_window_focus("slack", False)
    assert focus_fail == "Could not find a window matching 'slack'."

    # 3. Window State
    state_max = OperatorSummarizer.summarize_window_state("Spotify", "maximize", True)
    assert state_max == "Maximized Spotify."

    state_min = OperatorSummarizer.summarize_window_state("Spotify", "minimize", True)
    assert state_min == "Minimized Spotify."

    # 4. Window Close
    close_ok = OperatorSummarizer.summarize_window_close("Visual Studio Code", True)
    assert close_ok == "Closed Visual Studio Code."


@pytest.mark.asyncio
async def test_window_automation_skill():
    """Verify WindowAutomationSkill manifest, health, actions, and permission elevation."""
    skill = WindowAutomationSkill()
    assert skill.manifest.name == "window_automation"
    assert skill.manifest.permission_level == PermissionLevel.PROTECTED

    # 1. Health check
    health = await skill.check_health()
    assert health.healthy is True

    # 2. Close window without confirmation -> prompts confirmation (SENSITIVE tier)
    unconf_res = await skill.execute({"action": "close_window", "query": "notepad"}, context={})
    assert unconf_res.success is False
    assert "CONFIRMATION_REQUIRED" in unconf_res.error
    assert unconf_res.metadata.get("requires_confirmation") is True

    # 3. Close window targeting protected process with confirmation -> blocked
    explorer_win = None
    for w in DesktopEnvironment.get_visible_windows():
        if "explorer" in w["process_name"].lower():
            explorer_win = w
            break

    if explorer_win:
        blocked_res = await skill.execute(
            {"action": "close_window", "hwnd": explorer_win["hwnd"]},
            context={"confirmed": True},
        )
        assert blocked_res.success is False
        assert "SECURITY_DENIED" in blocked_res.error


def test_window_automation_tool_registry():
    """Verify tool registration and execution in ToolRegistry."""
    tool = ToolRegistry.get_tool("WindowAutomationTool")
    assert isinstance(tool, WindowAutomationTool)

    # 1. Missing target parameter for focus
    res_err = tool.execute(WindowAutomationAction(action="focus_window"))
    assert res_err.success is False

    # 2. Close on protected system window
    explorer_win = None
    for w in DesktopEnvironment.get_visible_windows():
        if "explorer" in w["process_name"].lower():
            explorer_win = w
            break

    if explorer_win:
        res_sec = tool.execute(WindowAutomationAction(action="close_window", hwnd=explorer_win["hwnd"]))
        assert res_sec.success is False
        assert "SECURITY_DENIED" in res_sec.error


def test_window_automation_rest_endpoints():
    """Verify REST API routes for application launching, window focus, state, and close."""
    api_key = auth_manager.get_master_key()
    headers = {"Authorization": f"Bearer {api_key}"}

    with TestClient(app) as client:
        # 1. Unauthenticated request -> 401
        assert client.post("/api/desktop/apps/launch", json={"app_name": "notepad"}).status_code == 401

        # 2. Launch non-existent app -> 404
        bad_launch = client.post(
            "/api/desktop/apps/launch",
            json={"app_name": "fake_non_existent_app_999"},
            headers=headers,
        )
        assert bad_launch.status_code == 404

        # 3. State change with invalid state -> 400
        bad_state = client.post(
            "/api/desktop/windows/state",
            json={"query": "notepad", "state": "invalid_mode_xyz"},
            headers=headers,
        )
        assert bad_state.status_code == 400

        # 4. Close protected process (explorer) -> 403 Forbidden
        for w in DesktopEnvironment.get_visible_windows():
            if "explorer" in w["process_name"].lower():
                close_res = client.post(
                    "/api/desktop/windows/close",
                    json={"hwnd": w["hwnd"]},
                    headers=headers,
                )
                assert close_res.status_code == 403
                assert "SECURITY_DENIED" in close_res.json()["detail"]
                break
