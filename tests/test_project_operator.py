import os
import shutil
import pytest
from pathlib import Path
from starlette.testclient import TestClient

from src.server.app import app
from src.security.auth import auth_manager
from src.agent.plan_manager import (
    PlanManager,
    PlanStatus,
    StepStatus,
    PermissionLevel,
    PlanStep,
)
from src.operator.workspace import ProjectWorkspace
from src.operator.task_runner import OperatorTaskRunner, FilePatch, DiagnosticReport
from src.operator.summarizer import OperatorSummarizer
from src.tools.manager import ToolManager


@pytest.fixture
def dummy_python_project(tmp_path):
    """
    Creates a real, self-contained Python project with a failing test suite.
    Zero mocks: operates against real filesystem and actual pytest runner.
    """
    proj_dir = tmp_path / "dummy_calc"
    proj_dir.mkdir(parents=True, exist_ok=True)

    calc_file = proj_dir / "calc.py"
    calc_file.write_text(
        "def add(a: int, b: int) -> int:\n"
        "    return a + b\n",
        encoding="utf-8"
    )

    test_file = proj_dir / "test_calc.py"
    test_file.write_text(
        "from calc import add\n\n"
        "def test_add():\n"
        "    assert add(2, 2) == 5\n",
        encoding="utf-8"
    )

    pyproject = proj_dir / "pyproject.toml"
    pyproject.write_text(
        "[project]\nname = \"dummy-calc\"\nversion = \"0.1.0\"\n",
        encoding="utf-8"
    )

    pytest_ini = proj_dir / "pytest.ini"
    pytest_ini.write_text(
        "[pytest]\npythonpath = .\n",
        encoding="utf-8"
    )

    return proj_dir


@pytest.mark.asyncio
async def test_project_operator_full_lifecycle(dummy_python_project):
    """
    Un-mocked End-to-End Acceptance Suite:
    1. Create a dummy Python project in temporary directory with failing test (assert add(2, 2) == 5).
    2. Run ProjectWorkspace.snapshot_environment() and diagnose_failure().
    3. Assert structured ExecutionPlan generated with unified diff_preview.
    4. Assert attempting to execute without cryptographic approval fails.
    5. Approve with valid token, execute, and verify test runner passes (assert add(2, 2) == 4) and exit code is 0.
    6. Verify that an intentional broken patch triggers an automatic rollback to the checkpoint.
    """
    project_path = str(dummy_python_project)

    # 1. Environment Intelligence: Snapshot repository structure
    snapshot = ProjectWorkspace.snapshot_environment(project_path)
    assert snapshot.project_type["language"] == "python"
    assert snapshot.project_type["test_runner"] == "pytest"
    assert snapshot.project_type["package_manager"] in ("pip", "uv", "poetry")
    assert "test_calc.py" in snapshot.files
    assert "calc.py" in snapshot.files
    assert "pyproject.toml" in snapshot.files

    # 2. Diagnostic Engine: Read-only test execution & root cause trace
    plan_manager = PlanManager()
    runner = OperatorTaskRunner(plan_manager=plan_manager)
    diagnostic = await runner.diagnose_failure(project_path)

    assert diagnostic.passed is False
    assert diagnostic.exit_code != 0
    assert "assert add(2, 2) == 5" in (diagnostic.stdout + diagnostic.stderr) or "AssertionError" in diagnostic.root_cause_trace
    assert diagnostic.target_file == "test_calc.py"

    # 3. Surgical Patch & Cryptographic ExecutionPlan Generation
    plan = runner.propose_patch(diagnostic)
    assert plan is not None
    assert plan.status == PlanStatus.STAGED
    assert plan.diff_preview is not None
    assert "--- a/test_calc.py" in plan.diff_preview
    assert "-    assert add(2, 2) == 5" in plan.diff_preview
    assert "+    assert add(2, 2) == 4" in plan.diff_preview
    assert plan.checkpoint_id is not None
    assert len(plan.steps) == 4

    # Verify step safety tiers
    assert plan.steps[0].permission_level == PermissionLevel.PUBLIC    # Checkpoint
    assert plan.steps[1].permission_level == PermissionLevel.SENSITIVE # Patch
    assert plan.steps[2].permission_level == PermissionLevel.PROTECTED # Test
    assert plan.steps[3].permission_level == PermissionLevel.PUBLIC    # Verification

    # 4. Strict Cryptographic Approval Enforcement
    tool_manager = ToolManager()

    # Attempting to execute unapproved plan must fail
    with pytest.raises(RuntimeError) as exc_info:
        await plan_manager.execute_approved_plan(plan.plan_id, orchestrator=tool_manager)
    assert "Plan must be APPROVED" in str(exc_info.value)

    # Attempting to approve with missing or invalid token must fail
    assert plan_manager.approve_plan(plan.plan_id, token="") is False
    assert plan_manager.approve_plan(plan.plan_id, token="tampered-token-999") is False
    assert plan.status == PlanStatus.STAGED

    # 5. Approve with valid cryptographic token, execute, and verify exit code 0
    valid_token = auth_manager.create_plan_approval_token(plan.plan_id, plan.content_hash)
    approved = plan_manager.approve_plan(plan.plan_id, token=valid_token)
    assert approved is True
    assert plan.status == PlanStatus.APPROVED

    executed_plan = await plan_manager.execute_approved_plan(plan.plan_id, orchestrator=tool_manager)
    assert executed_plan.status == PlanStatus.COMPLETED

    # Verify patch was applied to disk
    test_content = (dummy_python_project / "test_calc.py").read_text(encoding="utf-8")
    assert "assert add(2, 2) == 4" in test_content

    # Step 3 must have succeeded with exit code 0
    test_step = executed_plan.steps[2]
    assert test_step.status == StepStatus.COMPLETED
    assert test_step.result["output"]["exit_code"] == 0

    # Step 4 verification must have succeeded
    assert executed_plan.steps[3].status == StepStatus.COMPLETED

    # 6. Automatic Rollback on Broken Patch Failure
    # Test suite is currently passing. Stage an intentionally broken modification
    chk_id = ProjectWorkspace.create_checkpoint(project_path, "pre_broken_patch")
    broken_plan = plan_manager.create_plan(
        summary="Intentionally broken patch test",
        steps=[
            PlanStep(
                step_id=1,
                tool_name="ProjectOperatorTool",
                action_type="checkpoint",
                parameters={
                    "action": "create_checkpoint",
                    "project_path": project_path,
                    "checkpoint_id": chk_id,
                },
                description="Checkpoint verification",
                permission_level=PermissionLevel.PUBLIC,
            ),
            PlanStep(
                step_id=2,
                tool_name="ProjectOperatorTool",
                action_type="patch",
                parameters={
                    "action": "apply_patch",
                    "project_path": project_path,
                    "file_path": "test_calc.py",
                    "find_content": "assert add(2, 2) == 4",
                    "replace_content": "assert add(2, 2) == 9999",
                },
                description="Apply broken assertion",
                permission_level=PermissionLevel.SENSITIVE,
            ),
            PlanStep(
                step_id=3,
                tool_name="ProjectOperatorTool",
                action_type="test",
                parameters={
                    "action": "run_test",
                    "project_path": project_path,
                    "test_command": "pytest",
                },
                description="Run test suite verification",
                permission_level=PermissionLevel.PROTECTED,
            ),
            PlanStep(
                step_id=4,
                tool_name="ProjectOperatorTool",
                action_type="verification",
                parameters={
                    "action": "validate_exit_code",
                    "project_path": project_path,
                },
                description="Validate test exit code",
                permission_level=PermissionLevel.PUBLIC,
            ),
        ],
        checkpoint_id=chk_id,
        project_path=project_path,
    )

    broken_token = auth_manager.create_plan_approval_token(broken_plan.plan_id, broken_plan.content_hash)
    assert plan_manager.approve_plan(broken_plan.plan_id, token=broken_token) is True

    executed_broken_plan = await plan_manager.execute_approved_plan(broken_plan.plan_id, orchestrator=tool_manager)
    assert executed_broken_plan.status == PlanStatus.FAILED
    assert executed_broken_plan.steps[2].status == StepStatus.FAILED
    assert executed_broken_plan.steps[3].status == StepStatus.CANCELLED

    # Assert automatic rollback reverted test_calc.py back to pre-broken state
    rolled_back_content = (dummy_python_project / "test_calc.py").read_text(encoding="utf-8")
    assert "assert add(2, 2) == 4" in rolled_back_content
    assert "9999" not in rolled_back_content


@pytest.mark.asyncio
async def test_operator_rest_endpoints(dummy_python_project):
    """
    Test Project Operator REST API endpoints:
    - POST /api/operator/snapshot
    - POST /api/operator/diagnose
    - POST /api/operator/plan-fix
    - POST /api/plans/{plan_id}/rollback
    """
    project_path = str(dummy_python_project)
    api_key = auth_manager.get_master_key()
    headers = {"Authorization": f"Bearer {api_key}"}

    with TestClient(app) as client:
        # 1. Snapshot endpoint
        snap_res = client.post(
            "/api/operator/snapshot",
            json={"project_path": project_path},
            headers=headers,
        )
        assert snap_res.status_code == 200
        snap_data = snap_res.json()
        assert snap_data["project_type"]["language"] == "python"
        assert "test_calc.py" in snap_data["files"]

        # 2. Diagnose endpoint
        diag_res = client.post(
            "/api/operator/diagnose",
            json={"project_path": project_path},
            headers=headers,
        )
        assert diag_res.status_code == 200
        diag_data = diag_res.json()
        assert diag_data["passed"] is False
        assert diag_data["exit_code"] != 0

        # 3. Plan-fix endpoint
        fix_res = client.post(
            "/api/operator/plan-fix",
            json={"project_path": project_path},
            headers=headers,
        )
        assert fix_res.status_code == 200
        fix_data = fix_res.json()
        plan_id = fix_data["plan"]["plan_id"]
        assert fix_data["plan"]["diff_preview"] is not None
        assert fix_data["plan"]["checkpoint_id"] is not None

        # 4. 1-click Rollback endpoint
        roll_res = client.post(
            f"/api/plans/{plan_id}/rollback",
            headers=headers,
        )
        assert roll_res.status_code == 200
        roll_data = roll_res.json()
        assert roll_data["status"] == "ROLLED_BACK"
        assert roll_data["checkpoint_id"] == fix_data["plan"]["checkpoint_id"]


@pytest.fixture
def multi_file_python_project(tmp_path):
    """
    Creates a multi-file Python project with defects spanning multiple files:
    - models.py: TAX_RATE = -0.10 (should be 0.10)
    - processor.py: returns {"total": total, "status": "ERROR"} (should be "COMPLETED")
    - test_billing.py: failing test importing both models and processor
    """
    proj_dir = tmp_path / "billing_service"
    proj_dir.mkdir(parents=True, exist_ok=True)

    models_file = proj_dir / "models.py"
    models_file.write_text(
        "TAX_RATE = -0.10\n\n"
        "def calculate_tax(subtotal: float) -> float:\n"
        "    return subtotal * TAX_RATE\n",
        encoding="utf-8"
    )

    processor_file = proj_dir / "processor.py"
    processor_file.write_text(
        "from models import calculate_tax\n\n"
        "def process_order(subtotal: float) -> dict:\n"
        "    tax = calculate_tax(subtotal)\n"
        "    total = subtotal + tax\n"
        "    return {\"total\": round(total, 2), \"status\": \"ERROR\"}\n",
        encoding="utf-8"
    )

    test_file = proj_dir / "test_billing.py"
    test_file.write_text(
        "from models import TAX_RATE\n"
        "from processor import process_order\n\n"
        "def test_billing_calculation():\n"
        "    assert TAX_RATE == 0.10\n"
        "    res = process_order(100.0)\n"
        "    assert res[\"total\"] == 110.0\n"
        "    assert res[\"status\"] == \"COMPLETED\"\n",
        encoding="utf-8"
    )

    pyproject = proj_dir / "pyproject.toml"
    pyproject.write_text(
        "[project]\nname = \"billing-service\"\nversion = \"0.1.0\"\n",
        encoding="utf-8"
    )

    pytest_ini = proj_dir / "pytest.ini"
    pytest_ini.write_text(
        "[pytest]\npythonpath = .\n",
        encoding="utf-8"
    )

    return proj_dir


@pytest.mark.asyncio
async def test_multi_file_operator_diagnosis_patch_and_atomic_rollback(multi_file_python_project):
    """
    Acceptance test for coordinated multi-file diagnostics, diffs & atomic rollbacks:
    1. Verify multi-file project setup with defects in models.py and processor.py.
    2. Run diagnose_failure() and verify both models.py and processor.py are in affected_files.
    3. Stage coordinated multi-file ExecutionPlan and verify unified diff headers for a/models.py and a/processor.py.
    4. Test Atomic Multi-File Rollback: Stage deliberately bad patch (processor.py still returns "BROKEN"),
       approve and execute, assert failure and both models.py and processor.py are rolled back.
    5. Test Verified Multi-File Fix: Stage valid patch across both files, approve and execute,
       assert pytest passes with exit_code == 0 and both files retain the fixed code.
    """
    project_path = str(multi_file_python_project)
    tool_manager = ToolManager()
    plan_manager = PlanManager()
    runner = OperatorTaskRunner(plan_manager=plan_manager)

    # 1 & 2. Run multi-file diagnosis
    diagnostic = await runner.diagnose_failure(project_path)
    assert diagnostic.passed is False
    assert diagnostic.exit_code != 0
    assert "models.py" in diagnostic.affected_files
    assert "processor.py" in diagnostic.affected_files

    # Verify voice diagnostic summary mentions multi-file information
    diag_summary = OperatorSummarizer.summarize_diagnosis(diagnostic, project_name="billing-service")
    assert "billing-service" in diag_summary
    assert "2 files" in diag_summary or "models.py" in diag_summary

    # 3. Stage coordinated multi-file ExecutionPlan
    plan = runner.propose_patch(diagnostic)
    assert plan is not None
    assert plan.status == PlanStatus.STAGED
    assert plan.diff_preview is not None
    assert "--- a/models.py" in plan.diff_preview
    assert "+++ b/models.py" in plan.diff_preview
    assert "--- a/processor.py" in plan.diff_preview
    assert "+++ b/processor.py" in plan.diff_preview

    # Verify 5-step sequential cryptographic structure:
    # Step 1: create_checkpoint (PUBLIC)
    # Step 2: apply_patch models.py (SENSITIVE)
    # Step 3: apply_patch processor.py (SENSITIVE)
    # Step 4: run_test (PROTECTED)
    # Step 5: validate_exit_code (PUBLIC)
    assert len(plan.steps) == 5
    assert plan.steps[0].permission_level == PermissionLevel.PUBLIC
    assert plan.steps[1].permission_level == PermissionLevel.SENSITIVE
    assert plan.steps[2].permission_level == PermissionLevel.SENSITIVE
    assert plan.steps[3].permission_level == PermissionLevel.PROTECTED
    assert plan.steps[4].permission_level == PermissionLevel.PUBLIC

    # Verify voice plan summary
    plan_summary = OperatorSummarizer.summarize_plan(plan, project_name="billing-service")
    assert "coordinated repair plan across 2 files" in plan_summary
    assert "models.py" in plan_summary
    assert "processor.py" in plan_summary

    # 4. Test Atomic Multi-File Rollback
    # Stage deliberately bad patch where models.py is fixed to 0.10, but processor.py is patched to "BROKEN"
    bad_patches = [
        {"file_path": "models.py", "find": "TAX_RATE = -0.10", "replace": "TAX_RATE = 0.10"},
        {"file_path": "processor.py", "find": '"status": "ERROR"', "replace": '"status": "BROKEN"'},
    ]
    bad_plan = runner.propose_patch(diagnostic, patches=bad_patches)
    bad_token = auth_manager.create_plan_approval_token(bad_plan.plan_id, bad_plan.content_hash)
    assert plan_manager.approve_plan(bad_plan.plan_id, token=bad_token) is True

    executed_bad_plan = await plan_manager.execute_approved_plan(bad_plan.plan_id, orchestrator=tool_manager)
    assert executed_bad_plan.status == PlanStatus.FAILED
    # Step 4 (run_test) failed due to exit code != 0
    assert executed_bad_plan.steps[3].status == StepStatus.FAILED
    assert executed_bad_plan.steps[4].status == StepStatus.CANCELLED

    # Verify atomic rollback: BOTH models.py and processor.py must be restored to original pre-plan state
    models_rolled_back = (multi_file_python_project / "models.py").read_text(encoding="utf-8")
    proc_rolled_back = (multi_file_python_project / "processor.py").read_text(encoding="utf-8")
    assert "TAX_RATE = -0.10" in models_rolled_back
    assert "TAX_RATE = 0.10" not in models_rolled_back
    assert '"status": "ERROR"' in proc_rolled_back
    assert '"status": "BROKEN"' not in proc_rolled_back

    # 5. Test Verified Multi-File Fix
    # Stage valid coordinated patch across both files
    valid_patches = [
        {"file_path": "models.py", "find": "TAX_RATE = -0.10", "replace": "TAX_RATE = 0.10"},
        {"file_path": "processor.py", "find": '"status": "ERROR"', "replace": '"status": "COMPLETED"'},
    ]
    valid_plan = runner.propose_patch(diagnostic, patches=valid_patches)
    valid_token = auth_manager.create_plan_approval_token(valid_plan.plan_id, valid_plan.content_hash)
    assert plan_manager.approve_plan(valid_plan.plan_id, token=valid_token) is True

    executed_valid_plan = await plan_manager.execute_approved_plan(valid_plan.plan_id, orchestrator=tool_manager)
    assert executed_valid_plan.status == PlanStatus.COMPLETED
    assert executed_valid_plan.steps[3].status == StepStatus.COMPLETED
    assert executed_valid_plan.steps[3].result["output"]["exit_code"] == 0
    assert executed_valid_plan.steps[4].status == StepStatus.COMPLETED

    # Verify both files retain their fixed code on disk
    models_fixed = (multi_file_python_project / "models.py").read_text(encoding="utf-8")
    proc_fixed = (multi_file_python_project / "processor.py").read_text(encoding="utf-8")
    assert "TAX_RATE = 0.10" in models_fixed
    assert '"status": "COMPLETED"' in proc_fixed

