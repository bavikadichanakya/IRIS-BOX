import os
import sys
import json
import pytest
import sqlite3
import numpy as np
from unittest.mock import patch, MagicMock

from src.cli.doctor import SystemDoctor, CheckResult, main as doctor_main
from src.cli.hardware_test import HardwareDiagnostics


@pytest.fixture
def doctor(tmp_path):
    return SystemDoctor(root_dir=str(tmp_path))


def test_doctor_initialization():
    doctor = SystemDoctor()
    assert os.path.exists(doctor.root_dir)


def test_doctor_check_local_llm_success(doctor):
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({"models": [{"name": "qwen2.5:7b-instruct:latest"}]}).encode("utf-8")
    mock_response.__enter__.return_value = mock_response

    with patch("urllib.request.urlopen", return_value=mock_response):
        with patch.dict(os.environ, {"IRIS_LLM_BASE_URL": "http://localhost:11434", "IRIS_LLM_MODEL": "qwen2.5:7b-instruct"}):
            res = doctor.check_local_llm()
            assert res.status == "PASS"
            assert res.phase == "TESTED"
            assert "qwen2.5:7b-instruct" in res.message


def test_doctor_check_local_llm_missing_model(doctor):
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({"models": [{"name": "llama3:latest"}]}).encode("utf-8")
    mock_response.__enter__.return_value = mock_response

    with patch("urllib.request.urlopen", return_value=mock_response):
        with patch.dict(os.environ, {"IRIS_LLM_BASE_URL": "http://localhost:11434", "IRIS_LLM_MODEL": "qwen2.5:7b-instruct"}):
            res = doctor.check_local_llm()
            assert res.status == "WARN"
            assert res.phase == "LOADED"
            assert res.resolution is not None


def test_doctor_check_local_llm_connection_failure(doctor):
    with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
        res = doctor.check_local_llm()
        assert res.status == "FAIL"
        assert res.phase == "INSTALLED"
        assert "Could not connect" in res.message


def test_doctor_check_wake_word_missing(doctor):
    res = doctor.check_wake_word()
    assert res.status == "FAIL"
    assert "not found" in res.message.lower()


def test_doctor_check_wake_word_success(tmp_path):
    models_dir = tmp_path / "models" / "wakeword"
    models_dir.mkdir(parents=True)
    model_file = models_dir / "hey_iris.onnx"
    # Write dummy >10KB file
    model_file.write_bytes(b"\x00" * 20000)

    doc = SystemDoctor(root_dir=str(tmp_path))

    mock_sess = MagicMock()
    mock_input = MagicMock()
    mock_input.name = "input"
    mock_output = MagicMock()
    mock_output.name = "output"
    mock_sess.get_inputs.return_value = [mock_input]
    mock_sess.get_outputs.return_value = [mock_output]

    with patch("onnxruntime.InferenceSession", return_value=mock_sess):
        res = doc.check_wake_word()
        assert res.status == "PASS"
        assert res.phase == "TESTED"


def test_doctor_check_tts_engine_success(tmp_path):
    piper_dir = tmp_path / "models" / "piper"
    piper_dir.mkdir(parents=True)
    piper_bin = piper_dir / "piper.exe"
    piper_bin.write_bytes(b"dummy_piper")
    voice_file = piper_dir / "en_US-lessac-medium.onnx"
    voice_file.write_bytes(b"dummy_voice")

    doc = SystemDoctor(root_dir=str(tmp_path))

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    # Valid WAV header: RIFF....WAVE
    mock_proc.stdout = b"RIFF" + b"\x00" * 4 + b"WAVEfmt " + b"\x00" * 50
    mock_proc.stderr = b""

    with patch("subprocess.run", return_value=mock_proc):
        res = doc.check_tts_engine()
        assert res.status == "PASS"
        assert res.phase == "TESTED"
        assert "validated" in res.message.lower()


def test_doctor_check_sqlite_storage(tmp_path):
    db_file = tmp_path / "iris.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE sessions (session_id TEXT PRIMARY KEY, device_id TEXT, metadata_json TEXT);")
    conn.execute("CREATE TABLE user_preferences (user_id TEXT, key TEXT, value TEXT, category TEXT);")
    conn.execute("CREATE TABLE inferred_facts (id INTEGER PRIMARY KEY, user_id TEXT, fact TEXT);")
    conn.commit()
    conn.close()

    doc = SystemDoctor(root_dir=str(tmp_path))
    with patch.dict(os.environ, {"DATABASE_URL": str(db_file)}):
        res = doc.check_sqlite_storage()
        assert res.status == "PASS"
        assert res.phase == "TESTED"
        assert "verified" in res.message.lower()


def test_doctor_check_security_and_permissions(tmp_path):
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text(".env\n__pycache__/\n")

    doc = SystemDoctor(root_dir=str(tmp_path))

    # Test with weak token
    with patch.dict(os.environ, {"IRIS_MASTER_TOKEN": "secret", "IRIS_ALLOW_CLOUD": "false"}):
        res = doc.check_security_and_permissions()
        assert res.status in ("WARN", "FAIL")

    # Test with strong token
    with patch.dict(os.environ, {"IRIS_MASTER_TOKEN": "secure-production-master-token-offline-2026", "IRIS_ALLOW_CLOUD": "false"}):
        res = doc.check_security_and_permissions()
        assert res.status == "PASS"
        assert res.phase == "TESTED"


def test_doctor_check_audio_hardware():
    doc = SystemDoctor()
    mock_devices = [
        {"name": "Mic 1", "max_input_channels": 2, "max_output_channels": 0},
        {"name": "Speaker 1", "max_input_channels": 0, "max_output_channels": 2},
    ]

    with patch("sounddevice.query_devices", return_value=mock_devices):
        res = doc.check_audio_hardware()
        assert res.status == "PASS"
        assert res.phase == "LOADED"
        assert "1 input" in res.message
        assert "1 output" in res.message


def test_doctor_report_formatting():
    doc = SystemDoctor()
    sample_results = [
        CheckResult(name="Test Core", category="Inference", phase="TESTED", status="PASS", message="Operational"),
        CheckResult(name="Test Warn", category="Audio", phase="LOADED", status="WARN", message="Optional", resolution="Fix me"),
        CheckResult(name="Test Fail", category="Storage", phase="INSTALLED", status="FAIL", message="Broken", resolution="Reinstall", is_fatal=True),
    ]
    report = doc.generate_report(sample_results)
    assert "IRIS-BOX Setup Doctor" in report
    assert "Test Core" in report
    assert "Test Warn" in report
    assert "Test Fail" in report
    assert "Fix me" in report
    assert "Reinstall" in report


def test_doctor_main_exit_code_zero():
    passing_results = [
        CheckResult(name="Subsystem 1", category="Inference", phase="TESTED", status="PASS", message="OK", is_fatal=True),
        CheckResult(name="Subsystem 2", category="Audio", phase="LOADED", status="WARN", message="Minor", is_fatal=False),
    ]
    with patch.object(SystemDoctor, "run_all_checks", return_value=passing_results):
        code = doctor_main()
        assert code == 0


def test_doctor_main_exit_code_one_on_fatal():
    failing_results = [
        CheckResult(name="Subsystem 1", category="Inference", phase="INSTALLED", status="FAIL", message="Fatal Error", is_fatal=True),
    ]
    with patch.object(SystemDoctor, "run_all_checks", return_value=failing_results):
        code = doctor_main()
        assert code == 1


def test_hardware_diagnostics_vad_and_energy():
    diag = HardwareDiagnostics()

    # Silence (all zeros)
    silence = np.zeros(1600, dtype=np.int16)
    rms, db, is_speech = diag.evaluate_vad_energy(silence)
    assert rms == 0.0
    assert not is_speech

    # Loud speech-like signal
    loud = (np.sin(np.linspace(0, 100, 1600)) * 20000).astype(np.int16)
    rms_l, db_l, is_speech_l = diag.evaluate_vad_energy(loud, threshold=0.01)
    assert rms_l > 0.05
    assert is_speech_l
