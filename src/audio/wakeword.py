import os
import struct
import numpy as np
import logging
from typing import Optional, List, Union

logger = logging.getLogger("iris.audio.wakeword")

DEFAULT_MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "hey_iris.onnx")


class WakeWordDetector:
    """
    Production-grade Wake Word Detector for IRIS:
    - Real-time neural inference using openWakeWord & custom 'hey_iris.onnx'.
    - Exclusively relies on ONNX neural inference without synthetic template simulation.
    """
    FRAME_SIZE: int = 1280
    SAMPLE_RATE: int = 16000
    VALID_FRAME_SIZES: List[int] = [512, 1024, 1280]
    _SUPPORTED_KEYWORDS: List[str] = ["hey iris", "ok iris", "hello iris"]

    @classmethod
    def list_keywords(cls) -> List[str]:
        return list(cls._SUPPORTED_KEYWORDS)

    def __init__(
        self,
        keyword: str = "hey iris",
        sensitivity: float = 0.5,
        threshold: Optional[float] = None,
        frame_size: int = 1280,
        sample_rate: int = 16000,
        model_path: Optional[str] = None
    ):
        keyword_clean = keyword.strip().lower()
        if keyword_clean not in self._SUPPORTED_KEYWORDS:
            raise ValueError(f"Unsupported keyword '{keyword}'. Supported: {self._SUPPORTED_KEYWORDS}")

        effective_sensitivity = threshold if threshold is not None else sensitivity
        if not (0.0 <= effective_sensitivity <= 1.0):
            raise ValueError(f"Sensitivity must be between 0.0 and 1.0, got {effective_sensitivity}")

        if frame_size not in self.VALID_FRAME_SIZES:
            raise ValueError(f"Invalid frame_size {frame_size}. Must be one of {self.VALID_FRAME_SIZES}")

        self.keyword = keyword_clean
        self.sensitivity = float(effective_sensitivity)
        self.frame_size = frame_size
        self.sample_rate = sample_rate
        self.model_path = model_path or (DEFAULT_MODEL_PATH if os.path.exists(DEFAULT_MODEL_PATH) else None)

        self.is_onnx_mode = False
        self._oww_model = None
        self.model_key = None

        if self.model_path and os.path.exists(self.model_path):
            try:
                from openwakeword.model import Model
                self._oww_model = Model(wakeword_model_paths=[self.model_path], inference_framework="onnx")
                if self._oww_model.models:
                    self.model_key = list(self._oww_model.models.keys())[0]
                    self.is_onnx_mode = True
                    logger.info(f"Loaded openWakeWord model '{self.model_key}' from {self.model_path}")
            except Exception as e:
                logger.warning(f"Could not load openWakeWord model ({e}); detector unavailable.")
                self.is_onnx_mode = False

    def _parse_audio(self, audio: Union[bytes, np.ndarray, List[int]]) -> np.ndarray:
        if audio is None:
            raise ValueError("Audio chunk cannot be None")
        if isinstance(audio, bytes):
            if len(audio) == 0:
                raise ValueError("Audio chunk cannot be empty")
            if len(audio) % 2 != 0:
                raise ValueError("Audio byte length must be multiple of 2 for 16-bit PCM")
            num_samples = len(audio) // 2
            if num_samples != self.frame_size:
                raise ValueError(f"Expected {self.frame_size} samples, got {num_samples}")
            samples = struct.unpack(f"<{num_samples}h", audio)
            return np.array(samples, dtype=np.float32)
        elif isinstance(audio, (list, tuple)):
            if len(audio) != self.frame_size:
                raise ValueError(f"Expected {self.frame_size} samples, got {len(audio)}")
            return np.array(audio, dtype=np.float32)
        elif isinstance(audio, np.ndarray):
            if audio.size == 0:
                raise ValueError("Audio chunk cannot be empty")
            if audio.size != self.frame_size:
                raise ValueError(f"Expected {self.frame_size} samples, got {audio.size}")
            return audio.astype(np.float32).flatten()
        else:
            raise ValueError(f"Unsupported audio type: {type(audio)}")

    def detect(self, audio: Union[bytes, np.ndarray, List[int]]) -> bool:
        samples = self._parse_audio(audio)

        # Neural Inference via ONNX exclusively
        if self.is_onnx_mode and self._oww_model is not None:
            try:
                pcm = samples.astype(np.int16)
                prediction = self._oww_model.predict(pcm)
                model_key = self.model_key or self.keyword
                score = float(prediction.get(model_key, 0.0))
                threshold = 1.0 - (self.sensitivity * 0.5)
                return score >= threshold
            except Exception as e:
                logger.error(f"ONNX wake-word inference error: {e}")
                return False

        logger.debug("Wake-word detection unavailable: ONNX model not loaded.")
        return False

    def get_confidence(self, audio: Union[bytes, np.ndarray, List[int]]) -> float:
        samples = self._parse_audio(audio)
        if self.is_onnx_mode and self._oww_model is not None:
            try:
                pcm = samples.astype(np.int16)
                prediction = self._oww_model.predict(pcm)
                model_key = self.model_key or self.keyword
                return float(prediction.get(model_key, 0.0))
            except Exception as e:
                logger.error(f"ONNX wake-word confidence calculation error: {e}")
                return 0.0
        return 0.0

    def reset(self):
        if self.is_onnx_mode and self._oww_model is not None:
            self._oww_model.reset()
