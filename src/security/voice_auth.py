import logging
from typing import Dict, Optional, Union
from src.observability.event_bus import EventBus
from src.security.biometrics import Role, SpeakerIdentificationResult, AuthorizationDecision

logger = logging.getLogger("iris.security.voice_auth")

ROLE_HIERARCHY: Dict[Role, int] = {
    Role.ADMIN: 3,
    Role.MEMBER: 2,
    Role.GUEST: 1,
    Role.RESTRICTED: 0,
}

DEFAULT_TOOL_ROLES: Dict[str, Role] = {
    # ADMIN tier: high privilege, host execution, security disarming, file management
    "SystemCommandTool": Role.ADMIN,
    "system_command": Role.ADMIN,
    "SystemCommandSkill": Role.ADMIN,
    "BrowserAutomationSkill": Role.ADMIN,
    "BrowserTool": Role.ADMIN,
    "FileManagementTool": Role.ADMIN,
    "file_manager": Role.ADMIN,
    "TerminalTool": Role.ADMIN,
    "ShellTool": Role.ADMIN,
    "SecurityDisarmTool": Role.ADMIN,
    "SmartLockTool": Role.ADMIN,

    # MEMBER tier: smart home device control, thermostat, calendar, personalized memory
    "HomeAssistantTool": Role.MEMBER,
    "HomeAssistantSkill": Role.MEMBER,
    "ThermostatTool": Role.MEMBER,
    "CalendarTool": Role.MEMBER,
    "MemoryNoteTool": Role.MEMBER,
    "NotesTool": Role.MEMBER,
    "DeviceControlTool": Role.MEMBER,
    "SmartBulbTool": Role.MEMBER,

    # GUEST tier: public queries, status, weather, media playback, timer
    "WeatherTool": Role.GUEST,
    "CalculatorTool": Role.GUEST,
    "TimerTool": Role.GUEST,
    "ClockTool": Role.GUEST,
    "MediaPlaybackTool": Role.GUEST,
    "MusicTool": Role.GUEST,
    "StatusTool": Role.GUEST,
    "PlanManager": Role.GUEST,
}


class VoiceGatedAuthorization:
    """
    Role-based voice authorization guardrail.
    Enforces tiered tool execution policies based on speaker biometrics.
    Publishes security.voice_auth.denied and security.voice_auth.approved telemetry to EventBus.
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        tool_roles: Optional[Dict[str, Role]] = None,
        admin_threshold: float = 0.75
    ):
        self.event_bus = event_bus or EventBus()
        self.tool_roles = dict(DEFAULT_TOOL_ROLES)
        if tool_roles:
            self.tool_roles.update(tool_roles)
        self.admin_threshold = admin_threshold

    def register_tool_role(self, tool_name: str, role: Role):
        """Register or override the required role for a tool."""
        self.tool_roles[tool_name] = role

    def get_required_role(self, tool_name: str) -> Role:
        """Resolve the required role for a tool name or skill."""
        if tool_name in self.tool_roles:
            return self.tool_roles[tool_name]

        # Case-insensitive / prefix matching
        tool_lower = tool_name.lower()
        if any(kw in tool_lower for kw in ("system", "terminal", "shell", "browser", "exec", "file", "lock", "disarm")):
            return Role.ADMIN
        if any(kw in tool_lower for kw in ("home", "assistant", "device", "thermostat", "calendar", "note")):
            return Role.MEMBER

        # Default fallback for query / status tools
        return Role.GUEST

    def authorize_tool_execution(
        self,
        id_result: Optional[SpeakerIdentificationResult],
        tool_name: str,
        **kwargs
    ) -> AuthorizationDecision:
        """
        Authorize or deny tool execution based on the speaker's biometric identification result.
        Denies execution if speaker's role is below the required tier or if similarity is below threshold.
        Emits security.voice_auth.denied or security.voice_auth.approved telemetry events on EventBus.
        """
        required_role = self.get_required_role(tool_name)

        # Default to unidentified GUEST if no identification result is provided
        if id_result is None:
            id_result = SpeakerIdentificationResult(
                identified=False,
                speaker=None,
                similarity=0.0,
                role=Role.GUEST
            )

        speaker_role = id_result.role
        speaker_tier = ROLE_HIERARCHY.get(speaker_role, 0)
        required_tier = ROLE_HIERARCHY.get(required_role, 1)

        # Check for ADMIN verification threshold constraint
        if required_role == Role.ADMIN:
            if not id_result.identified or id_result.similarity < self.admin_threshold:
                reason = (
                    f"Voice authorization denied: Tool '{tool_name}' requires ADMIN biometrics (score >= {self.admin_threshold}), "
                    f"but speaker similarity was {id_result.similarity:.2f}."
                )
                self._publish_event("security.voice_auth.denied", {
                    "tool": tool_name,
                    "reason": reason,
                    "required_role": required_role.value,
                    "speaker_role": speaker_role.value,
                    "speaker_id": id_result.speaker.speaker_id if id_result.speaker else None,
                    "similarity": id_result.similarity
                })
                return AuthorizationDecision(
                    authorized=False,
                    reason=reason,
                    required_role=required_role,
                    speaker_role=speaker_role
                )

        # Check general role tier
        if speaker_tier < required_tier:
            reason = (
                f"Voice authorization denied: Tool '{tool_name}' requires role {required_role.value}, "
                f"but speaker has role {speaker_role.value}."
            )
            self._publish_event("security.voice_auth.denied", {
                "tool": tool_name,
                "reason": reason,
                "required_role": required_role.value,
                "speaker_role": speaker_role.value,
                "speaker_id": id_result.speaker.speaker_id if id_result.speaker else None,
                "similarity": id_result.similarity
            })
            return AuthorizationDecision(
                authorized=False,
                reason=reason,
                required_role=required_role,
                speaker_role=speaker_role
            )

        # Approved
        self._publish_event("security.voice_auth.approved", {
            "tool": tool_name,
            "required_role": required_role.value,
            "speaker_role": speaker_role.value,
            "speaker_id": id_result.speaker.speaker_id if id_result.speaker else None,
            "similarity": id_result.similarity
        })
        return AuthorizationDecision(
            authorized=True,
            reason=None,
            required_role=required_role,
            speaker_role=speaker_role
        )

    def _publish_event(self, event_name: str, payload: dict):
        try:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.event_bus.publish(event_name, payload))
            except RuntimeError:
                pass
        except Exception:
            pass
