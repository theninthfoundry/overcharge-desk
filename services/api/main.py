"""FastAPI main application entrypoint for Overcharge Desk Operations."""
from __future__ import annotations

from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from services.api.routes import audit, auth, cases, vendors

app = FastAPI(
    title="Overcharge Desk Operations API",
    description="Deterministic Vendor Reconciliation & Cryptographic Payment Control Platform",
    version="3.0.0",
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API Routers under /api/v1
api_prefix = "/api/v1"
app.include_router(auth.router, prefix=api_prefix)
app.include_router(cases.router, prefix=api_prefix)
app.include_router(audit.router, prefix=api_prefix)
app.include_router(vendors.router, prefix=api_prefix)


@app.get("/api/v1/health", tags=["Health"])
def health_check():
    return {
        "status": "healthy",
        "service": "overcharge-desk-api",
        "version": "3.0.0",
        "engine": "deterministic-decimal",
    }


# Static web app serving
web_dir = Path("apps/web")
if (web_dir / "index.html").exists():
    @app.get("/", response_class=HTMLResponse, tags=["Frontend"])
    def serve_frontend():
        return FileResponse(web_dir / "index.html")

    app.mount("/static", StaticFiles(directory=str(web_dir)), name="static")
