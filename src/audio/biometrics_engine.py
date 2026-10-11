import io
import logging
import os
import wave
from typing import List, Optional
import numpy as np

logger = logging.getLogger("iris.audio.biometrics")


def _hz_to_mel(hz: float) -> float:
    return 2595.0 * np.log10(1.0 + hz / 700.0)


def _mel_to_hz(mel: float) -> float:
    return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)


def _build_mel_filters(n_filters: int = 48, n_fft: int = 512, sample_rate: int = 16000,
                       f_min: float = 80.0, f_max: float = 7600.0) -> np.ndarray:
    """Build triangular Mel-scale filterbank matrix."""
    n_bins = n_fft // 2 + 1
    mel_min = _hz_to_mel(f_min)
    mel_max = _hz_to_mel(f_max)
    mel_points = np.linspace(mel_min, mel_max, n_filters + 2)
    hz_points = _mel_to_hz(mel_points)
    bin_points = np.floor((n_fft + 1) * hz_points / sample_rate).astype(int)
    bin_points = np.clip(bin_points, 0, n_bins - 1)

    filters = np.zeros((n_filters, n_bins), dtype=np.float32)
    for i in range(n_filters):
        b_prev, b_curr, b_next = bin_points[i], bin_points[i + 1], bin_points[i + 2]
        if b_curr > b_prev:
            filters[i, b_prev:b_curr] = (np.arange(b_prev, b_curr) - b_prev) / float(b_curr - b_prev)
        if b_next > b_curr:
            filters[i, b_curr:b_next] = (b_next - np.arange(b_curr, b_next)) / float(b_next - b_curr)

    return filters


class VoiceEmbeddingExtractor:
    """
    Acoustic voice embedding extractor extracting 192-dimensional L2-normalized vectors
    from 16kHz 16-bit mono PCM.
    Supports SpeechBrain ECAPA-TDNN ONNX models when present, with a deterministic,
    air-gapped filterbank spectral fallback.
    """

    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path or os.getenv("IRIS_BIOMETRICS_MODEL", "models/biometrics/ecapa_tdnn.onnx")
        self._onnx_session = None
        self._mel_filters = _build_mel_filters(n_filters=48, n_fft=512, sample_rate=16000)

        if os.path.exists(self.model_path):
            try:
                import onnxruntime as ort
                self._onnx_session = ort.InferenceSession(self.model_path)
                logger.info("Loaded ONNX speaker embedding model from '%s'", self.model_path)
            except Exception as e:
                logger.warning("Failed to load ONNX speaker model from '%s': %s. Falling back to local spectral engine.", self.model_path, e)
        else:
            logger.debug("No local ONNX speaker model found at '%s'. Using deterministic local spectral extractor.", self.model_path)

    def _extract_pcm_samples(self, pcm_bytes: bytes) -> np.ndarray:
        """Parse raw 16-bit mono PCM or WAV header bytes into float32 array in [-1.0, 1.0]."""
        if not pcm_bytes:
            return np.zeros(400, dtype=np.float32)

        # Check for WAV RIFF header
        if len(pcm_bytes) >= 12 and pcm_bytes[:4] == b"RIFF" and pcm_bytes[8:12] == b"WAVE":
            try:
                with wave.open(io.BytesIO(pcm_bytes), "rb") as wf:
                    raw_frames = wf.readframes(wf.getnframes())
                    int16_samples = np.frombuffer(raw_frames, dtype=np.int16)
                    return int16_samples.astype(np.float32) / 32768.0
            except Exception:
                pass

        # Treat as raw 16-bit signed PCM
        # Ensure even byte length for int16
        if len(pcm_bytes) % 2 != 0:
            pcm_bytes = pcm_bytes[:-1]

        if len(pcm_bytes) == 0:
            return np.zeros(400, dtype=np.float32)

        int16_samples = np.frombuffer(pcm_bytes, dtype=np.int16)
        samples = int16_samples.astype(np.float32) / 32768.0

        # Pad if shorter than minimum window length
        if len(samples) < 400:
            pad_len = 400 - len(samples)
            samples = np.pad(samples, (0, pad_len), mode="constant")

        return samples

    def extract_embedding(self, pcm_bytes: bytes) -> List[float]:
        """
        Extracts 192-dimensional L2-normalized acoustic vector from 16kHz 16-bit mono PCM.
        """
        samples = self._extract_pcm_samples(pcm_bytes)

        # 1. Try ONNX model if available
        if self._onnx_session is not None:
            try:
                input_name = self._onnx_session.get_inputs()[0].name
                # Shape [1, num_samples]
                input_tensor = np.expand_dims(samples, axis=0)
                outputs = self._onnx_session.run(None, {input_name: input_tensor})
                raw_emb = np.squeeze(outputs[0]).astype(np.float32)
                if len(raw_emb) == 192:
                    norm = float(np.linalg.norm(raw_emb))
                    if norm > 1e-12:
                        raw_emb = raw_emb / norm
                    return raw_emb.tolist()
            except Exception as e:
                logger.warning("ONNX speaker inference error: %s. Falling back to spectral extractor.", e)

        # 2. Local deterministic spectral acoustic extractor (192-dim)
        frame_len = 400   # 25ms @ 16kHz
        hop_len = 160     # 10ms @ 16kHz
        n_fft = 512

        num_frames = max(1, 1 + (len(samples) - frame_len) // hop_len)
        valid_len = (num_frames - 1) * hop_len + frame_len
        frames = np.lib.stride_tricks.sliding_window_view(samples[:valid_len], frame_len)[::hop_len]

        window = np.hanning(frame_len).astype(np.float32)
        windowed_frames = frames * window

        # Compute power spectrum
        spec = np.abs(np.fft.rfft(windowed_frames, n=n_fft)) ** 2

        # Apply 48-band Mel filterbank
        mel_energies = np.dot(spec, self._mel_filters.T)
        log_mels = np.log(mel_energies + 1e-6)

        # Pool 4 statistical moments across time frames for each of the 48 bands
        # (48 * 4 = 192 dimensions)
        m1_mean = np.mean(log_mels, axis=0)
        m2_std = np.std(log_mels, axis=0)
        m3_max = np.max(log_mels, axis=0)
        m4_min = np.min(log_mels, axis=0)

        embedding = np.concatenate([m1_mean, m2_std, m3_max, m4_min]).astype(np.float32)

        # L2 normalization
        norm = float(np.linalg.norm(embedding))
        if norm > 1e-12:
            embedding = embedding / norm
        else:
            embedding = np.ones(192, dtype=np.float32) / np.sqrt(192.0)

        return embedding.tolist()
