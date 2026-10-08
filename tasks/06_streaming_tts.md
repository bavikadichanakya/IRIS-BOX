# Task 06: Streaming Output & Audio Dispatch Schema
1. In `src/models/schemas.py`, add `StreamChunkPayload` schema containing `chunk_type` ("text_delta", "tool_call", "complete"), `delta_text` (str), and `session_id` (str).
2. In `src/agent/orchestrator.py`, add `stream_request(user_prompt: str)` asynchronous generator that yields streaming text tokens as they arrive from the LLM, or returns tool execution results if tools are triggered.
3. Add a WebSocket endpoint or route handler in `src/server/app.py` for `/ws/stream` (or update `/ws/voice-stream`) supporting chunk streaming.
4. Add unit and integration tests in `tests/test_streaming.py`. Ensure all pytest tests pass.
