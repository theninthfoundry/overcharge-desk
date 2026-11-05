from __future__ import annotations

import pytest
from common import ToolError
from domain.identity.key_manager import KeyManager, KeyStatus


def test_key_manager_initialization_and_active_key(tmp_path):
    km = KeyManager(config_dir=tmp_path, app_env="development")
    key_id, key_bytes = km.get_active_key()
    assert key_id is not None
    assert len(key_bytes) >= 32
    assert km.get_key_by_id(key_id) == key_bytes


def test_key_rotation_and_historical_verification(tmp_path):
    km = KeyManager(config_dir=tmp_path, app_env="development")
    first_id, first_bytes = km.get_active_key()

    # Rotate
    rotated_meta = km.rotate_key(new_key_id="key-2026-rotated")
    assert rotated_meta.key_id == "key-2026-rotated"
    assert rotated_meta.status == KeyStatus.ACTIVE

    new_id, new_bytes = km.get_active_key()
    assert new_id == "key-2026-rotated"
    assert new_bytes != first_bytes

    # Historical verification: previous key must still be retrievable
    historical = km.get_key_by_id(first_id)
    assert historical == first_bytes

    # Previous key is marked RETIRED in list
    keys = km.list_keys()
    old_k = [k for k in keys if k.key_id == first_id][0]
    assert old_k.status == KeyStatus.RETIRED


def test_key_revocation(tmp_path):
    km = KeyManager(config_dir=tmp_path, app_env="development")
    first_id, _ = km.get_active_key()

    # Cannot revoke active key
    with pytest.raises(ToolError, match="Cannot revoke key .* key is currently ACTIVE"):
        km.revoke_key(first_id, reason="Compromised")

    # Rotate first, then revoke old key
    km.rotate_key(new_key_id="key-active-2")
    revoked = km.revoke_key(first_id, reason="Key leak detected")
    assert revoked.status == KeyStatus.REVOKED
    assert revoked.revocation_reason == "Key leak detected"


def test_production_fails_closed_when_key_missing(tmp_path):
    # In production, missing manifest/key causes immediate failure
    with pytest.raises(ToolError, match="Production signing key manifest missing"):
        KeyManager(config_dir=tmp_path, app_env="production")


def test_multiple_sequential_key_rotations(tmp_path):
    """Verify multiple successive key rotations preserve all historical keys."""
    km = KeyManager(config_dir=tmp_path, app_env="development")
    keys_history = []
    
    for i in range(3):
        kid, kbytes = km.get_active_key()
        keys_history.append((kid, kbytes))
        km.rotate_key(new_key_id=f"key-seq-{i+1}")

    # The current key is the 3rd rotated key
    curr_id, _ = km.get_active_key()
    assert curr_id == "key-seq-3"

    # All prior keys must still be loadable by id
    for kid, kbytes in keys_history:
        assert km.get_key_by_id(kid) == kbytes


