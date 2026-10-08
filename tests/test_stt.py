import pytest
from unittest.mock import patch, MagicMock
import numpy as np

from src.audio.stt import Transcriber

class TestTranscriber:
    def test_init_mock_mode_when_whisper_not_installed(self):
        with patch('src.audio.stt.whisper', None):
            t = Transcriber()
            assert t.mock_mode is True

    def test_init_mock_mode_when_model_load_fails(self):
        with patch('src.audio.stt.whisper') as mock_whisper:
            mock_whisper.load_model.side_effect = Exception("load error")
            t = Transcriber()
            assert t.mock_mode is True

    def test_transcribe_pcm_mock_mode(self):
        with patch('src.audio.stt.whisper', None):
            t = Transcriber()
            result = t.transcribe_pcm(b'\x00\x00' * 100)
            assert isinstance(result, str)
            assert "Mock" in result

    def test_transcribe_pcm_success(self):
        mock_model = MagicMock()
        mock_model.transcribe.return_value = {"text": "Hello world", "language": "en"}
        with patch('src.audio.stt.whisper') as mock_whisper:
            mock_whisper.load_model.return_value = mock_model
            t = Transcriber()
            audio_bytes = (np.zeros(1600, dtype=np.int16) * 1000).tobytes()
            result = t.transcribe_pcm(audio_bytes)
            assert result == "Hello world"
            mock_model.transcribe.assert_called_once()

    def test_detect_language_success(self):
        mock_model = MagicMock()
        with patch('src.audio.stt.whisper') as mock_whisper:
            mock_whisper.load_model.return_value = mock_model
            mock_whisper.detect_language.return_value = ("en", 0.9)
            t = Transcriber()
            audio_bytes = (np.zeros(1600, dtype=np.int16)).tobytes()
            lang = t.detect_language(audio_bytes)
            assert lang == "en"
            mock_whisper.detect_language.assert_called_once()

    def test_detect_language_mock_mode(self):
        with patch('src.audio.stt.whisper', None):
            t = Transcriber()
            lang = t.detect_language(b'\x00\x00' * 10)
            assert lang == "en"
