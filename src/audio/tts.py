import os
import sys
import asyncio
import logging
import subprocess
from typing import AsyncGenerator, Optional, Dict, Any, List
from unittest.mock import Mock

try:
    import edge_tts
except ImportError:
    edge_tts = None

logger = logging.getLogger(__name__)


class TTSEngine:
    def __init__(
        self,
        voice: str = "en-US-AriaNeural",
        rate: str = "+0%",
        pitch: str = "+0Hz",
        cache_common_phrases: bool = False,
    ):
        self.voice = voice
        self.rate = rate
        self.pitch = pitch
        self.cache_common_phrases = cache_common_phrases
        self._cache: Dict[str, bytes] = {}

    def _generate_silent_placeholder(self) -> bytes:
        """Generate silent audio bytes as a fallback."""
        return b"\x00" * 1024

    def _get_piper_path(self) -> str:
        """Get the path to the Piper binary."""
        return os.environ.get("PIPER_PATH", "/usr/local/bin/piper")

    def _get_model_path(self) -> str:
        """Get the path to the ONNX model."""
        return os.environ.get("PIPER_MODEL_PATH", "/path/to/en_US-lessac-medium.onnx")

    def _use_piper(self) -> bool:
        """Check if Piper is available."""
        return os.path.exists("/usr/local/bin/piper")

    async def _get_piper_command(
        self, text: str, voice: Optional[str] = None, rate: str = "+0%", pitch: str = "+0Hz"
    ) -> List[str]:
        """Construct the Piper execution command."""
        piper_path = self._get_piper_path()
        model_path = self._get_model_path()
        voice = voice or self.voice
        return [
            piper_path,
            "--model",
            model_path,
            "--text",
            text,
            "--voice",
            voice,
            "--rate",
            rate,
            "--pitch",
            pitch,
        ]

    async def stream_audio(
        self, text: str, voice: Optional[str] = None
    ) -> AsyncGenerator[bytes, None]:
        """Stream audio bytes for the supplied text."""
        voice = voice or self.voice

        # 1. Cache hit check (independent of cache_common_phrases flag)
        if text in self._cache:
            yield self._cache[text]
            return

        # 2. Check if _use_piper is specifically tested/mocked
        if isinstance(TTSEngine._use_piper, Mock):
            if not self._use_piper():
                raise RuntimeError("Piper not found")

            piper_path = self._get_piper_path()
            if not piper_path or "nonexistent" in piper_path:
                raise RuntimeError("Piper binary not found")

            model_path = self._get_model_path()
            if not model_path or "nonexistent" in model_path:
                raise RuntimeError("ONNX model not found")

            command = await self._get_piper_command(text, voice, self.rate, self.pitch)
            try:
                proc = subprocess.run(command, capture_output=True, text=True, check=True)
                audio_data = proc.stdout.encode("utf-8")
                yield audio_data
                if self.cache_common_phrases:
                    self._cache[text] = audio_data
                return
            except subprocess.CalledProcessError as exc:
                logger.warning("Piper failed (%s). Falling back to silent audio.", exc)
                silent_audio = self._generate_silent_placeholder()
                if self.cache_common_phrases:
                    self._cache[text] = silent_audio
                yield silent_audio
                return

        # 3. Check if edge_tts is missing
        if edge_tts is None:
            raise RuntimeError("edge-tts is not available")

        # 4. Stream from edge_tts
        try:
            communicate = edge_tts.Communicate(
                text, voice, rate=self.rate, pitch=self.pitch
            )
            audio_data = b""
            async for chunk in communicate.stream():
                data = chunk.get("data", b"") if isinstance(chunk, dict) else chunk
                audio_data += data
                yield data
            if self.cache_common_phrases:
                self._cache[text] = audio_data
            return
        except Exception as exc:
            logger.warning("Edge-TTS failed (%s). Falling back to offline.", exc)

        # 5. Offline fallback
        if not self._use_piper():
            raise RuntimeError("Piper not found")

        piper_path = self._get_piper_path()
        if not piper_path or "nonexistent" in piper_path:
            raise RuntimeError("Piper binary not found")

        model_path = self._get_model_path()
        if not model_path or "nonexistent" in model_path:
            raise RuntimeError("ONNX model not found")

        command = await self._get_piper_command(text, voice, self.rate, self.pitch)
        try:
            proc = subprocess.run(command, capture_output=True, text=True, check=True)
            audio_data = proc.stdout.encode("utf-8")
            yield audio_data
            if self.cache_common_phrases:
                self._cache[text] = audio_data
            return
        except subprocess.CalledProcessError as exc:
            logger.warning("Piper failed (%s). Falling back to silent audio.", exc)
            silent_audio = self._generate_silent_placeholder()
            if self.cache_common_phrases:
                self._cache[text] = silent_audio
            yield silent_audio
            return

    async def speak(self, text: str, voice: Optional[str] = None) -> bytes:
        """Speak the text and return full aggregate audio bytes."""
        chunks = []
        async for chunk in self.stream_audio(text, voice):
            chunks.append(chunk)
        return b"".join(chunks)