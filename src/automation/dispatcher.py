import asyncio
import io
import json
import logging
import time
import wave
from typing import Optional, Dict, Any, List

from src.config.settings import settings
from src.server.websocket import ws_manager, WebSocketConnectionManager
from src.audio.tts import TTSEngine

logger = logging.getLogger("iris.automation.dispatcher")


class ProactiveSpeechDispatcher:
    """
    Dispatches proactive ambient voice announcements across connected WebSocket satellites
    and optional physical speaker outputs using local Piper TTS synthesis.
    """

    def __init__(
        self,
        tts_engine: Optional[TTSEngine] = None,
        connection_manager: Optional[WebSocketConnectionManager] = None,
        play_physical_speaker: Optional[bool] = None,
    ):
        self.tts_engine = tts_engine or TTSEngine(online_fallback=False)
        self.ws_manager = connection_manager or ws_manager
        self.play_physical_speaker = (
            play_physical_speaker
            if play_physical_speaker is not None
            else settings.PROACTIVE_PHYSICAL_SPEAKER
        )

    async def dispatch(
        self,
        text: str,
        severity: str = "INFO",
        entity_id: Optional[str] = None,
        timestamp: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Synthesizes speech and broadcasts proactive announcement envelope
        to all active WebSocket satellites and optional physical speaker.
        """
        ts = timestamp if timestamp is not None else time.time()
        envelope = {
            "type": "proactive_announcement",
            "text": text,
            "severity": severity,
            "entity_id": entity_id or "",
            "timestamp": ts,
        }

        # 1. Generate local binary WAV audio via TTSEngine
        audio_bytes: Optional[bytes] = None
        if self.tts_engine:
            try:
                audio_bytes = await self.tts_engine.synthesize(text)
                logger.debug("Synthesized %d bytes of speech for proactive announcement", len(audio_bytes))
            except Exception as e:
                logger.warning("Local TTS synthesis failed for announcement ('%s'): %s", text, e)

        # 2. Broadcast JSON envelope to all active WebSocket clients
        broadcast_tasks = []
        envelope_str = json.dumps(envelope)

        active_sessions = list(self.ws_manager.active_connections.keys())
        for session_id in active_sessions:
            ws = self.ws_manager.active_connections.get(session_id)
            if ws:
                broadcast_tasks.append(self._safe_send_ws(ws, session_id, envelope_str, audio_bytes))

        if broadcast_tasks:
            await asyncio.gather(*broadcast_tasks, return_exceptions=True)

        # 3. Optional local physical speaker playback via sounddevice
        if self.play_physical_speaker and audio_bytes:
            self._play_physical_audio(audio_bytes)

        logger.info(
            "Dispatched proactive announcement [%s] to %d satellite(s): '%s'",
            severity,
            len(active_sessions),
            text,
        )

        return {
            "status": "DISPATCHED",
            "text": text,
            "severity": severity,
            "satellites_notified": len(active_sessions),
            "audio_bytes": len(audio_bytes) if audio_bytes else 0,
            "timestamp": ts,
        }

    async def _safe_send_ws(self, ws, session_id: str, json_text: str, audio_bytes: Optional[bytes]):
        """Safely sends JSON envelope and optional binary audio down a WebSocket."""
        try:
            await ws.send_text(json_text)
            if audio_bytes:
                await ws.send_bytes(audio_bytes)
        except Exception as e:
            logger.debug("Failed to send proactive announcement to session %s: %s", session_id, e)
            await self.ws_manager.disconnect(session_id)

    def _play_physical_audio(self, audio_bytes: bytes) -> None:
        """Plays audio through the host speaker via sounddevice without blocking the event loop."""
        try:
            import sounddevice as sd
            import numpy as np

            # Read WAV bytes
            with io.BytesIO(audio_bytes) as wav_io:
                with wave.open(wav_io, "rb") as wf:
                    channels = wf.getnchannels()
                    samplerate = wf.getframerate()
                    sampwidth = wf.getsampwidth()
                    frames = wf.readframes(wf.getnframes())

            if sampwidth == 2:
                dtype = np.int16
            elif sampwidth == 4:
                dtype = np.int32
            else:
                dtype = np.uint8

            audio_array = np.frombuffer(frames, dtype=dtype)
            if channels > 1:
                audio_array = audio_array.reshape(-1, channels)

            # Fire and forget playback
            sd.play(audio_array, samplerate=samplerate)
        except Exception as e:
            logger.warning("Local physical speaker playback failed: %s", e)
