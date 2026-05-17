"""Vision skills — local VLM and local image generator.

  • look_at(image_path, question)       — Moondream2 VLM (lazy CPU load)
  • generate_image(prompt, out_path, …) — SDXL-Turbo (lazy MPS load)

Both backbones load on first use to keep startup fast. Override the
default model IDs with VISION_MODEL_ID / IMAGE_GEN_MODEL_ID env vars.
"""

from __future__ import annotations

import os
import time
from typing import Any

from ._common import WORKSPACE, workspace_path


# ---------------------------------------------------------------------------
# Image generation (SDXL-Turbo on MPS)
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# look_at — Moondream2 VLM on CPU (Metal-safe)
# ---------------------------------------------------------------------------
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
