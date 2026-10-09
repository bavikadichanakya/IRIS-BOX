# Task 18: Implement PermissionManager and ToolManager Execution Boundary

Refactor tool execution out of \IRISOrchestrator\ into dedicated \PermissionManager\ and \ToolManager\ modules.

## Requirements
1. Create \src/tools/capability.py\:
   - Define \PermissionLevel\ Enum ("PUBLIC", "PROTECTED", "SENSITIVE").
   - Define \ExecutionStatus\ Enum ("SUCCEEDED", "FAILED", "DENIED", "TIMEOUT", "UNAVAILABLE", "CANCELLED").
   - Define \Capability\ Pydantic model (\
ame\, \description\, \schema\, \permission_level\, \category\, \supported_devices\, \equires_confirmation\, \execution_timeout_sec\).
   - Define \ToolResult\ Pydantic model (\status\, \	ool_name\, \equest_id\, \	race_id\, \output\, \error\, \duration_ms\).

2. Create \src/tools/permissions.py\:
   - Implement \PermissionManager\ class with policy evaluation.
   - Support policy rules: Allow all PUBLIC tools; check device/role permissions for PROTECTED tools; require explicit confirmation token for SENSITIVE tools (such as OS shell execution or destructive deletes).
   - Method: \sync def evaluate(capability: Capability, context: dict) -> tuple[bool, Optional[str]]\.

3. Create \src/tools/manager.py\:
   - Implement \ToolManager\ that wraps \ToolRegistry\.
   - Method: \sync def execute_tool(name: str, arguments: dict, request_id: str, trace_id: str, context: dict) -> ToolResult\.
   - Workflow:
     1. Retrieve capability.
     2. Call \PermissionManager.evaluate()\. If denied, immediately return \ToolResult(status=ExecutionStatus.DENIED)\.
     3. Execute tool within \syncio.wait_for(timeout=capability.execution_timeout_sec)\.
     4. Catch exceptions and return cleanly formatted \ToolResult\.

4. Refactor \src/agent/orchestrator.py\:
   - Update \IRISOrchestrator\ to depend on \ToolManager\ instead of directly calling \ToolRegistry.execute()\.
   - Update \execute_tool_call\ to unpack \ToolResult\ and append it to \SessionMemory\.

5. Testing:
   - Create \	ests/test_permissions.py\ testing PUBLIC, PROTECTED, and SENSITIVE policy decisions.
   - Create \	ests/test_tool_manager.py\ verifying permission denial, execution success, and timeout handling.
   - Ensure all existing tests in \	ests/\ pass without regression.
