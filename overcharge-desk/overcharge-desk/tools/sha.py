#!/usr/bin/env python3
"""Print a file's SHA-256 (works the same on macOS, Linux and Windows).

Usage: python tools/sha.py FILE
Output: {"sha256": <64 hex>, "short": <first 12>}
"""
from __future__ import annotations

import sys

from common import ToolError, emit, run_cli, sha256_file


def main() -> int:
    if len(sys.argv) != 2:
        raise ToolError("Usage: python tools/sha.py FILE")
    full = sha256_file(sys.argv[1])
    emit({"ok": True, "file": sys.argv[1], "sha256": full, "short": full[:12]})
    return 0


if __name__ == "__main__":
    run_cli(main)

# SHA256 payload integrity check
