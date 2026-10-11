from typing import Optional, Any, Dict, List
from fastapi import APIRouter, Request, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.storage.memory_store import MemoryStore, FactRecord, PreferenceRecord

router = APIRouter(prefix="/memory", tags=["Personal Memory & Preferences"])


class PreferencePayload(BaseModel):
    key: str
    value: Any
    category: Optional[str] = "general"
    user_id: Optional[str] = "default"


class FactCreatePayload(BaseModel):
    fact: str
    confidence: Optional[float] = 1.0
    user_id: Optional[str] = "default"
    source_session_id: Optional[str] = None


def get_memory_store(request: Request) -> MemoryStore:
    store = getattr(request.app.state, "memory_store", None)
    if store is not None:
        return store
    db = getattr(request.app.state, "db", None)
    return MemoryStore(db=db)


@router.get("/preferences")
async def get_preferences(
    request: Request,
    user_id: str = Query("default", description="User ID to retrieve preferences for")
):
    """List all explicit preferences for the specified user."""
    store = get_memory_store(request)
    prefs_map = await store.list_preferences(user_id=user_id)
    records = await store.list_preference_records(user_id=user_id)
    return {
        "user_id": user_id,
        "preferences": prefs_map,
        "items": [r.model_dump() for r in records]
    }


@router.post("/preferences", status_code=status.HTTP_200_OK)
async def set_preference(
    payload: PreferencePayload,
    request: Request
):
    """Create or update an explicit user preference."""
    store = get_memory_store(request)
    user_id = payload.user_id or "default"
    category = payload.category or "general"
    await store.set_preference(
        user_id=user_id,
        key=payload.key,
        value=payload.value,
        category=category
    )
    return {
        "status": "saved",
        "user_id": user_id,
        "key": payload.key,
        "value": payload.value,
        "category": category
    }


@router.delete("/preferences/{key}")
async def delete_preference(
    key: str,
    request: Request,
    user_id: str = Query("default", description="User ID to delete preference from")
):
    """Delete an explicit preference by key."""
    store = get_memory_store(request)
    deleted = await store.delete_preference(user_id=user_id, key=key)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Preference '{key}' not found for user '{user_id}'."
        )
    return {"status": "deleted", "key": key, "user_id": user_id}


@router.get("/facts")
async def get_facts(
    request: Request,
    user_id: str = Query("default", description="User ID to retrieve facts for"),
    min_confidence: float = Query(0.6, ge=0.0, le=1.0, description="Minimum confidence threshold")
):
    """List inferred facts with confidence scores."""
    store = get_memory_store(request)
    facts = await store.list_facts(user_id=user_id, min_confidence=min_confidence)
    return {
        "user_id": user_id,
        "facts": [f.model_dump() for f in facts]
    }


@router.post("/facts", status_code=status.HTTP_201_CREATED)
async def create_fact(
    payload: FactCreatePayload,
    request: Request
):
    """Record an inferred fact."""
    store = get_memory_store(request)
    user_id = payload.user_id or "default"
    conf = payload.confidence if payload.confidence is not None else 1.0
    fact_id = await store.record_inferred_fact(
        user_id=user_id,
        fact=payload.fact,
        confidence=conf,
        session_id=payload.source_session_id
    )
    return {
        "status": "created",
        "fact_id": fact_id,
        "user_id": user_id,
        "fact": payload.fact,
        "confidence": conf
    }


@router.post("/facts/{fact_id}/confirm")
async def confirm_fact(
    fact_id: int,
    request: Request
):
    """Promote / confirm an inferred fact by user."""
    store = get_memory_store(request)
    confirmed = await store.confirm_fact(fact_id=fact_id)
    if not confirmed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Fact with ID {fact_id} not found."
        )
    return {"status": "confirmed", "fact_id": fact_id}


@router.delete("/facts/{fact_id}")
async def delete_fact(
    fact_id: int,
    request: Request
):
    """Delete an inferred fact by ID."""
    store = get_memory_store(request)
    deleted = await store.delete_fact(fact_id=fact_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Fact with ID {fact_id} not found."
        )
    return {"status": "deleted", "fact_id": fact_id}


# ==========================================
# Semantic Vector Memory & RAG Endpoints
# ==========================================

class NoteCreatePayload(BaseModel):
    note: str = Field(..., min_length=1, description="Episodic note or fact content")
    category: Optional[str] = Field("general", description="Category or tag")
    user_id: Optional[str] = Field("default", description="User ID")


def get_vector_store(request: Request) -> Optional[Any]:
    store = getattr(request.app.state, "vector_store", None)
    if store is not None:
        return store
    try:
        from src.memory.vector_store import VectorMemoryStore
        return VectorMemoryStore()
    except Exception as e:
        return None


@router.get("/semantic/search")
async def search_semantic_memory(
    request: Request,
    q: str = Query(..., min_length=1, description="Semantic search query"),
    limit: Optional[int] = Query(None, ge=1, le=20, description="Max results"),
    threshold: Optional[float] = Query(None, ge=0.0, le=1.0, description="Cosine similarity threshold"),
):
    """Test semantic retrieval with score inspection across episodic vector collections."""
    from src.config.settings import settings
    effective_limit = limit if limit is not None else settings.RAG_MAX_RESULTS
    effective_threshold = threshold if threshold is not None else settings.RAG_SIMILARITY_THRESHOLD

    vstore = get_vector_store(request)
    if not vstore:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vector memory store is unavailable.",
        )
    results = vstore.search_relevant(query=q, limit=effective_limit, threshold=effective_threshold)
    return {
        "query": q,
        "count": len(results),
        "threshold": effective_threshold,
        "results": [r.model_dump() for r in results],
    }


@router.post("/semantic/notes", status_code=status.HTTP_201_CREATED)
async def add_semantic_note(
    payload: NoteCreatePayload,
    request: Request,
):
    """Add an explicit episodic note or fact to the semantic vector store."""
    vstore = get_vector_store(request)
    if not vstore:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vector memory store is unavailable.",
        )
    memory_id = vstore.add_note(
        note=payload.note,
        category=payload.category or "general",
        user_id=payload.user_id or "default",
    )
    if not memory_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to index note: local embedding engine is unavailable offline.",
        )
    return {
        "status": "created",
        "memory_id": memory_id,
        "note": payload.note,
        "category": payload.category or "general",
        "user_id": payload.user_id or "default",
    }


@router.delete("/semantic/{memory_id}")
async def delete_semantic_memory(
    memory_id: str,
    request: Request,
):
    """Remove a semantic memory entry by ID across all collections."""
    vstore = get_vector_store(request)
    if not vstore:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vector memory store is unavailable.",
        )
    deleted = vstore.delete_memory(memory_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Semantic memory with ID '{memory_id}' not found.",
        )
    return {
        "status": "deleted",
        "memory_id": memory_id,
    }

