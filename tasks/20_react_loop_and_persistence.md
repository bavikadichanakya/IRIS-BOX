# Task 20: Implement Multi-Step ReAct Loop and SQLite Session Persistence

## Requirements
1. Create src/agent/react_loop.py or update IRISOrchestrator:
   - Allow the LLM to execute a tool, receive the typed ToolResult, and feed it back into the model context for conversational conclusion.
   - Max iterations bound (e.g. 5 steps) to prevent infinite loops.
2. Create src/memory/conversation_store.py:
   - SQLite backed store for conversation turns and tool results with in-memory caching.
3. Testing:
   - Create 	ests/test_react_loop.py and 	ests/test_conversation_store.py.
   - Verify uv run pytest passes cleanly.
