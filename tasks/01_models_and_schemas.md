Implement the core data models and tool validation schemas for Project IRIS in `src/models/schemas.py`.

Requirements:
1. Define Pydantic v2 models:
   - `SmartHomeAction`: entity_id (str), domain (str), action ("on" | "off" | "toggle"), attributes (dict optional).
   - `LaptopSystemAction`: command (str), action_type ("launch" | "file" | "terminal"), timeout_sec (int = 10).
   - `BrowserAction`: url (str), action ("goto" | "click" | "extract"), selector (str optional).
   - `VoiceCommandPayload`: raw_transcript (str), confidence (float), timestamp (str).
   - `AgentExecutionResult`: success (bool), tool_name (str), output_payload (dict), error (str optional).
2. Write unit tests in `tests/test_schemas.py` testing serialization, defaults, and validation errors.
3. Ensure all tests in `tests/test_schemas.py` pass.
