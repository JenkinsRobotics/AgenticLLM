"""Safe local tools for the agent test."""

from __future__ import annotations

import ast
import datetime as dt
import operator as op
import os
import platform
import re
import shutil
import time
from pathlib import Path
from typing import Any


WORKSPACE = Path(__file__).resolve().parent / "workspace"

# Kokoro is loaded lazily on first speak() call so startup stays fast.
KOKORO_VOICE = "af_heart"
KOKORO_LANG = "a"
KOKORO_SAMPLE_RATE = 24000
_kokoro_pipeline: Any = None


def ensure_workspace() -> None:
    WORKSPACE.mkdir(parents=True, exist_ok=True)


def workspace_path(path: str) -> Path:
    ensure_workspace()
    target = (WORKSPACE / path).resolve()
    if not target.is_relative_to(WORKSPACE):
        raise ValueError("path must stay inside agent_test/workspace")
    return target


def get_time(timezone: str | None = None) -> dict[str, Any]:
    """Current local date/time, or in a specific IANA timezone if provided.

    Examples: timezone="Asia/Shanghai", "America/New_York", "Europe/London".
    """
    if timezone:
        try:
            from zoneinfo import ZoneInfo

            now = dt.datetime.now(ZoneInfo(timezone))
        except Exception as exc:
            return {"error": f"unknown timezone: {timezone!r} ({exc})"}
    else:
        now = dt.datetime.now().astimezone()
    return {
        "datetime": now.strftime("%Y-%m-%d %I:%M:%S %p %Z"),
        "iso": now.isoformat(timespec="seconds"),
        "timezone": str(now.tzinfo),
    }


def create_file(path: str, content: str) -> dict[str, Any]:
    target = workspace_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {
        "created": True,
        "path": str(target.relative_to(WORKSPACE)),
        "bytes": len(content.encode("utf-8")),
    }


def append_file(path: str, content: str) -> dict[str, Any]:
    target = workspace_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as fh:
        fh.write(content)
    return {
        "appended": True,
        "path": str(target.relative_to(WORKSPACE)),
        "bytes": len(content.encode("utf-8")),
    }


def _destructive_confirm_required() -> bool:
    """Production / voice modes set DESTRUCTIVE_OPS_REQUIRE_CONFIRM=1 so the
    agent is forced to preview destructive ops before committing. Bench /
    dev keep the legacy behavior (zero perf cost when unset)."""
    return os.environ.get("DESTRUCTIVE_OPS_REQUIRE_CONFIRM", "").strip() in ("1", "true", "yes")


def delete_file(path: str, confirm: bool = False) -> dict[str, Any]:
    """Delete a workspace file.

    When DESTRUCTIVE_OPS_REQUIRE_CONFIRM=1 is set (voice / production mode),
    the first call previews the deletion instead of executing — the agent
    is expected to call `ask_user` to get explicit human authorization
    and then call `delete_file(path, confirm=True)` to commit. When the
    env var is unset (default / bench), `confirm` is ignored.
    """
    target = workspace_path(path)
    if not target.exists():
        return {"deleted": False, "reason": "not found", "path": path}
    if target.is_dir():
        return {"deleted": False, "reason": "is a directory", "path": path}

    if _destructive_confirm_required() and not confirm:
        size = target.stat().st_size
        return {
            "deleted": False,
            "preview": True,
            "path": str(target.relative_to(WORKSPACE)),
            "size_bytes": size,
            "hint": "Ask the user to confirm, then call delete_file again with confirm=True.",
        }

    target.unlink()
    return {"deleted": True, "path": str(target.relative_to(WORKSPACE))}


def read_file(path: str) -> dict[str, Any]:
    target = workspace_path(path)
    return {
        "path": str(target.relative_to(WORKSPACE)),
        "content": target.read_text(encoding="utf-8"),
    }


def list_directory(path: str = ".") -> dict[str, Any]:
    target = workspace_path(path)
    if not target.exists():
        raise FileNotFoundError(str(target.relative_to(WORKSPACE)))
    if not target.is_dir():
        raise NotADirectoryError(str(target.relative_to(WORKSPACE)))

    entries = []
    for child in sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        entries.append(
            {
                "name": child.name,
                "type": "directory" if child.is_dir() else "file",
                "bytes": child.stat().st_size if child.is_file() else None,
            }
        )
    return {"path": str(target.relative_to(WORKSPACE)), "entries": entries}


_CALC_OPS: dict[type, Any] = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.Pow: op.pow,
    ast.Mod: op.mod,
    ast.FloorDiv: op.floordiv,
    ast.USub: op.neg,
    ast.UAdd: op.pos,
}


def _calc_eval(node: Any) -> Any:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _CALC_OPS:
        return _CALC_OPS[type(node.op)](_calc_eval(node.left), _calc_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _CALC_OPS:
        return _CALC_OPS[type(node.op)](_calc_eval(node.operand))
    raise ValueError(f"unsupported expression: {ast.dump(node)}")


def calculate(expression: str) -> dict[str, Any]:
    tree = ast.parse(expression, mode="eval")
    result = _calc_eval(tree.body)
    if isinstance(result, float) and result.is_integer():
        result = int(result)
    return {"expression": expression, "result": result}


def _ensure_kokoro() -> Any:
    global _kokoro_pipeline
    if _kokoro_pipeline is None:
        from kokoro import KPipeline

        # Pass repo_id explicitly to suppress the "Defaulting repo_id..."
        # warning Kokoro emits on every fresh pipeline construction.
        _kokoro_pipeline = KPipeline(lang_code=KOKORO_LANG, repo_id="hexgrad/Kokoro-82M")
    return _kokoro_pipeline


def warm_kokoro() -> dict[str, Any]:
    """Pre-load Kokoro at process startup so the first user-facing speak()
    or speak_file() call doesn't pay the ~3-5 s weight-load tax."""
    started = time.perf_counter()
    try:
        pipe = _ensure_kokoro()
        # Iterate once to trigger any remaining lazy initialization inside
        # the pipeline. We don't actually play the audio.
        for _ in pipe(" ", voice=KOKORO_VOICE):
            break
    except Exception as exc:
        return {"warmed": False, "reason": str(exc)}
    return {"warmed": True, "seconds": round(time.perf_counter() - started, 3)}


# Minimal SSML-style markup supported by speak()/speak_file():
#   <speak>...</speak>            wrapper, stripped
#   <break time="200ms"/>          insert silence (ms or s units)
#   <breath/>                      short silent gap, mimics a breath
# Anything else falls through as plain text to Kokoro.
_SSML_SPEAK_TAG = re.compile(r"</?speak\s*>", re.IGNORECASE)
_SSML_TAG = re.compile(
    r'<break\s+time=["\'](\d+(?:\.\d+)?)\s*(ms|s)["\']\s*/?>|<breath\s*/?>',
    re.IGNORECASE,
)
_BREATH_GAP_MS = 220  # silent stand-in for a soft inhale


def _ssml_segments(text: str):
    """Yield ('text', str) | ('silence_ms', int) chunks. Pure parsing; no audio."""
    cleaned = _SSML_SPEAK_TAG.sub("", text)
    pos = 0
    for match in _SSML_TAG.finditer(cleaned):
        before = cleaned[pos:match.start()]
        if before.strip():
            yield ("text", before.strip())
        tag = match.group(0).lower()
        if tag.startswith("<break"):
            value = float(match.group(1))
            unit = match.group(2).lower()
            ms = int(value * 1000) if unit == "s" else int(value)
            yield ("silence_ms", ms)
        else:  # <breath/>
            yield ("silence_ms", _BREATH_GAP_MS)
        pos = match.end()
    tail = cleaned[pos:]
    if tail.strip():
        yield ("text", tail.strip())


def speak(text: str) -> dict[str, Any]:
    """Synthesize speech with Kokoro and play it through the default output.

    Supports minimal SSML: <speak>, <break time="Xms"/>, <breath/>. Plain text
    without tags takes the original fast path (single Kokoro call).
    """
    import numpy as np
    import sounddevice as sd

    cleaned = text.strip()
    if not cleaned:
        return {"spoken": False, "reason": "empty text"}

    pipe = _ensure_kokoro()
    started = time.perf_counter()
    chunks: list[Any] = []
    has_ssml = ("<break" in cleaned.lower()) or ("<breath" in cleaned.lower()) or ("<speak" in cleaned.lower())

    if has_ssml:
        for kind, value in _ssml_segments(cleaned):
            if kind == "text":
                for r in pipe(value, voice=KOKORO_VOICE):
                    if r.audio is not None:
                        chunks.append(np.asarray(r.audio, dtype=np.float32))
            else:  # silence_ms
                n = int(KOKORO_SAMPLE_RATE * value / 1000)
                if n > 0:
                    chunks.append(np.zeros(n, dtype=np.float32))
    else:
        for r in pipe(cleaned, voice=KOKORO_VOICE):
            if r.audio is not None:
                chunks.append(np.asarray(r.audio, dtype=np.float32))

    if not chunks:
        return {"spoken": False, "reason": "no audio generated"}

    audio = np.concatenate(chunks)
    device = _play_audio_with_live_device(sd, audio)
    if isinstance(device, dict):
        # Error info dict from playback failure
        return {**device, "text": cleaned}
    return {
        "spoken": True,
        "text": cleaned,                # include text so chat shows what was spoken
        "chars": len(cleaned),
        "seconds": round(time.perf_counter() - started, 3),
        "ssml": has_ssml,
        "device": device,
    }


def _play_audio_with_live_device(sd, audio):
    """Play `audio` through the *current* system default output device.

    sounddevice / PortAudio caches the default device at process startup.
    If the user switches macOS output (AirPods ↔ Speakers) mid-session, the
    cached device is stale and playback either goes to the disconnected
    device or fails with `PaErrorCode -9986`. We resolve the live default
    before each call and, on failure, reinitialize PortAudio so it picks up
    the new system state.

    Returns the device index on success, or an error-info dict on failure.
    """
    # 1. Try to look up the live default output device.
    device: int | None = None
    try:
        info = sd.query_devices(kind="output")
        if isinstance(info, dict) and "index" in info:
            device = int(info["index"])
    except Exception:
        device = None

    # 2. Attempt playback with that device.
    try:
        sd.play(audio, samplerate=KOKORO_SAMPLE_RATE, device=device)
        sd.wait()
        return device
    except Exception as first_exc:
        # 3. PortAudio's state may be stale — terminate + reinitialize and retry.
        try:
            sd._terminate()
            sd._initialize()
        except Exception:
            pass
        try:
            info = sd.query_devices(kind="output")
            device = int(info["index"]) if isinstance(info, dict) and "index" in info else None
        except Exception:
            device = None
        try:
            sd.play(audio, samplerate=KOKORO_SAMPLE_RATE, device=device)
            sd.wait()
            return device
        except Exception as second_exc:
            return {
                "spoken": False,
                "reason": f"playback failed after reinit: {second_exc}",
                "first_error": str(first_exc),
                "device": device,
            }


def speak_file(path: str) -> dict[str, Any]:
    """Read a workspace file and speak its contents through Kokoro."""
    target = workspace_path(path)
    if not target.exists() or not target.is_file():
        return {"spoken": False, "reason": "file not found", "path": path}
    text = target.read_text(encoding="utf-8")
    result = speak(text)
    result["from_file"] = str(target.relative_to(WORKSPACE))
    return result


def remember(key: str, value: str) -> dict[str, Any]:
    """Store a fact in unified memory shared across all agent processes."""
    from memory.memory_module import remember as _remember

    _remember(key, value)
    return {"remembered": True, "key": key, "value": value}


def recall(key: str) -> dict[str, Any]:
    """Retrieve a fact previously stored via remember()."""
    from memory.memory_module import recall as _recall

    value = _recall(key)
    if value is None:
        return {"found": False, "key": key}
    return {"found": True, "key": key, "value": value}


def forget(key: str, confirm: bool = False) -> dict[str, Any]:
    """Remove a stored fact. Returns whether it existed.

    Same approval-gate semantics as `delete_file`: when
    DESTRUCTIVE_OPS_REQUIRE_CONFIRM=1, the first call previews and the
    agent must call `ask_user` + then call again with `confirm=True`.
    """
    from memory.memory_module import forget as _forget, recall as _recall

    if _destructive_confirm_required() and not confirm:
        existing = _recall(key)
        if existing is None:
            return {"forgotten": False, "preview": True, "key": key, "reason": "no such key"}
        return {
            "forgotten": False,
            "preview": True,
            "key": key,
            "current_value": existing,
            "hint": "Ask the user to confirm, then call forget again with confirm=True.",
        }

    existed = _forget(key)
    return {"forgotten": existed, "key": key}


def list_facts() -> dict[str, Any]:
    """List every fact currently stored in unified memory."""
    from memory.memory_module import list_facts as _list_facts

    return {"facts": _list_facts()}


def launch_url(url: str) -> dict[str, Any]:
    """Open a URL in the default web browser (macOS `open`)."""
    import subprocess

    clean = url.strip()
    if not (clean.startswith("http://") or clean.startswith("https://")):
        return {"error": "URL must start with http:// or https://", "url": clean}
    if platform.system() != "Darwin":
        return {"error": f"launch_url only supported on macOS (got {platform.system()})", "url": clean}
    try:
        result = subprocess.run(["open", clean], capture_output=True, timeout=5)
        if result.returncode != 0:
            return {"error": result.stderr.decode("utf-8", errors="replace")[:200], "url": clean}
    except Exception as exc:
        return {"error": str(exc), "url": clean}
    return {"opened": True, "url": clean}


def open_file(path: str) -> dict[str, Any]:
    """Open a workspace file in its default macOS app."""
    import subprocess

    target = workspace_path(path)
    if not target.exists():
        return {"error": "file not found", "path": path}
    if platform.system() != "Darwin":
        return {"error": f"open_file only supported on macOS (got {platform.system()})", "path": str(target)}
    try:
        result = subprocess.run(["open", str(target)], capture_output=True, timeout=5)
        if result.returncode != 0:
            return {"error": result.stderr.decode("utf-8", errors="replace")[:200], "path": str(target)}
    except Exception as exc:
        return {"error": str(exc), "path": str(target)}
    return {"opened": True, "path": str(target.relative_to(WORKSPACE))}


def open_app(app_name: str) -> dict[str, Any]:
    """Launch a macOS application by name (e.g. 'Safari', 'Notes', 'Terminal')."""
    import subprocess

    clean = app_name.strip()
    if not clean:
        return {"error": "empty app name"}
    if platform.system() != "Darwin":
        return {"error": f"open_app only supported on macOS (got {platform.system()})", "app": clean}
    try:
        result = subprocess.run(["open", "-a", clean], capture_output=True, timeout=5)
        if result.returncode != 0:
            return {"error": result.stderr.decode("utf-8", errors="replace")[:200], "app": clean}
    except Exception as exc:
        return {"error": str(exc), "app": clean}
    return {"opened": True, "app": clean}


def get_weather(location: str) -> dict[str, Any]:
    """Look up current weather at a location via wttr.in (no API key)."""
    clean = location.strip()
    if not clean:
        return {"error": "empty location"}
    try:
        import certifi
        import requests
    except ImportError as exc:
        return {"error": f"requests/certifi missing: {exc}", "location": clean}
    fmt = "%C+%t+(feels+%f),+humidity+%h,+wind+%w"
    url = f"https://wttr.in/{clean}"
    try:
        response = requests.get(
            url,
            params={"format": fmt},
            headers={"User-Agent": "AgenticLLM/0.1 (curl)"},
            timeout=10,
            verify=certifi.where(),
        )
        text = response.text.strip()
    except Exception as exc:
        return {"error": str(exc), "location": clean}
    if not text or text.lower().startswith("unknown location") or "<html" in text.lower():
        return {"error": "unknown location", "location": clean}
    # wttr.in's format string uses literal '+' as space; collapse runs.
    pretty = re.sub(r"\s+", " ", text.replace("+", " ")).strip()
    return {"location": clean, "weather": pretty}


def web_search(query: str, max_results: int = 5) -> dict[str, Any]:
    """DuckDuckGo HTML search. No API key required."""
    try:
        from ddgs import DDGS  # newer package name
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return {"error": "duckduckgo-search not installed", "query": query}

    cleaned = query.strip()
    if not cleaned:
        return {"error": "empty query"}

    try:
        with DDGS() as ddgs:
            raw = list(ddgs.text(cleaned, max_results=max_results))
    except Exception as exc:
        return {"error": str(exc), "query": cleaned}

    results = [
        {
            "title": item.get("title"),
            "url": item.get("href") or item.get("url"),
            "snippet": item.get("body") or item.get("snippet"),
        }
        for item in raw
    ]
    return {"query": cleaned, "results": results}


# Image generation: lazily-loaded SDXL-Turbo pipeline. Apache-2.0 compatible
# upstream; ~6 GB weights downloaded on first call. Override via IMAGE_GEN_MODEL_ID.
_imagegen_state: dict[str, Any] = {"pipeline": None, "model_id": None}


def _ensure_imagegen_pipeline() -> tuple[Any, str]:
    model_id = os.environ.get("IMAGE_GEN_MODEL_ID", "stabilityai/sdxl-turbo")
    if _imagegen_state["pipeline"] is not None and _imagegen_state["model_id"] == model_id:
        return _imagegen_state["pipeline"], model_id

    try:
        from diffusers import AutoPipelineForText2Image
        import torch
    except ImportError as exc:
        raise RuntimeError(f"diffusers/torch missing — pip install diffusers accelerate ({exc})")

    started = time.perf_counter()
    device = "mps" if hasattr(torch.backends, "mps") and torch.backends.mps.is_available() else "cpu"
    dtype = torch.float16 if device != "cpu" else torch.float32
    pipe = AutoPipelineForText2Image.from_pretrained(
        model_id, torch_dtype=dtype, variant="fp16" if dtype == torch.float16 else None
    ).to(device)
    print(f"[image_gen] {model_id} loaded on {device} in {time.perf_counter() - started:.1f}s", flush=True)
    _imagegen_state["pipeline"] = pipe
    _imagegen_state["model_id"] = model_id
    return pipe, model_id


def generate_image(
    prompt: str,
    out_path: str = "generated.png",
    num_inference_steps: int = 1,
    guidance_scale: float = 0.0,
    seed: int | None = None,
) -> dict[str, Any]:
    """Generate an image from a text prompt and save to the workspace.

    Defaults to SDXL-Turbo (1-step inference, designed for speed on Apple
    Silicon). The first call downloads ~6 GB of weights from Hugging Face;
    subsequent calls are fast (~1–3 s per image on M-series).

    out_path is workspace-relative. Generation parameters default to the
    SDXL-Turbo author's recommendation (1 step, no CFG). Override seed for
    reproducibility.
    """
    clean_prompt = (prompt or "").strip()
    if not clean_prompt:
        return {"generated": False, "error": "empty prompt"}
    try:
        target = workspace_path(out_path)
    except Exception as exc:
        return {"generated": False, "error": str(exc)}

    try:
        pipe, model_id = _ensure_imagegen_pipeline()
    except Exception as exc:
        return {"generated": False, "error": str(exc)}

    try:
        import torch

        gen = torch.Generator(device=pipe.device).manual_seed(seed) if seed is not None else None
        started = time.perf_counter()
        result = pipe(
            prompt=clean_prompt,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale,
            generator=gen,
        )
        elapsed = time.perf_counter() - started
        image = result.images[0]
    except Exception as exc:
        return {"generated": False, "error": f"inference failed: {exc}"}

    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target)
    return {
        "generated": True,
        "path": str(target.relative_to(WORKSPACE)),
        "absolute_path": str(target),
        "model_id": model_id,
        "elapsed_s": round(elapsed, 3),
        "prompt": clean_prompt,
        "seed": seed,
    }


# Vision: lazily-loaded local VLM. Default is Moondream2 (~1.9 B params,
# Apache-2.0). Override via VISION_MODEL_ID env var. Loading is deferred
# until the first look_at() call so the bench / cold-path stays clean.
_vision_state: dict[str, Any] = {"model": None, "tokenizer": None, "model_id": None}


def _ensure_vision_model() -> tuple[Any, Any, str]:
    model_id = os.environ.get("VISION_MODEL_ID", "vikhyatk/moondream2")
    if _vision_state["model"] is not None and _vision_state["model_id"] == model_id:
        return _vision_state["model"], _vision_state["tokenizer"], model_id

    from transformers import AutoModelForCausalLM, AutoTokenizer
    import torch

    started = time.perf_counter()
    tok = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
    # Pin the VLM to CPU. Moondream is small (~1.9 B); a few seconds on
    # CPU beats the Metal-context fight that corrupts llama-cpp's KV
    # cache when both pytorch and llama.cpp claim Metal at the same time.
    device = "cpu"
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        trust_remote_code=True,
        torch_dtype=torch.float32,
    ).to(device).eval()
    print(f"[vision] {model_id} loaded on {device} in {time.perf_counter() - started:.1f}s", flush=True)
    _vision_state["model"] = model
    _vision_state["tokenizer"] = tok
    _vision_state["model_id"] = model_id
    return model, tok, model_id


def look_at(image_path: str, question: str = "Describe this image in one short sentence.") -> dict[str, Any]:
    """Look at a local image file and answer a question about it.

    Defaults to a single-sentence description if `question` is omitted.
    The image path is workspace-relative; absolute paths are rejected so
    the robot can't read arbitrary files on the host.

    Uses Moondream2 by default (small Apache-2.0 VLM, ~1.9 B params).
    Set VISION_MODEL_ID to switch backbones; first call lazy-loads.
    """
    clean_path = (image_path or "").strip()
    if not clean_path:
        return {"saw": False, "error": "empty image path"}
    try:
        target = workspace_path(clean_path)
    except Exception as exc:
        return {"saw": False, "error": str(exc)}
    if not target.exists():
        return {"saw": False, "error": "image not found", "path": clean_path}

    try:
        from PIL import Image
    except Exception as exc:
        return {"saw": False, "error": f"Pillow missing: {exc}"}

    try:
        model, tok, model_id = _ensure_vision_model()
    except Exception as exc:
        return {"saw": False, "error": f"vision model load failed: {exc}"}

    try:
        img = Image.open(target).convert("RGB")
    except Exception as exc:
        return {"saw": False, "error": f"could not open image: {exc}"}

    q = (question or "Describe this image in one short sentence.").strip()
    started = time.perf_counter()
    try:
        # Moondream2's preferred API: encode_image + answer_question
        if hasattr(model, "encode_image") and hasattr(model, "answer_question"):
            enc = model.encode_image(img)
            answer = model.answer_question(enc, q, tok)
        else:
            # Generic transformers fallback for other VLMs
            inputs = tok(q, return_tensors="pt").to(model.device)
            out = model.generate(**inputs, max_new_tokens=128)
            answer = tok.decode(out[0], skip_special_tokens=True)
    except Exception as exc:
        return {"saw": False, "error": f"inference failed: {exc}"}
    elapsed = time.perf_counter() - started

    return {
        "saw": True,
        "answer": str(answer).strip(),
        "model_id": model_id,
        "elapsed_s": round(elapsed, 3),
        "path": clean_path,
    }


def run_python(code: str, timeout_s: float = 10.0) -> dict[str, Any]:
    """Execute Python code in a fresh, isolated subprocess.

    Sandboxing rules — all enforced by the subprocess boundary, not the
    snippet:
      - Fresh `python` with no inherited site-packages of ours (uses the
        venv's python so common libs are available but no `tools` /
        `python_pydantic_ai` modules leak in).
      - cwd is a fresh tempdir, not the workspace — the snippet cannot
        accidentally clobber the agent's files.
      - 10s timeout by default (the model may pass `timeout_s`).
      - Hard size cap on captured stdout/stderr (200 KB each) so a runaway
        loop can't blow up our log file.

    Returns: {ok, stdout, stderr, exit_code, elapsed_s, timed_out}.
    """
    import subprocess
    import sys
    import tempfile

    cleaned = (code or "").strip()
    if not cleaned:
        return {"ok": False, "error": "empty code"}

    MAX_CAP = 200_000  # bytes per stream

    started = time.perf_counter()
    timed_out = False
    with tempfile.TemporaryDirectory(prefix="agent_run_python_") as scratch:
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "-c", cleaned],
                capture_output=True,
                text=True,
                timeout=timeout_s,
                cwd=scratch,
                env={"PATH": os.environ.get("PATH", ""), "HOME": scratch},
            )
            exit_code = proc.returncode
            stdout = proc.stdout
            stderr = proc.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            exit_code = -1
            stdout = (exc.stdout or b"").decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = (exc.stderr or b"").decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
    elapsed = time.perf_counter() - started

    truncated_stdout = stdout[:MAX_CAP]
    truncated_stderr = stderr[:MAX_CAP]
    return {
        "ok": exit_code == 0 and not timed_out,
        "exit_code": exit_code,
        "stdout": truncated_stdout,
        "stderr": truncated_stderr,
        "stdout_truncated": len(stdout) > MAX_CAP,
        "stderr_truncated": len(stderr) > MAX_CAP,
        "elapsed_s": round(elapsed, 3),
        "timed_out": timed_out,
    }


def send_message(channel: str, recipient: str, text: str) -> dict[str, Any]:
    """Send a proactive message to a user on a registered channel.

    `channel` is one of the bridges started by `messaging.gateway`:
    "discord", "telegram", "imessage".
    `recipient` is the channel-specific ID:
      - discord:  numeric user ID or channel ID (as a string)
      - telegram: numeric chat ID (as a string)
      - imessage: phone number ("+15551234567") or Apple ID email
    `text` is the message body.

    Use this for cron jobs ("every morning send weather to Discord") or
    mid-conversation routing ("text the user the result on iMessage").
    Returns {sent, ...} on success or {sent: False, error: "..."}.
    """
    channel = (channel or "").strip().lower()
    recipient = (recipient or "").strip()
    text = (text or "").strip()
    if not channel or not recipient or not text:
        return {"sent": False, "error": "channel, recipient, and text are all required"}

    try:
        from messaging import get_bridge, list_bridges
    except Exception as exc:
        return {"sent": False, "error": f"messaging module not importable: {exc}"}

    bridge = get_bridge(channel)
    if bridge is None:
        return {
            "sent": False,
            "error": f"no bridge registered for {channel!r}; live bridges: {list_bridges()}",
        }
    try:
        return bridge.send(recipient, text)
    except Exception as exc:
        return {"sent": False, "error": f"bridge.send failed: {type(exc).__name__}: {exc}"}


def schedule_prompt(cron_expr: str, prompt: str, name: str | None = None) -> dict[str, Any]:
    """Schedule a prompt to run unattended on a cron expression.

    `cron_expr` is standard 5-field cron — e.g. "0 7 * * *" for 7 AM daily,
    "*/10 * * * *" for every 10 minutes. The named schedule fires by
    invoking the same agent loop a fresh user turn would; tool results,
    memory updates, and TTS all behave the same. Use `list_schedules` /
    `cancel_schedule` to inspect and remove entries.
    """
    from memory.memory_module import add_schedule

    try:
        row = add_schedule(cron_expr=cron_expr, prompt=prompt, name=name)
    except Exception as exc:
        return {"scheduled": False, "error": str(exc)}
    return {"scheduled": True, **row}


def list_schedules() -> dict[str, Any]:
    """List every active scheduled prompt with its next-run timestamp."""
    from memory.memory_module import list_schedules as _ls

    rows = _ls()
    return {"count": len(rows), "schedules": rows}


def cancel_schedule(name: str) -> dict[str, Any]:
    """Remove a previously-scheduled prompt by name."""
    from memory.memory_module import cancel_schedule as _cs

    ok = _cs(name)
    return {"cancelled": ok, "name": name}


def search_memory(query: str, k: int = 5) -> dict[str, Any]:
    """Semantic search over our cross-session episodic log.

    Use this when the user asks about something past — "what did we talk
    about yesterday?", "did I tell you about my dog?", "what's that thing
    we were doing with the printer?" — and `recall` (exact-key) misses.

    Returns the top-k most relevant past turns with cosine scores.
    """
    from memory.memory_module import search_memory as _search

    clean = (query or "").strip()
    if not clean:
        return {"found": 0, "results": []}
    hits = _search(clean, k=k)
    return {"found": len(hits), "query": clean, "results": hits}


def ask_user(question: str) -> dict[str, Any]:
    """Ask the user a clarifying question instead of guessing.

    The agent should call this whenever it's about to guess at the user's
    intent — ambiguous pronouns, missing destination, "the file" with no
    name, "open it" with no antecedent. The voice loop will speak the
    question; the next phrase from the mic becomes the user's answer.
    Returns a marker so the harness knows this turn ended on a question
    rather than a normal answer.
    """
    clean = (question or "").strip()
    if not clean:
        return {"asked": False, "error": "empty question"}
    return {"asked": True, "question": clean}


def system_status() -> dict[str, Any]:
    total, used, free = shutil.disk_usage(WORKSPACE)
    load_avg = os.getloadavg() if hasattr(os, "getloadavg") else None
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "load_average": load_avg,
        "workspace": str(WORKSPACE),
        "disk": {
            "total_gb": round(total / 1024**3, 2),
            "used_gb": round(used / 1024**3, 2),
            "free_gb": round(free / 1024**3, 2),
        },
    }
