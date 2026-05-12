"""LLM clients for local llama.cpp testing."""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


DEFAULT_MODEL_PATH = Path(
    "/Users/jonathanjenkins/.lmstudio/models/lmstudio-community/"
    "gemma-4-26B-A4B-it-GGUF/gemma-4-26B-A4B-it-Q4_K_M.gguf"
)


@dataclass
class LLMResult:
    text: str
    latency_s: float
    ttft_s: float = 0.0


class LlamaCppPythonClient:
    def __init__(
        self,
        model_path: Path = DEFAULT_MODEL_PATH,
        ctx: int = 8192,
        gpu_layers: int = -1,
        batch: int = 512,
        ubatch: int = 512,
        flash_attn: bool = True,
        swa_full: bool = False,
        threads: int | None = None,
        warmup: bool = True,
    ) -> None:
        from llama_cpp import Llama

        path = model_path.expanduser()
        if not path.exists():
            raise FileNotFoundError(f"Model file not found: {path}")

        kwargs: dict[str, Any] = {
            "model_path": str(path),
            "n_ctx": ctx,
            "n_gpu_layers": gpu_layers,
            "n_batch": batch,
            "n_ubatch": ubatch,
            "flash_attn": flash_attn,
            "swa_full": swa_full,
            "verbose": False,
        }
        if threads is not None:
            kwargs["n_threads"] = threads

        print(f"[llama.cpp] Loading {path.name}...", flush=True)
        started = time.perf_counter()
        self.llm = Llama(**kwargs)
        self._grammar_cache: dict[str, Any] = {}
        print(f"[llama.cpp] Loaded in {time.perf_counter() - started:.1f}s.", flush=True)

        if warmup:
            print("[llama.cpp] Warming up...", flush=True)
            started = time.perf_counter()
            self.llm.create_chat_completion(
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=1,
                temperature=0.0,
            )
            print(f"[llama.cpp] Warm-up done in {time.perf_counter() - started:.1f}s.\n", flush=True)

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        temperature: float = 0.0,
        top_p: float = 0.8,
        stream: bool = True,
        grammar: str | None = None,
    ) -> LLMResult:
        kwargs: dict[str, Any] = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "stream": stream,
        }
        if grammar:
            compiled = self._compile_grammar(grammar)
            if compiled is not None:
                kwargs["grammar"] = compiled

        started = time.perf_counter()
        completion = self.llm.create_chat_completion(**kwargs)
        if stream:
            text, ttft = self._collect_stream(completion, started)
        else:
            text = completion["choices"][0]["message"]["content"]
            ttft = time.perf_counter() - started
        elapsed = time.perf_counter() - started
        return LLMResult(text=text.strip(), latency_s=elapsed, ttft_s=ttft)

    def _compile_grammar(self, grammar: str) -> Any:
        cached = self._grammar_cache.get(grammar)
        if cached is not None:
            return cached
        try:
            from llama_cpp import LlamaGrammar

            compiled = LlamaGrammar.from_string(grammar, verbose=False)
        except Exception as exc:
            print(f"[grammar] disabled: {exc}", file=sys.stderr)
            self._grammar_cache[grammar] = None
            return None
        self._grammar_cache[grammar] = compiled
        return compiled

    @staticmethod
    def _collect_stream(chunks, started: float) -> tuple[str, float]:
        parts: list[str] = []
        ttft = 0.0
        for chunk in chunks:
            text = chunk["choices"][0].get("delta", {}).get("content", "")
            if text:
                if ttft == 0.0:
                    ttft = time.perf_counter() - started
                parts.append(text)
        return "".join(parts), ttft

    def health_check(self) -> bool:
        return True


class LlamaCppServerClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080",
        model: str = "local",
        timeout_s: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        temperature: float = 0.0,
        top_p: float = 0.8,
        stream: bool = True,
        grammar: str | None = None,
    ) -> LLMResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        if grammar:
            # llama.cpp server extension; ignored by stricter OpenAI-only backends.
            payload["grammar"] = grammar

        started = time.perf_counter()
        if stream:
            text, ttft = self._stream_chat(payload, started)
        else:
            text = self._blocking_chat(payload)
            ttft = time.perf_counter() - started
        elapsed = time.perf_counter() - started
        return LLMResult(text=text.strip(), latency_s=elapsed, ttft_s=ttft)

    def _blocking_chat(self, payload: dict[str, Any]) -> str:
        response = requests.post(
            f"{self.base_url}/v1/chat/completions",
            json=payload,
            timeout=self.timeout_s,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    def _stream_chat(self, payload: dict[str, Any], started: float) -> tuple[str, float]:
        chunks: list[str] = []
        ttft = 0.0
        with requests.post(
            f"{self.base_url}/v1/chat/completions",
            json=payload,
            timeout=self.timeout_s,
            stream=True,
        ) as response:
            response.raise_for_status()
            for raw_line in response.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                line = raw_line.strip()
                if line.startswith("data: "):
                    line = line[6:]
                if line == "[DONE]":
                    break
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                delta = data.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content")
                if content:
                    if ttft == 0.0:
                        ttft = time.perf_counter() - started
                    chunks.append(content)
        return "".join(chunks), ttft

    def health_check(self) -> bool:
        try:
            response = requests.get(f"{self.base_url}/health", timeout=3)
            if response.ok:
                return True
        except requests.RequestException:
            pass

        try:
            response = requests.get(f"{self.base_url}/v1/models", timeout=3)
            return response.ok
        except requests.RequestException:
            return False
