import math
from collections import deque
from typing import List, Tuple

class CircularAudioBuffer:
    """A ring buffer for storing audio samples with a fixed capacity in seconds."""

    def __init__(self, capacity_seconds: float, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self.capacity = int(capacity_seconds * sample_rate)
        self.buffer = deque(maxlen=self.capacity)

    def add(self, samples: List[float]):
        """Add samples to the buffer, discarding oldest if full."""
        self.buffer.extend(samples)

    def get(self) -> List[float]:
        """Return all samples currently in the buffer."""
        return list(self.buffer)

    def clear(self):
        """Remove all samples from the buffer."""
        self.buffer.clear()

    def __len__(self) -> int:
        return len(self.buffer)


class VoiceActivityDetector:
    """Simple energy-based voice activity detector that segments speech from silence."""

    def __init__(self, sample_rate: int = 16000, frame_duration_ms: int = 30, threshold: float = 0.01):
        self.sample_rate = sample_rate
        self.frame_duration_ms = frame_duration_ms
        self.frame_size = int(sample_rate * frame_duration_ms / 1000)
        self.threshold = threshold

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
        """Process a list of audio samples and return a boolean list indicating speech per frame."""
        flags = []
        for i in range(0, len(samples) - self.frame_size + 1, self.frame_size):
            frame = samples[i:i + self.frame_size]
            flags.append(self.is_speech(frame))
        return flags

    def segment_speech(self, samples: List[float]) -> List[Tuple[int, int]]:
        """Return a list of (start_sample, end_sample) tuples for detected speech segments."""
        flags = self.detect(samples)
        segments = []
        start = None
        for i, flag in enumerate(flags):
            if flag and start is None:
                start = i * self.frame_size
            elif not flag and start is not None:
                end = i * self.frame_size
                segments.append((start, end))
                start = None
        if start is not None:
            segments.append((start, len(samples)))
        return segments
