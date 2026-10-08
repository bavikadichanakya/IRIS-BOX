import struct
import hashlib
import random
from typing import List

class WakeWordDetector:
    """
    Simulates a wake word detector engine (Porcupine/openWakeWord compatible API).
    """
    SUPPORTED_KEYWORDS: List[str] = ["hey iris", "ok iris", "hello iris"]
    FRAME_SIZE = 512  # number of 16-bit samples per frame

    def __init__(self, keyword: str, sensitivity: float = 0.5, frame_size: int = 512):
        """
        Initialize the wake word detector.

        :param keyword: The wake word phrase. Must be in SUPPORTED_KEYWORDS.
        :param sensitivity: Detection sensitivity (0.0 to 1.0). Higher = easier.
        :param frame_size: Number of audio samples per frame (must be 512).
        """
        if keyword not in self.SUPPORTED_KEYWORDS:
            raise ValueError(f"Unsupported keyword: {keyword}. Supported: {self.SUPPORTED_KEYWORDS}")
        if not (0.0 <= sensitivity <= 1.0):
            raise ValueError("Sensitivity must be between 0.0 and 1.0")
        if frame_size != self.FRAME_SIZE:
            raise ValueError(f"Frame size must be {self.FRAME_SIZE} samples")

        self.keyword = keyword
        self.sensitivity = sensitivity
        self.frame_size = frame_size
        # Generate a deterministic template for the keyword
        self.template = self._generate_template(keyword, frame_size)

    def _generate_template(self, keyword: str, frame_size: int) -> List[int]:
        """Generate a pseudo-random template based on the keyword."""
        seed = int(hashlib.md5(keyword.encode()).hexdigest(), 16)
        rng = random.Random(seed)
        return [rng.randint(-32768, 32767) for _ in range(frame_size)]

    def detect(self, audio_frame: bytes) -> bool:
        """
        Process an audio frame and return True if the wake word is detected.

        :param audio_frame: Raw PCM 16-bit little-endian audio data.
        :return: True if wake word detected, False otherwise.
        :raises ValueError: If the frame size is incorrect.
        """
        expected_bytes = self.frame_size * 2
        if len(audio_frame) != expected_bytes:
            raise ValueError(f"Audio frame must be {expected_bytes} bytes for {self.frame_size} samples")

        # Unpack bytes to signed 16-bit integers
        samples = struct.unpack(f'<{self.frame_size}h', audio_frame)

        # Compute dot product between audio and template
        dot = sum(s * t for s, t in zip(samples, self.template))
        max_dot = sum(t * t for t in self.template)

        # Threshold: higher sensitivity -> lower threshold
        threshold = (1.0 - self.sensitivity) * max_dot
        return dot >= threshold

    @classmethod
    def list_keywords(cls) -> List[str]:
        """Return the list of supported wake word keywords."""
        return cls.SUPPORTED_KEYWORDS.copy()
