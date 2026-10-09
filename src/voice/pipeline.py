import asyncio
import logging
import re
from typing import AsyncGenerator, Dict, Any, List, Optional, Union
import numpy as np

from src.audio.vad import VoiceActivityDetector, CircularAudioBuffer
from src.audio.wakeword import WakeWordDetector
from src.audio.stt import Transcriber
from src.audio.tts import TTSEngine
from src.agent.orchestrator import IRISOrchestrator
from src.observability.event_bus import EventBus
from src.observability.tracing import TraceContext, create_trace_context

logger = logging.getLogger("iris.voice.pipeline")


class VoicePipeline:
    """
    End-to-End Voice Pipeline Orchestrator:
    Chains VAD -> Wakeword Detection -> STT -> Agent Orchestrator -> TTS.
    Provides real-time event telemetry via EventBus and graceful cancellation for barge-in interruptions.
    """

    def __init__(
        self,
        vad: Optional[VoiceActivityDetector] = None,
        wakeword: Optional[WakeWordDetector] = None,
        stt: Optional[Transcriber] = None,
        orchestrator: Optional[IRISOrchestrator] = None,
        tts: Optional[TTSEngine] = None,
        event_bus: Optional[EventBus] = None,
        device_id: str = "pod-living-room",
        sample_rate: int = 16000,
    ):
        self.vad = vad or VoiceActivityDetector(sample_rate=sample_rate)
        self.wakeword = wakeword or WakeWordDetector(sample_rate=sample_rate)
        self.stt = stt or Transcriber()
        self.orchestrator = orchestrator or IRISOrchestrator(
            api_base="http://localhost:11434/v1", api_key="ollama"
        )
        self.tts = tts or TTSEngine()
        self.event_bus = event_bus or EventBus()
        self.device_id = device_id
        self.sample_rate = sample_rate

        self.audio_buffer = CircularAudioBuffer(capacity_seconds=10.0, sample_rate=sample_rate)
        self.is_speaking = False
        self.is_listening = True
        self.state = "IDLE"  # IDLE, RECORDING, PROCESSING, SPEAKING
        self._interrupt_event = asyncio.Event()
        self._active_tts_task: Optional[asyncio.Task] = None

    def interrupt_tts(self):
        """Cancel current TTS stream gracefully on user interruption (barge-in)."""
        if self.is_speaking or self.state == "SPEAKING":
            logger.info("Barge-in detected! Interrupting active TTS playback.")
            self._interrupt_event.set()
            if self._active_tts_task and not self._active_tts_task.done():
                self._active_tts_task.cancel()
            self.is_speaking = False
            self.state = "IDLE"

    async def process_audio_chunk(
        self,
        chunk: Union[bytes, List[int], np.ndarray],
        trace_context: Optional[TraceContext] = None
    ) -> Dict[str, Any]:
        """
        Process a single audio frame/chunk through Wakeword detection and VAD.
        Returns a payload status dictionary.
        """
        trace = trace_context or create_trace_context(device_id=self.device_id)

        # 1. Wakeword check
        wakeword_detected = False
        try:
            wakeword_detected = self.wakeword.detect(chunk)
        except Exception:
            wakeword_detected = False

        if wakeword_detected:
            # If user spoke wakeword while TTS was outputting audio -> Barge-in interruption
            if self.is_speaking:
                self.interrupt_tts()
                await self.event_bus.publish("voice.barge_in", {"device_id": self.device_id}, trace=trace)

            await self.event_bus.publish(
                "voice.wakeword.detected",
                {"device_id": self.device_id, "keyword": self.wakeword.keyword},
                trace=trace
            )
            self.state = "RECORDING"
            return {"status": "wakeword_detected", "state": self.state}

        # 2. Convert chunk to list of samples for VAD & buffer storage
        samples = []
        if isinstance(chunk, bytes):
            num_samples = len(chunk) // 2
            if num_samples > 0:
                import struct
                samples = list(struct.unpack(f"<{num_samples}h", chunk))
        elif isinstance(chunk, (list, tuple)):
            samples = list(chunk)
        elif isinstance(chunk, np.ndarray):
            samples = chunk.flatten().tolist()

        if samples:
            self.audio_buffer.add(samples)

        is_speech = False
        if len(samples) >= self.vad.frame_size:
            is_speech = self.vad.is_speech(samples[:self.vad.frame_size])

        return {
            "status": "processed",
            "is_speech": is_speech,
            "state": self.state,
            "buffer_len": len(self.audio_buffer)
        }

    async def execute_end_to_end(
        self,
        audio_pcm: bytes,
        session_id: Optional[str] = None,
        trace_context: Optional[TraceContext] = None
    ) -> AsyncGenerator[bytes, None]:
        """
        Full end-to-end voice pipeline execution:
        STT (pcm) -> Agent Orchestration -> TTS audio streaming
        Yields synthesized TTS audio bytes.
        """
        trace = trace_context or create_trace_context(device_id=self.device_id, session_id=session_id)
        self._interrupt_event.clear()

        # Step 1: STT
        self.state = "PROCESSING"
        await self.event_bus.publish("voice.stt.started", {"device_id": self.device_id}, trace=trace)
        
        try:
            transcript = self.stt.transcribe_pcm(audio_pcm, sample_rate=self.sample_rate)
        except Exception as err:
            logger.error(f"STT failed: {err}")
            await self.event_bus.publish("voice.stt.failed", {"device_id": self.device_id, "error": str(err)}, trace=trace)
            self.state = "IDLE"
            return

        await self.event_bus.publish(
            "voice.stt.completed",
            {"device_id": self.device_id, "transcript": transcript},
            trace=trace
        )

        if not transcript or not transcript.strip():
            logger.info("Empty transcript from STT. Aborting turn.")
            self.state = "IDLE"
            return

        # Step 2: Agent Orchestration Streaming
        await self.event_bus.publish(
            "voice.agent.started",
            {"device_id": self.device_id, "prompt": transcript},
            trace=trace
        )

        self.state = "SPEAKING"
        self.is_speaking = True
        await self.event_bus.publish("voice.tts.started", {"device_id": self.device_id}, trace=trace)

        delimiters = re.compile(r"([.!?\n]+(?:\s+|$))")
        text_buffer = ""

        try:
            async for chunk_payload in self.orchestrator.stream_request(
                user_prompt=transcript,
                session_id=trace.session_id,
                device_id=self.device_id,
                request_id=trace.request_id,
                trace_id=trace.trace_id,
            ):
                if self._interrupt_event.is_set():
                    await self.event_bus.publish(
                        "voice.tts.interrupted",
                        {"device_id": self.device_id},
                        trace=trace
                    )
                    break

                if chunk_payload.chunk_type == "text_delta" and chunk_payload.delta_text:
                    text_buffer += chunk_payload.delta_text
                    parts = delimiters.split(text_buffer)
                    if len(parts) > 2:
                        ready_sentence = "".join(parts[:-1]).strip()
                        text_buffer = parts[-1]
                        if ready_sentence:
                            async for audio_bytes in self.tts.stream_audio(ready_sentence):
                                if self._interrupt_event.is_set():
                                    break
                                yield audio_bytes

                elif chunk_payload.chunk_type == "tool_call":
                    # If tool execution returned output text/result
                    tool_json = chunk_payload.delta_text
                    if "output_payload" in tool_json:
                        pass

            # Flush trailing sentence buffer
            if text_buffer.strip() and not self._interrupt_event.is_set():
                async for audio_bytes in self.tts.stream_audio(text_buffer.strip()):
                    if self._interrupt_event.is_set():
                        break
                    yield audio_bytes

        except asyncio.CancelledError:
            logger.info("Voice pipeline execution cancelled.")
            await self.event_bus.publish("voice.tts.interrupted", {"device_id": self.device_id}, trace=trace)
        except Exception as exc:
            logger.error(f"Error during voice pipeline execution: {exc}")
            await self.event_bus.publish("voice.pipeline.failed", {"device_id": self.device_id, "error": str(exc)}, trace=trace)
        finally:
            self.is_speaking = False
            self.state = "IDLE"
            await self.event_bus.publish("voice.pipeline.completed", {"device_id": self.device_id}, trace=trace)


VoicePipelineService = VoicePipeline
