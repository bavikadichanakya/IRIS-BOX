# Task 19: Implement EventBus and Structured Tracing Subsystem

## Requirements
1. Create src/observability/tracing.py:
   - Implement TraceContext Pydantic model (device_id, session_id, 	urn_id, equest_id, 	ask_id, gent_execution_id, 	race_id).
   - Implement helper create_trace_context(device_id: str, session_id: Optional[str]) -> TraceContext.
2. Create src/observability/event_bus.py:
   - Implement asynchronous EventBus pub/sub supporting topic subscriptions.
   - Implement EventLedger storing sequential audit events.
3. Wire EventBus into ToolManager:
   - Publish 	ool.execution.started, 	ool.execution.succeeded, 	ool.execution.failed, and 	ool.execution.denied events.
4. Testing:
   - Create 	ests/test_event_bus.py testing subscriber callbacks, ledger event recording, and trace context propagation.
   - Verify uv run pytest passes cleanly.
