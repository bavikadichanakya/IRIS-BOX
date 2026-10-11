import os
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration settings for IRIS-BOX system components and vector memory."""

    VECTOR_DB_PATH: str = Field(default="data/vector_store", description="Path to ChromaDB persistence directory")
    EMBEDDING_MODEL_NAME: str = Field(default="all-MiniLM-L6-v2", description="HuggingFace model name or local directory")
    EMBEDDING_CACHE_DIR: str = Field(default="models/embeddings", description="Local cache directory for embeddings")
    RAG_MAX_RESULTS: int = Field(default=3, description="Maximum semantic results to retrieve")
    RAG_SIMILARITY_THRESHOLD: float = Field(default=0.65, description="Cosine similarity threshold")

    model_config = SettingsConfigDict(
        env_prefix="",
        extra="ignore",
    )


settings = Settings()
