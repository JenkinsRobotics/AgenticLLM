"""Time, math, and machine-state skills.

  • get_time(timezone)
  • calculate(expression)
  • system_status()

All three are skip-final candidates — the dict result IS the answer the
user wants, no LLM rewrite needed.
"""

from __future__ import annotations

import ast
import datetime as dt
import operator as op
import os
import platform
import shutil
from typing import Any

from ._common import WORKSPACE


# ---------------------------------------------------------------------------
# get_time
# ---------------------------------------------------------------------------
def get_time(timezone: str | None = None) -> dict[str, Any]:
    """Current local date/time, or in a specific IANA timezone if provided.

    Examples: timezone="Asia/Shanghai", "America/New_York", "Europe/London".
    """
    if timezone:
        try:
            from zoneinfo import ZoneInfo

            now = dt.datetime.now(ZoneInfo(timezone))
        except Exception as exc:
            return {"error": f"unknown timezone: {timezone!r} ({exc})"}
    else:
        now = dt.datetime.now().astimezone()
    return {
        "datetime": now.strftime("%Y-%m-%d %I:%M:%S %p %Z"),
        "iso": now.isoformat(timespec="seconds"),
        "timezone": str(now.tzinfo),
    }


# ---------------------------------------------------------------------------
# calculate — safe AST eval (no arbitrary code)
# ---------------------------------------------------------------------------
_CALC_OPS: dict[type, Any] = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.Pow: op.pow,
    ast.Mod: op.mod,
    ast.FloorDiv: op.floordiv,
    ast.USub: op.neg,
    ast.UAdd: op.pos,
}


def _calc_eval(node: Any) -> Any:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _CALC_OPS:
        return _CALC_OPS[type(node.op)](_calc_eval(node.left), _calc_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _CALC_OPS:
        return _CALC_OPS[type(node.op)](_calc_eval(node.operand))
    raise ValueError(f"unsupported expression: {ast.dump(node)}")


def calculate(expression: str) -> dict[str, Any]:
    """Evaluate a safe arithmetic expression (+ - * / ** % //)."""
    tree = ast.parse(expression, mode="eval")
    result = _calc_eval(tree.body)
    if isinstance(result, float) and result.is_integer():
        result = int(result)
    return {"expression": expression, "result": result}


# ---------------------------------------------------------------------------
# system_status
# ---------------------------------------------------------------------------
def system_status() -> dict[str, Any]:
    total, used, free = shutil.disk_usage(WORKSPACE)
    load_avg = os.getloadavg() if hasattr(os, "getloadavg") else None
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "load_average": load_avg,
        "workspace": str(WORKSPACE),
        "disk": {
            "total_gb": round(total / 1024**3, 2),
            "used_gb": round(used / 1024**3, 2),
            "free_gb": round(free / 1024**3, 2),
        },
    }
