import os
import uuid
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

import chromadb
from chromadb.config import Settings as ChromaSettings

from src.config.settings import settings
from src.memory.embeddings import LocalEmbeddingEngine

logger = logging.getLogger("iris.memory.vector_store")


class MemorySearchResult(BaseModel):
    """Result item from a semantic vector search query."""
    id: str
    content: str
    collection: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    similarity: float
    distance: float


class VectorMemoryStore:
    """
    Local, persistent vector memory and episodic semantic store for IRIS-BOX.
    Embeds ChromaDB and uses LocalEmbeddingEngine for strict offline operation.
    """

    def __init__(
        self,
        persist_path: Optional[str] = None,
        embedding_engine: Optional[LocalEmbeddingEngine] = None,
    ):
        self.persist_path = persist_path or settings.VECTOR_DB_PATH
        self.embedding_engine = embedding_engine or LocalEmbeddingEngine()

        # Initialize ChromaDB client
        if self.persist_path == ":memory:":
            self._client = chromadb.Client()
        else:
            os.makedirs(self.persist_path, exist_ok=True)
            self._client = chromadb.PersistentClient(path=self.persist_path)

        # Initialize collections
        self._collections: Dict[str, Any] = {}
        self._init_collections()

    def _init_collections(self):
        """Initializes standard IRIS-BOX memory collections with cosine metric."""
        collection_names = ["conversations", "episodic_notes", "tool_history"]
        for name in collection_names:
            try:
                self._collections[name] = self._client.get_or_create_collection(
                    name=name,
                    embedding_function=self.embedding_engine,
                    metadata={"hnsw:space": "cosine"},
                )
            except Exception as e:
                logger.error("Failed to initialize vector collection '%s': %s", name, e)
                raise

    def add_interaction(
        self,
        session_id: str,
        prompt: str,
        response: str,
        user_id: str = "default",
    ) -> str:
        """
        Indexes a completed conversational turn into the 'conversations' collection.
        Returns the created memory_id.
        """
        if not self.embedding_engine.is_available:
            logger.warning("Cannot index interaction: LocalEmbeddingEngine is unavailable.")
            return ""

        memory_id = f"conv_{uuid.uuid4().hex[:12]}"
        iso_time = datetime.now(timezone.utc).isoformat()
        content = f"User: {prompt.strip()}\nIRIS: {response.strip()}"
        metadata = {
            "type": "conversation",
            "session_id": session_id,
            "user_id": user_id,
            "timestamp": iso_time,
            "prompt": prompt.strip()[:500],
            "response": response.strip()[:500],
        }

        try:
            self._collections["conversations"].add(
                ids=[memory_id],
                documents=[content],
                metadatas=[metadata],
            )
            logger.debug("Indexed conversation turn %s (session %s)", memory_id, session_id)
            return memory_id
        except Exception as e:
            logger.error("Failed to add interaction to vector store: %s", e)
            raise

    def add_note(
        self,
        note: str,
        category: str = "general",
        user_id: str = "default",
    ) -> str:
        """
        Indexes an explicit episodic note, fact, or bookmark into 'episodic_notes'.
        Returns the created memory_id.
        """
        if not self.embedding_engine.is_available:
            logger.warning("Cannot index note: LocalEmbeddingEngine is unavailable.")
            return ""

        memory_id = f"note_{uuid.uuid4().hex[:12]}"
        iso_time = datetime.now(timezone.utc).isoformat()
        metadata = {
            "type": "note",
            "category": category,
            "user_id": user_id,
            "timestamp": iso_time,
        }

        try:
            self._collections["episodic_notes"].add(
                ids=[memory_id],
                documents=[note.strip()],
                metadatas=[metadata],
            )
            logger.debug("Indexed episodic note %s (category %s)", memory_id, category)
            return memory_id
        except Exception as e:
            logger.error("Failed to add note to vector store: %s", e)
            raise

    def add_tool_execution(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        result: str,
        session_id: str = "default",
        user_id: str = "default",
    ) -> str:
        """
        Indexes a tool execution entry into 'tool_history'.
        Returns the created memory_id.
        """
        if not self.embedding_engine.is_available:
            logger.warning("Cannot index tool execution: LocalEmbeddingEngine is unavailable.")
            return ""

        memory_id = f"tool_{uuid.uuid4().hex[:12]}"
        iso_time = datetime.now(timezone.utc).isoformat()
        content = f"Executed {tool_name} with arguments {arguments}. Outcome: {result.strip()}"
        metadata = {
            "type": "tool_execution",
            "tool_name": tool_name,
            "session_id": session_id,
            "user_id": user_id,
            "timestamp": iso_time,
        }

        try:
            self._collections["tool_history"].add(
                ids=[memory_id],
                documents=[content],
                metadatas=[metadata],
            )
            logger.debug("Indexed tool execution %s (tool: %s)", memory_id, tool_name)
            return memory_id
        except Exception as e:
            logger.error("Failed to add tool execution to vector store: %s", e)
            raise

    def search_relevant(
        self,
        query: str,
        limit: int = 3,
        threshold: float = 0.65,
    ) -> List[MemorySearchResult]:
        """
        Queries all memory collections, computes cosine similarity, filters by threshold,
        and returns the top-k highest scoring memories.
        """
        if not query.strip() or not self.embedding_engine.is_available:
            return []

        all_results: List[MemorySearchResult] = []

        for col_name, collection in self._collections.items():
            try:
                count = collection.count()
                if count == 0:
                    continue

                k = min(limit, count)
                query_res = collection.query(
                    query_texts=[query.strip()],
                    n_results=k,
                    include=["documents", "metadatas", "distances"],
                )

                ids = query_res.get("ids", [[]])[0]
                documents = query_res.get("documents", [[]])[0]
                metadatas = query_res.get("metadatas", [[]])[0]
                distances = query_res.get("distances", [[]])[0]

                for item_id, doc, meta, dist in zip(ids, documents, metadatas, distances):
                    # Chroma cosine distance = 1 - cosine_similarity
                    # Distance can be slightly negative or > 1 due to floating point rounding
                    raw_dist = float(dist) if dist is not None else 1.0
                    similarity = max(0.0, min(1.0, 1.0 - raw_dist))

                    if similarity >= threshold:
                        all_results.append(
                            MemorySearchResult(
                                id=item_id,
                                content=doc or "",
                                collection=col_name,
                                metadata=meta or {},
                                similarity=round(similarity, 4),
                                distance=round(raw_dist, 4),
                            )
                        )
            except Exception as e:
                logger.warning("Error querying collection '%s': %s", col_name, e)

        # Sort descending by similarity
        all_results.sort(key=lambda item: item.similarity, reverse=True)
        return all_results[:limit]

    def delete_memory(self, memory_id: str) -> bool:
        """
        Deletes a memory item across all collections by its ID.
        Returns True if found and deleted, False otherwise.
        """
        found = False
        for col_name, collection in self._collections.items():
            try:
                # Check if item exists in collection
                res = collection.get(ids=[memory_id])
                if res and res.get("ids") and len(res["ids"]) > 0:
                    collection.delete(ids=[memory_id])
                    found = True
                    logger.debug("Deleted memory item %s from %s", memory_id, col_name)
            except Exception as e:
                logger.warning("Error deleting %s from '%s': %s", memory_id, col_name, e)

        return found

    def clear_all(self):
        """Clears all records in all collections."""
        for col_name, collection in self._collections.items():
            try:
                # Delete all by getting all IDs
                existing = collection.get()
                if existing and existing.get("ids"):
                    collection.delete(ids=existing["ids"])
                logger.info("Cleared vector collection '%s'.", col_name)
            except Exception as e:
                logger.error("Failed to clear vector collection '%s': %s", col_name, e)
