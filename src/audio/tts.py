import logging
from typing import AsyncGenerator, Dict, Optional

try:
    import edge_tts
except ImportError:  # pragma: no cover
    edge_tts = None

logger = logging.getLogger(__name__)


class TTSEngine:
    """
    Async text‑to‑speech engine using Edge‑TTS with an offline fallback.

    Features
    --------
    * Streaming audio generation via Edge‑TTS when internet connectivity
      and the library are available.
    * Simple in‑memory cache for frequently used phrases.
    * Offline fallback that returns a silent audio placeholder when the
      network is unreachable or ``edge‑tts`` is not installed.
    * Optional pitch and rate modulation.
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
            logger.warning(
                "edge-tts not installed; TTS will operate in offline fallback mode."
            )

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #
    async def stream_audio(
        self, text: str, voice: Optional[str] = None
    ) -> AsyncGenerator[bytes, None]:
        """
        Stream audio bytes for the supplied ``text``.

        Parameters
        ----------
        text:
            The text to be synthesised.
        voice:
            Optional voice override; defaults to the instance's ``voice``.

        Yields
        ------
        bytes
            Chunks of audio data. When the offline fallback is used, a single
            silent chunk is yielded.
        """
        voice = voice or self.voice

        # -----------------------------------------------------------------
        # 1️⃣ Return cached audio if we have it.
        # -----------------------------------------------------------------
        if self.cache_common_phrases and text in self._cache:
            cached = self._cache[text]
            chunk_size = 4096
            for i in range(0, len(cached), chunk_size):
                yield cached[i : i + chunk_size]
            return

        # -----------------------------------------------------------------
        # 2️⃣ Try the online Edge‑TTS path.
        # -----------------------------------------------------------------
        if edge_tts is None:
            raise RuntimeError("edge-tts is not available")
        if edge_tts is not None:
            try:
                communicate = edge_tts.Communicate(
                    text, voice, rate=self.rate, pitch=self.pitch
                )
                audio_data = b""
                async for chunk in communicate.stream():
                    # Edge‑TTS may yield raw bytes or a dict with an ``audio`` key.
                    if isinstance(chunk, dict):
                        data = chunk.get("data", b"")
                    else:
                        data = chunk
                    audio_data += data
                    yield data
                # Cache the result for future calls.
                if self.cache_common_phrases:
                    self._cache[text] = audio_data
                return
            except Exception as exc:  # pragma: no cover
                # Network errors, authentication problems, etc.
                logger.warning(
                    "Edge‑TTS failed (%s). Falling back to offline silent audio.", exc
                )
                # Continue to offline fallback.

        # -----------------------------------------------------------------
        # 3️⃣ Offline fallback – return a short silent audio placeholder.
        # -----------------------------------------------------------------
        silent_audio = self._generate_silent_placeholder()
        # Cache the silent placeholder if caching is enabled – it is cheap.
        if self.cache_common_phrases:
            self._cache[text] = silent_audio
        # Yield the placeholder in a single chunk to keep the async contract.
        yield silent_audio

    async def speak(self, text: str, voice: Optional[str] = None) -> bytes:
        """
        Convenience method that returns the full audio as a single ``bytes``
        object. It internally uses :meth:`stream_audio`.
        """
        chunks = [chunk async for chunk in self.stream_audio(text, voice)]
        return b"".join(chunks)

    def clear_cache(self):
        """Empty the phrase cache."""
        self._cache.clear()

    # --------------------------------------------------------------------- #
    # Private helpers
    # --------------------------------------------------------------------- #
    @staticmethod
    def _generate_silent_placeholder(duration_ms: int = 200) -> bytes:
        """
        Produce a minimal silent WAV payload.

        The placeholder is a 16‑bit PCM mono WAV file containing ``duration_ms``
        of silence. This is sufficient for downstream components that expect
        a valid audio container but do not require actual speech.

        Parameters
        ----------
        duration_ms:
            Length of the silent audio in milliseconds (default: 200 ms).

        Returns
        -------
        bytes
            WAV file bytes representing silence.
        """
        import wave
        import io

        sample_rate = 16000  # 16 kHz – matches the rest of the repo.
        num_channels = 1
        sampwidth = 2  # 16‑bit
        num_frames = int(sample_rate * (duration_ms / 1000.0))

        silent_frame = (0).to_bytes(sampwidth, byteorder="little", signed=True)

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wf:
            wf.setnchannels(num_channels)
            wf.setsampwidth(sampwidth)
            wf.setframerate(sample_rate)
            wf.writeframes(silent_frame * num_frames)

        return buffer.getvalue()

def _generate_silent_audio(duration_sec: float = 1.0, sample_rate: int = 16000) -> bytes:
    import io, wave
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * int(sample_rate * duration_sec))
    return buffer.getvalue()
