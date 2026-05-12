"""LLM clients for local llama.cpp testing."""

from __future__ import annotations

import json
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


class LlamaCppPythonClient:
    def __init__(
        self,
        model_path: Path = DEFAULT_MODEL_PATH,
        ctx: int = 8192,
        gpu_layers: int = -1,
        batch: int = 128,
        ubatch: int = 128,
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
    ) -> LLMResult:
        started = time.perf_counter()
        completion = self.llm.create_chat_completion(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            stream=stream,
        )
        if stream:
            text = self._collect_stream(completion)
        else:
            text = completion["choices"][0]["message"]["content"]
        return LLMResult(text=text.strip(), latency_s=time.perf_counter() - started)

    @staticmethod
    def _collect_stream(chunks) -> str:
        parts: list[str] = []
        for chunk in chunks:
            text = chunk["choices"][0].get("delta", {}).get("content", "")
            if text:
                parts.append(text)
        return "".join(parts)

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
    ) -> LLMResult:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        started = time.perf_counter()
        if stream:
            text = self._stream_chat(payload)
        else:
            text = self._blocking_chat(payload)
        return LLMResult(text=text.strip(), latency_s=time.perf_counter() - started)

    def _blocking_chat(self, payload: dict[str, Any]) -> str:
        response = requests.post(
            f"{self.base_url}/v1/chat/completions",
            json=payload,
            timeout=self.timeout_s,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    def _stream_chat(self, payload: dict[str, Any]) -> str:
        chunks: list[str] = []
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
                    chunks.append(content)
        return "".join(chunks)

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
