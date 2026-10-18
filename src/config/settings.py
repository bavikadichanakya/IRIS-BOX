import os
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict



class Settings(BaseSettings):
    """Configuration settings for IRIS-BOX system components and vector memory."""

    # LLM Models & Execution Fallback
    DEFAULT_MODEL: str = Field(
        default=os.getenv("IRIS_LLM_MODEL", os.getenv("OPENAI_MODEL", "heretic-iris:latest")),
        description="Default primary LLM model"
    )
    FALLBACK_MODEL: str = Field(
        default=os.getenv("IRIS_FALLBACK_MODEL", "qwen2.5:7b-instruct"),
        description="Automatic rollback fallback model"
    )

    VECTOR_DB_PATH: str = Field(default="data/vector_store", description="Path to ChromaDB persistence directory")
    EMBEDDING_MODEL_NAME: str = Field(default="all-MiniLM-L6-v2", description="HuggingFace model name or local directory")
    EMBEDDING_CACHE_DIR: str = Field(default="models/embeddings", description="Local cache directory for embeddings")
    RAG_MAX_RESULTS: int = Field(default=3, description="Maximum semantic results to retrieve")
    RAG_SIMILARITY_THRESHOLD: float = Field(default=0.65, description="Cosine similarity threshold")

    # Home Assistant WebSocket & Proactive Ambient Engine
    HA_WS_URL: str = Field(default="ws://127.0.0.1:8123/api/websocket", description="Home Assistant WebSocket URL")
    HA_TOKEN: Optional[str] = Field(default=None, description="Home Assistant Long-Lived Access Token")
    PROACTIVE_ENABLED: bool = Field(default=True, description="Enable proactive ambient announcements")
    PROACTIVE_QUIET_HOURS_START: str = Field(default="23:00", description="Quiet hours start time HH:MM")
    PROACTIVE_QUIET_HOURS_END: str = Field(default="07:00", description="Quiet hours end time HH:MM")
    PROACTIVE_DEFAULT_COOLDOWN_SEC: float = Field(default=60.0, description="Default cooldown interval in seconds")
    PROACTIVE_PHYSICAL_SPEAKER: bool = Field(default=False, description="Enable local host physical speaker output")


    model_config = SettingsConfigDict(
        env_prefix="",
        extra="ignore",
    )


settings = Settings()
