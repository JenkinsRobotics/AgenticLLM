"""Package entry point — lets you run pydantic_ai as `python -m python_pydantic_ai`.

Equivalent to `python -m python_pydantic_ai.main`. Delegates to `main.main()`
which routes to either CLI chat (default) or the voice loop daemon
(when `--voice` is passed). See `python -m python_pydantic_ai --help` and
`python -m python_pydantic_ai --voice --help`.
"""

from __future__ import annotations

from .main import main


if __name__ == "__main__":
    raise SystemExit(main())
