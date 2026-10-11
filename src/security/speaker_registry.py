import json
import logging
import time
import uuid
from typing import Dict, List, Optional, Union
import numpy as np

from src.audio.biometrics_engine import VoiceEmbeddingExtractor
from src.security.biometrics import Role, SpeakerProfile, SpeakerIdentificationResult
from src.storage.db import Database

logger = logging.getLogger("iris.security.speaker_registry")


class SpeakerRegistry:
    """
    Registry for enrolled speaker biometric profiles.
    Performs enrollment averaging over multiple utterances, persists profiles in SQLite,
    and conducts sub-millisecond 1:N cosine similarity matching.
    """

    def __init__(
        self,
        db: Optional[Database] = None,
        extractor: Optional[VoiceEmbeddingExtractor] = None
    ):
        self.db = db
        self.extractor = extractor or VoiceEmbeddingExtractor()
        self._profiles: Dict[str, SpeakerProfile] = {}

    async def load_from_db(self):
        """Load enrolled speaker profiles from SQLite into in-memory cache."""
        if not self.db:
            return
        try:
            rows = await self.db.list_speaker_profiles()
            for r in rows:
                emb = json.loads(r["embedding_blob"]) if isinstance(r["embedding_blob"], str) else r["embedding_blob"]
                profile = SpeakerProfile(
                    speaker_id=r["speaker_id"],
                    name=r["name"],
                    role=Role(r["role"]),
                    embedding=emb,
                    enrolled_samples=r.get("enrolled_samples", 1),
                    created_at=r.get("created_at", time.time())
                )
                self._profiles[profile.speaker_id] = profile
            logger.info("Loaded %d speaker profiles into in-memory registry.", len(self._profiles))
        except Exception as e:
            logger.error("Failed to load speaker profiles from database: %s", e)

    async def enroll_speaker(
        self,
        name: str,
        role: Union[Role, str],
        audio_samples: List[bytes],
        speaker_id: Optional[str] = None
    ) -> SpeakerProfile:
        """
        Extracts embeddings for each audio sample, computes centroid, L2 normalizes,
        persists to SQLite, and caches in memory.
        """
        if not audio_samples:
            raise ValueError("At least one audio sample is required for speaker enrollment.")

        role_enum = Role(role) if isinstance(role, str) else role

        embeddings: List[np.ndarray] = []
        for sample in audio_samples:
            emb = self.extractor.extract_embedding(sample)
            embeddings.append(np.array(emb, dtype=np.float32))

        # Calculate centroid (average embedding across all enrolled samples)
        centroid = np.mean(embeddings, axis=0)

        # L2-normalize centroid
        norm = float(np.linalg.norm(centroid))
        if norm > 1e-12:
            centroid = centroid / norm
        else:
            centroid = np.ones(192, dtype=np.float32) / np.sqrt(192.0)

        spk_id = speaker_id or f"spk_{uuid.uuid4().hex[:8]}"
        created_at = time.time()

        profile = SpeakerProfile(
            speaker_id=spk_id,
            name=name,
            role=role_enum,
            embedding=centroid.tolist(),
            enrolled_samples=len(audio_samples),
            created_at=created_at
        )

        self._profiles[spk_id] = profile

        if self.db:
            try:
                await self.db.save_speaker_profile(
                    speaker_id=spk_id,
                    name=name,
                    role=role_enum.value,
                    embedding_blob=json.dumps(profile.embedding),
                    enrolled_samples=len(audio_samples),
                    created_at=created_at
                )
            except Exception as e:
                logger.error("Failed to persist speaker profile '%s' to database: %s", spk_id, e)

        return profile

    def identify_speaker(
        self,
        pcm_audio: bytes,
        threshold: float = 0.75
    ) -> SpeakerIdentificationResult:
        """
        Identifies active speaker by computing cosine similarity against registered profiles.
        Sub-millisecond 1:N matching over in-memory cache.
        If highest similarity >= threshold, returns identified profile; otherwise returns GUEST.
        """
        if not self._profiles:
            return SpeakerIdentificationResult(
                identified=False,
                speaker=None,
                similarity=0.0,
                role=Role.GUEST
            )

        query_emb = np.array(self.extractor.extract_embedding(pcm_audio), dtype=np.float32)

        best_profile: Optional[SpeakerProfile] = None
        best_similarity = -1.0

        for profile in self._profiles.values():
            prof_emb = np.array(profile.embedding, dtype=np.float32)
            # Both vectors are L2-normalized: dot product is cosine similarity
            sim = float(np.dot(query_emb, prof_emb))
            if sim > best_similarity:
                best_similarity = sim
                best_profile = profile

        if best_profile is not None and best_similarity >= threshold:
            return SpeakerIdentificationResult(
                identified=True,
                speaker=best_profile,
                similarity=round(best_similarity, 4),
                role=best_profile.role
            )

        return SpeakerIdentificationResult(
            identified=False,
            speaker=None,
            similarity=round(max(0.0, best_similarity), 4),
            role=Role.GUEST
        )

    def list_speakers(self) -> List[SpeakerProfile]:
        """Return list of all enrolled speaker profiles."""
        return list(self._profiles.values())

    def get_speaker(self, speaker_id: str) -> Optional[SpeakerProfile]:
        """Retrieve an enrolled speaker profile by ID."""
        return self._profiles.get(speaker_id)

    async def delete_speaker(self, speaker_id: str) -> bool:
        """Delete an enrolled speaker profile by ID."""
        existed = speaker_id in self._profiles
        self._profiles.pop(speaker_id, None)

        if self.db:
            try:
                db_deleted = await self.db.delete_speaker_profile(speaker_id)
                return db_deleted or existed
            except Exception as e:
                logger.error("Failed to delete speaker profile '%s' from DB: %s", speaker_id, e)
        return existed

    async def update_role(self, speaker_id: str, new_role: Union[Role, str]) -> Optional[SpeakerProfile]:
        """Update role for an enrolled speaker profile."""
        profile = self._profiles.get(speaker_id)
        if not profile:
            return None

        role_enum = Role(new_role) if isinstance(new_role, str) else new_role
        profile.role = role_enum

        if self.db:
            try:
                await self.db.update_speaker_role(speaker_id, role_enum.value)
            except Exception as e:
                logger.error("Failed to update speaker role for '%s' in DB: %s", speaker_id, e)

        return profile
