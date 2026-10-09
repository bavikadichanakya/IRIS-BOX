Upgrade the client simulator to support live microphone capture and integrate local Piper TTS offline speech synthesis.

Requirements:
1. In scripts/simulate_speaker.py:
   - Add a --live CLI flag.
   - When --live is passed, use sounddevice to capture 16kHz 16-bit mono PCM audio from the laptop's actual microphone and stream frames into /ws/audio.
   - Play received TTS audio bytes back through the laptop's speakers.
   - Maintain the synthetic sine-wave/silent mode as default when --live is not specified.
2. In src/audio/tts.py:
   - Implement an offline synthesizer using local piper binary execution and an ONNX voice model (en_US-lessac-medium.onnx).
   - If piper or the model file is not found, fallback to _generate_silent_audio().
3. Add unit tests in 	ests/test_tts.py verifying that the Piper synthesis command is constructed properly and handles missing binary errors gracefully.
4. Ensure all tests pass with uv run --python 3.12 pytest -v.
