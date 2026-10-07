Implement the central LLM agent orchestrator in `src/agent/orchestrator.py`.

Requirements:
1. Implement `IRISOrchestrator` that:
   - Connects to an OpenAI-compatible endpoint.
   - Converts tool schemas from `ToolRegistry` into standard function calling format.
   - Parses the model's function-calling JSON response into the validated Pydantic models from `schemas.py`.
   - Executes the corresponding tool and returns `AgentExecutionResult`.
2. Write unit tests in `tests/test_orchestrator.py` mocking tool dispatch and LLM responses.
3. Ensure all tests in `tests/test_orchestrator.py` pass.
