import pytest
import struct
import math
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

from src.audio.vad import VoiceActivityDetector, CircularAudioBuffer
from src.audio.wakeword import WakeWordDetector
from src.audio.stt import Transcriber, validate_audio_header
from src.audio.tts import TTSEngine
from src.voice.pipeline import VoicePipeline, VoicePipelineState
from src.observability.event_bus import EventBus
from src.models.schemas import StreamChunkPayload


def test_real_audio_math_pcm_validation():
    # 1. Test PCM byte validation
    valid_pcm = b"\x00\x01" * 100
    assert validate_audio_header(valid_pcm) == valid_pcm

    with pytest.raises(ValueError, match="Audio bytes cannot be empty"):
        validate_audio_header(b"")

    with pytest.raises(ValueError, match="multiple of 2"):
        validate_audio_header(b"\x00\x01\x02")

    # 2. Test WAV header parsing
    wav_header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 44 + 20, b"WAVE",
        b"fmt ", 16, 1, 1, 16000, 32000, 2, 16,
        b"data", 20
    )
    wav_bytes = wav_header + (b"\x00\x00" * 10)
    pcm_payload = validate_audio_header(wav_bytes)
    assert pcm_payload == b"\x00\x00" * 10

    # 3. RMS energy computation in VAD
    vad = VoiceActivityDetector(sample_rate=16000, frame_duration_ms=30, threshold=0.01)
    silence_frame = [0.0] * vad.frame_size
    assert vad._frame_energy(silence_frame) == 0.0
    assert vad.is_speech(silence_frame) is False

    t = [i / 16000.0 for i in range(vad.frame_size)]
    sine_frame = [0.5 * math.sin(2 * math.pi * 440 * ti) for ti in t]
    rms = vad._frame_energy(sine_frame)
    assert rms > 0.3
    assert vad.is_speech(sine_frame) is True


def test_vad_ring_buffer_and_hangover():
    buf = CircularAudioBuffer(capacity_seconds=1.0, sample_rate=8000)
    pcm_bytes = b"\x00\x01" * 100
    buf.add(pcm_bytes)
    assert len(buf) == 100
    retrieved_bytes = buf.get_bytes()
    assert len(retrieved_bytes) == 200

    # Test hangover speech segmentation
    vad = VoiceActivityDetector(sample_rate=8000, frame_duration_ms=20, threshold=0.01, hangover_ms=100)
    frame_size = vad.frame_size

    t = [i / 8000.0 for i in range(frame_size)]
    speech = [0.5 * math.sin(2 * math.pi * 440 * ti) for ti in t]
    silence = [0.0] * frame_size

    # Speech for 1 frame, followed by 10 silent frames
    samples = speech + (silence * 10)
    segments = vad.segment_speech(samples)
    assert len(segments) == 1
    # End sample should include hangover frames (1 speech frame + 5 hangover frames = 6 frames)
    start_s, end_s = segments[0]
    assert start_s == 0
    assert end_s >= frame_size * 5


@pytest.mark.asyncio
async def test_pipeline_state_machine_transitions():
    event_bus = EventBus()
    state_changes = []

    async def listener(evt):
        if evt.topic == "voice.state_changed":
            state_changes.append((evt.payload["old_state"], evt.payload["new_state"]))

    event_bus.subscribe("voice.state_changed", listener)

    pipeline = VoicePipeline(event_bus=event_bus, device_id="pod-test")
    assert pipeline.state == VoicePipelineState.IDLE

    await pipeline.set_state(VoicePipelineState.WAKE_DETECTED)
    await pipeline.set_state(VoicePipelineState.LISTENING)
    await pipeline.set_state(VoicePipelineState.PROCESSING)
    await pipeline.set_state(VoicePipelineState.SPEAKING)
    await pipeline.set_state(VoicePipelineState.IDLE)

    assert state_changes == [
        ("IDLE", "WAKE_DETECTED"),
        ("WAKE_DETECTED", "LISTENING"),
        ("LISTENING", "PROCESSING"),
        ("PROCESSING", "SPEAKING"),
        ("SPEAKING", "IDLE")
    ]


@pytest.mark.asyncio
async def test_barge_in_cancellation():
    event_bus = EventBus()
    barge_in_events = []
    event_bus.subscribe("voice.barge_in", lambda evt: barge_in_events.append(evt.topic))

    mock_ww = MagicMock()
    mock_ww.detect.return_value = True
    mock_ww.keyword = "hey iris"

    pipeline = VoicePipeline(wakeword=mock_ww, event_bus=event_bus, device_id="pod-test")
    pipeline.is_speaking = True
    pipeline.state = VoicePipelineState.SPEAKING

    res = await pipeline.process_audio_chunk(b"\x00" * 2560)
    assert res["status"] == "wakeword_detected"
    assert pipeline.is_speaking is False
    assert pipeline.state == VoicePipelineState.LISTENING
    assert len(barge_in_events) == 1


def test_stt_and_tts_unavailable_error_handling():
    # STT fallback_mock=False raises error when whisper unavailable
    with patch("src.audio.stt.WhisperModel", None), patch("src.audio.stt.whisper", None):
        stt = Transcriber(fallback_mock=False)
        with pytest.raises(RuntimeError, match="STT engine is UNAVAILABLE"):
            stt.transcribe_pcm(b"\x00\x00" * 100)

    # TTS edge-tts missing raises error
    async def run_tts_missing():
        with patch("src.audio.tts.edge_tts", None):
            tts = TTSEngine()
            async for _ in tts.stream_audio("Hello"):
                pass

    with pytest.raises(RuntimeError, match=r"(edge-tts is not available|No usable speech synthesis engine available)"):
        asyncio.run(run_tts_missing())


@pytest.mark.asyncio
async def test_pipeline_lifecycle_events():
    event_bus = EventBus()
    topics = []
    event_bus.subscribe("*", lambda evt: topics.append(evt.topic))

    mock_stt = MagicMock()
    mock_stt.transcribe_pcm.return_value = "Turn on desk lamp"

    mock_orch = MagicMock()
    async def mock_stream(*args, **kwargs):
        yield StreamChunkPayload(chunk_type="text_delta", delta_text="Turning on ", session_id="s1")
        yield StreamChunkPayload(chunk_type="text_delta", delta_text="desk lamp.", session_id="s1")
    mock_orch.stream_request = mock_stream

    mock_tts = MagicMock()
    async def mock_stream_audio(text, voice=None):
        yield f"AUDIO[{text}]".encode("utf-8")
    mock_tts.stream_audio = mock_stream_audio

    pipeline = VoicePipeline(
        stt=mock_stt,
        orchestrator=mock_orch,
        tts=mock_tts,
        event_bus=event_bus,
        device_id="pod-test"
    )

    chunks = []
    async for chunk in pipeline.execute_end_to_end(b"\x00" * 3200):
        chunks.append(chunk)

    assert len(chunks) > 0
    assert "voice.state_changed" in topics
    assert "voice.stt.started" in topics
    assert "voice.stt.completed" in topics
    assert "voice.transcription_completed" in topics
    assert "voice.agent.started" in topics
    assert "voice.tts.started" in topics
    assert "voice.tts_started" in topics
    assert "voice.tts_completed" in topics
    assert "voice.pipeline.completed" in topics
