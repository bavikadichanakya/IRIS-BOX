# Task 21: Implement HealthSupervisor and RuntimeMetrics

## Requirements
1. Create src/observability/health.py:
   - Implement HealthSupervisor that checks Ollama backend connection, TTS readiness, tool count, and registered satellite nodes.
   - Expose system snapshot format.
2. Add GET /health endpoint in src/server/app.py returning the full aggregated subsystem status.
3. Testing:
   - Create 	ests/test_health.py.
   - Ensure all tests pass.
