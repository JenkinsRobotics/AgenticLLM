"""Package entry point — lets you run jaeger as `python -m python_jaeger`.

Equivalent to `python -m python_jaeger.main`. Delegates to `main.main()`
which routes to either CLI chat (default) or the voice loop daemon
(when `--voice` is passed). See `python -m python_jaeger --help` and
`python -m python_jaeger --voice --help`.
"""

from __future__ import annotations

from .main import main


if __name__ == "__main__":
    raise SystemExit(main())
