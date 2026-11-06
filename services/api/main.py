"""FastAPI main application entrypoint with security hardening."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure repo root and tools directory are in sys.path for direct CLI/uvicorn execution
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
TOOLS_DIR = ROOT_DIR / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from common import ToolError
from domain.identity.key_manager import KeyManager
from domain.identity.repository import IdentityRepository
from services.api.middleware import SecurityHeadersMiddleware, get_key_manager
from services.api.routes import (
    approvals,
    audit,
    auth,
    cases,
    contracts,
    demo,
    evidence,
    integrations,
    overview,
    payments,
    settings,
    vendors,
)

APP_ENV = os.getenv("APP_ENV", "development").lower()

# CORS Allowed Origins Configuration
raw_cors = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000,http://localhost:8000")
allowed_origins = [o.strip() for o in raw_cors.split(",") if o.strip()]

if APP_ENV == "production":
    if not allowed_origins or "*" in allowed_origins:
        raise RuntimeError("FATAL: Insecure CORS configuration in production. Explicit trusted origins are required.")

app = FastAPI(
    title="Overcharge Desk Operations API",
    description="Deterministic Vendor Reconciliation & Cryptographic Payment Control Platform",
    version="3.2.0",
)

# Security headers middleware
app.add_middleware(SecurityHeadersMiddleware)

# Strict CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)

# Include API Routers under /api/v1
api_prefix = "/api/v1"
app.include_router(overview.router, prefix=api_prefix)
app.include_router(auth.router, prefix=api_prefix)
app.include_router(cases.router, prefix=api_prefix)
app.include_router(contracts.router, prefix=api_prefix)
app.include_router(evidence.router, prefix=api_prefix)
app.include_router(approvals.router, prefix=api_prefix)
app.include_router(payments.router, prefix=api_prefix)
app.include_router(audit.router, prefix=api_prefix)
app.include_router(vendors.router, prefix=api_prefix)
app.include_router(integrations.router, prefix=api_prefix)
app.include_router(settings.router, prefix=api_prefix)
app.include_router(demo.router, prefix=api_prefix)


@app.get("/api/v1/health", tags=["Health"])
@app.get("/api/v1/system/health", tags=["Health"])
@app.get("/api/health", tags=["Health"])
def health_check():
    """Operational health endpoint distinguishing LIVE, READY, and DEGRADED states.
    
    Subsystem Checks:
    - identity_database: Verifies SQLite schema and production demo credentials safety.
    - signing_key: Verifies availability of active HMAC signing key.
    - storage: Verifies filesystem write accessibility in cases/.
    """
    checks = {}
    is_ready = True

    # 1. Database check
    try:
        id_repo = IdentityRepository()
        id_repo.check_production_safety()
        checks["identity_database"] = "OK"
        checks["database"] = "OK"
    except Exception as exc:
        checks["identity_database"] = f"ERROR: {exc}"
        checks["database"] = f"ERROR: {exc}"
        is_ready = False

    # 2. Key Manager check
    try:
        km = get_key_manager()
        active_id, _ = km.get_active_key()
        checks["signing_key"] = f"OK ({active_id})"
        checks["key_manager"] = "OK"
    except Exception as exc:
        checks["signing_key"] = f"ERROR: {exc}"
        checks["key_manager"] = f"ERROR: {exc}"
        is_ready = False

    # 3. Storage check
    try:
        cases_p = Path("cases")
        cases_p.mkdir(parents=True, exist_ok=True)
        test_file = cases_p / ".health_check.tmp"
        test_file.write_text("health")
        test_file.unlink()
        checks["storage"] = "OK"
    except Exception as exc:
        checks["storage"] = f"ERROR: {exc}"
        is_ready = False

    # Aggregated status: READY indicates all subsystems passed; DEGRADED alerts orchestrators/load balancers
    overall_status = "READY" if is_ready else "DEGRADED"

    return {
        "status": overall_status,
        "is_ready": is_ready,
        "service": "overcharge-desk-api",
        "version": "3.2.0",
        "environment": APP_ENV,
        "checks": checks,
    }


# Static web app serving
web_dir = Path("apps/web")
if (web_dir / "index.html").exists():
    @app.get("/", response_class=HTMLResponse, tags=["Frontend"])
    def serve_frontend():
        return FileResponse(web_dir / "index.html")

    app.mount("/static", StaticFiles(directory=str(web_dir)), name="static")
