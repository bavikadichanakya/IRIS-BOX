import os
import sys
import shutil
import asyncio
import logging
import subprocess
from typing import AsyncGenerator, AsyncIterator, Optional, Dict, Any, List
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
        online_fallback: bool = False,
    ):
        self.voice = voice
        self.rate = rate
        self.pitch = pitch
        self.cache_common_phrases = cache_common_phrases
        self.online_fallback = online_fallback
        self._cache: Dict[str, bytes] = {}

    def _get_piper_path(self) -> str:
        """Get the path to the Piper binary with OS auto-detection."""
        env_path = os.environ.get("PIPER_PATH")
        if env_path:
            return env_path

        which_path = shutil.which("piper") or shutil.which("piper.exe")
        if which_path:
            return which_path

        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        candidates = [
            os.path.join(base_dir, "models", "piper", "piper.exe"),
            os.path.join(base_dir, "models", "piper", "piper"),
            os.path.join(base_dir, "bin", "piper.exe"),
            os.path.join(base_dir, "bin", "piper"),
            "/usr/local/bin/piper",
            "/usr/bin/piper",
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
        return "/usr/local/bin/piper"

    def _get_model_path(self) -> str:
        """Get the path to the ONNX voice model."""
        env_path = os.environ.get("PIPER_MODEL_PATH")
        if env_path:
            return env_path

        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        candidates = [
            os.path.join(base_dir, "models", "piper", "en_US-lessac-medium.onnx"),
            os.path.join(base_dir, "models", "en_US-lessac-medium.onnx"),
            os.path.join(base_dir, "models", "voice.onnx"),
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
        return "/path/to/en_US-lessac-medium.onnx"

    def _use_piper(self) -> bool:
        """Check if Piper is available."""
        piper_path = self._get_piper_path()
        return bool(piper_path and (os.path.exists(piper_path) or shutil.which(piper_path)))

    async def _get_piper_command(
        self, text: str, voice: Optional[str] = None, rate: str = "+0%", pitch: str = "+0Hz"
    ) -> List[str]:
        """Construct the Piper execution command."""
        piper_path = self._get_piper_path()
        model_path = self._get_model_path()
        return [
            piper_path,
            "--model",
            model_path,
            "--output_file",
            "-",
        ]

    async def stream_audio(
        self, text: str, voice: Optional[str] = None, chunk_size: int = 2048
    ) -> AsyncGenerator[bytes, None]:
        """Stream audio bytes for the supplied text. Offline Piper synthesis is prioritized."""
        voice = voice or self.voice

        # 1. Cache hit check
        if text in self._cache:
            yield self._cache[text]
            return

        # 2. Check if Piper is available
        use_piper = self._use_piper()

        if use_piper:
            piper_path = self._get_piper_path()
            if not piper_path or "nonexistent" in piper_path or (not os.path.exists(piper_path) and not shutil.which(piper_path)):
                raise RuntimeError("Piper binary not found")

            model_path = self._get_model_path()
            if not model_path or "nonexistent" in model_path or not os.path.exists(model_path):
                raise RuntimeError("ONNX model not found")

            command = await self._get_piper_command(text, voice, self.rate, self.pitch)
            proc = None
            try:
                # Asynchronous subprocess streaming for progressive chunk delivery
                proc = await asyncio.create_subprocess_exec(
                    *command,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                proc.stdin.write(text.encode("utf-8"))
                await proc.stdin.drain()
                proc.stdin.close()

                full_data = bytearray()
                while True:
                    chunk = await proc.stdout.read(chunk_size)
                    if not chunk:
                        break
                    full_data.extend(chunk)
                    yield chunk

                await proc.wait()
                if proc.returncode != 0:
                    err_msg = (await proc.stderr.read()).decode("utf-8", errors="replace")
                    logger.error("Piper synthesis failed: %s", err_msg)
                    raise RuntimeError(f"TTS synthesis failed: Piper execution error ({err_msg})")

                if not full_data:
                    raise RuntimeError("Piper generated empty audio buffer")

                if self.cache_common_phrases:
                    self._cache[text] = bytes(full_data)
                return
            except asyncio.CancelledError:
                if proc:
                    try:
                        proc.kill()
                    except (ProcessLookupError, Exception):
                        pass
                    await proc.wait()
                raise
            except (NotImplementedError, AttributeError):
                # Fallback to subprocess.run if event loop does not support async subprocess
                try:
                    proc_sync = subprocess.run(
                        command,
                        input=text.encode("utf-8"),
                        capture_output=True,
                        text=False,
                        check=True
                    )
                    audio_data = proc_sync.stdout
                    if not audio_data:
                        raise RuntimeError("Piper generated empty audio buffer")
                    yield audio_data
                    if self.cache_common_phrases:
                        self._cache[text] = audio_data
                    return
                except subprocess.CalledProcessError as exc:
                    err_msg = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else str(exc)
                    logger.error("Piper synthesis failed: %s", err_msg)
                    raise RuntimeError(f"TTS synthesis failed: Piper execution error ({err_msg})")
        # 3. Optional Edge-TTS online fallback if explicitly enabled/available
        if self.online_fallback:
            if edge_tts is None:
                raise RuntimeError("edge-tts is not available")

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
                logger.error("Edge-TTS failed: %s", exc)
                raise RuntimeError(f"TTS synthesis failed (Edge-TTS error): {exc}")

        # 4. No synthesis engine available
        raise RuntimeError("Piper not found")

    async def synthesize_stream(
        self, text_stream: AsyncIterator[str], chunk_size: int = 2048, voice: Optional[str] = None
    ) -> AsyncGenerator[bytes, None]:
        """
        Consumes streaming sentence chunks from text_stream, synthesizes each via Piper stdin,
        and yields binary audio chunks progressively as they arrive from stdout.
        Supports cooperative cancellation: terminates process immediately on CancelledError.
        """
        voice = voice or self.voice
        async for sentence in text_stream:
            clean = sentence.strip()
            if not clean:
                continue
            try:
                async for pcm_chunk in self.stream_audio(clean, voice=voice, chunk_size=chunk_size):
                    yield pcm_chunk
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("TTS synthesis error for sentence '%s': %s", clean, e)

    async def speak(self, text: str, voice: Optional[str] = None) -> bytes:
        """Speak the text and return full aggregate audio bytes."""
        chunks = []
        async for chunk in self.stream_audio(text, voice):
            chunks.append(chunk)
        return b"".join(chunks)

    async def synthesize(self, text: str, voice: Optional[str] = None) -> bytes:
        """Synthesize text into full audio bytes (alias for speak)."""
        return await self.speak(text, voice)