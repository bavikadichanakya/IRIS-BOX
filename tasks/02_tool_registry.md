Implement the tool execution registry in `src/tools/registry.py` referencing `src/models/schemas.py`.

Requirements:
1. Create `ToolRegistry` class with decorator `@register_tool`.
2. Implement 3 concrete tool handlers:
   - `HomeAssistantTool`: Dispatches local REST requests to Home Assistant with token auth. Include mock mode for testing without a live HA instance.
   - `SystemCommandTool`: Safe local command executor with a whitelist of allowed commands (reject dangerous commands).
   - `BrowserTool`: Headless browser helper interface.
3. Write unit tests in `tests/test_tools.py` using unittest.mock.
4. Ensure all tests in `tests/test_tools.py` pass.
