import math
import pytest
from src.audio.vad import CircularAudioBuffer, VoiceActivityDetector


class TestCircularAudioBuffer:
    def test_init_default_sample_rate(self):
        buf = CircularAudioBuffer(capacity_seconds=1.0)
        assert buf.sample_rate == 16000
        assert buf.capacity == 16000
        assert len(buf) == 0

    def test_init_custom_sample_rate(self):
        buf = CircularAudioBuffer(capacity_seconds=2.0, sample_rate=8000)
        assert buf.capacity == 16000
        assert len(buf) == 0

    def test_add_and_get(self):
        buf = CircularAudioBuffer(capacity_seconds=1.0, sample_rate=8000)
        samples = [0.1, 0.2, 0.3]
        buf.add(samples)
        assert buf.get() == samples
        assert len(buf) == 3

    def test_capacity_limit(self):
        buf = CircularAudioBuffer(capacity_seconds=1.0, sample_rate=8000)  # capacity 8000
        # add more than capacity
        buf.add([0.0] * 10000)
        assert len(buf) == 8000
        # first 2000 should be dropped
        assert buf.get() == [0.0] * 8000

    def test_clear(self):
        buf = CircularAudioBuffer(capacity_seconds=1.0, sample_rate=8000)
        buf.add([0.1, 0.2])
        buf.clear()
        assert len(buf) == 0
        assert buf.get() == []


class TestVoiceActivityDetector:
    def test_init_defaults(self):
        vad = VoiceActivityDetector()
        assert vad.sample_rate == 16000
        assert vad.frame_duration_ms == 30
        assert vad.frame_size == 480  # 16000 * 0.03
        assert vad.threshold == 0.01

    def test_init_custom_params(self):
        vad = VoiceActivityDetector(sample_rate=8000, frame_duration_ms=20, threshold=0.05)
        assert vad.frame_size == 160  # 8000 * 0.02
        assert vad.threshold == 0.05

    def test_is_speech_silence(self):
        vad = VoiceActivityDetector(threshold=0.1)
        silent_frame = [0.0] * vad.frame_size
        assert vad.is_speech(silent_frame) is False

    def test_is_speech_speech(self):
        vad = VoiceActivityDetector(threshold=0.01, sample_rate=8000, frame_duration_ms=20)
        # generate a sine wave with amplitude 0.5 -> RMS ~0.35
        freq = 440.0
        duration = vad.frame_size / 8000.0
        t = [i / 8000.0 for i in range(vad.frame_size)]
        frame = [0.5 * math.sin(2 * math.pi * freq * ti) for ti in t]
        assert vad.is_speech(frame) is True

    def test_detect(self):
        vad = VoiceActivityDetector(threshold=0.01, sample_rate=8000, frame_duration_ms=20)
        # create 1 second of audio: 0.5s silence, 0.5s sine, 0.5s silence
        frame_size = vad.frame_size
        silent = [0.0] * frame_size
        freq = 440.0
        t_speech = [i / 8000.0 for i in range(frame_size)]
        speech = [0.5 * math.sin(2 * math.pi * freq * ti) for ti in t_speech]
        samples = silent + speech + silent
        flags = vad.detect(samples)
        # number of frames: 3 frames (each frame_size)
        assert len(flags) == 3
        assert flags[0] is False
        assert flags[1] is True
        assert flags[2] is False

    def test_segment_speech(self):
        vad = VoiceActivityDetector(threshold=0.01, sample_rate=8000, frame_duration_ms=20)
        frame_size = vad.frame_size
        silent = [0.0] * frame_size
        freq = 440.0
        t_speech = [i / 8000.0 for i in range(frame_size)]
        speech = [0.5 * math.sin(2 * math.pi * freq * ti) for ti in t_speech]
        # pattern: silence, speech, silence, speech, silence
        samples = silent + speech + silent + speech + silent
        segments = vad.segment_speech(samples)
        # expected segments: (frame_size, 2*frame_size), (3*frame_size, 4*frame_size)
        assert len(segments) == 2
        assert segments[0] == (frame_size, 2 * frame_size)
        assert segments[1] == (3 * frame_size, 4 * frame_size)

    def test_segment_speech_trailing_speech(self):
        vad = VoiceActivityDetector(threshold=0.01, sample_rate=8000, frame_duration_ms=20)
        frame_size = vad.frame_size
        silent = [0.0] * frame_size
        freq = 440.0
        t_speech = [i / 8000.0 for i in range(frame_size)]
        speech = [0.5 * math.sin(2 * math.pi * freq * ti) for ti in t_speech]
        # silence then speech at end (no trailing silence)
        samples = silent + speech
        segments = vad.segment_speech(samples)
        assert len(segments) == 1
        assert segments[0] == (frame_size, 2 * frame_size)
