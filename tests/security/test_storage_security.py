from __future__ import annotations

import os
from pathlib import Path
import pytest
from common import ToolError
from domain.cases.storage import CaseStorage, StorageSecurityError


@pytest.fixture
def storage(tmp_path):
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()
    return CaseStorage(base_cases_dir=cases_dir)


def test_valid_case_id_and_storage(storage):
    c_dir = storage.get_case_directory("OC-20261106-01")
    assert c_dir.name == "OC-20261106-01"
    assert c_dir.exists()


def test_reject_path_traversal_case_id(storage):
    invalid_ids = [
        "../etc",
        "../../config",
        "..\\..\\windows",
        "case/sub",
        "case\\sub",
        "C:\\Windows",
        "/etc/passwd",
        "case%2e%2e",
        "case\0hidden",
        "ab",  # too short (<3)
        "a" * 65,  # too long (>64)
    ]
    for cid in invalid_ids:
        with pytest.raises(StorageSecurityError):
            storage.get_case_directory(cid)


def test_reject_artifact_traversal(storage):
    invalid_artifacts = [
        "../signing.key",
        "../../config/signing.key",
        "..\\signing.key",
        "/etc/shadow",
        "C:\\secret.key",
        "invoice.json%00.txt",
    ]
    for art in invalid_artifacts:
        with pytest.raises(StorageSecurityError):
            storage.resolve_artifact_path("OC-20261106-01", art)


def test_reject_unauthorized_artifact_filename(storage):
    # Only explicitly allowed artifact names may be accessed
    with pytest.raises(StorageSecurityError, match="not in allowed artifact registry"):
        storage.resolve_artifact_path("OC-20261106-01", "random_script.py")

    with pytest.raises(StorageSecurityError, match="not in allowed artifact registry"):
        storage.resolve_artifact_path("OC-20261106-01", "id_rsa")


def test_symlink_escape_prevention(storage, tmp_path):
    c_dir = storage.get_case_directory("OC-20261106-01")
    external_secret = tmp_path / "external_secret.txt"
    external_secret.write_text("SUPER_SECRET_KEY")

    # Create malicious symlink inside case dir pointing to external secret
    symlink_path = c_dir / "invoice.json"
    try:
        os.symlink(external_secret, symlink_path)
    except (OSError, NotImplementedError):
        # On Windows without SeCreateSymbolicLinkPrivilege, skip symlink creation test
        pytest.skip("Symlink creation requires elevated privileges on Windows")

    # Attempting to read through symlink escaping case dir must fail
    with pytest.raises(StorageSecurityError, match="Symlink escape prohibited"):
        storage.read_artifact("OC-20261106-01", "invoice.json")


def test_oversized_upload_rejection(storage):
    oversized = b"0" * (10 * 1024 * 1024 + 1)  # 10 MB + 1 byte
    with pytest.raises(StorageSecurityError, match="exceeds maximum allowed size"):
        storage.write_artifact("OC-20261106-01", "invoice.json", oversized)
