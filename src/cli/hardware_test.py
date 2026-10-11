import sys
import time
import io
import wave
import argparse
import subprocess
import numpy as np
from typing import Optional, Tuple

try:
    import sounddevice as sd
except ImportError:
    sd = None


class HardwareDiagnostics:
    """
    Interactive and automated Physical Hardware Bring-Up diagnostic tool for IRIS-BOX.
    Exercises physical microphone capture, VAD speech energy, offline Whisper STT,
    Piper TTS synthesis, and physical speaker playback.
    """

    def __init__(self, sample_rate: int = 16000, duration_seconds: float = 3.0):
        self.sample_rate = sample_rate
        self.duration_seconds = duration_seconds

    def check_devices(self) -> Tuple[Optional[str], Optional[str]]:
        if sd is None:
            raise RuntimeError("sounddevice library is not installed.")

        devices = sd.query_devices()
        input_dev = None
        output_dev = None
        try:
            def_in, def_out = sd.default.device
            if def_in >= 0:
                input_dev = devices[def_in]["name"]
            if def_out >= 0:
                output_dev = devices[def_out]["name"]
        except Exception:
            pass

        return input_dev or "Default Microphone", output_dev or "Default Speaker"

    def record_audio(self, duration: Optional[float] = None) -> np.ndarray:
        dur = duration or self.duration_seconds
        total_samples = int(dur * self.sample_rate)
        print(f"[*] Recording {dur}s from microphone at {self.sample_rate}Hz...")

        recording = sd.rec(
            total_samples,
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
        )
        sd.wait()
        return recording.flatten()

    def evaluate_vad_energy(self, pcm_samples: np.ndarray, threshold: float = 0.01) -> Tuple[float, float, bool]:
        """
        Calculates Root Mean Square (RMS) signal energy and decibel level.
        Returns: (rms, db, is_speech_detected)
        """
        if len(pcm_samples) == 0:
            return 0.0, -100.0, False

        float_samples = pcm_samples.astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(float_samples ** 2)))
        db = float(20 * np.log10(max(rms, 1e-6)))
        is_speech = rms >= threshold
        return rms, db, is_speech

    def transcribe_audio(self, pcm_samples: np.ndarray) -> Tuple[str, float]:
        """Transcribe audio using offline Faster-Whisper."""
        start = time.perf_counter()
        try:
            from src.audio.stt import Transcriber

            transcriber = Transcriber(model_name="base", device="cpu", fallback_mock=False)
            float_audio = pcm_samples.astype(np.float32) / 32768.0

            if transcriber.fw_model:
                segments, _ = transcriber.fw_model.transcribe(float_audio, beam_size=1)
                text = " ".join(seg.text for seg in segments).strip()
            elif transcriber.model:
                result = transcriber.model.transcribe(float_audio)
                text = result.get("text", "").strip()
            else:
                text = "[STT Engine unavailable]"

            elapsed_ms = (time.perf_counter() - start) * 1000.0
            return text or "[No speech transcribed]", elapsed_ms
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            return f"[Transcription error: {exc}]", elapsed_ms

    def synthesize_tts(self, text: str) -> Tuple[bytes, float]:
        """Synthesize audio using local Piper TTS executable."""
        start = time.perf_counter()
        piper_bin = "models/piper/piper.exe"
        model_path = "models/piper/en_US-lessac-medium.onnx"

        proc = subprocess.run(
            [piper_bin, "--model", model_path, "--output_file", "-"],
            input=text.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10.0,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000.0

        if proc.returncode != 0:
            raise RuntimeError(f"Piper synthesis error: {proc.stderr.decode('utf-8', errors='ignore')}")

        return proc.stdout, elapsed_ms

    def play_audio(self, wav_bytes: bytes):
        """Play generated WAV stream via physical host speaker."""
        with io.BytesIO(wav_bytes) as bio:
            with wave.open(bio, "rb") as wf:
                sample_rate = wf.getframerate()
                num_frames = wf.getnframes()
                raw_frames = wf.readframes(num_frames)
                audio_data = np.frombuffer(raw_frames, dtype=np.int16)

        sd.play(audio_data, samplerate=sample_rate)
        sd.wait()

    def run_full_diagnostic(self, play_sound: bool = True) -> dict:
        """Executes full hardware bring-up sequence and reports latencies."""
        print("================================================================================")
        print("                 IRIS-BOX Physical Hardware Bring-Up Tool                       ")
        print("================================================================================")

        t_start = time.perf_counter()
        in_dev, out_dev = self.check_devices()
        print(f"[+] Microphone Input: {in_dev}")
        print(f"[+] Speaker Output:    {out_dev}")
        print("--------------------------------------------------------------------------------")

        # 1. Capture microphone
        print(f"[*] Step 1/4: Speak into your microphone now (recording {self.duration_seconds}s)...")
        samples = self.record_audio()
        print(f"[✓] Captured {len(samples)} samples ({len(samples) * 2} bytes PCM16)")

        # 2. VAD & Energy
        rms, db, is_speech = self.evaluate_vad_energy(samples)
        vad_status = "SPEECH DETECTED" if is_speech else "SILENCE / AMBIENT NOISE"
        print(f"[*] Step 2/4: Signal Analysis -> RMS: {rms:.4f} ({db:.1f} dB) [{vad_status}]")

        # 3. Offline STT
        print("[*] Step 3/4: Processing Offline Speech-to-Text via Faster-Whisper...")
        transcription, stt_ms = self.transcribe_audio(samples)
        print(f"[✓] Transcription ({stt_ms:.1f}ms): \"{transcription}\"")

        # 4. Piper Offline TTS Synthesis & Playback
        tts_prompt = "IRIS hardware audio bring-up successful. Audio input and output are fully operational."
        print(f"[*] Step 4/4: Synthesizing confirmation via Piper TTS...")
        wav_bytes, tts_ms = self.synthesize_tts(tts_prompt)
        print(f"[✓] Synthesized {len(wav_bytes)} bytes WAV in {tts_ms:.1f}ms")

        if play_sound:
            print("[*] Playing audio confirmation through host speaker...")
            self.play_audio(wav_bytes)
            print("[✓] Playback complete.")
        else:
            print("[i] Speaker playback skipped (--no-playback specified).")

        total_ms = (time.perf_counter() - t_start) * 1000.0
        print("--------------------------------------------------------------------------------")
        print(f"[✓] HARDWARE BRING-UP TEST COMPLETE: Round-trip latency: {total_ms:.1f}ms")
        print("================================================================================")

        return {
            "input_device": in_dev,
            "output_device": out_dev,
            "rms_energy": rms,
            "db_level": db,
            "speech_detected": is_speech,
            "transcription": transcription,
            "stt_latency_ms": round(stt_ms, 2),
            "tts_latency_ms": round(tts_ms, 2),
            "total_latency_ms": round(total_ms, 2),
        }


def main():
    parser = argparse.ArgumentParser(description="IRIS-BOX Physical Hardware Bring-Up Diagnostic")
    parser.add_argument("--duration", type=float, default=3.0, help="Microphone recording duration in seconds")
    parser.add_argument("--no-playback", action="store_true", help="Skip physical speaker playback")
    args = parser.parse_args()

    diag = HardwareDiagnostics(duration_seconds=args.duration)
    diag.run_full_diagnostic(play_sound=not args.no_playback)


if __name__ == "__main__":
    main()
