"""Prints whatever GET /api/solve-status reports on the running backend --
the implementation behind `make solve-status`. A separate script rather
than an inline Makefile recipe, since anything past "call one HTTP endpoint
and format the reply" gets unreadable fast as shell-escaped Python inside a
Make recipe line.

Usage: uv run python scripts/solve_status.py
"""
from __future__ import annotations

import requests

URL = "http://127.0.0.1:8000/api/solve-status"


def main() -> int:
    try:
        resp = requests.get(URL, timeout=5)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"Backend isn't reachable at {URL} -- is it running? ('make status' / 'make start')")
        print(f"  ({exc})")
        return 1

    entries = resp.json()["in_progress"]
    if not entries:
        print("No solve currently running.")
        return 0

    for e in entries:
        print(
            f"{e['kind']}: base={e['base_name']!r} objective={e['objective']} "
            f"n_trials={e['n_trials']} running for {e['running_for_seconds']:.1f}s"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
