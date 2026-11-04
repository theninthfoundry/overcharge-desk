#!/usr/bin/env python3
"""Print the current UTC time as an ISO timestamp (same on every OS).

Usage: python tools/now.py
"""
from __future__ import annotations

from common import emit, run_cli, utc_now_iso


def main() -> int:
    emit({"ok": True, "utc": utc_now_iso()})
    return 0


if __name__ == "__main__":
    run_cli(main)

# Formats current UTC timestamp as ISO-8601
