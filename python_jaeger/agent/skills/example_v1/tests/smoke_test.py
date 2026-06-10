"""Smoke test for hello_v1.

Runs as a subprocess from the skill loader before registration. Must:
  - exit 0 if the skill is healthy
  - exit non-zero (and print to stderr) if anything is broken

Keep smoke tests fast (under a few seconds) — they run at every startup.
"""

import importlib.util
import sys
from pathlib import Path


def main() -> int:
    spec = importlib.util.spec_from_file_location("hello", Path(__file__).resolve().parent.parent / "hello.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    out = mod.say_hello("jaeger")
    assert out == {"greeting": "Hello, jaeger!", "skill": "hello_v1"}, out
    out2 = mod.say_hello()  # default arg
    assert out2["greeting"] == "Hello, world!", out2
    print("hello_v1 smoke OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
