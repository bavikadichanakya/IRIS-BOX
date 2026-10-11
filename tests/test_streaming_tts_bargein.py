import asyncio
import base64
import math
import struct
import time
from typing import AsyncGenerator
from unittest.mock import patch, MagicMock, AsyncMock

import pytest
from fastapi.testclient import TestClient

from src.audio.chunker import SentenceChunker
from src.audio.tts import TTSEngine
from src.models.schemas import StreamChunkPayload
from src.observability.event_bus import EventBus
from src.observability.metrics import runtime_metrics
from src.security.auth import auth_manager
from src.server.app import app
from src.server.protocol import (
    OutboundAudioFlushPayload,
    OutboundTokenDeltaPayload,
    OutboundAudioOutputPayload,
    OutboundTurnCompletePayload,
    parse_inbound_message,
)
from src.server.websocket import WebSocketConnectionManager, ws_manager


# ==============================================================================
# 1. Sentence Chunker Unit Tests
# ==============================================================================

class TestSentenceChunker:
    """Unit tests for SentenceChunker clause boundary extraction and filtering."""

    def test_chunker_basic_boundaries(self):
        chunker = SentenceChunker(min_words=4)
        tokens = [
            "Hello ", "there, ", "how are ", "you today? ",
            "I am doing ", "very well ", "thank you. ",
        ]
        emitted = []
        for t in tokens:
            emitted.extend(chunker.add_token(t))
        emitted.extend(chunker.flush())

        assert len(emitted) == 2
        assert emitted[0] == "Hello there, how are you today?"
        assert emitted[1] == "I am doing very well thank you."

    def test_chunker_abbreviation_protection(self):
        chunker = SentenceChunker(min_words=4)
        tokens = [
            "Dr. ", "Smith ", "arrived ", "at the clinic ",
            "at 10 a.m. ", "for the appointment. ",
        ]
        emitted = []
        for t in tokens:
            emitted.extend(chunker.add_token(t))
        emitted.extend(chunker.flush())

        # Should not split prematurely on "Dr."
        assert len(emitted) == 1
        assert "Dr. Smith arrived at the clinic at 10 a.m. for the appointment." in emitted[0]

    def test_chunker_decimal_number_protection(self):
        chunker = SentenceChunker(min_words=4)
        tokens = [
            "The system temperature ", "is exactly ", "98.6 degrees ",
            "Fahrenheit right now. ",
        ]
        emitted = []
        for t in tokens:
            emitted.extend(chunker.add_token(t))
        emitted.extend(chunker.flush())

        assert len(emitted) == 1
        assert "98.6" in emitted[0]
        assert emitted[0].endswith("right now.")

    def test_chunker_minimum_word_threshold(self):
        chunker = SentenceChunker(min_words=4)
        # Short clause "Yes." with only 1 word should NOT emit immediately
        res1 = chunker.add_token("Yes. ")
        assert res1 == []

        # When more words accumulate and a second boundary arrives:
        res2 = chunker.add_token("Indeed it is quite wonderful outside. ")
        assert len(res2) == 1
        assert "Yes. Indeed it is quite wonderful outside." in res2[0]

    def test_chunker_flush_trailing_text(self):
        chunker = SentenceChunker(min_words=4)
        chunker.add_token("Here is an incomplete sentence without punctuation")
        assert chunker._buffer != ""

        trailing = chunker.flush()
        assert trailing == ["Here is an incomplete sentence without punctuation"]
        assert chunker._buffer == ""

    @pytest.mark.asyncio
    async def test_chunker_async_stream(self):
        chunker = SentenceChunker(min_words=3)

        async def token_gen():
            yield "First sentence here. "
            yield "Second clause follows now. "
            yield "Trailing thought"

        chunks = []
        async for c in chunker.chunk_stream(token_gen()):
            chunks.append(c)

        assert len(chunks) == 3
        assert chunks[0] == "First sentence here."
        assert chunks[1] == "Second clause follows now."
        assert chunks[2] == "Trailing thought"


# ==============================================================================
# 2. Piper Streaming Voice Worker Tests
# ==============================================================================

class TestTTSSynthesizeStream:
    """Tests for progressive chunk streaming and zero-mock offline policy."""

    def test_zero_mock_offline_policy(self):
        """Verify Piper engine maintains strict zero-mock online_fallback=False policy."""
        tts = TTSEngine(online_fallback=False)
        assert tts.online_fallback is False

        # When Piper is missing and online_fallback=False, it must raise RuntimeError
        with patch.object(TTSEngine, "_use_piper", return_value=False):
            with pytest.raises(RuntimeError, match="Piper not found"):
                asyncio.run(tts.speak("Hello world"))

    @pytest.mark.asyncio
    async def test_synthesize_stream_progressive_yielding(self):
        """Verify synthesize_stream consumes sentence chunks and yields PCM chunks."""
        tts = TTSEngine(online_fallback=False)

        async def sentence_stream():
            yield "Sentence number one."
            yield "Sentence number two."

        # Mock stream_audio to yield progressive 1024-byte chunks
        async def mock_stream_audio(text, voice=None, chunk_size=2048):
            yield b"\x01\x02" * 512
            yield b"\x03\x04" * 512

        with patch.object(tts, "stream_audio", side_effect=mock_stream_audio):
            pcm_chunks = []
            async for chunk in tts.synthesize_stream(sentence_stream()):
                pcm_chunks.append(chunk)

            # 2 sentences * 2 chunks each = 4 chunks
            assert len(pcm_chunks) == 4
            for c in pcm_chunks:
                assert len(c) == 1024

    @pytest.mark.asyncio
    async def test_synthesize_stream_cooperative_cancellation(self):
        """Verify cancellation terminates streaming cleanly without uncaught exceptions."""
        tts = TTSEngine(online_fallback=False)

        async def slow_sentence_stream():
            yield "First sentence."
            await asyncio.sleep(5)
            yield "Second sentence."

        async def slow_stream_audio(text, voice=None, chunk_size=2048):
            yield b"\x00" * 1024
            await asyncio.sleep(10)
            yield b"\x00" * 1024

        with patch.object(tts, "stream_audio", side_effect=slow_stream_audio):
            task = asyncio.create_task(
                tts.speak("Test text")  # or synthesize_stream
            )

            # Create task to consume synthesize_stream
            async def consumer():
                async for _ in tts.synthesize_stream(slow_sentence_stream()):
                    pass

            consumer_task = asyncio.create_task(consumer())
            await asyncio.sleep(0.05)
            consumer_task.cancel()

            with pytest.raises(asyncio.CancelledError):
                await consumer_task


# ==============================================================================
# 3. Full Duplex Barge-In WebSocket Tests
# ==============================================================================

@pytest.fixture
def test_client():
    from src.agent.orchestrator import IRISOrchestrator
    from src.audio.tts import TTSEngine

    if not hasattr(app.state, "orchestrator") or app.state.orchestrator is None:
        app.state.orchestrator = IRISOrchestrator(api_base="http://localhost:11434/v1", api_key="ollama")
    if not hasattr(app.state, "tts_engine") or app.state.tts_engine is None:
        app.state.tts_engine = TTSEngine(online_fallback=False)
    app.state.ws_manager = ws_manager

    with TestClient(app) as client:
        yield client


class TestDuplexBargeIn:
    """Tests for low-latency duplex barge-in cancellation and audio flush envelopes."""

    @pytest.mark.asyncio
    async def test_cancel_playback_method(self):
        """Test WebSocketConnectionManager.cancel_playback directly."""
        mgr = WebSocketConnectionManager()
        sess_id = "test-sess-bargein"

        async def dummy():
            await asyncio.sleep(10)

        task = asyncio.create_task(dummy())
        mgr.current_playback_tasks[sess_id] = task

        assert mgr.cancel_playback(sess_id) is True
        await asyncio.sleep(0)
        assert task.cancelled() or task.done()
        # Second call returns False since task is gone
        assert mgr.cancel_playback(sess_id) is False

    def test_barge_in_cancellation_during_playback(self, test_client):
        """
        Verify that an incoming high-energy audio frame during active generation
        immediately cancels the playback task, triggers OutboundAudioFlushPayload,
        and increments runtime_metrics.voice_barge_in_count.
        """
        initial_barge_ins = runtime_metrics.voice_barge_in_count

        async def mock_slow_stream_request(*args, **kwargs):
            # Slowly yield tokens to simulate active LLM generation
            yield StreamChunkPayload(chunk_type="text_delta", delta_text="This is sentence one. ", session_id="test-sess")
            await asyncio.sleep(0.5)
            yield StreamChunkPayload(chunk_type="text_delta", delta_text="This is sentence two. ", session_id="test-sess")
            await asyncio.sleep(0.5)
            yield StreamChunkPayload(chunk_type="complete", delta_text="", session_id="test-sess")

        async def mock_stream_audio(clean_text, voice=None, chunk_size=2048):
            yield b"\xaa" * 1024
            await asyncio.sleep(0.2)

        orch = getattr(app.state, "orchestrator", None)
        tts_eng = getattr(app.state, "tts_engine", None)

        with patch.object(orch, "stream_request", side_effect=mock_slow_stream_request), \
             patch.object(tts_eng, "stream_audio", side_effect=mock_stream_audio):

            url = f"/ws?device_id=barge-device-1&token={auth_manager.master_key}"
            with test_client.websocket_connect(url) as ws:
                conn_msg = ws.receive_json()
                assert conn_msg["type"] == "connected"
                sess_id = conn_msg["session_id"]

                # 1. Trigger text input that starts background playback task
                ws.send_json({"type": "text_input", "text": "Tell me a long story"})
                transcript_msg = ws.receive_json()
                assert transcript_msg["type"] == "transcript"

                # Wait briefly for playback task to be registered and start streaming
                time.sleep(0.05)
                assert sess_id in ws_manager.current_playback_tasks

                # 2. Simulate loud speech frame (> 0.015 RMS)
                # Create 16-bit PCM samples with high amplitude (e.g. 15000)
                samples = [15000 if i % 2 == 0 else -15000 for i in range(320)]
                pcm_data = struct.pack(f"<{len(samples)}h", *samples)

                # Send binary PCM frame while assistant is generating
                ws.send_bytes(pcm_data)

                # 3. Collect received messages
                received_types = []
                flush_payload = None
                for _ in range(5):
                    try:
                        msg = ws.receive_json()
                        received_types.append(msg["type"])
                        if msg["type"] == "audio_flush":
                            flush_payload = msg
                            break
                    except Exception:
                        break

                # 4. Verify barge-in behavior
                assert "audio_flush" in received_types
                assert flush_payload is not None
                assert flush_payload["type"] == "audio_flush"
                assert flush_payload.get("reason") == "barge_in"

                # Verify metrics incremented
                assert runtime_metrics.voice_barge_in_count > initial_barge_ins

                # Verify current playback task was removed/cancelled
                assert sess_id not in ws_manager.current_playback_tasks

    def test_barge_in_via_base64_audio_payload(self, test_client):
        """Verify barge-in works identically via InboundAudioFramePayload JSON frames."""
        initial_barge_ins = runtime_metrics.voice_barge_in_count

        async def mock_slow_stream_request(*args, **kwargs):
            yield StreamChunkPayload(chunk_type="text_delta", delta_text="Streaming clause one. ", session_id="test-sess")
            await asyncio.sleep(0.5)

        orch = getattr(app.state, "orchestrator", None)

        with patch.object(orch, "stream_request", side_effect=mock_slow_stream_request):
            url = f"/ws?device_id=barge-device-2&token={auth_manager.master_key}"
            with test_client.websocket_connect(url) as ws:
                conn_msg = ws.receive_json()
                sess_id = conn_msg["session_id"]

                ws.send_json({"type": "text_input", "text": "What is the weather?"})
                _ = ws.receive_json()  # transcript

                time.sleep(0.05)
                assert sess_id in ws_manager.current_playback_tasks

                # Send loud base64 audio payload
                samples = [16000 if i % 2 == 0 else -16000 for i in range(320)]
                pcm_data = struct.pack(f"<{len(samples)}h", *samples)
                b64_audio = base64.b64encode(pcm_data).decode("utf-8")

                ws.send_json({
                    "type": "audio_frame",
                    "data": b64_audio,
                    "format": "pcm16",
                    "sample_rate": 16000
                })

                # Check for audio_flush message
                received = []
                for _ in range(5):
                    try:
                        m = ws.receive_json()
                        received.append(m["type"])
                        if m["type"] == "audio_flush":
                            break
                    except Exception:
                        break

                assert "audio_flush" in received
                assert runtime_metrics.voice_barge_in_count > initial_barge_ins
