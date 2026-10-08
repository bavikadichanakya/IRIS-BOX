# Task 05: Modern FastAPI Lifespan & WebSocket Resilience
1. In `src/server/app.py`, eliminate the `@app.on_event("startup")` deprecation warning by converting to the modern FastAPI `lifespan(app: FastAPI)` async context manager pattern.
2. In the `/ws/voice-stream` WebSocket route, add handling for client heartbeat/ping messages `{"type": "ping"}` returning `{"type": "pong"}` to keep live connections open indefinitely.
3. Update `tests/test_server.py` to test the lifespan startup and verify WebSocket ping/pong behavior. Ensure all pytest tests pass.
