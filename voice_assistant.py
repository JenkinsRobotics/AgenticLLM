#!/usr/bin/env python3
"""Google-Home-style local voice assistant.

Pipeline:
  mic ─► audio_queue ─► VAD worker thread ─► phrase_queue
                                               │
                                               ▼
       main loop ─► wake / 2-pass STT ─► pydantic_ai agent ─► TTS

The agent (python_pydantic_ai) decides everything: which tools to call, when
to use MCP, when to remember/recall. Voice mode treats TTS as the *default*
final-step output: the voice loop speaks the agent's final answer text — but
if the agent already vocalized through its own speak/speak_file tool, the
voice loop skips its TTS to avoid double-speaking.

  • full-duplex audio via Speex AEC (pyaec) — mic stays live during TTS
    so the user can interrupt mid-reply (barge-in, Zoom/Meet-style)
  • short tone instead of spoken "Yes?" so the user isn't clipped
  • 5-second follow-up window after each reply (no wake word required)

Just hit Run. Loads can take ~15–25s the first time.
"""

from __future__ import annotations

import collections
import importlib
import os
import queue
import re
import sys
import threading
import time
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
import pyaec
import sounddevice as sd
import webrtcvad
from scipy.signal import resample_poly


# Framework adapter — picks pydantic_ai (default) or hermes_xml so we can
# A/B compare under the same mic+TTS+AEC pipeline. Each framework exposes the
# same surface: LlamaCppPythonClient, init_extensions(args, client),
# run_for_voice(client, text), shutdown_extensions(wait), and a tools module
# with ensure_workspace().
_VOICE_FRAMEWORK = os.environ.get("VOICE_FRAMEWORK", "pydantic_ai").strip()

# Voice mode → robot-style production posture. Require explicit confirm=True
# on destructive ops (delete_file, forget). The agent must call ask_user
# first and only commit after the user authorizes that specific operation.
os.environ.setdefault("DESTRUCTIVE_OPS_REQUIRE_CONFIRM", "1")
_FRAMEWORK_MODULES = {
    "pydantic_ai": ("python_pydantic_ai.main", "python_pydantic_ai.tools"),
    "hermes_xml": ("python_hermes_xml.main", "python_hermes_xml.tools"),
}
if _VOICE_FRAMEWORK not in _FRAMEWORK_MODULES:
    raise RuntimeError(
        f"Unknown VOICE_FRAMEWORK={_VOICE_FRAMEWORK!r}; "
        f"expected one of {list(_FRAMEWORK_MODULES)}."
    )
_FW_MAIN = importlib.import_module(_FRAMEWORK_MODULES[_VOICE_FRAMEWORK][0])
agent_tools = importlib.import_module(_FRAMEWORK_MODULES[_VOICE_FRAMEWORK][1])

LlamaCppPythonClient = _FW_MAIN.LlamaCppPythonClient
init_extensions = _FW_MAIN.init_extensions
run_for_voice = _FW_MAIN.run_for_voice
shutdown_extensions = _FW_MAIN.shutdown_extensions


# ── config ─────────────────────────────────────────────────────────────
LLM_MODEL_PATH = Path(
    "/Users/jonathanjenkins/.lmstudio/models/lmstudio-community/"
    "gemma-4-26B-A4B-it-GGUF/gemma-4-26B-A4B-it-Q4_K_M.gguf"
)

# Two-pass STT: fast model runs every phrase to detect wake words. Accurate
# model only re-transcribes when wake matches or we're in follow-up mode,
# so we don't pay its cost on background noise.
STT_FAST = "base.en"
STT_ACCURATE = "medium.en"

KOKORO_VOICE = "af_heart"
KOKORO_LANG = "a"

# Whisper often mishears "jaeger" — covering common phonetic transcriptions
# so any of yeager/yager/jager/jaeger triggers the wake.
_WAKE_PREFIXES = ("ok", "okay", "hey")
_ASSISTANT_NAMES = ("jaeger", "yeager", "yager", "jager")
WAKE_PHRASES = tuple(f"{p} {n}" for p in _WAKE_PREFIXES for n in _ASSISTANT_NAMES)
WAKE_MATCH_THRESHOLD = 0.78
FOLLOWUP_WINDOW_S = 10.0      # listen this long after a reply, no wake needed

SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000   # 480 samples — VAD/STT cadence

# AEC operates on 10ms int16 frames. 3 AEC frames = 1 VAD frame.
AEC_FRAME_MS = 10
AEC_FRAME_SAMPLES = SAMPLE_RATE * AEC_FRAME_MS // 1000  # 160 samples
AEC_FRAMES_PER_VAD = FRAME_MS // AEC_FRAME_MS           # 3
AEC_FILTER_LENGTH = 3200        # 200ms tail — covers typical room+device round-trip delay

# Kokoro TTS native rate; we downsample to SAMPLE_RATE for unified duplex I/O.
TTS_NATIVE_SR = 24000

VAD_AGGRESSIVENESS = 2

PRE_ROLL_MS = 240             # capture speech onset
POST_PADDING_MS = 250         # capture trailing word — fixes "what time is it" → "time is in"
SILENCE_HANGOVER_MS = 700     # match the working command listener
MIN_SPEECH_MS = 400
MAX_SPEECH_MS = 8000

# Barge-in: how much sustained user speech (post-AEC) we need to see during
# TTS playback before we interrupt. Shorter than MIN_SPEECH_MS so interrupts
# feel snappy; longer than a single VAD frame so AEC residual doesn't false-trigger.
BARGE_IN_MS = 200

# ── short chime so the user knows we're listening ──────────────────────
def make_beep(freq: float = 880.0, duration_ms: int = 110,
              sr: int = 24000, amp: float = 0.25) -> np.ndarray:
    n = int(sr * duration_ms / 1000)
    t = np.arange(n) / sr
    # short fade-in/out to avoid clicks
    env = np.minimum(np.minimum(t / 0.01, 1.0), (duration_ms / 1000 - t) / 0.01).clip(0, 1)
    return (amp * env * np.sin(2 * np.pi * freq * t)).astype(np.float32)


BEEP = make_beep()
DOUBLE_BEEP = np.concatenate([
    make_beep(freq=660, duration_ms=80),
    np.zeros(int(24000 * 0.05), dtype=np.float32),
    make_beep(freq=880, duration_ms=80),
])


# ── audio I/O with AEC ────────────────────────────────────────────────
class AudioIO:
    """Full-duplex 16kHz audio with Speex Acoustic Echo Cancellation.

    Replaces the half-duplex `MicStream` + blocking `sd.play` pattern. The
    same callback fires every 10ms and does three things atomically:
      1. Pulls 160 samples from the playback queue, writes to outdata (or zeros).
      2. Captures that same buffer as the AEC reference signal.
      3. Runs `aec.cancel_echo(mic, ref)` on the incoming mic frame.

    Because the reference is what we *just* sent to the speaker, Speex's
    adaptive filter learns the actual round-trip echo (output buffer → DAC →
    speaker → air → mic → input buffer, typically 5–50ms on a PC) within
    `AEC_FILTER_LENGTH/SAMPLE_RATE` = 200ms and converges to >20dB suppression.

    Cleaned mic frames are bundled into 30ms VAD-sized chunks and exposed
    on `.q` for the existing VadWorker. Barge-in: when the VAD worker sees
    sustained voice while we're playing, it calls `interrupt_playback()`
    which drops every queued chunk so TTS cuts off mid-sentence.
    """

    def __init__(self) -> None:
        self.q: queue.Queue[np.ndarray] = queue.Queue()
        self._play_q: queue.Queue[np.ndarray] = queue.Queue()
        self._current_chunk = np.zeros(0, dtype=np.int16)
        self._mic_pending: list[np.ndarray] = []
        self._aec = pyaec.Aec(
            frame_size=AEC_FRAME_SAMPLES,
            filter_length=AEC_FILTER_LENGTH,
            sample_rate=SAMPLE_RATE,
            enable_preprocess=True,
        )
        self._playing = False
        self._barged = False
        self._stream = sd.Stream(
            samplerate=SAMPLE_RATE,
            channels=(1, 1),
            dtype="int16",
            blocksize=AEC_FRAME_SAMPLES,
            callback=self._cb,
            latency=("low", "low"),
        )

    # --- realtime audio callback -------------------------------------------
    def _cb(self, indata, outdata, frames, time_info, status) -> None:
        if status:
            print(f"[audio] {status}", file=sys.stderr)
        if frames != AEC_FRAME_SAMPLES:
            outdata.fill(0)
            return

        # 1. Fill outdata from current chunk + queued chunks.
        out = np.zeros(frames, dtype=np.int16)
        n_filled = 0
        while n_filled < frames:
            if len(self._current_chunk) == 0:
                try:
                    self._current_chunk = self._play_q.get_nowait()
                except queue.Empty:
                    break
            take = min(frames - n_filled, len(self._current_chunk))
            out[n_filled : n_filled + take] = self._current_chunk[:take]
            self._current_chunk = self._current_chunk[take:]
            n_filled += take
        outdata[:, 0] = out
        self._playing = (
            n_filled > 0 or len(self._current_chunk) > 0 or not self._play_q.empty()
        )

        # 2. AEC: cancel any echo of `out` that bled into the mic.
        mic_frame = indata[:, 0].astype(np.int16).tolist()
        ref_frame = out.tolist()
        cleaned = self._aec.cancel_echo(mic_frame, ref_frame)
        cleaned_arr = np.asarray(cleaned, dtype=np.int16)

        # 3. Bundle 3×10ms AEC frames into one 30ms VAD frame matching the
        #    old MicStream contract: shape (FRAME_SAMPLES, 1) float32 in [-1,1].
        self._mic_pending.append(cleaned_arr)
        if len(self._mic_pending) >= AEC_FRAMES_PER_VAD:
            bundled = np.concatenate(self._mic_pending[:AEC_FRAMES_PER_VAD])
            self._mic_pending = self._mic_pending[AEC_FRAMES_PER_VAD:]
            f32 = (bundled.astype(np.float32) / 32767.0).reshape(-1, 1)
            self.q.put(f32)

    # --- public API ---------------------------------------------------------
    def play_chunk(self, chunk_int16: np.ndarray) -> None:
        """Queue an int16 mono chunk at SAMPLE_RATE for playback. Non-blocking."""
        self._play_q.put(chunk_int16)

    def wait_until_drained(self, poll_s: float = 0.02, max_s: float = 30.0) -> None:
        """Block until the playback queue is empty AND the current chunk finishes."""
        deadline = time.time() + max_s
        while time.time() < deadline:
            if self._play_q.empty() and len(self._current_chunk) == 0:
                return
            if self._barged:
                return
            time.sleep(poll_s)

    def is_playing(self) -> bool:
        return self._playing

    def interrupt_playback(self) -> None:
        """Drop everything queued for playback. Stops TTS mid-sentence."""
        with self._play_q.mutex:
            self._play_q.queue.clear()
        self._current_chunk = np.zeros(0, dtype=np.int16)
        self._barged = True

    def clear_barge(self) -> None:
        self._barged = False

    def was_barged(self) -> bool:
        return self._barged

    def drain(self) -> None:
        with self.q.mutex:
            self.q.queue.clear()

    def __enter__(self) -> "AudioIO":
        self._stream.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stream.stop()
        self._stream.close()


# ── VAD worker thread ──────────────────────────────────────────────────
class VadWorker(threading.Thread):
    """Reads audio blocks, runs VAD, accumulates phrases, fast-transcribes,
    then pushes (audio_float32, fast_transcript) onto phrase_queue.

    Also triggers barge-in: when sustained voice is detected during TTS
    playback, immediately calls audio.interrupt_playback() so the user can
    talk over the assistant the same way they would on a Zoom call.
    """

    def __init__(self, audio: AudioIO, fast_model,
                 phrase_queue: queue.Queue, stop_event: threading.Event) -> None:
        super().__init__(daemon=True)
        self.audio = audio
        self.fast_model = fast_model
        self.phrase_queue = phrase_queue
        self.stop_event = stop_event
        self.vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)

        self.silence_blocks_to_end = max(1, SILENCE_HANGOVER_MS // FRAME_MS)
        self.min_speech_blocks = max(1, MIN_SPEECH_MS // FRAME_MS)
        self.max_speech_blocks = max(self.min_speech_blocks, MAX_SPEECH_MS // FRAME_MS)
        self.pre_roll_blocks = max(0, PRE_ROLL_MS // FRAME_MS)
        self.post_pad_samples = int(SAMPLE_RATE * POST_PADDING_MS / 1000)
        self.barge_blocks = max(1, BARGE_IN_MS // FRAME_MS)

        # Exposed so the main loop can avoid expiring the follow-up window
        # while the user is still mid-sentence.
        self.in_speech = False

    def _is_speech(self, chunk: np.ndarray) -> bool:
        pcm = (chunk[:, 0] * 32767).clip(-32768, 32767).astype(np.int16).tobytes()
        return self.vad.is_speech(pcm, SAMPLE_RATE)

    def _finalize(self, chunks: list[np.ndarray]) -> None:
        audio = np.concatenate(chunks, axis=0).astype(np.float32).reshape(-1)
        audio = np.concatenate([audio, np.zeros(self.post_pad_samples, dtype=np.float32)])
        try:
            segments = self.fast_model.transcribe(audio, language="en")
            text = " ".join(s.text for s in segments).strip()
        except Exception as exc:
            print(f"[stt-fast] {exc}", file=sys.stderr)
            text = ""
        if text:
            self.phrase_queue.put((audio, text))

    def run(self) -> None:
        pre_roll: collections.deque[np.ndarray] = collections.deque(maxlen=self.pre_roll_blocks)
        speech: list[np.ndarray] = []
        speech_blocks = 0
        silent_blocks = 0
        in_speech = False

        while not self.stop_event.is_set():
            try:
                chunk = self.audio.q.get(timeout=0.3)
            except queue.Empty:
                continue

            is_speech = self._is_speech(chunk)

            if is_speech:
                if not in_speech:
                    speech = list(pre_roll)
                    speech_blocks = len(speech)
                    silent_blocks = 0
                    in_speech = True
                speech.append(chunk)
                speech_blocks += 1
                silent_blocks = 0
            elif in_speech:
                speech.append(chunk)
                silent_blocks += 1
            else:
                pre_roll.append(chunk)

            # Publish speech state once we've seen enough sustained voice
            # to be confident this isn't a noise blip.
            self.in_speech = in_speech and speech_blocks >= self.min_speech_blocks

            # Barge-in: if the assistant is currently speaking and we've
            # detected enough sustained user voice (post-AEC), cut it off
            # immediately so the user can interrupt.
            if (
                in_speech
                and speech_blocks >= self.barge_blocks
                and self.audio.is_playing()
                and not self.audio.was_barged()
            ):
                self.audio.interrupt_playback()
                print("[barge-in — user is speaking, TTS cut]")

            phrase_done = in_speech and speech_blocks >= self.min_speech_blocks and (
                silent_blocks >= self.silence_blocks_to_end
                or speech_blocks >= self.max_speech_blocks
            )
            if phrase_done:
                self._finalize(speech)
                speech = []
                speech_blocks = 0
                silent_blocks = 0
                in_speech = False
                self.in_speech = False
                pre_roll.clear()


# ── wake-word logic ────────────────────────────────────────────────────
def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()


def find_wake(text: str) -> tuple[bool, str]:
    """Return (matched, remainder_after_wake_phrase)."""
    norm = normalize(text)
    for phrase in WAKE_PHRASES:
        idx = norm.find(phrase)
        if idx != -1:
            return True, norm[idx + len(phrase):].strip()
    tokens = norm.split()
    for phrase in WAKE_PHRASES:
        n = len(phrase.split())
        for i in range(0, max(0, len(tokens) - n + 1)):
            window = " ".join(tokens[i:i + n])
            if SequenceMatcher(None, window, phrase).ratio() >= WAKE_MATCH_THRESHOLD:
                return True, " ".join(tokens[i + n:]).strip()
    return False, ""


# ── Agent (pydantic_ai) ───────────────────────────────────────────────
def load_agent_client():
    """Load the selected framework's client + extensions once. The Llama
    instance inside the client is the model we share with the agent.
    Framework choice comes from VOICE_FRAMEWORK env var (default pydantic_ai;
    `hermes_xml` for the head-to-head comparison)."""
    print(f"[agent] framework={_VOICE_FRAMEWORK} — loading {LLM_MODEL_PATH.name}...", flush=True)
    t0 = time.perf_counter()
    client = LlamaCppPythonClient(model_path=LLM_MODEL_PATH, ctx=4096, warmup=True)
    print(f"[agent] loaded in {time.perf_counter()-t0:.1f}s", flush=True)

    # Memory on by default in voice mode — identity + episodic continuity.
    class _Args:
        with_memory = True
        with_mcp = False
        think = False

    init_extensions(_Args(), client)
    agent_tools.ensure_workspace()
    print(f"[agent] {_VOICE_FRAMEWORK} ready", flush=True)
    return client


def clean_for_tts(text: str) -> str:
    """Strip markdown the agent might emit so TTS doesn't read it literally."""
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\*+", "", text)
    text = re.sub(r"^[\-\*\d\.\)]+\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


# ── TTS ────────────────────────────────────────────────────────────────
def load_tts():
    from kokoro import KPipeline
    print("[tts] loading Kokoro...", flush=True)
    t0 = time.perf_counter()
    pipe = KPipeline(lang_code=KOKORO_LANG)
    list(pipe("Ready.", voice=KOKORO_VOICE))     # warm-up
    print(f"[tts] ready ({time.perf_counter()-t0:.1f}s)", flush=True)
    return pipe


def drain_phrase_queue(q: queue.Queue) -> None:
    """Discard phrases the VAD finalized while we were speaking — otherwise the
    follow-up window would treat stale buffered speech as a fresh command."""
    with q.mutex:
        q.queue.clear()


def _resample_to_mic_rate(audio_f32: np.ndarray) -> np.ndarray:
    """Kokoro outputs 24kHz; the duplex stream runs at 16kHz so AEC has a
    sample-aligned reference. Resample once per chunk; polyphase keeps the
    voice band intact and adds well under a millisecond.
    """
    if audio_f32.size == 0:
        return np.zeros(0, dtype=np.int16)
    resampled = resample_poly(audio_f32, up=SAMPLE_RATE, down=TTS_NATIVE_SR)
    return np.clip(resampled * 32767.0, -32768, 32767).astype(np.int16)


def play_beep(audio_io: AudioIO, audio_24k: np.ndarray) -> None:
    """Queue a short tone through the duplex stream so AEC captures it as
    a reference signal too — otherwise mic frames during the beep would
    leak echo into VAD."""
    chunk = _resample_to_mic_rate(audio_24k.astype(np.float32))
    audio_io.play_chunk(chunk)
    audio_io.wait_until_drained()


def speak(pipe, audio_io: AudioIO, text: str) -> bool:
    """Generate Kokoro chunks and stream them through the duplex AEC pipeline.
    Returns True if the full reply played, False if the user barged in.
    """
    if not text:
        return True
    audio_io.clear_barge()
    for r in pipe(text, voice=KOKORO_VOICE):
        if audio_io.was_barged():
            break
        if r.audio is None:
            continue
        chunk_24k = np.asarray(r.audio, dtype=np.float32)
        chunk_16k = _resample_to_mic_rate(chunk_24k)
        audio_io.play_chunk(chunk_16k)
    audio_io.wait_until_drained()
    return not audio_io.was_barged()


# ── main loop ──────────────────────────────────────────────────────────
def warm_stt(model, label: str) -> None:
    """Prime pywhispercpp once so the first real phrase avoids setup latency."""
    warm_audio = np.zeros(SAMPLE_RATE, dtype=np.float32)
    print(f"[{label}] warming up...", flush=True)
    t0 = time.perf_counter()
    try:
        list(model.transcribe(warm_audio, language="en"))
    except Exception as exc:
        # Some Whisper builds dislike pure silence. Startup should continue;
        # the model is still loaded and ready for normal speech.
        print(f"[{label}] warm-up skipped: {exc}", file=sys.stderr, flush=True)
    else:
        print(f"[{label}] primed ({time.perf_counter()-t0:.1f}s)", flush=True)


def main() -> int:
    from pywhispercpp.model import Model as STTModel

    print(f"[stt-fast] loading {STT_FAST}...", flush=True)
    t0 = time.perf_counter()
    fast_stt = STTModel(
        STT_FAST, print_realtime=False, print_progress=False,
        single_segment=True, no_context=True,
    )
    print(f"[stt-fast] ready ({time.perf_counter()-t0:.1f}s)", flush=True)
    warm_stt(fast_stt, "stt-fast")

    print(f"[stt-accurate] loading {STT_ACCURATE}...", flush=True)
    t0 = time.perf_counter()
    accurate_stt = STTModel(
        STT_ACCURATE, print_realtime=False, print_progress=False,
        single_segment=True, no_context=True,
    )
    print(f"[stt-accurate] ready ({time.perf_counter()-t0:.1f}s)", flush=True)
    warm_stt(accurate_stt, "stt-accurate")

    def transcribe_accurate(audio: np.ndarray) -> str:
        segments = accurate_stt.transcribe(audio, language="en")
        return " ".join(s.text for s in segments).strip()

    client = load_agent_client()
    tts = load_tts()

    phrase_queue: queue.Queue[tuple[np.ndarray, str]] = queue.Queue()
    stop_event = threading.Event()

    print(f"\n[ready] say one of: {', '.join(WAKE_PHRASES)} — Ctrl-C to quit.\n")

    state = "WAKE"           # "WAKE" or "FOLLOWUP"
    followup_deadline = 0.0

    with AudioIO() as audio_io:
        worker = VadWorker(audio_io, fast_stt, phrase_queue, stop_event)
        worker.start()
        try:
            while True:
                # Follow-up timeout?  Don't expire while the user is still
                # mid-sentence — wait for them to finish, then we'll see the
                # phrase on the queue and treat it as a follow-up command.
                if (
                    state == "FOLLOWUP"
                    and time.time() > followup_deadline
                    and not worker.in_speech
                ):
                    print("[follow-up window expired — say wake word again]")
                    state = "WAKE"

                try:
                    audio, fast_text = phrase_queue.get(timeout=0.3)
                except queue.Empty:
                    continue

                print(f"[heard]  {fast_text!r}")

                # Decide whether to act
                if state == "FOLLOWUP":
                    # In follow-up window any utterance counts as a command.
                    command = transcribe_accurate(audio).strip() or fast_text
                    print(f"[follow-up command]  {command!r}")
                else:
                    matched, remainder = find_wake(fast_text)
                    if not matched:
                        continue

                    # Re-transcribe the same audio with the accurate model
                    accurate_text = transcribe_accurate(audio)
                    a_matched, a_remainder = find_wake(accurate_text)
                    if a_matched and (a_remainder or not remainder):
                        remainder = a_remainder
                        print(f"[heard*] {accurate_text!r}")

                    if remainder:
                        command = remainder
                    else:
                        # Wake-only utterance: chime, then wait for the command.
                        play_beep(audio_io, BEEP)
                        drain_phrase_queue(phrase_queue)
                        try:
                            cmd_audio, cmd_fast = phrase_queue.get(timeout=6.0)
                        except queue.Empty:
                            print("[no command — back to wake]")
                            continue
                        print(f"[heard]  {cmd_fast!r}")
                        command = transcribe_accurate(cmd_audio).strip() or cmd_fast

                if not command:
                    continue

                # Hand the command to the pydantic_ai agent. With AEC live,
                # the mic stays open the whole time — any audio the agent
                # emits via its own speak tool is cancelled out, and the
                # user can interrupt mid-reply (handled by VadWorker).
                print(f"[agent] {command!r}")
                result = run_for_voice(client, command)
                reply = clean_for_tts(result.get("text") or "")
                for line in result.get("tool_activity") or []:
                    print(line)
                elapsed = result.get("elapsed_s", 0.0)
                if result.get("error"):
                    print(f"[agent error] {result['error']}")

                if reply and not result.get("spoke_via_tool"):
                    print(f"[reply]  {reply!r}  ({elapsed:.2f}s)")
                    completed = speak(tts, audio_io, reply)
                    if not completed:
                        print("[reply cut short by barge-in]")
                elif result.get("spoke_via_tool"):
                    print(f"[agent spoke via tool — skipping voice TTS] ({elapsed:.2f}s)")
                else:
                    print(f"[no reply] ({elapsed:.2f}s)")

                drain_phrase_queue(phrase_queue)

                # Open follow-up window
                play_beep(audio_io, DOUBLE_BEEP)
                drain_phrase_queue(phrase_queue)
                state = "FOLLOWUP"
                followup_deadline = time.time() + FOLLOWUP_WINDOW_S
                print(f"[follow-up open for {FOLLOWUP_WINDOW_S:.0f}s — keep talking]")

        except KeyboardInterrupt:
            print("\n[bye]")
            return 0
        finally:
            stop_event.set()
            worker.join(timeout=2)
            shutdown_extensions(wait=False)


if __name__ == "__main__":
    raise SystemExit(main())
