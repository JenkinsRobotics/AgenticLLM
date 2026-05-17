#!/usr/bin/env python3
"""Dispatcher entry point.

Usage:
  python main.py python_custom_json [args...]   # our JSON + GBNF framework
  python main.py python_hermes_xml [args...]    # our Nous-XML-format framework
  python main.py [args...]                       # defaults to python_custom_json

When we add the real upstream libraries, the dispatch table grows:
  python main.py pygentic [args...]      # the real ruvnet/pygentic
  python main.py hermes_agent [args...]  # the real nousresearch/hermes-agent

All trailing args are passed through to the agent's own argparse.
"""

from __future__ import annotations

import sys


FRAMEWORKS = {
    "python_custom_json",
    "python_hermes_xml",
    "python_pydantic_ai",
    "python_jaeger",
}


def main() -> int:
    argv = sys.argv[1:]
    framework = "python_custom_json"
    if argv and argv[0] in FRAMEWORKS:
        framework = argv[0]
        argv = argv[1:]

    sys.argv = [f"{framework}/main.py", *argv]

    if framework == "python_hermes_xml":
        from python_hermes_xml.main import main as agent_main
    elif framework == "python_pydantic_ai":
        from python_pydantic_ai.main import main as agent_main
    elif framework == "python_jaeger":
        from python_jaeger.main import main as agent_main
    else:
        from python_custom_json.main import main as agent_main
    return agent_main()


if __name__ == "__main__":
    raise SystemExit(main())
