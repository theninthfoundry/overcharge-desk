"""Shared helpers for the Overcharge Desk tools. Standard library only (Python 3.9+)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

CENT = Decimal("0.01")
CASE_ID_RE = re.compile(r"^OC-(\d{8})-(\d{2})$")


class ToolError(Exception):
    """A problem the caller must see. `code` becomes the process exit code."""

    def __init__(self, message: str, code: int = 2):
        super().__init__(message)
        self.code = code


def load_json(path):
    try:
        with Path(path).open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise ToolError(f"File not found: {path}")
    except json.JSONDecodeError as exc:
        raise ToolError(f"Invalid JSON in {path}: {exc}")


def write_json_atomic(path, data) -> None:
    """Write JSON so a crash can never leave a half-written file."""
    p = Path(path)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=f".{p.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, p)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def to_decimal(value, what: str = "value") -> Decimal:
    """Exact decimal from a JSON number or numeric string. Never uses float math."""
    if value is None or isinstance(value, bool):
        raise ToolError(f"{what} is missing or not a number")
    try:
        d = Decimal(str(value).strip())
    except InvalidOperation:
        raise ToolError(f"{what} is not a number: {value!r}")
    if not d.is_finite():
        raise ToolError(f"{what} is not a finite number: {value!r}")
    return d


def q2(d: Decimal) -> Decimal:
    return d.quantize(CENT, rounding=ROUND_HALF_UP)


def money_str(d: Decimal) -> str:
    return format(q2(d), "f")


def exact_str(d: Decimal) -> str:
    """Show a price without rounding it, but always with at least 2 decimals."""
    s = format(d.normalize(), "f")
    if "." not in s:
        return s + ".00"
    if len(s.split(".")[1]) == 1:
        return s + "0"
    return s


def num_str(d: Decimal) -> str:
    return format(d.normalize(), "f")


def parse_date(value, what: str = "date") -> date:
    if not value:
        raise ToolError(f"{what} is missing")
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ToolError(f"{what} is not an ISO date (YYYY-MM-DD): {value!r}")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def norm(text) -> str:
    return " ".join(str(text).casefold().split())


def sha256_file(path) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
    except FileNotFoundError:
        raise ToolError(f"File not found: {path}")
    return h.hexdigest()


def emit(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def run_cli(fn) -> None:
    """Run a CLI main(). Errors print as JSON on stdout and text on stderr."""
    try:
        code = fn()
    except ToolError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(exc.code)
    sys.exit(code or 0)

# Custom error boundary for CLI execution

# Atomic write ensures zero half-written state

# Precision constant for currency rounding

# Safe JSON deserialization with path context

# Case ID schema validation rules

# Strict UTF-8 file encoding across IO operations
