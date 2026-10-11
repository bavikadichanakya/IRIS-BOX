import asyncio
import os
import pytest
from starlette.testclient import TestClient

from src.server.app import app
from src.security.auth import auth_manager
from src.observability.event_bus import EventBus
from src.skills.base import (
    BaseSkill,
    SkillManifest,
    SkillExecutionResult,
    SkillHealthResult,
)
from src.skills.registry import SkillRegistry
from src.skills.core.system_command import SystemCommandSkill
from src.skills.core.browser import BrowserAutomationSkill
from src.skills.core.home_assistant import HomeAssistantSkill
from src.tools.capability import PermissionLevel


class DummySlowSkill(BaseSkill):
    def __init__(self):
        super().__init__(
            SkillManifest(
                name="DummySlowSkill",
                description="Intentionally sleeps past timeout",
                permission_level=PermissionLevel.PUBLIC,
                requires_network=False,
                timeout_seconds=0.1,
            )
        )

    async def execute(self, params, context=None):
        await asyncio.sleep(0.5)
        return SkillExecutionResult(success=True, skill_name=self.name, output="done")

    async def check_health(self):
        return SkillHealthResult(skill_name=self.name, healthy=True)


class DummyNetworkSkill(BaseSkill):
    def __init__(self):
        super().__init__(
            SkillManifest(
                name="DummyNetworkSkill",
                description="Simulates network requiring skill",
                permission_level=PermissionLevel.PUBLIC,
                requires_network=True,
                timeout_seconds=5.0,
            )
        )

    async def execute(self, params, context=None):
        return SkillExecutionResult(success=True, skill_name=self.name, output="network response")

    async def check_health(self):
        return SkillHealthResult(skill_name=self.name, healthy=True)


def test_skill_manifest_validation_and_schemas():
    """
    Verify skill manifests enforce mandatory properties, schema formats,
    and strict offline defaults.
    """
    cmd_skill = SystemCommandSkill()
    assert cmd_skill.manifest.name == "SystemCommandSkill"
    assert cmd_skill.manifest.permission_level == PermissionLevel.SENSITIVE
    assert cmd_skill.manifest.requires_network is False
    assert "properties" in cmd_skill.manifest.parameters_schema
    assert "command" in cmd_skill.manifest.parameters_schema["properties"]

    ha_skill = HomeAssistantSkill()
    assert ha_skill.manifest.name == "HomeAssistantSkill"
    assert ha_skill.manifest.permission_level == PermissionLevel.PROTECTED
    assert ha_skill.manifest.requires_network is False
    assert "domain" in ha_skill.manifest.parameters_schema["properties"]

    browser_skill = BrowserAutomationSkill()
    assert browser_skill.manifest.name == "BrowserAutomationSkill"
    assert browser_skill.manifest.permission_level == PermissionLevel.PROTECTED
    assert browser_skill.manifest.requires_network is True
    assert "url" in browser_skill.manifest.parameters_schema["properties"]


@pytest.mark.asyncio
async def test_registration_and_health_checks():
    """
    Verify dynamic skill registration and bulk runtime health checking.
    """
    registry = SkillRegistry(auto_register_core=True)

    skills = registry.list_skills()
    names = {s.name for s in skills}
    assert "SystemCommandSkill" in names
    assert "BrowserAutomationSkill" in names
    assert "HomeAssistantSkill" in names

    health_map = await registry.check_all_health()
    assert "SystemCommandSkill" in health_map
    assert health_map["SystemCommandSkill"].healthy is True
    assert "HomeAssistantSkill" in health_map


@pytest.mark.asyncio
async def test_timeout_enforcement_and_telemetry():
    """
    Verify timeout containment and lifecycle telemetry emission on EventBus.
    """
    event_bus = EventBus()
    registry = SkillRegistry(event_bus=event_bus, auto_register_core=False)

    slow_skill = DummySlowSkill()
    registry.register_skill(slow_skill)

    res = await registry.execute_skill("DummySlowSkill", {})
    assert res.success is False
    assert "timed out" in (res.error or "").lower()

    # Verify EventBus recorded started and failed events
    events = event_bus.ledger.get_events("skill.execution")
    topics = [e.topic for e in events]
    assert "skill.execution.started" in topics
    assert "skill.execution.failed" in topics

    # Test successful telemetry
    sys_skill = SystemCommandSkill()
    registry.register_skill(sys_skill)
    succ_res = await registry.execute_skill("SystemCommandSkill", {"command": "echo test_telemetry"})
    assert succ_res.success is True

    events_after = event_bus.ledger.get_events("skill.execution")
    topics_after = [e.topic for e in events_after]
    assert "skill.execution.completed" in topics_after


@pytest.mark.asyncio
async def test_offline_policy_blocks_network_skills(monkeypatch):
    """
    Verify that the strict offline policy denies any skill with requires_network=True
    when IRIS_ALLOW_CLOUD is false.
    """
    registry = SkillRegistry(auto_register_core=False)
    net_skill = DummyNetworkSkill()
    registry.register_skill(net_skill)

    # 1. When IRIS_ALLOW_CLOUD is disabled
    monkeypatch.setenv("IRIS_ALLOW_CLOUD", "false")
    res_blocked = await registry.execute_skill("DummyNetworkSkill", {})
    assert res_blocked.success is False
    assert "OFFLINE_POLICY_VIOLATION" in res_blocked.error

    # 2. When IRIS_ALLOW_CLOUD is explicitly enabled
    monkeypatch.setenv("IRIS_ALLOW_CLOUD", "true")
    res_allowed = await registry.execute_skill("DummyNetworkSkill", {})
    assert res_allowed.success is True
    assert res_allowed.output == "network response"


def test_rest_api_skills_endpoints_and_security():
    """
    Verify authenticated skills management REST endpoints and HTTP 401 gates.
    """
    client = TestClient(app)
    registry = SkillRegistry(auto_register_core=True)
    app.state.skill_registry = registry

    # 1. Unauthenticated rejection (HTTP 401)
    assert client.get("/api/skills").status_code == 401
    assert client.get("/api/skills/SystemCommandSkill").status_code == 401
    assert client.post("/api/skills/SystemCommandSkill/health").status_code == 401
    assert client.post("/api/skills/SystemCommandSkill/execute").status_code == 401

    # 2. Authenticated inspection
    headers = {"X-API-Key": auth_manager.master_key}

    list_res = client.get("/api/skills", headers=headers)
    assert list_res.status_code == 200
    skills_data = list_res.json()
    assert skills_data["count"] >= 3
    skill_names = [s["name"] for s in skills_data["skills"]]
    assert "SystemCommandSkill" in skill_names

    get_res = client.get("/api/skills/SystemCommandSkill", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["name"] == "SystemCommandSkill"
    assert "manifest" in get_res.json()
    assert "health" in get_res.json()

    health_res = client.post("/api/skills/SystemCommandSkill/health", headers=headers)
    assert health_res.status_code == 200
    assert health_res.json()["skill_name"] == "SystemCommandSkill"

    # 3. Direct execution with PermissionLevel.SENSITIVE gate
    # Missing confirmation token -> HTTP 403 with CONFIRMATION_REQUIRED
    exec_unconfirmed = client.post(
        "/api/skills/SystemCommandSkill/execute",
        json={"parameters": {"command": "echo api_sensitive"}},
        headers=headers
    )
    assert exec_unconfirmed.status_code == 403
    err_detail = exec_unconfirmed.json()["detail"]
    assert err_detail["error"] == "CONFIRMATION_REQUIRED"
    cfm_token = err_detail["confirmation_token"]

    # Provide single-use confirmation token -> Successfully executes
    exec_confirmed = client.post(
        "/api/skills/SystemCommandSkill/execute",
        json={
            "parameters": {"command": "echo api_sensitive"},
            "confirmation_token": cfm_token
        },
        headers=headers
    )
    assert exec_confirmed.status_code == 200
    assert exec_confirmed.json()["success"] is True
    assert "api_sensitive" in str(exec_confirmed.json()["output"])
