import struct
import pytest
from src.audio.wakeword import WakeWordDetector

class TestWakeWordDetector:
    @classmethod
    def setup_class(cls):
        cls.keyword = "hey iris"
        cls.frame_size = WakeWordDetector.FRAME_SIZE

    def test_supported_keywords(self):
        keywords = WakeWordDetector.list_keywords()
        assert "hey iris" in keywords
        assert "ok iris" in keywords
        assert "hello iris" in keywords

    def test_init_valid(self):
        detector = WakeWordDetector(self.keyword, sensitivity=0.5)
        assert detector.keyword == self.keyword
        assert detector.sensitivity == 0.5
        assert detector.frame_size == self.frame_size

    def test_init_invalid_keyword(self):
        with pytest.raises(ValueError):
            WakeWordDetector("unknown word")

    def test_init_sensitivity_too_low(self):
        with pytest.raises(ValueError):
            WakeWordDetector(self.keyword, sensitivity=-0.1)

    def test_init_sensitivity_too_high(self):
        with pytest.raises(ValueError):
            WakeWordDetector(self.keyword, sensitivity=1.1)

    def test_init_invalid_frame_size(self):
        with pytest.raises(ValueError):
            WakeWordDetector(self.keyword, frame_size=256)

    def test_detect_wrong_size_raises(self):
        detector = WakeWordDetector(self.keyword)
        with pytest.raises(ValueError):
            detector.detect(b'\x00' * 100)

    def test_detect_zeros_returns_false(self):
        detector = WakeWordDetector(self.keyword)
        audio = struct.pack(f'<{self.frame_size}h', *([0] * self.frame_size))
        assert detector.detect(audio) is False

    def test_detect_exact_template_returns_true(self):
        detector = WakeWordDetector(self.keyword)
        template = detector.template
        audio = struct.pack(f'<{self.frame_size}h', *template)
        assert detector.detect(audio) is True

    def test_detect_scaled_template_sensitivity(self):
        # Create a detector with low sensitivity
        detector_low = WakeWordDetector(self.keyword, sensitivity=0.0)
        template = detector_low.template
        # Scale template by 0.8
        scaled = [int(s * 0.8) for s in template]
        audio = struct.pack(f'<{self.frame_size}h', *scaled)
        # At low sensitivity, should not detect
        assert detector_low.detect(audio) is False

        # With high sensitivity, should detect
        detector_high = WakeWordDetector(self.keyword, sensitivity=0.5)
        assert detector_high.detect(audio) is True

    def test_detect_empty_frame_raises(self):
        detector = WakeWordDetector(self.keyword)
        with pytest.raises(ValueError):
            detector.detect(b'')
