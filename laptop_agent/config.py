import os
import json
from pathlib import Path
from pydantic import BaseModel, Field

CONFIG_FILE_PATH = Path(__file__).resolve().parent / "config.json"


class AgentConfig(BaseModel):
    device_name: str = Field(default="laptop1", description="Unique device ID (e.g. laptop1, laptop2)")
    hub_url: str = Field(default="ws://127.0.0.1:8000/ws/agent", description="Phone A WebSocket server URL")
    auth_token: str = Field(default="", description="Authentication pairing token")
    heartbeat_seconds: float = Field(default=15.0, description="Ping interval to maintain connection")
    reconnect_interval_seconds: float = Field(default=3.0, description="Wait time before reconnecting")
    browser_user_data_dir: str = Field(
        default=str(Path.home() / ".iris_browser_profile"),
        description="Persistent directory for browser cookies and logins"
    )
    headed_browser: bool = Field(default=True, description="Open visible browser window instead of headless")


def load_config() -> AgentConfig:
    """Load configuration from config.json or environment variables, falling back to defaults."""
    data = {}
    if CONFIG_FILE_PATH.exists():
        try:
            with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass

    # Environment variable overrides
    if "IRIS_DEVICE_NAME" in os.environ:
        data["device_name"] = os.environ["IRIS_DEVICE_NAME"]
    if "IRIS_HUB_URL" in os.environ:
        data["hub_url"] = os.environ["IRIS_HUB_URL"]
    if "IRIS_AUTH_TOKEN" in os.environ:
        data["auth_token"] = os.environ["IRIS_AUTH_TOKEN"]

    return AgentConfig(**data)


def save_config(config: AgentConfig) -> None:
    """Persist agent configuration to disk."""
    with open(CONFIG_FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(config.model_dump(), f, indent=2)
