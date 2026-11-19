"""Voice in and out: "Hey Ray" wake word, Alexa-style chime, text-to-speech.

All optional. If the voice packages are missing, Ray still works by typing.
"""

from __future__ import annotations

import io
import math
import os
import queue
import struct
import threading
import time
import wave
from typing import Callable, Optional

from .commands import find_wake_word

IS_WINDOWS = os.name == "nt"
WHISPER_HINT = (
    "Hey Ray, open Chrome. Hey Ray, play lofi music on YouTube. Open Spotify, VS Code, WhatsApp, Bluetooth settings. "
    "Turn on dark mode. Volume up. Book a flight. Apply for this job on LinkedIn. Ask Claude to write the code."
)


# ----------------------------------------------------------------------- chime
def _tone_wav(notes: list[tuple[float, float]], volume: float = 0.35, rate: int = 22050) -> bytes:
    frames = bytearray()
    for freq, seconds in notes:
        count = int(rate * seconds)
        for i in range(count):
            envelope = min(1.0, i / (rate * 0.01)) * math.exp(-3.5 * i / count)
            sample = volume * envelope * (math.sin(2 * math.pi * freq * i / rate) + 0.3 * math.sin(4 * math.pi * freq * i / rate))
            frames += struct.pack("<h", int(max(-1.0, min(1.0, sample)) * 32767))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(bytes(frames))
    return buffer.getvalue()


WAKE_CHIME = _tone_wav([(784.0, 0.09), (1175.0, 0.22)])
DONE_CHIME = _tone_wav([(1175.0, 0.08), (784.0, 0.16)], volume=0.2)


def play_sound(wav_bytes: bytes) -> None:
    if IS_WINDOWS:
        import winsound

        try:
            winsound.PlaySound(wav_bytes, winsound.SND_MEMORY)
        except RuntimeError:
            pass


# ----------------------------------------------------------------------- speak
class Speaker:
    """Speaks on a background thread and can be interrupted mid-sentence."""

    def __init__(self, on_start: Callable[[], None] = lambda: None, on_done: Callable[[], None] = lambda: None) -> None:
        self.on_start = on_start
        self.on_done = on_done
        self._queue: "queue.Queue[Optional[str]]" = queue.Queue()
        self._cancel = threading.Event()
        self.busy = False
        self.available = self._detect()
        if self.available:
            threading.Thread(target=self._run, daemon=True, name="ray-speaker").start()

    def _detect(self) -> bool:
        for module in (("win32com.client",) if IS_WINDOWS else ()) + ("pyttsx3",):
            try:
                __import__(module)
                return True
            except ImportError:
                continue
        return False

    def say(self, text: str) -> None:
        if self.available and text.strip():
            self._cancel.clear()
            self._queue.put(text)

    def stop(self) -> None:
        self._cancel.set()
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def _run(self) -> None:
        try:
            speak = self._sapi() if IS_WINDOWS else None
        except Exception:
            speak = None
        if speak is None:
            speak = self._pyttsx3()
        while True:
            text = self._queue.get()
            if text is None:
                return
            self.busy = True
            self.on_start()
            try:
                speak(text)
            except Exception:
                pass
            self.busy = False
            self.on_done()

    def _sapi(self) -> Callable[[str], None]:
        import pythoncom  # type: ignore
        import win32com.client  # type: ignore

        pythoncom.CoInitialize()
        voice = win32com.client.Dispatch("SAPI.SpVoice")
        preferred = os.getenv("RAY_VOICE", "zira").lower()
        for i in range(voice.GetVoices().Count):
            candidate = voice.GetVoices().Item(i)
            if preferred in candidate.GetDescription().lower():
                voice.Voice = candidate
                break
        voice.Rate = 1

        def speak(text: str) -> None:
            voice.Speak(text, 1)  # SVSFlagsAsync
            while not voice.WaitUntilDone(50):
                if self._cancel.is_set():
                    voice.Speak("", 3)  # async + purge: stop immediately
                    return

        return speak

    def _pyttsx3(self) -> Callable[[str], None]:
        import pyttsx3  # type: ignore

        engine = pyttsx3.init()
        engine.setProperty("rate", 185)
        preferred = os.getenv("RAY_VOICE", "zira").lower()
        for v in engine.getProperty("voices"):
            if preferred in (v.name or "").lower():
                engine.setProperty("voice", v.id)
                break

        def speak(text: str) -> None:
            engine.say(text)
            engine.runAndWait()

        return speak


# ---------------------------------------------------------------------- listen
class Listener:
    """Owns the microphone on one thread.

    * Wake-word mode: always listening for "Hey Ray", like a smart speaker.
    * Push-to-talk: ``listen_now()`` skips the wake word for one command.
    """

    def __init__(
        self,
        on_command: Callable[[str], None],
        on_state: Callable[[str], None],
        on_error: Callable[[str], None],
        is_speaking: Callable[[], bool] = lambda: False,
    ) -> None:
        self.on_command = on_command
        self.on_state = on_state
        self.on_error = on_error
        self.is_speaking = is_speaking
        self.wake_enabled = os.getenv("RAY_WAKE_WORD", "1") != "0"
        self.offline = os.getenv("RAY_OFFLINE_SPEECH", "0") == "1"
        # "auto": Whisper if installed (most accurate), else Google. Or force "whisper" / "google".
        self.engine = os.getenv("RAY_STT", "auto").lower()
        self._whisper = None
        self._push = threading.Event()
        self._started = False
        self.problem = self._detect()

    @property
    def available(self) -> bool:
        return self.problem is None

    def _detect(self) -> Optional[str]:
        try:
            import speech_recognition  # noqa: F401  # type: ignore
        except ImportError:
            return "Voice is off: run  pip install -r requirements.txt  to enable it."
        try:
            import pyaudio  # noqa: F401  # type: ignore
        except ImportError:
            return "Voice is off: the PyAudio package is missing."
        return None

    def start(self) -> None:
        if self.available and not self._started:
            self._started = True
            threading.Thread(target=self._run, daemon=True, name="ray-listener").start()

    def listen_now(self) -> None:
        self.start()
        self._push.set()

    # ------------------------------------------------------------------ loop
    def _run(self) -> None:
        import speech_recognition as sr  # type: ignore

        recognizer = sr.Recognizer()
        recognizer.pause_threshold = 0.7
        recognizer.dynamic_energy_threshold = True
        try:
            microphone = sr.Microphone()
            with microphone as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.8)
                while True:
                    if self.is_speaking():
                        time.sleep(0.1)
                        continue
                    if self._push.is_set():
                        self._push.clear()
                        self._capture_command(recognizer, source, sr)
                        continue
                    if not self.wake_enabled:
                        time.sleep(0.1)
                        continue
                    try:
                        audio = recognizer.listen(source, timeout=1, phrase_time_limit=6)
                    except sr.WaitTimeoutError:
                        continue
                    if self._push.is_set() or self.is_speaking():
                        continue
                    heard, rest = find_wake_word(self._recognize(recognizer, audio, sr), strict=True)
                    if not heard:
                        continue
                    if rest:  # "Hey Ray, open Spotify" in one breath
                        play_sound(WAKE_CHIME)
                        self.on_state("thinking")
                        self.on_command(rest)
                    else:
                        self._capture_command(recognizer, source, sr)
        except Exception as exc:  # microphone unplugged, no input device...
            self._started = False
            self.on_error(f"Microphone problem: {exc}")

    def _capture_command(self, recognizer, source, sr) -> None:
        self.on_state("listening")
        play_sound(WAKE_CHIME)
        # Allow natural pauses mid-sentence ("book a table for two... at 8 pm").
        recognizer.pause_threshold = 1.1
        try:
            audio = recognizer.listen(source, timeout=7, phrase_time_limit=25)
        except sr.WaitTimeoutError:
            play_sound(DONE_CHIME)
            self.on_state("idle")
            return
        finally:
            recognizer.pause_threshold = 0.7
        self.on_state("thinking")
        text = self._recognize(recognizer, audio, sr)
        play_sound(DONE_CHIME)
        _, text = find_wake_word(text)
        if text:
            self.on_command(text)
        else:
            self.on_error("Sorry, I didn't catch that.")

    def _whisper_model(self):
        if self._whisper is None:
            from faster_whisper import WhisperModel  # type: ignore

            size = os.getenv("RAY_WHISPER_MODEL", "small.en")
            self._whisper = WhisperModel(size, device="auto", compute_type="int8")
        return self._whisper

    def _use_whisper(self) -> bool:
        if self.engine == "google":
            return False
        try:
            import faster_whisper  # noqa: F401  # type: ignore
            return True
        except ImportError:
            return False

    def _recognize(self, recognizer, audio, sr) -> str:
        if self._use_whisper():
            try:
                import numpy as np  # type: ignore

                samples = np.frombuffer(audio.get_raw_data(convert_rate=16000, convert_width=2), np.int16)
                segments, _ = self._whisper_model().transcribe(
                    samples.astype(np.float32) / 32768.0,
                    language="en",
                    beam_size=5,
                    vad_filter=True,
                    # Vocabulary hint: makes app names and Ray's name come out right.
                    initial_prompt=WHISPER_HINT,
                )
                return " ".join(seg.text for seg in segments).strip()
            except Exception:
                pass  # fall through to the other recognizers
        if not self.offline:
            try:
                return recognizer.recognize_google(audio)
            except sr.UnknownValueError:
                return ""
            except sr.RequestError:
                pass  # no internet: fall back to offline recognition
        try:
            return recognizer.recognize_sphinx(audio)
        except Exception:
            return ""
