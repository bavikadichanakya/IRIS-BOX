import logging
import io

try:
    import whisper
except ImportError:
    whisper = None

try:
    import numpy as np
except ImportError:
    np = None

logger = logging.getLogger(__name__)

class Transcriber:
    """Offline Whisper-compatible STT processor with fallback mock mode."""

    def __init__(self, model_name: str = "base", device: str = "cpu", fallback_mock: bool = True):
        self.model_name = model_name
        self.device = device
        self.fallback_mock = fallback_mock
        self.mock_mode = False
        self.model = None
        self._load_model()

    def _load_model(self):
        if whisper is None:
            logger.warning("whisper not installed, using mock mode")
            self.mock_mode = True
            return
        try:
            self.model = whisper.load_model(self.model_name, device=self.device)
            logger.info(f"Loaded Whisper model '{self.model_name}' on {self.device}")
        except Exception as e:
            logger.warning(f"Failed to load Whisper model '{self.model_name}': {e}")
            if self.fallback_mock:
                self.mock_mode = True
                logger.info("Falling back to mock STT mode")
            else:
                raise

    def transcribe_pcm(self, audio_bytes: bytes, sample_rate: int = 16000) -> str:
        """Transcribe PCM audio bytes to text."""
        if self.mock_mode:
            return self._mock_transcribe(audio_bytes, sample_rate)
        if np is None:
            raise RuntimeError("numpy is required for transcription")
        audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        result = self.model.transcribe(audio, language=None, fp16=False)
        return result["text"].strip()

    def detect_language(self, audio_bytes: bytes, sample_rate: int = 16000) -> str:
        """Detect language of PCM audio bytes."""
        if self.mock_mode:
            return self._mock_detect_language(audio_bytes, sample_rate)
        if np is None:
            raise RuntimeError("numpy is required for language detection")
        audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        language, _ = whisper.detect_language(self.model, audio)
        return language

    def _mock_transcribe(self, audio_bytes: bytes, sample_rate: int) -> str:
        return "Mock transcription"

    def _mock_detect_language(self, audio_bytes: bytes, sample_rate: int) -> str:
        return "en"
