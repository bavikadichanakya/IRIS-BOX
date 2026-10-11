import base64
import io
import json
import wave
import numpy as np
import pytest
from fastapi.testclient import TestClient

from src.audio.biometrics_engine import VoiceEmbeddingExtractor
from src.security.biometrics import Role, SpeakerProfile, SpeakerIdentificationResult, AuthorizationDecision
from src.security.speaker_registry import SpeakerRegistry
from src.security.voice_auth import VoiceGatedAuthorization, ROLE_HIERARCHY
from src.storage.db import Database
from src.observability.event_bus import EventBus
from src.tools.manager import ToolManager
from src.tools.capability import ExecutionStatus
from src.server.app import app
from src.security.auth import auth_manager


def _generate_pcm(f0: float, formants: list[float], duration: float = 1.0, sr: int = 16000) -> bytes:
    """Generate synthetic voice PCM audio with fundamental frequency and formant harmonics."""
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    sig = np.sin(2 * np.pi * f0 * t)
    for h in [2, 3, 4]:
        sig += (1.0 / h) * np.sin(2 * np.pi * (h * f0) * t)
    for f in formants:
        sig += 0.4 * np.sin(2 * np.pi * f * t)
    sig = sig / np.max(np.abs(sig))
    return (sig * 32767).astype(np.int16).tobytes()


def _pcm_to_wav_bytes(pcm_data: bytes, sr: int = 16000) -> bytes:
    """Wrap raw 16-bit mono PCM into a standard WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm_data)
    return buf.getvalue()


@pytest.fixture
def auth_headers():
    return {"X-API-Key": auth_manager.master_key}


@pytest.fixture
def test_client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. Embedding Extraction Tests
# ---------------------------------------------------------------------------

def test_embedding_extraction_consistency():
    extractor = VoiceEmbeddingExtractor()
    pcm = _generate_pcm(150, [700, 1200, 2500])

    emb1 = extractor.extract_embedding(pcm)
    emb2 = extractor.extract_embedding(pcm)

    assert len(emb1) == 192
    assert len(emb2) == 192

    # L2 normalization test
    norm1 = np.linalg.norm(emb1)
    norm2 = np.linalg.norm(emb2)
    assert norm1 == pytest.approx(1.0, rel=1e-4)
    assert norm2 == pytest.approx(1.0, rel=1e-4)

    # Identical vectors for identical audio
    assert emb1 == emb2


def test_embedding_extraction_wav_format():
    extractor = VoiceEmbeddingExtractor()
    pcm = _generate_pcm(200, [800, 1400, 2800])
    wav = _pcm_to_wav_bytes(pcm)

    emb_raw = extractor.extract_embedding(pcm)
    emb_wav = extractor.extract_embedding(wav)

    assert len(emb_wav) == 192
    assert np.linalg.norm(emb_wav) == pytest.approx(1.0, rel=1e-4)
    # Cosine similarity between raw and wav extraction of same audio should be virtually 1.0
    sim = np.dot(emb_raw, emb_wav)
    assert sim > 0.99


def test_embedding_extraction_empty_and_short_audio():
    extractor = VoiceEmbeddingExtractor()
    emb_empty = extractor.extract_embedding(b"")
    assert len(emb_empty) == 192
    assert np.linalg.norm(emb_empty) == pytest.approx(1.0, rel=1e-4)

    short_pcm = (np.array([100, 200, 300], dtype=np.int16)).tobytes()
    emb_short = extractor.extract_embedding(short_pcm)
    assert len(emb_short) == 192
    assert np.linalg.norm(emb_short) == pytest.approx(1.0, rel=1e-4)


# ---------------------------------------------------------------------------
# 2. Speaker Enrollment & Centroid Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_speaker_enrollment_and_centroid():
    db = Database(db_path=":memory:")
    await db.connect()
    registry = SpeakerRegistry(db=db)

    s1 = _generate_pcm(130, [600, 1100, 2400])
    s2 = _generate_pcm(132, [600, 1100, 2400])
    s3 = _generate_pcm(128, [600, 1100, 2400])

    profile = await registry.enroll_speaker(
        name="Alice",
        role=Role.ADMIN,
        audio_samples=[s1, s2, s3],
        speaker_id="spk_alice"
    )

    assert profile.speaker_id == "spk_alice"
    assert profile.name == "Alice"
    assert profile.role == Role.ADMIN
    assert profile.enrolled_samples == 3
    assert len(profile.embedding) == 192
    assert np.linalg.norm(profile.embedding) == pytest.approx(1.0, rel=1e-4)

    # Verify persistence in SQLite
    row = await db.get_speaker_profile("spk_alice")
    assert row is not None
    assert row["name"] == "Alice"
    assert row["role"] == "ADMIN"
    assert row["enrolled_samples"] == 3

    # Verify reload into a new registry instance
    new_reg = SpeakerRegistry(db=db)
    await new_reg.load_from_db()
    loaded = new_reg.get_speaker("spk_alice")
    assert loaded is not None
    assert loaded.name == "Alice"
    assert loaded.role == Role.ADMIN
    assert loaded.embedding == profile.embedding

    await db.close()


# ---------------------------------------------------------------------------
# 3. 1:N Cosine Similarity Matching Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_speaker_identification_1_to_n():
    registry = SpeakerRegistry()

    # Voice 1: Low-pitch male-like voice
    v1_sample1 = _generate_pcm(110, [500, 1000, 2300])
    v1_sample2 = _generate_pcm(112, [500, 1000, 2300])
    # Voice 2: High-pitch female-like voice
    v2_sample1 = _generate_pcm(350, [900, 1800, 3200])
    v2_sample2 = _generate_pcm(348, [900, 1800, 3200])
    # Voice 3: Unregistered stranger voice
    stranger_sample = _generate_pcm(600, [1500, 2600, 4000])

    await registry.enroll_speaker(name="Alice", role=Role.ADMIN, audio_samples=[v1_sample1], speaker_id="spk_alice")
    await registry.enroll_speaker(name="Bob", role=Role.MEMBER, audio_samples=[v2_sample1], speaker_id="spk_bob")

    # 1. Identify Alice with a distinct utterance
    res_alice = registry.identify_speaker(v1_sample2, threshold=0.75)
    assert res_alice.identified is True
    assert res_alice.speaker is not None
    assert res_alice.speaker.speaker_id == "spk_alice"
    assert res_alice.speaker.name == "Alice"
    assert res_alice.role == Role.ADMIN
    assert res_alice.similarity >= 0.75

    # 2. Identify Bob with a distinct utterance
    res_bob = registry.identify_speaker(v2_sample2, threshold=0.75)
    assert res_bob.identified is True
    assert res_bob.speaker is not None
    assert res_bob.speaker.speaker_id == "spk_bob"
    assert res_bob.speaker.name == "Bob"
    assert res_bob.role == Role.MEMBER
    assert res_bob.similarity >= 0.75

    # 3. Test outsider / stranger audio: must fail threshold matching and return GUEST
    res_stranger = registry.identify_speaker(stranger_sample, threshold=0.75)
    assert res_stranger.identified is False
    assert res_stranger.speaker is None
    assert res_stranger.role == Role.GUEST


def test_speaker_identification_empty_registry():
    registry = SpeakerRegistry()
    pcm = _generate_pcm(200, [800, 1200])
    res = registry.identify_speaker(pcm)
    assert res.identified is False
    assert res.speaker is None
    assert res.role == Role.GUEST


# ---------------------------------------------------------------------------
# 4. Voice-Gated Authorization Guardrail Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_voice_gated_authorization_tiers():
    event_bus = EventBus()
    events_captured = []

    async def event_handler(evt):
        events_captured.append(evt)

    event_bus.subscribe("security.voice_auth.approved", event_handler)
    event_bus.subscribe("security.voice_auth.denied", event_handler)

    voice_auth = VoiceGatedAuthorization(event_bus=event_bus, admin_threshold=0.75)

    alice_profile = SpeakerProfile(speaker_id="spk_alice", name="Alice", role=Role.ADMIN, embedding=[0.0]*192)
    bob_profile = SpeakerProfile(speaker_id="spk_bob", name="Bob", role=Role.MEMBER, embedding=[0.0]*192)

    admin_res = SpeakerIdentificationResult(identified=True, speaker=alice_profile, similarity=0.92, role=Role.ADMIN)
    member_res = SpeakerIdentificationResult(identified=True, speaker=bob_profile, similarity=0.85, role=Role.MEMBER)
    guest_res = SpeakerIdentificationResult(identified=False, speaker=None, similarity=0.45, role=Role.GUEST)

    # 1. Admin voice can execute SystemCommandTool
    dec_admin_sys = voice_auth.authorize_tool_execution(admin_res, "SystemCommandTool")
    assert dec_admin_sys.authorized is True
    assert dec_admin_sys.required_role == Role.ADMIN
    assert dec_admin_sys.speaker_role == Role.ADMIN

    # 2. Member voice is denied SystemCommandTool with clear error
    dec_member_sys = voice_auth.authorize_tool_execution(member_res, "SystemCommandTool")
    assert dec_member_sys.authorized is False
    assert "ADMIN" in (dec_member_sys.reason or "")
    assert dec_member_sys.speaker_role == Role.MEMBER

    # 3. Member voice can execute HomeAssistantTool
    dec_member_ha = voice_auth.authorize_tool_execution(member_res, "HomeAssistantTool")
    assert dec_member_ha.authorized is True
    assert dec_member_ha.speaker_role == Role.MEMBER

    # 4. Guest / Unidentified voice is denied HomeAssistantTool
    dec_guest_ha = voice_auth.authorize_tool_execution(guest_res, "HomeAssistantTool")
    assert dec_guest_ha.authorized is False
    assert "MEMBER" in (dec_guest_ha.reason or "")

    # 5. Guest / Unidentified voice can access public/guest tools (WeatherTool)
    dec_guest_weather = voice_auth.authorize_tool_execution(guest_res, "WeatherTool")
    assert dec_guest_weather.authorized is True
    assert dec_guest_weather.required_role == Role.GUEST

    # 6. Admin with low similarity score (< threshold) is denied
    admin_low_sim = SpeakerIdentificationResult(identified=True, speaker=alice_profile, similarity=0.70, role=Role.ADMIN)
    dec_low_sim = voice_auth.authorize_tool_execution(admin_low_sim, "SystemCommandTool")
    assert dec_low_sim.authorized is False
    assert "similarity" in (dec_low_sim.reason or "").lower()


# ---------------------------------------------------------------------------
# 5. ToolManager Voice-Gated Integration Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tool_manager_voice_gating_blocks_execution():
    event_bus = EventBus()
    voice_auth = VoiceGatedAuthorization(event_bus=event_bus)
    tool_manager = ToolManager(event_bus=event_bus, voice_auth=voice_auth)

    guest_res = SpeakerIdentificationResult(identified=False, speaker=None, similarity=0.40, role=Role.GUEST)
    admin_profile = SpeakerProfile(speaker_id="spk_admin", name="Admin", role=Role.ADMIN, embedding=[0.0]*192)
    admin_res = SpeakerIdentificationResult(identified=True, speaker=admin_profile, similarity=0.95, role=Role.ADMIN)

    # 1. Guest attempting SystemCommandTool is blocked before invocation
    result_denied = await tool_manager.execute_tool(
        name="SystemCommandTool",
        arguments={"command": "echo test"},
        context={"speaker": guest_res}
    )
    assert result_denied.status == ExecutionStatus.DENIED
    assert "Voice authorization denied" in (result_denied.error or "")

    # 2. Admin attempting SystemCommandTool passes voice authorization
    result_approved = await tool_manager.execute_tool(
        name="SystemCommandTool",
        arguments={"command": "echo hello"},
        context={"speaker": admin_res, "confirmation_token": "valid"}
    )
    # Execution was not denied by voice auth
    assert "Voice authorization denied" not in (result_approved.error or "")


# ---------------------------------------------------------------------------
# 6. REST API Endpoints & Security CRUD Tests
# ---------------------------------------------------------------------------

def test_biometrics_api_unauthorized_access(test_client):
    res = test_client.get("/api/biometrics/speakers")
    assert res.status_code == 401


def test_biometrics_api_crud_and_identification(test_client, auth_headers):
    # 1. List speakers initially
    res = test_client.get("/api/biometrics/speakers", headers=auth_headers)
    assert res.status_code == 200
    initial_speakers = res.json()
    assert isinstance(initial_speakers, list)

    # 2. Enroll a new speaker
    pcm_audio = _generate_pcm(140, [650, 1150, 2450])
    b64_audio = base64.b64encode(pcm_audio).decode("utf-8")

    enroll_payload = {
        "name": "Sarah Connor",
        "role": "ADMIN",
        "samples": [b64_audio],
        "speaker_id": "spk_sarah"
    }
    enroll_res = test_client.post("/api/biometrics/enroll", json=enroll_payload, headers=auth_headers)
    assert enroll_res.status_code == 200
    enroll_data = enroll_res.json()
    assert enroll_data["success"] is True
    assert enroll_data["speaker_id"] == "spk_sarah"
    assert enroll_data["name"] == "Sarah Connor"
    assert enroll_data["role"] == "ADMIN"
    # Verify raw embedding is not exposed
    assert "embedding" not in enroll_data

    # 3. Verify speaker listed with masked embedding
    list_res = test_client.get("/api/biometrics/speakers", headers=auth_headers)
    assert list_res.status_code == 200
    speakers = list_res.json()
    sarah = next((s for s in speakers if s["speaker_id"] == "spk_sarah"), None)
    assert sarah is not None
    assert sarah["name"] == "Sarah Connor"
    assert sarah["embedding_dim"] == 192
    assert "embedding" not in sarah

    # 4. Test identification endpoint with Sarah's audio
    id_payload = {
        "audio": b64_audio,
        "threshold": 0.75
    }
    id_res = test_client.post("/api/biometrics/identify", json=id_payload, headers=auth_headers)
    assert id_res.status_code == 200
    id_data = id_res.json()
    assert id_data["identified"] is True
    assert id_data["speaker"]["speaker_id"] == "spk_sarah"
    assert id_data["role"] == "ADMIN"
    assert id_data["similarity"] >= 0.75

    # 5. Update role to MEMBER
    role_res = test_client.patch(
        "/api/biometrics/speakers/spk_sarah/role",
        json={"role": "MEMBER"},
        headers=auth_headers
    )
    assert role_res.status_code == 200
    assert role_res.json()["role"] == "MEMBER"

    # 6. Delete speaker
    del_res = test_client.delete("/api/biometrics/speakers/spk_sarah", headers=auth_headers)
    assert del_res.status_code == 200
    assert del_res.json()["success"] is True

    # 7. Confirm deletion
    list_res_after = test_client.get("/api/biometrics/speakers", headers=auth_headers)
    sarah_after = next((s for s in list_res_after.json() if s["speaker_id"] == "spk_sarah"), None)
    assert sarah_after is None


def test_biometrics_api_enroll_with_audio_samples_alias(test_client, auth_headers):
    """Verify enrollment succeeds when payload uses 'audio_samples' instead of 'samples'."""
    pcm = _generate_pcm(160, [750, 1300, 2600])
    b64_audio = base64.b64encode(pcm).decode("utf-8")

    payload = {
        "name": "Primary Admin",
        "role": "ADMIN",
        "audio_samples": [b64_audio],
        "speaker_id": "spk_primary_admin"
    }
    res = test_client.post("/api/biometrics/enroll", json=payload, headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["speaker_id"] == "spk_primary_admin"
    assert data["name"] == "Primary Admin"
    assert data["role"] == "ADMIN"

    # Cleanup
    del_res = test_client.delete("/api/biometrics/speakers/spk_primary_admin", headers=auth_headers)
    assert del_res.status_code == 200

