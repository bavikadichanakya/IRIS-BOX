import time
from typing import Dict, Any, List, Optional, Union
from pydantic import BaseModel, Field
from src.tools.capability import PermissionLevel


class TaskTestCase(BaseModel):
    """
    Standard test case definition for evaluating agent intent, tool dispatch,
    parameter extraction, and security adherence.
    """
    id: str
    user_prompt: str
    expected_intent: Optional[str] = None
    expected_tool: Optional[str] = None
    expected_params_subset: Optional[Dict[str, Any]] = None
    min_permission_level: Optional[PermissionLevel] = PermissionLevel.PUBLIC
    ground_truth_tokens: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)


class TaskBenchmarkCase(TaskTestCase):
    """
    Alias model supporting benchmark-centric naming conventions
    (input_prompt, expected_permission, etc.).
    """
    def __init__(
        self,
        id: Optional[str] = None,
        user_prompt: Optional[str] = None,
        input_prompt: Optional[str] = None,
        expected_tool: Optional[str] = None,
        expected_permission: Optional[Union[PermissionLevel, str]] = None,
        expected_params_subset: Optional[Dict[str, Any]] = None,
        ground_truth_tokens: Optional[List[str]] = None,
        expected_intent: Optional[str] = None,
        **kwargs
    ):
        prompt = user_prompt or input_prompt or ""
        cid = id or kwargs.get("case_id") or f"case_{int(time.time() * 1000)}"
        
        perm = expected_permission or kwargs.get("min_permission_level") or PermissionLevel.PUBLIC
        if isinstance(perm, str):
            try:
                perm = PermissionLevel(perm)
            except Exception:
                perm = PermissionLevel.PUBLIC

        super().__init__(
            id=cid,
            user_prompt=prompt,
            expected_intent=expected_intent,
            expected_tool=expected_tool,
            expected_params_subset=expected_params_subset or {},
            min_permission_level=perm,
            ground_truth_tokens=ground_truth_tokens or [],
            metadata=kwargs
        )


class TaskExecutionResult(BaseModel):
    """Evaluation result for a single task test case."""
    case_id: str
    tool_called: Optional[str] = None
    actual_params: Optional[Dict[str, Any]] = None
    tool_selection_correct: bool = False
    params_matched: bool = False
    security_adherent: bool = True
    ground_truth_tokens_matched: bool = True
    latency_ms: float = 0.0
    passed: bool = False
    status: str = "COMPLETED"
    output_summary: Optional[str] = None
    error: Optional[str] = None


class BenchmarkReport(BaseModel):
    """Aggregate benchmark report summarizing an evaluation run."""
    timestamp: str
    model_name: str
    total_cases: int
    passed_cases: int
    failed_cases: int
    accuracy_pct: float
    tool_accuracy_pct: float
    param_fidelity_pct: float
    security_adherence_pct: float
    avg_latency_ms: float
    median_latency_ms: float = 0.0
    mean_latency_sec: float = 0.0
    median_latency_sec: float = 0.0
    regressions: List[str] = Field(default_factory=list)
    results: List[TaskExecutionResult] = Field(default_factory=list)
    report_file_path: Optional[str] = None
