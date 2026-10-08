# 10_stt_engine.md
Implement offline Whisper-compatible STT processor in src/audio/stt.py with Transcriber class supporting transcribe_pcm(audio_bytes: bytes, sample_rate: int = 16000) -> str, fallback mock mode when model weights missing, and language detection. Add unit tests in tests/test_stt.py.
Ensure all existing and new pytest tests pass.
