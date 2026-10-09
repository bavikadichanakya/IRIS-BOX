import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock

from src.voice.pipeline import VoicePipeline
from src.observability.event_bus import EventBus
from src.models.schemas import StreamChunkPayload
from src.observability.tracing import create_trace_context


@pytest.mark.asyncio
async def test_voice_pipeline_end_to_end():
    # 1. Mock STT
    mock_stt = MagicMock()
    mock_stt.transcribe_pcm.return_value = "Turn on living room light"

    # 2. Mock Agent Orchestrator
    mock_orchestrator = MagicMock()
    async def mock_stream_request(*args, **kwargs):
        yield StreamChunkPayload(chunk_type="text_delta", delta_text="Turning on ", session_id="s1")
        yield StreamChunkPayload(chunk_type="text_delta", delta_text="the living room light.", session_id="s1")
    mock_orchestrator.stream_request = mock_stream_request

    # 3. Mock TTS Engine
    mock_tts = MagicMock()
    async def mock_stream_audio(text, voice=None):
        yield f"AUDIO[{text}]".encode("utf-8")
    mock_tts.stream_audio = mock_stream_audio

    # 4. EventBus listener
    event_bus = EventBus()
    published_topics = []
    event_bus.subscribe("*", lambda evt: published_topics.append(evt.topic))

    pipeline = VoicePipeline(
        stt=mock_stt,
        orchestrator=mock_orchestrator,
        tts=mock_tts,
        event_bus=event_bus,
        device_id="test-pod-01"
    )

    audio_bytes_result = []
    dummy_pcm = b"\x00" * 3200

    async for chunk in pipeline.execute_end_to_end(dummy_pcm):
        audio_bytes_result.append(chunk)

    # Verifications
    assert len(audio_bytes_result) > 0
    full_audio = b"".join(audio_bytes_result)
    assert b"AUDIO" in full_audio

    # Verify lifecycle events
    assert "voice.stt.started" in published_topics
    assert "voice.stt.completed" in published_topics
    assert "voice.agent.started" in published_topics
    assert "voice.tts.started" in published_topics
    assert "voice.pipeline.completed" in published_topics


@pytest.mark.asyncio
async def test_voice_pipeline_barge_in_interruption():
    event_bus = EventBus()
    published_topics = []
    event_bus.subscribe("*", lambda evt: published_topics.append(evt.topic))

    mock_wakeword = MagicMock()
    mock_wakeword.detect.return_value = True
    mock_wakeword.keyword = "hey iris"

    pipeline = VoicePipeline(
        wakeword=mock_wakeword,
        event_bus=event_bus,
        device_id="test-pod-01"
    )

    # Set state as speaking
    pipeline.is_speaking = True
    pipeline.state = "SPEAKING"

    # Process audio chunk with wakeword
    result = await pipeline.process_audio_chunk(b"\x00" * 2560)

    assert result["status"] == "wakeword_detected"
    assert pipeline.is_speaking is False
    assert "voice.barge_in" in published_topics
    assert "voice.wakeword.detected" in published_topics


@pytest.mark.asyncio
async def test_voice_pipeline_empty_transcript():
    mock_stt = MagicMock()
    mock_stt.transcribe_pcm.return_value = "   "  # Empty transcript

    mock_orchestrator = MagicMock()
    mock_orchestrator.stream_request = AsyncMock()

    event_bus = EventBus()
    published_topics = []
    event_bus.subscribe("*", lambda evt: published_topics.append(evt.topic))

    pipeline = VoicePipeline(
        stt=mock_stt,
        orchestrator=mock_orchestrator,
        event_bus=event_bus,
        device_id="test-pod-01"
    )

    chunks = []
    async for chunk in pipeline.execute_end_to_end(b"\x00" * 1000):
        chunks.append(chunk)

    assert len(chunks) == 0
    assert "voice.stt.completed" in published_topics
    assert "voice.agent.started" not in published_topics
