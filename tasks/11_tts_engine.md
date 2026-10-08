# 11_tts_engine.md
Implement async Edge-TTS/gTTS streaming voice synthesis module in src/audio/tts.py. Include TTSEngine with async stream_audio(text: str, voice: str) -> AsyncGenerator[bytes, None], caching of common phrases, and pitch/rate modulation. Add unit tests in tests/test_tts.py.
Ensure all existing and new pytest tests pass.
