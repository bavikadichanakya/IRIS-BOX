Expand web and browser automation capabilities in the tool registry using Playwright and Browser-Use patterns.

Requirements:
1. In src/models/schemas.py:
   - Expand BrowserAction to support actions: navigate, click, type_text, extract_text, and screenshot.
   - Add optional fields: selector (str), input_text (str), and 	imeout_ms (int = 5000).
2. In src/tools/registry.py:
   - Upgrade the browser handler to maintain an async Playwright browser context.
   - Implement execution logic for clicking elements, typing into form fields, and extracting page innerText.
   - Add mock fallback mode when Playwright browsers are not installed.
3. In 	ests/test_tools.py:
   - Add unit tests verifying BrowserAction validation and execution handling with mocked browser pages.
4. Ensure all tests pass with uv run --python 3.12 pytest -v.
