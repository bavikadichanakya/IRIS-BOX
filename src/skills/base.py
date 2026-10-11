from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from src.tools.capability import PermissionLevel


class SkillManifest(BaseModel):
    """
    Formal metadata manifest describing a skill capability, its parameters schema,
    safety permissions, network requirements, and runtime timeout bounds.
    """
    name: str
    version: str = "1.0.0"
    description: str
    category: str = "utility"  # e.g., 'system', 'media', 'automation', 'utility', 'browser'
    permission_level: PermissionLevel = PermissionLevel.PUBLIC
    requires_network: bool = False  # Strict Offline Policy: defaults to False
    timeout_seconds: float = 30.0
    parameters_schema: Dict[str, Any] = Field(default_factory=dict)
    supported_platforms: List[str] = Field(
        default_factory=lambda: ["windows", "linux", "darwin"]
    )


class SkillExecutionResult(BaseModel):
    """
    Standardized execution outcome for any Skill invocation.
    """
    success: bool
    skill_name: str
    output: Optional[Any] = None
    error: Optional[str] = None
    duration_ms: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SkillHealthResult(BaseModel):
    """
    Readiness and operational health status report for a Skill.
    """
    skill_name: str
    healthy: bool
    message: str = "Ready"
    details: Dict[str, Any] = Field(default_factory=dict)


class BaseSkill(ABC):
    """
    Abstract base class for all unified IRIS Skills.
    """

    def __init__(self, manifest: SkillManifest):
        self.manifest = manifest

    @property
    def name(self) -> str:
        return self.manifest.name

    @abstractmethod
    async def execute(
        self,
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> SkillExecutionResult:
        """
        Execute the skill with provided parameters and execution context.
        """
        pass

    @abstractmethod
    async def check_health(self) -> SkillHealthResult:
        """
        Verify runtime readiness and environmental dependencies.
        """
        pass
