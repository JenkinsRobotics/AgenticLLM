#!/usr/bin/env python3
"""CLI chat using llama-cpp-python (Metal-accelerated GGUF inference).

Loads the model and runs a 1-token warm-up before the first prompt so the
first user message doesn't pay Metal-kernel-compilation tax.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path


DEFAULT_MODEL = Path(
    "/Users/jonathanjenkins/.lmstudio/models/lmstudio-community/"
    "gemma-4-26B-A4B-it-GGUF/gemma-4-26B-A4B-it-Q4_K_M.gguf"
)
DEFAULT_SYSTEM_PROMPT = "You are a helpful, concise assistant."
EXIT_COMMANDS = {"/exit", "/quit", "exit", "quit", "q"}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Chat with a GGUF model via llama-cpp-python.")
    p.add_argument("-m", "--model-path", default=str(DEFAULT_MODEL))
    p.add_argument("--system", default=DEFAULT_SYSTEM_PROMPT)
    p.add_argument("--ctx", type=int, default=8192)
    p.add_argument("--gpu-layers", type=int, default=-1, help="-1 = all layers on GPU.")
    p.add_argument("--threads", type=int, default=None)
    p.add_argument("--max-tokens", type=int, default=512)
    p.add_argument("--temperature", type=float, default=0.7)
    p.add_argument("--top-p", type=float, default=0.95)
    p.add_argument("--no-stream", action="store_true")
    return p


def load_model(args: argparse.Namespace):
    from llama_cpp import Llama

    path = Path(args.model_path).expanduser()
    if not path.exists():
        raise SystemExit(f"Model file not found: {path}")

    kwargs = {
        "model_path": str(path),
        "n_ctx": args.ctx,
        "n_gpu_layers": args.gpu_layers,
        "verbose": False,
    }
    if args.threads is not None:
        kwargs["n_threads"] = args.threads

    print(f"[llama.cpp] Loading {path.name}...", flush=True)
    t0 = time.perf_counter()
    llm = Llama(**kwargs)
    print(f"[llama.cpp] Loaded in {time.perf_counter() - t0:.1f}s. Warming up...", flush=True)

    t0 = time.perf_counter()
    llm.create_chat_completion(
        messages=[{"role": "user", "content": "hi"}], max_tokens=1, temperature=0.0
    )
    print(f"[llama.cpp] Warm-up done in {time.perf_counter() - t0:.1f}s. Ready.\n", flush=True)
    return llm


def stream_print(chunks) -> str:
    parts: list[str] = []
    for chunk in chunks:
        text = chunk["choices"][0].get("delta", {}).get("content", "")
        if text:
            print(text, end="", flush=True)
            parts.append(text)
    print()
    return "".join(parts).strip()


def run_chat(args: argparse.Namespace) -> int:
    llm = load_model(args)
    messages = [{"role": "system", "content": args.system}]
    print("Type /exit to quit, /reset to clear history.")

    while True:
        try:
            user_text = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            return 0

        if not user_text:
            continue
        if user_text.lower() in EXIT_COMMANDS:
            print("Goodbye.")
            return 0
        if user_text.lower() == "/reset":
            messages = [{"role": "system", "content": args.system}]
            print("History cleared.")
            continue

        messages.append({"role": "user", "content": user_text})

        try:
            print("Assistant: ", end="", flush=True)
            completion = llm.create_chat_completion(
                messages=messages,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
                top_p=args.top_p,
                stream=not args.no_stream,
            )
            if args.no_stream:
                reply = completion["choices"][0]["message"]["content"].strip()
                print(reply)
            else:
                reply = stream_print(completion)
        except Exception as exc:
            messages.pop()
            print(f"\nGeneration failed: {exc}", file=sys.stderr)
            return 1

        messages.append({"role": "assistant", "content": reply})


def main() -> int:
    return run_chat(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
