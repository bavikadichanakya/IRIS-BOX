# Task 07: Multi-Turn Conversation Memory & Context Management
1. In `src/agent/orchestrator.py`, implement an in-memory session manager `SessionMemory` that maintains a sliding window of recent conversation turns (up to 10 messages per `session_id`).
2. Update `process_request` and `stream_request` to take an optional `session_id: str`. If provided, prepend previous conversation history to system prompt and user query.
3. Add tests in `tests/test_memory.py` validating that follow-up queries retain context across multiple sequential messages in the same session. Ensure all pytest tests pass.
