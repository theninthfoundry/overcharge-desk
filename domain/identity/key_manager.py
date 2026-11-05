"""Signing Key Management with Lifecycle, Rotation, and Production Fail-Closed Gates."""
from __future__ import annotations

import json
import os
import secrets
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from common import ToolError, canonical_json_bytes, load_json, utc_now_iso, write_json_atomic


class KeyStatus:
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"
    REVOKED = "REVOKED"


@dataclass
class KeyMetadata:
    key_id: str
    status: str
    algorithm: str
    created_at: str
    activated_at: str
    retired_at: Optional[str] = None
    revoked_at: Optional[str] = None
    revocation_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class KeyManager:
    """Manages cryptographic provisioning keys, historical verification, and key rotation."""

    def __init__(
        self,
        config_dir: Path | str = "config",
        app_env: Optional[str] = None,
    ):
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.app_env = (app_env or os.getenv("APP_ENV", "development")).lower()
        self.manifest_file = self.config_dir / "keys_manifest.json"
        self._keys_cache: Dict[str, bytes] = {}
        self._init_or_verify_keys()

    def _init_or_verify_keys(self) -> None:
        """Verify key availability and security policies based on environment."""
        legacy_key_p = self.config_dir / "signing.key"

        if not self.manifest_file.exists():
            if self.app_env == "production":
                # Strict production invariant: Missing keys manifest is fatal
                raise ToolError(
                    "FATAL: Production signing key manifest missing in config/. "
                    "Startup refused: Production requires an explicit, pre-provisioned signing key.",
                    4,
                )

            # Development/Test bootstrap
            if legacy_key_p.exists():
                raw = legacy_key_p.read_bytes().strip()
                initial_meta = KeyMetadata(
                    key_id="key-2026-01",
                    status=KeyStatus.ACTIVE,
                    algorithm="HMAC-SHA-256",
                    created_at=utc_now_iso(),
                    activated_at=utc_now_iso(),
                )
                self._save_manifest({"active_key_id": initial_meta.key_id, "keys": [initial_meta.to_dict()]})
                (self.config_dir / f"{initial_meta.key_id}.key").write_bytes(raw)
            else:
                # Provision initial dev key
                self.rotate_key(new_key_id="key-dev-initial")

        # Load and validate active key
        manifest = load_json(self.manifest_file)
        active_id = manifest.get("active_key_id")
        if not active_id:
            raise ToolError("FATAL: No active signing key specified in keys manifest", 4)

        active_path = self.config_dir / f"{active_id}.key"
        if not active_path.exists():
            if legacy_key_p.exists():
                active_path = legacy_key_p
            elif self.app_env != "production":
                new_meta = self.rotate_key(new_key_id=active_id)
                active_path = self.config_dir / f"{active_id}.key"
            else:
                raise ToolError(f"FATAL: Active signing key file '{active_id}.key' does not exist on disk", 4)

        # File permission checks in production on POSIX systems
        if self.app_env == "production" and os.name != "nt":
            mode = active_path.stat().st_mode
            if mode & (stat.S_IRWXG | stat.S_IRWXO):
                raise ToolError(
                    f"FATAL: Insecure permissions on signing key file '{active_path.name}'. "
                    "Production requires strict file permissions (chmod 600).",
                    4,
                )

    def _save_manifest(self, manifest_data: dict) -> None:
        write_json_atomic(self.manifest_file, manifest_data)

    def get_active_key(self) -> Tuple[str, bytes]:
        """Return the active key ID and its raw secret bytes. Never logs raw bytes."""
        manifest = load_json(self.manifest_file)
        active_id = manifest["active_key_id"]
        key_bytes = self.get_key_by_id(active_id)
        if not key_bytes:
            raise ToolError(f"Active key '{active_id}' could not be loaded", 4)
        return active_id, key_bytes

    def get_key_by_id(self, key_id: str) -> Optional[bytes]:
        """Retrieve key bytes for historical receipt or checkpoint verification."""
        if key_id in self._keys_cache:
            return self._keys_cache[key_id]

        cand_file = self.config_dir / f"{key_id}.key"
        if cand_file.exists():
            key_bytes = cand_file.read_bytes().strip()
            self._keys_cache[key_id] = key_bytes
            return key_bytes

        # Check fallback legacy path
        legacy_file = self.config_dir / "signing.key"
        if legacy_file.exists() and (key_id in ("default", "key-2026-01", "key-dev-initial")):
            key_bytes = legacy_file.read_bytes().strip()
            self._keys_cache[key_id] = key_bytes
            return key_bytes

        return None

    def rotate_key(self, new_key_id: Optional[str] = None) -> KeyMetadata:
        """Rotate the signing key: retire the active key and activate a new key."""
        now = utc_now_iso()
        manifest = load_json(self.manifest_file) if self.manifest_file.exists() else {"keys": []}
        old_active_id = manifest.get("active_key_id")

        # Retire previous key
        for k in manifest.get("keys", []):
            if k["key_id"] == old_active_id and k["status"] == KeyStatus.ACTIVE:
                k["status"] = KeyStatus.RETIRED
                k["retired_at"] = now

        # Generate new key
        if not new_key_id:
            compact_date = now[:10].replace("-", "")
            rand_suffix = secrets.token_hex(4)
            new_key_id = f"key-{compact_date}-{rand_suffix}"

        new_key_bytes = secrets.token_hex(32).encode("utf-8")  # 64-char hex key
        new_key_path = self.config_dir / f"{new_key_id}.key"
        new_key_path.write_bytes(new_key_bytes)

        # Update permissions
        if os.name != "nt":
            try:
                new_key_path.chmod(0o600)
            except Exception:
                pass

        new_meta = KeyMetadata(
            key_id=new_key_id,
            status=KeyStatus.ACTIVE,
            algorithm="HMAC-SHA-256",
            created_at=now,
            activated_at=now,
        )

        manifest["active_key_id"] = new_key_id
        manifest.setdefault("keys", []).append(new_meta.to_dict())
        self._save_manifest(manifest)
        self._keys_cache[new_key_id] = new_key_bytes

        # Update legacy signing.key pointer for backward CLI compatibility
        (self.config_dir / "signing.key").write_bytes(new_key_bytes)

        return new_meta

    def revoke_key(self, key_id: str, reason: str) -> KeyMetadata:
        """Revoke a compromised key. Refuses if key is currently active."""
        manifest = load_json(self.manifest_file)
        if manifest.get("active_key_id") == key_id:
            raise ToolError(f"Cannot revoke key '{key_id}': key is currently ACTIVE. Rotate key first.", 4)

        now = utc_now_iso()
        revoked_meta = None
        for k in manifest.get("keys", []):
            if k["key_id"] == key_id:
                k["status"] = KeyStatus.REVOKED
                k["revoked_at"] = now
                k["revocation_reason"] = reason
                revoked_meta = KeyMetadata(**k)
                break

        if not revoked_meta:
            raise ToolError(f"Key '{key_id}' not found in manifest", 2)

        self._save_manifest(manifest)
        return revoked_meta

    def list_keys(self) -> List[KeyMetadata]:
        manifest = load_json(self.manifest_file)
        return [KeyMetadata(**k) for k in manifest.get("keys", [])]
