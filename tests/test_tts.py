import asyncio
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from src.audio.tts import TTSEngine


def _make_async_gen(items):
    """Helper to create an async generator from a list of items."""
    async def gen():
        for item in items:
            yield item
    return gen


class TestTTSEngine:
    """Unit tests for the TTSEngine class."""

    def test_stream_audio_yields_chunks(self):
        """Test that stream_audio yields audio chunks from edge-tts."""
        async def _test():
            mock_communicate = MagicMock()
            mock_communicate.stream = _make_async_gen([b"chunk1", b"chunk2", b"chunk3"])

            with patch("src.audio.tts.edge_tts") as mock_edge_tts:
                mock_edge_tts.Communicate.return_value = mock_communicate
                engine = TTSEngine()
                chunks = []
                async for chunk in engine.stream_audio("Hello world"):
                    chunks.append(chunk)
                return chunks, mock_edge_tts

        chunks, mock_edge_tts = asyncio.run(_test())
        assert chunks == [b"chunk1", b"chunk2", b"chunk3"]
        mock_edge_tts.Communicate.assert_called_once_with(
            "Hello world", "en-US-AriaNeural", rate="+0%", pitch="+0Hz"
        )

    def test_stream_audio_caching(self):
        """Test that common phrases are cached and reused."""
        async def _test():
            mock_communicate = MagicMock()
            mock_communicate.stream = _make_async_gen([b"cached_audio"])

            with patch("src.audio.tts.edge_tts") as mock_edge_tts:
                mock_edge_tts.Communicate.return_value = mock_communicate
                engine = TTSEngine()
                engine._cache["Hello"] = b"cached_audio"  # pre‑seed cache

                chunks = []
                async for chunk in engine.stream_audio("Hello"):
                    chunks.append(chunk)
                return chunks, mock_edge_tts

        chunks, mock_edge_tts = asyncio.run(_test())
        assert chunks == [b"cached_audio"]
        # edge_tts.Communicate should NOT be called because cache hit
        mock_edge_tts.Communicate.assert_not_called()

    def test_stream_audio_custom_voice(self):
        """Test that a custom voice is passed to edge-tts."""
        async def _test():
            mock_communicate = MagicMock()
            mock_communicate.stream = _make_async_gen([b"data"])

            with patch("src.audio.tts.edge_tts") as mock_edge_tts:
                mock_edge_tts.Communicate.return_value = mock_communicate
                engine = TTSEngine()
                async for _ in engine.stream_audio("Test", voice="en-GB-SoniaNeural"):
                    pass
                return mock_edge_tts

        mock_edge_tts = asyncio.run(_test())
        mock_edge_tts.Communicate.assert_called_once_with(
            "Test", "en-GB-SoniaNeural", rate="+0%", pitch="+0Hz"
        )

    def test_stream_audio_pitch_rate_modulation(self):
        """Test that pitch and rate are forwarded to edge-tts."""
        async def _test():
            mock_communicate = MagicMock()
            mock_communicate.stream = _make_async_gen([b"mod"])

            with patch("src.audio.tts.edge_tts") as mock_edge_tts:
                mock_edge_tts.Communicate.return_value = mock_communicate
                engine = TTSEngine(rate="+20%", pitch="+100Hz")
                async for _ in engine.stream_audio("Modulate"):
                    pass
                return mock_edge_tts

        mock_edge_tts = asyncio.run(_test())
        mock_edge_tts.Communicate.assert_called_once_with(
            "Modulate", "en-US-AriaNeural", rate="+20%", pitch="+100Hz"
        )

    def test_speak_returns_aggregate_bytes(self):
        """Test that speak() returns all audio data concatenated."""
        async def _test():
            mock_communicate = MagicMock()
            mock_communicate.stream = _make_async_gen([b"part1", b"part2"])

            with patch("src.audio.tts.edge_tts") as mock_edge_tts:
                mock_edge_tts.Communicate.return_value = mock_communicate
                engine = TTSEngine()
                result = await engine.speak("Hello")
                return result

        result = asyncio.run(_test())
        assert result == b"part1part2"

    def test_edge_tts_not_installed_raises(self):
        """Test that a RuntimeError is raised when edge-tts is missing."""
        async def _test():
            with patch("src.audio.tts.edge_tts", None):
                engine = TTSEngine()
                async for _ in engine.stream_audio("Hi"):
                    pass

        with pytest.raises(RuntimeError, match="edge-tts is not available"):
            asyncio.run(_test())

    def test_cache_disabled(self):
        """Test that caching does not occur when disabled."""
        async def _test():
            mock_communicate = MagicMock()
            mock_communicate.stream = _make_async_gen([b"data"])

            with patch("src.audio.tts.edge_tts") as mock_edge_tts:
                mock_edge_tts.Communicate.return_value = mock_communicate
                engine = TTSEngine(cache_common_phrases=False)

                # First call
                chunks1 = [c async for c in engine.stream_audio("Hello")]
                # Second call – should call edge_tts again
                chunks2 = [c async for c in engine.stream_audio("Hello")]
                return chunks1, chunks2, mock_edge_tts

        chunks1, chunks2, mock_edge_tts = asyncio.run(_test())
        assert chunks1 == [b"data"]
        assert chunks2 == [b"data"]
        assert mock_edge_tts.Communicate.call_count == 2
