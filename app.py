"""Overcharge Desk Canonical Server Entrypoint.

Consolidated entrypoint delegating to hardened FastAPI application in services.api.main.
Ensures zero duplication, strict cryptographic validation, and standard ASGI execution.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
TOOLS_DIR = ROOT_DIR / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import uvicorn
from services.api.main import app
from services.api.workspace_service import ensure_base_storage_initialized


def main() -> None:
    port = int(os.environ.get("PORT", "3000"))
    host = os.environ.get("HOST", "127.0.0.1")
    ensure_base_storage_initialized()
    print(f"Overcharge Desk server listening on http://{host}:{port}", flush=True)
    uvicorn.run("services.api.main:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
