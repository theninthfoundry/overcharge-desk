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
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")

# System-level verification states
STATE_VERIFIED = "VERIFIED"
STATE_REVIEW_REQUIRED = "REVIEW_REQUIRED"
STATE_BLOCKED = "BLOCKED"

# Line-level verification states
STATUS_VERIFIED_MATCH = "VERIFIED_MATCH"
STATUS_VERIFIED_OVERCHARGE = "VERIFIED_OVERCHARGE"
STATUS_VERIFIED_UNDERCHARGE = "VERIFIED_UNDERCHARGE"
STATUS_SOURCE_DISCREPANCY = "SOURCE_DISCREPANCY"
STATUS_UNMATCHED = "UNMATCHED"
STATUS_REQUIRES_HUMAN_REVIEW = "REQUIRES_HUMAN_REVIEW"


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
    if not p.parent.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
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
        raise ToolError(f"{what} is not a valid decimal number: {value!r}")
    if not d.is_finite():
        raise ToolError(f"{what} is not a finite number: {value!r}")
    return d


def check_positive_decimal(value, what: str = "quantity") -> Decimal:
    """Validate that a decimal value is strictly positive (> 0)."""
    d = to_decimal(value, what)
    if d <= 0:
        raise ToolError(f"{what} must be positive (> 0), got {value}")
    return d


def check_non_negative_decimal(value, what: str = "amount") -> Decimal:
    """Validate that a decimal value is non-negative (>= 0)."""
    d = to_decimal(value, what)
    if d < 0:
        raise ToolError(f"{what} cannot be negative, got {value}")
    return d


def q2(d: Decimal) -> Decimal:
    """Quantize to two decimal places using explicit ROUND_HALF_UP."""
    return d.quantize(CENT, rounding=ROUND_HALF_UP)


def money_str(d: Decimal) -> str:
    """Format decimal as monetary string with two decimal places."""
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
    """Show a quantity formatted cleanly."""
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


def is_safe_relative_path(path_str: str) -> bool:
    """Reject path traversal attempts across Windows and POSIX systems.
    
    Prevents:
    - Parent directory traversal ('..' segments via '/' or '\\')
    - Absolute paths ('/etc/passwd', '\\windows\\system32', 'C:\\...')
    - Windows drive letters and alternate data streams (':')
    - UNC network shares ('//server/share' or '\\\\server\\share')
    """
    if not path_str or not isinstance(path_str, str):
        return False
    s = str(path_str).strip()
    if not s:
        return False
    # Normalize backslashes to forward slashes for cross-platform checking
    norm_path = s.replace("\\", "/")
    # Reject leading slashes (POSIX root or UNC)
    if norm_path.startswith("/"):
        return False
    # Reject Windows drive colons or ADS
    if ":" in norm_path:
        return False
    # Check for '..' path segments
    segments = [seg for seg in norm_path.split("/") if seg and seg != "."]
    if ".." in segments:
        return False
    return True


def canonical_json_bytes(obj: dict) -> bytes:
    """Deterministic, sorted-key UTF-8 byte serialization for cryptographic hashing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def hash_comparison_result(obj: dict) -> str:
    """Compute the full 64-character SHA-256 hex digest of a comparison result."""
    return hashlib.sha256(canonical_json_bytes(obj)).hexdigest()


def save_comparison_with_digest(result: dict, json_path: Path | str) -> str:
    """Save comparison JSON atomically and write a companion .sha256 digest file.
    
    Returns the calculated 64-character SHA-256 digest.
    """
    jp = Path(json_path)
    write_json_atomic(jp, result)
    digest = hash_comparison_result(result)
    digest_path = Path(f"{jp}.sha256")
    with open(digest_path, "w", encoding="utf-8") as fh:
        fh.write(digest + "\n")
    return digest


def verify_comparison_digest_file(json_path: Path | str, digest_path: Path | str | None = None) -> tuple[bool, str, str]:
    """Verify that a comparison result matches its recorded .sha256 companion file.
    
    Returns: (is_valid, calculated_digest, recorded_digest)
    """
    jp = Path(json_path)
    dp = Path(digest_path) if digest_path else Path(f"{jp}.sha256")
    if not jp.exists():
        raise ToolError(f"Comparison JSON not found: {jp}")
    if not dp.exists():
        raise ToolError(f"Companion digest file not found: {dp}")
    
    try:
        data = load_json(jp)
        calc = hash_comparison_result(data)
    except Exception as exc:
        raise ToolError(f"Failed to read or hash comparison JSON: {exc}")
        
    try:
        recorded = dp.read_text(encoding="utf-8").strip()
    except Exception as exc:
        raise ToolError(f"Failed to read digest file: {exc}")
        
    return (calc.lower() == recorded.lower(), calc, recorded)


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
