# Project IRIS: AI Smart Speaker Backend

Local AI Smart Speaker backend supporting real-time voice streaming, tool execution registries, and LLM orchestration.

## Features
- **Data Models & Schemas**: Pydantic v2 schemas for smart home, browser, and local system actions.
- **Tool Execution Registry**: Handlers for Home Assistant REST integration, secure local system commands, and headless browser navigation.
- **Agent Orchestrator**: Connects to OpenAI-compatible LLM endpoints with automated function calling and response routing.
- **Real-Time WebSocket Server**: FastAPI WebSocket stream at /ws/voice-stream for live microphone/audio clients and smart speaker pods.

## Running Tests
Run all unit and integration tests:
  uv run --python 3.12 pytest -v

## Running the Server
Launch the FastAPI development server:
  uv run --python 3.12 uvicorn src.server.app:app --reload --port 8000
