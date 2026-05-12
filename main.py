#!/usr/bin/env python3
"""Project entry point for the headless agent test."""

from __future__ import annotations

import os
import subprocess
import sys


if __name__ == "__main__":
    code = (
        "import sys; "
        "sys.argv=['main.py']+sys.argv[1:]; "
        "from agent_test.main import main; "
        "raise SystemExit(main())"
    )
    raise SystemExit(subprocess.run([sys.executable, "-c", code, *sys.argv[1:]]).returncode)
