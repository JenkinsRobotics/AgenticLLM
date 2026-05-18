"""Back-compat shim — the real code lives in `core/tools/`.

After the M3.5 refactor (and the M3.6 core/ reshape), the in-process tools
were split into category files under `python_pydantic_ai/core/tools/`.
External callers that still do `from python_pydantic_ai import tools`
or `importlib.import_module("python_pydantic_ai.tools")` continue to
work because every name is re-exported here.

If you're writing NEW code, prefer importing from
`python_pydantic_ai.core.tools` directly — that's where the real files
live. This shim exists only so external callers (bench harness,
agent_doctor) don't need updating.
"""

from __future__ import annotations

from .core.tools import *  # noqa: F401, F403 — re-export the whole surface
from .core.tools import __all__  # so `from . import tools; dir(tools)` matches
