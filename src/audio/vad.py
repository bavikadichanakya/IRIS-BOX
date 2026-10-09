import math
import struct
from collections import deque
from typing import List, Tuple, Union
import numpy as np


class CircularAudioBuffer:
    """A sample-accurate circular audio ring buffer for storing PCM samples with fixed time capacity."""

    def __init__(self, capacity_seconds: float = 10.0, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self.capacity = int(capacity_seconds * sample_rate)
        self.buffer: deque = deque(maxlen=self.capacity)

    def add(self, samples: Union[List[float], List[int], np.ndarray, bytes]):
        """Add PCM samples or bytes to the buffer, discarding oldest if full."""
        if isinstance(samples, bytes):
            if len(samples) % 2 != 0:
                raise ValueError("PCM bytes length must be a multiple of 2")
            num_samples = len(samples) // 2
            int_samples = struct.unpack(f"<{num_samples}h", samples)
            float_samples = [s / 32768.0 for s in int_samples]
            self.buffer.extend(float_samples)
        elif isinstance(samples, np.ndarray):
            flat = samples.flatten()
            if flat.dtype in (np.int16, np.int32):
                float_samples = (flat / 32768.0).tolist()
            else:
                float_samples = flat.tolist()
            self.buffer.extend(float_samples)
        else:
            self.buffer.extend(samples)

    def get(self) -> List[float]:
        """Return all samples currently in the buffer as float values."""
        return list(self.buffer)

    def get_bytes(self) -> bytes:
        """Return all samples currently in the buffer as 16-bit PCM bytes."""
        int_samples = [max(-32768, min(32767, int(s * 32768.0))) if isinstance(s, float) else max(-32768, min(32767, int(s))) for s in self.buffer]
        return struct.pack(f"<{len(int_samples)}h", *int_samples)

    def clear(self):
        """Remove all samples from the buffer."""
        self.buffer.clear()

    def __len__(self) -> int:
        return len(self.buffer)


class VoiceActivityDetector:
    """Energy & spectral RMS voice activity detector with hangover timing for smooth segmentation."""

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_duration_ms: int = 30,
        threshold: float = 0.01,
        hangover_ms: int = 0
    ):

        self.sample_rate = sample_rate
        self.frame_duration_ms = frame_duration_ms
        self.frame_size = int(sample_rate * frame_duration_ms / 1000)
        self.threshold = threshold
        self.hangover_ms = hangover_ms
        self.hangover_frames = math.ceil(hangover_ms / frame_duration_ms) if frame_duration_ms > 0 else 0

    def _frame_energy(self, frame: List[float]) -> float:
        """Compute RMS energy of a frame."""
        if not frame:
            return 0.0
        return math.sqrt(sum(s * s for s in frame) / len(frame))

    def is_speech(self, frame: List[float]) -> bool:
        """Determine if a frame contains speech based on energy threshold."""
        if len(frame) < self.frame_size:
            return False
        return self._frame_energy(frame) > self.threshold

    def detect(self, samples: List[float]) -> List[bool]:
        """Process audio samples and return a boolean list indicating speech per frame."""
        flags = []
        for i in range(0, len(samples) - self.frame_size + 1, self.frame_size):
            frame = samples[i:i + self.frame_size]
            flags.append(self.is_speech(frame))
        return flags

    def segment_speech(self, samples: List[float]) -> List[Tuple[int, int]]:
        """Return a list of (start_sample, end_sample) tuples for detected speech segments with hangover padding."""
        flags = self.detect(samples)
        segments = []
        start = None
        silence_count = 0

        for i, flag in enumerate(flags):
            if flag:
                if start is None:
                    start = i * self.frame_size
                silence_count = 0
            else:
                if start is not None:
                    silence_count += 1
                    if self.hangover_frames == 0 or silence_count >= self.hangover_frames:
                        end = (i * self.frame_size) if self.hangover_frames == 0 else min((i + 1) * self.frame_size, len(samples))
                        segments.append((start, end))
                        start = None
                        silence_count = 0

        if start is not None:
            segments.append((start, len(samples)))

        return segments


