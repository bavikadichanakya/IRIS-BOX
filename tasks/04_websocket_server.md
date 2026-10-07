Implement the real-time WebSocket server in `src/server/app.py` for physical IRIS pod audio/transcript streaming.

Requirements:
1. Build a FastAPI app with WebSocket route `/ws/voice-stream`.
2. When a JSON payload matching `VoiceCommandPayload` is received over WebSocket:
   - Route through `IRISOrchestrator`.
   - Send back an `AgentExecutionResult`.
3. Add health check endpoint `GET /health`.
4. Write integration tests in `tests/test_server.py` using `TestClient` from `starlette.testclient`.
5. Ensure all tests pass.
