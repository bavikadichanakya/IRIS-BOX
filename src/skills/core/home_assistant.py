import logging
import os
import time
from typing import Any, Dict, Optional
import requests

from src.models.schemas import SmartHomeAction
from src.skills.base import BaseSkill, SkillExecutionResult, SkillHealthResult, SkillManifest
from src.tools.capability import PermissionLevel

logger = logging.getLogger("iris.skills.home_assistant")


class HomeAssistantSkill(BaseSkill):
    """
    Core skill providing local smart home device controls via Home Assistant REST API.
    Enforces strict zero-mock fallback.
    """

    def __init__(self, ha_url: str = "", ha_token: str = ""):
        self.ha_url = ha_url or os.environ.get("HA_URL", "")
        self.ha_token = ha_token or os.environ.get("HA_TOKEN", "")
        manifest = SkillManifest(
            name="HomeAssistantSkill",
            version="1.0.0",
            description="Control local smart home lights, switches, and scenes via Home Assistant REST API.",
            category="automation",
            permission_level=PermissionLevel.PROTECTED,
            requires_network=False,  # Local intranet / LAN communication
            timeout_seconds=10.0,
            parameters_schema=SmartHomeAction.model_json_schema(),
            supported_platforms=["windows", "linux", "darwin"],
        )
        super().__init__(manifest)

    async def check_health(self) -> SkillHealthResult:
        """Check Home Assistant configuration readiness."""
        if not self.ha_url or not self.ha_token:
            return SkillHealthResult(
                skill_name=self.name,
                healthy=False,
                message="Home Assistant credentials (HA_URL, HA_TOKEN) missing or unconfigured.",
                details={"ha_url_set": bool(self.ha_url), "ha_token_set": bool(self.ha_token)}
            )

        try:
            headers = {"Authorization": f"Bearer {self.ha_token}"}
            resp = requests.get(f"{self.ha_url}/api/", headers=headers, timeout=2.0)
            if resp.status_code == 200:
                return SkillHealthResult(
                    skill_name=self.name,
                    healthy=True,
                    message="Home Assistant instance is online and reachable.",
                    details={"url": self.ha_url}
                )
            return SkillHealthResult(
                skill_name=self.name,
                healthy=False,
                message=f"Home Assistant returned HTTP {resp.status_code}",
                details={"status_code": resp.status_code}
            )
        except Exception as e:
            return SkillHealthResult(
                skill_name=self.name,
                healthy=False,
                message=f"Home Assistant unreachable: {e}",
                details={"url": self.ha_url}
            )

    async def execute(
        self,
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> SkillExecutionResult:
        start_time = time.perf_counter()

        if not self.ha_url or not self.ha_token:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return SkillExecutionResult(
                success=False,
                skill_name=self.name,
                error="Home Assistant unavailable: credentials missing or connection refused",
                duration_ms=duration_ms
            )

        domain = params.get("domain", "")
        action = params.get("action", "")
        entity_id = params.get("entity_id", "")
        attributes = params.get("attributes") or {}

        if not domain or not action or not entity_id:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return SkillExecutionResult(
                success=False,
                skill_name=self.name,
                error="Missing required parameters: domain, action, or entity_id.",
                duration_ms=duration_ms
            )

        try:
            service_url = f"{self.ha_url}/api/services/{domain}/{action}"
            headers = {
                "Authorization": f"Bearer {self.ha_token}",
                "Content-Type": "application/json",
            }
            data = {"entity_id": entity_id}
            if attributes:
                data.update(attributes)

            response = requests.post(service_url, headers=headers, json=data, timeout=10)
            response.raise_for_status()

            duration_ms = (time.perf_counter() - start_time) * 1000.0
            output_payload = response.json() if response.content else {"message": "Service call successful"}
            return SkillExecutionResult(
                success=True,
                skill_name=self.name,
                output=output_payload,
                duration_ms=duration_ms
            )
        except Exception:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return SkillExecutionResult(
                success=False,
                skill_name=self.name,
                error="Home Assistant unavailable: credentials missing or connection refused",
                duration_ms=duration_ms
            )
