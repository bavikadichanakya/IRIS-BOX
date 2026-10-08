import logging
from typing import AsyncGenerator, Dict, Optional

try:
    import edge_tts
except ImportError:
    edge_tts = None

logger = logging.getLogger(__name__)


class TTSEngine:
    """
    Async text‑to‑speech engine using Edge‑TTS.

    Supports streaming audio generation, caching of common phrases,
    and pitch/rate modulation.
    """

    def __init__(
        self,
        voice: str = "en-US-AriaNeural",
        rate: str = "+0%",
        pitch: str = "+0Hz",
        cache_common_phrases: bool = True,
    ):
        self.voice = voice
        self.rate = rate
        self.pitch = pitch
        self.cache_common_phrases = cache_common_phrases
        self._cache: Dict[str, bytes] = {}

        if edge_tts is None:
            logger.warning("edge-tts not installed; TTS functionality will be unavailable.")

    async def stream_audio(
        self, text: str, voice: Optional[str] = None
    ) -> AsyncGenerator[bytes, None]:
        """
        Stream audio bytes for the given text.

        If caching is enabled and the phrase has been synthesised before,
        the cached audio is yielded in chunks instead of calling edge‑tts.
        """
        voice = voice or self.voice

        # Return cached audio if available and caching is on
        if self.cache_common_phrases and text in self._cache:
            cached = self._cache[text]
            chunk_size = 4096
            for i in range(0, len(cached), chunk_size):
                yield cached[i : i + chunk_size]
            return

        if edge_tts is None:
            raise RuntimeError("edge-tts is not available")

        communicate = edge_tts.Communicate(text, voice, rate=self.rate, pitch=self.pitch)
        audio_data = b""

        async for chunk in communicate.stream():
            # edge-tts may yield bytes directly or dicts with "audio" key
            if isinstance(chunk, dict):
                data = chunk.get("data", b"")
                audio_data += data
                yield data
            else:
                audio_data += chunk
                yield chunk

        if self.cache_common_phrases:
            self._cache[text] = audio_data

    async def speak(self, text: str, voice: Optional[str] = None) -> bytes:
        """Convenience method that returns the full audio as a single bytes object."""
        chunks = [chunk async for chunk in self.stream_audio(text, voice)]
        return b"".join(chunks)

    def clear_cache(self):
        """Empty the phrase cache."""
        self._cache.clear()
