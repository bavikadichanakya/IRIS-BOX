import os
import logging
from typing import List, Optional, Any, Union
import numpy as np

from src.config.settings import settings

logger = logging.getLogger("iris.memory.embeddings")


class LocalEmbeddingEngine:
    """
    Lightweight local text embedding engine for IRIS-BOX.
    Enforces strict air-gapped offline operation with local_files_only=True.
    Can be used as a standalone encoder or as a ChromaDB EmbeddingFunction.
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        cache_dir: Optional[str] = None,
        model: Optional[Any] = None,
        fallback_dimension: int = 384,
    ):
        self.model_name = model_name or settings.EMBEDDING_MODEL_NAME
        self.cache_dir = cache_dir or settings.EMBEDDING_CACHE_DIR
        self.fallback_dimension = fallback_dimension
        self._model = model
        self.status = "UNINITIALIZED"
        self.is_available = False
        self.error_message: Optional[str] = None

        if self._model is not None:
            self.status = "LOADED"
            self.is_available = True
        else:
            self._load_local_model()

    def _load_local_model(self):
        """Attempts to load SentenceTransformer model strictly from local files."""
        # Candidate directories to check for local model weights
        candidates = [
            os.path.join(self.cache_dir, self.model_name),
            os.path.join(self.cache_dir, self.model_name.replace("/", "_")),
            self.cache_dir,
            self.model_name,
        ]

        target_path = None
        for candidate in candidates:
            if os.path.isdir(candidate):
                files = os.listdir(candidate)
                if any(f.endswith((".bin", ".safetensors", ".onnx", ".json")) for f in files):
                    target_path = candidate
                    break

        if target_path is None:
            self._model = None
            self.status = "UNAVAILABLE"
            self.is_available = False
            self.error_message = (
                f"Local embedding model '{self.model_name}' not found in local cache. "
                f"Place weights in '{self.cache_dir}/{self.model_name}' for offline operation."
            )
            logger.info(self.error_message)
            return

        try:
            from sentence_transformers import SentenceTransformer

            # Strict offline enforcement: local_files_only=True prevents remote network fetch
            load_target = target_path
            self._model = SentenceTransformer(load_target, local_files_only=True)
            self.status = "LOADED"
            self.is_available = True
            logger.info("Loaded local embedding model '%s' successfully.", load_target)
        except Exception as exc:
            self._model = None
            self.status = "UNAVAILABLE"
            self.is_available = False
            self.error_message = (
                f"Local embedding model '{self.model_name}' unavailable offline ({exc}). "
                f"Please place model weights in '{self.cache_dir}/{self.model_name}' "
                "for strict air-gapped offline operation."
            )
            logger.warning(self.error_message)

    def embed_text(self, text: str) -> List[float]:
        """Embed a single text string into a float vector."""
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Embed a list of text strings into normalized float vectors.
        Raises RuntimeError if model is unavailable.
        """
        if not texts:
            return []

        if not self.is_available or self._model is None:
            raise RuntimeError(self.error_message or "Embedding model is unavailable offline.")

        try:
            # Generate normalized vectors for accurate cosine similarity
            embeddings = self._model.encode(
                texts,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            if isinstance(embeddings, np.ndarray):
                return embeddings.tolist()
            return [list(e) for e in embeddings]
        except Exception as e:
            logger.error("Embedding generation failed: %s", e)
            raise RuntimeError(f"Embedding generation error: {e}") from e

    def __call__(self, input: Union[str, List[str]]) -> List[List[float]]:
        """
        ChromaDB EmbeddingFunction protocol adapter.
        Allows passing LocalEmbeddingEngine directly as embedding_function.
        """
        if isinstance(input, str):
            input = [input]
        return self.embed_batch(list(input))

    def embed_query(self, input: Union[str, List[str]]) -> List[List[float]]:
        """ChromaDB embed_query hook."""
        return self.__call__(input)

    def embed_documents(self, input: Union[str, List[str]]) -> List[List[float]]:
        """ChromaDB embed_documents hook."""
        return self.__call__(input)

    def name(self) -> str:
        return f"LocalEmbeddingEngine({self.model_name})"

    def is_legacy(self) -> bool:
        return False


