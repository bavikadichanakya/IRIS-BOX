"""
IRIS-BOX Automation & Proactive Ambient Smart Home Subsystem.
"""

from src.automation.ha_listener import HomeAssistantWSClient
from src.automation.dispatcher import ProactiveSpeechDispatcher
from src.automation.proactive_engine import ProactiveEngine, ProactiveRule, ProactiveAnnouncement

__all__ = [
    "HomeAssistantWSClient",
    "ProactiveSpeechDispatcher",
    "ProactiveEngine",
    "ProactiveRule",
    "ProactiveAnnouncement",
]
