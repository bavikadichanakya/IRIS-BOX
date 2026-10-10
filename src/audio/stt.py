import logging
import io
import struct

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None

try:
    import whisper
except ImportError:
    whisper = None

try:
    import numpy as np
except ImportError:
    np = None

logger = logging.getLogger(__name__)


def validate_audio_header(audio_bytes: bytes, expected_sample_rate: int = 16000) -> bytes:
    """
    Validate audio bytes formatting (RAW PCM 16-bit LE or WAV header).
    Returns raw PCM payload bytes.
    """
    if not audio_bytes or len(audio_bytes) == 0:
        raise ValueError("Audio bytes cannot be empty")

    # Check for WAV header (RIFF ... WAVE)
    if audio_bytes.startswith(b"RIFF") and len(audio_bytes) >= 44:
        header = audio_bytes[:44]
        chunk_id, _, format_tag, subchunk1_id, subchunk1_size, audio_format, num_channels, sample_rate, byte_rate, block_align, bits_per_sample = struct.unpack(
            "<4sI4s4sIHHIIHH", header[:36]
        )
        if chunk_id != b"RIFF" or format_tag != b"WAVE":
            raise ValueError("Invalid WAV header format")

        data_offset = audio_bytes.find(b"data")
        if data_offset != -1 and len(audio_bytes) >= data_offset + 8:
            return audio_bytes[data_offset + 8:]
        return audio_bytes[44:]

    if len(audio_bytes) % 2 != 0:
        raise ValueError("Audio byte length must be a multiple of 2 for 16-bit PCM")

    return audio_bytes


class Transcriber:
    """Offline faster-whisper / Whisper STT processor with explicit status reporting."""

    def __init__(self, model_name: str = "base", device: str = "cpu", fallback_mock: bool = False):
        self.model_name = model_name
        self.device = device
        self.fallback_mock = fallback_mock
        self.mock_mode = False
        self.status = "UNAVAILABLE"
        self.fw_model = None
        self.model = None
        self._load_model()

    def _load_model(self):
        if WhisperModel is not None:
            try:
                compute_type = "float32" if self.device == "cpu" else "float16"
                self.fw_model = WhisperModel(self.model_name, device=self.device, compute_type=compute_type)
                self.status = "READY"
                self.mock_mode = False
                logger.info(f"Loaded faster-whisper model '{self.model_name}' on {self.device}")
                return
            except Exception as e:
                logger.warning(f"Could not load faster-whisper model '{self.model_name}': {e}")

        if whisper is not None:
            try:
                self.model = whisper.load_model(self.model_name, device=self.device)
                self.status = "READY"
                self.mock_mode = False
                logger.info(f"Loaded Whisper model '{self.model_name}' on {self.device}")
                return
            except Exception as e:
                logger.warning(f"Failed to load Whisper model '{self.model_name}': {e}")

        logger.warning("Neither faster-whisper nor whisper is loadable, setting status to UNAVAILABLE")
        self.status = "UNAVAILABLE"
        if self.fallback_mock:
            self.mock_mode = True
            logger.info("Falling back to mock STT mode")
        else:
            self.mock_mode = False

    def transcribe_pcm(self, audio_bytes: bytes, sample_rate: int = 16000) -> str:
        """Transcribe PCM audio bytes to text."""
        raw_pcm = validate_audio_header(audio_bytes, expected_sample_rate=sample_rate)

        if self.mock_mode:
            return self._mock_transcribe(raw_pcm, sample_rate)

        if self.status != "READY" or (self.fw_model is None and self.model is None):
            raise RuntimeError(
                "STT engine is UNAVAILABLE: faster-whisper model weights not found or failed to load. "
                "Ensure model weights are cached locally in 'models/whisper' or '~/.cache/huggingface/hub/'."
            )

        if np is None:
            raise RuntimeError("numpy is required for transcription")

        audio = np.frombuffer(raw_pcm, dtype=np.int16).astype(np.float32) / 32768.0

        if self.fw_model is not None:
            segments, _ = self.fw_model.transcribe(audio, beam_size=1)
            return " ".join([seg.text for seg in segments]).strip()
        elif self.model is not None:
            result = self.model.transcribe(audio, language=None, fp16=False)
            return result.get("text", "").strip()
        return ""

    def detect_language(self, audio_bytes: bytes, sample_rate: int = 16000) -> str:
        """Detect language of PCM audio bytes."""
        raw_pcm = validate_audio_header(audio_bytes, expected_sample_rate=sample_rate)

        if self.mock_mode:
            return self._mock_detect_language(raw_pcm, sample_rate)

        if self.status != "READY" or (self.fw_model is None and self.model is None):
            raise RuntimeError("STT engine is UNAVAILABLE: Whisper model is not loaded")

        if np is None:
            raise RuntimeError("numpy is required for language detection")

        audio = np.frombuffer(raw_pcm, dtype=np.int16).astype(np.float32) / 32768.0

        if self.fw_model is not None:
            _, info = self.fw_model.transcribe(audio, beam_size=1)
            return getattr(info, "language", "en")
        elif self.model is not None:
            language, _ = whisper.detect_language(self.model, audio)
            return language
        return "en"

    def _mock_transcribe(self, audio_bytes: bytes, sample_rate: int) -> str:
        return "Mock transcription"

    def _mock_detect_language(self, audio_bytes: bytes, sample_rate: int) -> str:
        return "en"

