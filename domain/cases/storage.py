"""Strict Case Storage Isolation, Path Containment, and Artifact Access Boundary."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Set

from common import ToolError, canonical_json_bytes, load_json, write_json_atomic

CASE_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]{3,64}$")
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB limit

ALLOWED_ARTIFACT_NAMES: Set[str] = {
    "invoice.json",
    "case.json",
    "evidence_registry.json",
    "compare.json",
    "compare.json.sha256",
    "verification.json",
    "verification.json.sha256",
    "manifest.json",
    "payment_preview.csv",
    "corrected_payment.csv",
    "partial_review.csv",
    "blocked_review_report.csv",
    "approval_receipt.json",
    "audit_integrity_report.json",
}


class StorageSecurityError(ToolError):
    """Raised when an attempt to escape case boundary or access unauthorized paths occurs."""
    def __init__(self, message: str):
        super().__init__(f"Storage security violation: {message}", 4)


class CaseStorage:
    """Encapsulates all on-disk case file access with strict containment and validation."""

    def __init__(self, base_cases_dir: Path | str = "cases"):
        self.cases_dir = Path(base_cases_dir).resolve()
        self.cases_dir.mkdir(parents=True, exist_ok=True)

    def validate_case_id(self, case_id: str) -> str:
        """Validate case identifier format and prevent path manipulation characters.
        
        Defense Rules:
        - Alphanumeric, hyphens, underscores only (3-64 chars via regex).
        - Explicitly blocks path separators (/, \\), parent directory references (..),
          colons (:), URL encoded dots (%2e), and null bytes (\\0).
        """
        if not case_id or not isinstance(case_id, str):
            raise StorageSecurityError("Case identifier must be a non-empty string")
        clean_id = case_id.strip()
        if not CASE_ID_RE.match(clean_id):
            raise StorageSecurityError(
                f"Invalid case identifier {case_id!r}. "
                "Must be 3-64 characters matching alphanumeric, hyphens, and underscores only."
            )
        # Explicit rejection of path separators, dots, or drive characters
        if any(c in clean_id for c in ("/", "\\", "..", ":", "%", "\0")):
            raise StorageSecurityError("Path traversal or control characters in case ID")
        return clean_id

    def get_case_directory(self, case_id: str, create: bool = True) -> Path:
        """Get canonical validated case directory within storage root."""
        clean_id = self.validate_case_id(case_id)
        c_dir = (self.cases_dir / clean_id).resolve()

        # Path containment assertion
        try:
            c_dir.relative_to(self.cases_dir)
        except ValueError:
            raise StorageSecurityError(f"Directory escape detected for case '{clean_id}'")

        if create:
            c_dir.mkdir(parents=True, exist_ok=True)

        return c_dir

    def resolve_artifact_path(self, case_id: str, artifact_name: str) -> Path:
        """Resolve a specific allowed artifact file inside case directory."""
        c_dir = self.get_case_directory(case_id)
        if not artifact_name or not isinstance(artifact_name, str):
            raise StorageSecurityError("Artifact name must be a non-empty string")

        clean_name = artifact_name.strip()
        # Prevent any path traversal in artifact name
        if any(c in clean_name for c in ("/", "\\", "..", ":", "%", "\0")):
            raise StorageSecurityError(f"Path traversal detected in artifact name '{artifact_name}'")

        if clean_name not in ALLOWED_ARTIFACT_NAMES:
            raise StorageSecurityError(f"Artifact '{clean_name}' is not in allowed artifact registry")

        # Resolve artifact: check standard case root and approvals/audit subfolders
        candidates = [
            c_dir / clean_name,
            c_dir / "audit" / clean_name,
            c_dir / "approvals" / clean_name,
            c_dir / "comparison" / clean_name,
        ]

        target: Optional[Path] = None
        for cand in candidates:
            resolved = cand.resolve()
            # Verify containment
            try:
                resolved.relative_to(c_dir)
            except ValueError:
                raise StorageSecurityError(f"Symlink or directory escape in artifact '{clean_name}'")

            # Check for symlink escape
            if cand.is_symlink():
                real_target = cand.resolve()
                try:
                    real_target.relative_to(c_dir)
                except ValueError:
                    raise StorageSecurityError(f"Symlink escape prohibited: '{cand}' targets external file")

            if resolved.exists():
                target = resolved
                break

        if target is None:
            # Default to root candidate for write operations
            target = (c_dir / clean_name).resolve()

        return target

    def read_artifact(self, case_id: str, artifact_name: str) -> bytes:
        """Safely read artifact contents under size and containment limits."""
        art_path = self.resolve_artifact_path(case_id, artifact_name)
        if not art_path.exists():
            raise ToolError(f"Artifact '{artifact_name}' does not exist for case '{case_id}'", 2)

        size = art_path.stat().st_size
        if size > MAX_FILE_SIZE_BYTES:
            raise StorageSecurityError(f"Artifact exceeds maximum size of {MAX_FILE_SIZE_BYTES} bytes")

        return art_path.read_bytes()

    def write_artifact(self, case_id: str, artifact_name: str, content_bytes: bytes) -> Path:
        """Safely write artifact atomically."""
        if len(content_bytes) > MAX_FILE_SIZE_BYTES:
            raise StorageSecurityError(f"Content exceeds maximum allowed size ({len(content_bytes)} bytes)")

        art_path = self.resolve_artifact_path(case_id, artifact_name)
        art_path.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write via temporary file
        tmp_p = art_path.with_suffix(".tmp")
        tmp_p.write_bytes(content_bytes)
        tmp_p.replace(art_path)
        return art_path

    def list_available_artifacts(self, case_id: str) -> List[str]:
        """List allowed artifact names that currently exist on disk for this case."""
        c_dir = self.get_case_directory(case_id)
        if not c_dir.exists():
            return []

        found = []
        for name in ALLOWED_ARTIFACT_NAMES:
            try:
                p = self.resolve_artifact_path(case_id, name)
                if p.exists():
                    found.append(name)
            except Exception:
                pass
        return sorted(found)
