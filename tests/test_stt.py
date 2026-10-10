import pytest
from unittest.mock import patch, MagicMock

from src.audio.stt import Transcriber

class TestTranscriber:
    def test_init_unavailable_when_whisper_not_installed(self):
        with patch('src.audio.stt.WhisperModel', None), patch('src.audio.stt.whisper', None):
            t = Transcriber()
            assert t.status == "UNAVAILABLE"

    def test_init_unavailable_when_model_load_fails(self):
        with patch('src.audio.stt.WhisperModel', side_effect=Exception("load error")), \
             patch('src.audio.stt.whisper', None):
            t = Transcriber()
            assert t.status == "UNAVAILABLE"

    def test_transcribe_pcm_unavailable_raises_error(self):
        with patch('src.audio.stt.WhisperModel', None), patch('src.audio.stt.whisper', None):
            t = Transcriber()
            with pytest.raises(RuntimeError, match="STT engine is UNAVAILABLE"):
                t.transcribe_pcm(b'\x00\x00' * 100)

    def test_transcribe_pcm_success(self):
        mock_fw = MagicMock()
        mock_seg = MagicMock()
        mock_seg.text = "Hello world"
        mock_fw.transcribe.return_value = ([mock_seg], MagicMock())
        with patch('src.audio.stt.WhisperModel', return_value=mock_fw):
            t = Transcriber()
            audio_bytes = b'\x00\x00' * 1600
            result = t.transcribe_pcm(audio_bytes)
            assert result == "Hello world"
            mock_fw.transcribe.assert_called_once()

    def test_detect_language_success(self):
        mock_fw = MagicMock()
        mock_info = MagicMock()
        mock_info.language = "en"
        mock_fw.transcribe.return_value = ([], mock_info)
        with patch('src.audio.stt.WhisperModel', return_value=mock_fw):
            t = Transcriber()
            audio_bytes = b'\x00\x00' * 1600
            lang = t.detect_language(audio_bytes)
            assert lang == "en"
            mock_fw.transcribe.assert_called_once()

    def test_detect_language_unavailable_raises_error(self):
        with patch('src.audio.stt.WhisperModel', None), patch('src.audio.stt.whisper', None):
            t = Transcriber()
            with pytest.raises(RuntimeError, match="STT engine is UNAVAILABLE"):
                t.detect_language(b'\x00\x00' * 10)
