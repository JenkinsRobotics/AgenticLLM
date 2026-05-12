#!/usr/bin/env python3
"""Dispatcher entry point.

Usage:
  python main.py pygentic [args...]     # run the Pygentic agent
  python main.py hermes [args...]       # run the Hermes agent
  python main.py [args...]              # defaults to pygentic

All trailing args are passed through to the agent's own argparse (so e.g.
`python main.py hermes --self-test` works).
"""

from __future__ import annotations

import sys


FRAMEWORKS = {"pygentic", "hermes"}


def main() -> int:
    argv = sys.argv[1:]
    framework = "pygentic"
    if argv and argv[0] in FRAMEWORKS:
        framework = argv[0]
        argv = argv[1:]

    sys.argv = [f"{framework}/main.py", *argv]

    if framework == "hermes":
        from hermes.main import main as agent_main
    else:
        from pygentic.main import main as agent_main
    return agent_main()


if __name__ == "__main__":
    raise SystemExit(main())
