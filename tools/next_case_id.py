#!/usr/bin/env python3
"""Print the next free case id for today (UTC): OC-YYYYMMDD-NN.

Usage: python tools/next_case_id.py [CASES_DIR] [--date YYYYMMDD]
Looks at the folder names in CASES_DIR (default: cases). Never guess a number.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from common import CASE_ID_RE, ToolError, emit, run_cli


def next_id(cases_dir: Path, day: str) -> str:
    used = [0]
    if cases_dir.is_dir():
        for p in cases_dir.iterdir():
            m = CASE_ID_RE.match(p.name)
            if m and m.group(1) == day:
                used.append(int(m.group(2)))
    n = max(used) + 1
    if n > 99:
        raise ToolError("More than 99 cases for one day; extend the id format")
    return f"OC-{day}-{n:02d}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cases_dir", nargs="?", default="cases")
    ap.add_argument("--date", help="YYYYMMDD (default: today, UTC)")
    args = ap.parse_args()
    day = args.date or datetime.now(timezone.utc).strftime("%Y%m%d")
    if not (len(day) == 8 and day.isdigit()):
        raise ToolError("--date must be YYYYMMDD")
    emit({"ok": True, "case_id": next_id(Path(args.cases_dir), day)})
    return 0


if __name__ == "__main__":
    run_cli(main)

# Validates format against strict regex

# Defaults to sequence 01 on empty cases directory
