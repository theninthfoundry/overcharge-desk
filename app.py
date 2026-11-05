#!/usr/bin/env python3
"""Overcharge Desk — Production HTTP Server & Operations API Entrypoint.

Zero-dependency Python 3.10+ HTTP server binding to 0.0.0.0:3000 that bridges
the Overcharge Desk Finance Operations Workspace (`apps/web/index.html`) to the
deterministic financial verification, RBAC authorization, and tamper-evident
SQLite audit ledger engines in `domain/` and `tools/`.
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

# Ensure repository root and tools/ are on sys.path
ROOT_DIR = Path(__file__).resolve().parent
TOOLS_DIR = ROOT_DIR / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from audit_ledger import create_checkpoint, list_events, verify_ledger
from auth import get_default_key_path, load_signing_key
from common import ToolError, load_json
from domain.authorization.policies import (
    AuthorizationService,
    PERM_AUDIT_CHECKPOINT,
    PERM_AUDIT_READ,
    PERM_CASE_APPROVE,
    PERM_CASE_CREATE,
    PERM_CASE_READ,
    PERM_CASE_RECONCILE,
    PERM_PAYMENT_EXPORT,
    ROLE_PERMISSIONS,
)
from domain.cases.service import CaseService
from domain.identity.key_manager import KeyManager
from domain.identity.models import IdentityService, User
from domain.identity.repository import IdentityRepository
from run_demo_suite import run_full_demo

APP_ENV = os.getenv("APP_ENV", "development").lower()
WEB_DIR = ROOT_DIR / "apps" / "web"

# Shared domain singletons
_identity_service = IdentityService()
_auth_service = AuthorizationService(enforce_strict_separation_of_duties=True)
_key_manager = KeyManager(app_env=APP_ENV)
_case_service = CaseService(base_dir=ROOT_DIR, auth_service=_auth_service)

# Brute-force login lockout tracking: 5 failed attempts -> 300s lockout
_FAILED_LOGINS: Dict[str, Tuple[int, float]] = {}
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION_SECONDS = 300


def record_failed_login(username: str) -> bool:
    now = time.time()
    key = username.lower()
    count, until = _FAILED_LOGINS.get(key, (0, 0.0))
    if now < until:
        return True
    count += 1
    if count >= MAX_FAILED_ATTEMPTS:
        _FAILED_LOGINS[key] = (count, now + LOCKOUT_DURATION_SECONDS)
        return True
    _FAILED_LOGINS[key] = (count, 0.0)
    return False


def is_user_locked_out(username: str) -> bool:
    now = time.time()
    _, until = _FAILED_LOGINS.get(username.lower(), (0, 0.0))
    return now < until


def reset_failed_logins(username: str) -> None:
    _FAILED_LOGINS.pop(username.lower(), None)


def ensure_demo_initialized() -> None:
    """Seed canonical 6 benchmark cases and ledger hash chain if not yet initialized."""
    ledger_db = ROOT_DIR / "ledger.db"
    clean_comp = ROOT_DIR / "cases" / "demo-clean" / "compare.json"
    if not ledger_db.exists() or not clean_comp.exists():
        try:
            run_full_demo(base_dir=ROOT_DIR, clean_run=True)
        except Exception as exc:
            print(f"[WARN] Initial demo suite seed warning: {exc}", file=sys.stderr)


def build_health_payload() -> Dict[str, Any]:
    checks: Dict[str, str] = {}
    is_ready = True

    try:
        id_repo = IdentityRepository()
        id_repo.check_production_safety(app_env=APP_ENV)
        checks["identity_database"] = "OK"
        checks["database"] = "OK"
    except Exception as exc:
        checks["identity_database"] = f"ERROR: {exc}"
        checks["database"] = f"ERROR: {exc}"
        is_ready = False

    try:
        active_id, _ = _key_manager.get_active_key()
        checks["signing_key"] = f"OK ({active_id})"
        checks["key_manager"] = "OK"
    except Exception as exc:
        checks["signing_key"] = f"ERROR: {exc}"
        checks["key_manager"] = f"ERROR: {exc}"
        is_ready = False

    try:
        cases_p = ROOT_DIR / "cases"
        cases_p.mkdir(parents=True, exist_ok=True)
        test_file = cases_p / ".health_check.tmp"
        test_file.write_text("health", encoding="utf-8")
        test_file.unlink()
        checks["storage"] = "OK"
    except Exception as exc:
        checks["storage"] = f"ERROR: {exc}"
        is_ready = False

    return {
        "status": "READY" if is_ready else "DEGRADED",
        "is_ready": is_ready,
        "service": "overcharge-desk-api",
        "version": "3.2.0",
        "environment": APP_ENV,
        "checks": checks,
    }


def list_vendors_payload() -> list[Dict[str, Any]]:
    vendors_dir = ROOT_DIR / "vendors"
    results: list[Dict[str, Any]] = []
    if vendors_dir.exists():
        for f in sorted(vendors_dir.glob("*.json")):
            try:
                data = load_json(f)
                contract = data.get("contract", {})
                rates = contract.get("rates") or []
                items = contract.get("items") or {}
                first_rate = rates[0] if isinstance(rates, list) and rates else {}
                currency = data.get("currency") or contract.get("currency") or first_rate.get("currency") or "INR"
                effective_from = contract.get("effective_from") or first_rate.get("effective_from") or "2026-01-01"
                effective_to = contract.get("effective_to") or first_rate.get("effective_to") or "Active"
                items_count = len(rates) if rates else len(items)
                results.append(
                    {
                        "vendor_id": data.get("vendor_id"),
                        "vendor_name": data.get("name"),
                        "currency": currency,
                        "contract_id": contract.get("contract_id"),
                        "source_file": contract.get("source_file"),
                        "effective_from": effective_from,
                        "effective_to": effective_to,
                        "items_count": items_count,
                        "rates": rates,
                    }
                )
            except Exception:
                pass
    return results


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


class OverchargeDeskHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        # Quiet standard access logging to keep stdout clean
        pass

    def _send_security_headers(self, is_api: bool = True) -> None:
        req_id = self.headers.get("X-Request-ID") or os.urandom(8).hex()
        self.send_header("X-Request-ID", req_id)
        self.send_header("X-Content-Type-Options", "nosniff")
        if is_api:
            self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com; "
            "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
            "img-src 'self' data:; "
            "connect-src 'self';",
        )

    def _send_json(self, status_code: int, payload: Any, extra_headers: Optional[Dict[str, str]] = None) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self._send_security_headers(is_api=True)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(
        self,
        status_code: int,
        content: bytes,
        content_type: str,
        is_api: bool = False,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.send_response(status_code)
        self._send_security_headers(is_api=is_api)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(content)

    def _read_json_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            raise ToolError(f"Invalid JSON request body: {exc}", 2)

    def _authenticate(self, required_permission: Optional[str] = None) -> Optional[User]:
        auth_header = self.headers.get("Authorization")
        if not auth_header:
            self._send_json(
                401,
                {"detail": "Missing Authorization header"},
                extra_headers={"WWW-Authenticate": "Bearer"},
            )
            return None

        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            self._send_json(
                401,
                {"detail": "Invalid Authorization header format. Expected 'Bearer <token>'"},
                extra_headers={"WWW-Authenticate": "Bearer"},
            )
            return None

        user = _identity_service.verify_session_token(parts[1])
        if not user:
            self._send_json(
                401,
                {"detail": "Invalid, expired, or revoked session token"},
                extra_headers={"WWW-Authenticate": "Bearer"},
            )
            return None

        if required_permission and not _auth_service.has_permission(user, required_permission):
            self._send_json(
                403,
                {"detail": f"Permission denied: Requires '{required_permission}'"},
            )
            return None

        return user

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._send_security_headers(is_api=True)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Request-ID")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        # 1. Frontend routes
        if path in ("/", "/index.html"):
            index_file = WEB_DIR / "index.html"
            if index_file.exists():
                self._send_bytes(200, index_file.read_bytes(), "text/html; charset=utf-8", is_api=False)
                return
            self._send_bytes(200, b"<h1>Overcharge Desk</h1>", "text/html; charset=utf-8", is_api=False)
            return

        if path.startswith("/static/"):
            rel = path[len("/static/"):]
            target = (WEB_DIR / rel).resolve()
            if str(target).startswith(str(WEB_DIR.resolve())) and target.is_file():
                ctype, _ = mimetypes.guess_type(str(target))
                self._send_bytes(200, target.read_bytes(), ctype or "application/octet-stream", is_api=False)
                return
            self._send_json(404, {"detail": "Static asset not found"})
            return

        # 2. Health check endpoints
        if path in ("/api/v1/health", "/api/health"):
            self._send_json(200, build_health_payload())
            return

        # 3. Auth /me
        if path == "/api/v1/auth/me":
            user = self._authenticate()
            if not user:
                return
            perms = sorted(list(ROLE_PERMISSIONS.get(user.role, set())))
            self._send_json(
                200,
                {
                    "user_id": user.user_id,
                    "username": user.username,
                    "full_name": user.full_name,
                    "email": user.email,
                    "role": user.role,
                    "is_active": user.is_active,
                    "permissions": perms,
                },
            )
            return

        # 4. List Cases
        if path == "/api/v1/cases":
            user = self._authenticate(PERM_CASE_READ)
            if not user:
                return
            status_filter = query.get("status", [None])[0]
            summaries = _case_service.list_cases(filter_status=status_filter)
            self._send_json(200, [s.to_dict() for s in summaries])
            return

        # 5. Download Case Artifact
        m_art = re.match(r"^/api/v1/cases/([^/]+)/artifacts/([^/]+)$", path)
        if m_art:
            case_id, artifact_name = m_art.group(1), m_art.group(2)
            user = self._authenticate(PERM_CASE_READ)
            if not user:
                return
            if artifact_name == "corrected_payment.csv":
                if not _auth_service.has_permission(user, PERM_PAYMENT_EXPORT):
                    self._send_json(
                        403,
                        {
                            "detail": "Permission denied: Downloading authorized payment sheets requires 'payment:export' permission"
                        },
                    )
                    return
            art_p = _case_service.get_artifact_path(case_id, artifact_name)
            if not art_p or not art_p.exists():
                self._send_json(
                    404,
                    {"detail": f"Artifact '{artifact_name}' not available for case '{case_id}'"},
                )
                return
            media_type = "text/csv; charset=utf-8" if artifact_name.endswith(".csv") else "application/json; charset=utf-8"
            self._send_bytes(
                200,
                art_p.read_bytes(),
                media_type,
                is_api=True,
                extra_headers={"Content-Disposition": f'inline; filename="{artifact_name}"'},
            )
            return

        # 6. Export Payment Instruction
        m_pay_exp = re.match(r"^/api/v1/cases/([^/]+)/payment-instruction/([^/]+)/export$", path)
        if m_pay_exp:
            case_id, instruction_id = m_pay_exp.group(1), m_pay_exp.group(2)
            user = self._authenticate(PERM_PAYMENT_EXPORT)
            if not user:
                return
            fmt = query.get("format", ["csv"])[0]
            if fmt not in ("csv", "json"):
                self._send_json(400, {"detail": "Invalid format; expected 'csv' or 'json'"})
                return
            try:
                media_type, content = _case_service.export_payment_instruction(
                    case_id=case_id,
                    instruction_id=instruction_id,
                    operator=user,
                    format_type=fmt,
                )
                ext = "json" if fmt == "json" else "csv"
                self._send_bytes(
                    200,
                    content,
                    media_type,
                    is_api=True,
                    extra_headers={"Content-Disposition": f'attachment; filename="{instruction_id}.{ext}"'},
                )
            except ToolError as exc:
                code = 403 if exc.code == 4 else 400
                self._send_json(code, {"detail": str(exc)})
            return

        # 7. Get Single Case Detail
        m_case = re.match(r"^/api/v1/cases/([^/]+)$", path)
        if m_case:
            case_id = m_case.group(1)
            user = self._authenticate(PERM_CASE_READ)
            if not user:
                return
            detail = _case_service.get_case(case_id)
            if not detail:
                self._send_json(404, {"detail": f"Case '{case_id}' not found"})
                return
            self._send_json(200, detail.to_dict())
            return

        # 8. Audit Ledger Events
        if path == "/api/v1/audit/ledger/events":
            user = self._authenticate(PERM_AUDIT_READ)
            if not user:
                return
            case_id_filter = query.get("case_id", [None])[0]
            try:
                limit = int(query.get("limit", ["50"])[0])
                limit = max(1, min(500, limit))
            except ValueError:
                limit = 50
            events = list_events(case_id=case_id_filter)
            self._send_json(200, events[-limit:])
            return

        # 9. Audit Ledger Verify
        if path == "/api/v1/audit/ledger/verify":
            user = self._authenticate(PERM_AUDIT_READ)
            if not user:
                return
            valid, issues = verify_ledger()
            events = list_events()
            self._send_json(
                200,
                {
                    "ok": valid,
                    "valid": valid,
                    "total_events": len(events),
                    "issues_count": len(issues),
                    "issues": issues,
                },
            )
            return

        # 10. Vendors List
        if path == "/api/v1/vendors":
            user = self._authenticate(PERM_CASE_READ)
            if not user:
                return
            self._send_json(200, list_vendors_payload())
            return

        self._send_json(404, {"detail": f"Endpoint '{path}' not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        try:
            body = self._read_json_body()
        except ToolError as exc:
            self._send_json(400, {"detail": str(exc)})
            return

        # 1. Auth Login
        if path == "/api/v1/auth/login":
            username = str(body.get("username", "")).strip()
            password = str(body.get("password", ""))
            if is_user_locked_out(username):
                self._send_json(
                    429,
                    {
                        "detail": "Account temporarily locked due to multiple failed login attempts. Please try again later."
                    },
                )
                return

            user = _identity_service.authenticate(username, password)
            if not user:
                if record_failed_login(username):
                    self._send_json(
                        429,
                        {
                            "detail": "Account temporarily locked due to multiple failed login attempts. Please try again later."
                        },
                    )
                    return
                self._send_json(401, {"detail": "Invalid username or password"})
                return

            reset_failed_logins(username)
            token = _identity_service.issue_session_token(user)
            self._send_json(
                200,
                {
                    "ok": True,
                    "access_token": token,
                    "token_type": "bearer",
                    "user_id": user.user_id,
                    "username": user.username,
                    "role": user.role,
                    "full_name": user.full_name,
                },
            )
            return

        # 2. Auth Logout
        if path == "/api/v1/auth/logout":
            auth_header = self.headers.get("Authorization", "")
            parts = auth_header.split()
            if len(parts) == 2 and parts[0].lower() == "bearer":
                _identity_service.revoke_token(parts[1])
            self._send_json(200, {"ok": True, "action": "logged_out"})
            return

        # 3. Re-run Demo Benchmark Suite
        if path == "/api/v1/demo/run":
            user = self._authenticate(PERM_CASE_READ)
            if not user:
                return
            try:
                res = run_full_demo(base_dir=ROOT_DIR, clean_run=True)
                self._send_json(200, res)
            except Exception as exc:
                self._send_json(400, {"detail": str(exc)})
            return

        # 4. Create New Case
        if path == "/api/v1/cases":
            user = self._authenticate(PERM_CASE_CREATE)
            if not user:
                return
            case_id = str(body.get("case_id", "")).strip()
            vendor_id = str(body.get("vendor_id", "acme")).strip() or "acme"
            invoice_json = body.get("invoice_json")
            if not case_id or not isinstance(invoice_json, dict):
                self._send_json(400, {"detail": "Missing required 'case_id' or 'invoice_json' object"})
                return
            try:
                detail = _case_service.create_case(
                    case_id=case_id,
                    vendor_id=vendor_id,
                    invoice_json_content=invoice_json,
                    creator_user=user,
                )
                self._send_json(201, detail.to_dict())
            except ToolError as exc:
                self._send_json(400, {"detail": str(exc)})
            return

        # 5. Reconcile Case
        m_rec = re.match(r"^/api/v1/cases/([^/]+)/reconcile$", path)
        if m_rec:
            case_id = m_rec.group(1)
            user = self._authenticate(PERM_CASE_RECONCILE)
            if not user:
                return
            require_approval = bool(body.get("require_approval", False))
            try:
                res = _case_service.reconcile_case(
                    case_id=case_id,
                    operator=user,
                    require_approval=require_approval,
                )
                self._send_json(
                    200,
                    {
                        "ok": res["ok"],
                        "pipeline_status": res["pipeline_status"],
                        "execution_id": res["execution_id"],
                        "case_id": res["case_id"],
                        "verification_status": res["verification_status"],
                        "commercial_status": res["commercial_status"],
                        "settlement_status": res["settlement_status"],
                        "source_digest_verified": res["source_digest_verified"],
                        "comparison_digest": res["comparison_digest"],
                        "artifact_type": res["artifact_type"],
                        "artifact_file": res["artifact_file"],
                        "approval_verified": res.get("approval_verified"),
                    },
                )
            except ToolError as exc:
                self._send_json(400, {"detail": str(exc)})
            return

        # 6. Approve or Reject Case
        m_app = re.match(r"^/api/v1/cases/([^/]+)/approve$", path)
        if m_app:
            case_id = m_app.group(1)
            user = self._authenticate(PERM_CASE_APPROVE)
            if not user:
                return
            decision = str(body.get("decision", "")).strip()
            reason = body.get("reason")
            amount = body.get("amount")
            try:
                res = _case_service.approve_or_reject_case(
                    case_id=case_id,
                    approver=user,
                    decision=decision,
                    reason=str(reason) if reason is not None else None,
                    amount=str(amount) if amount is not None else None,
                )
                self._send_json(
                    200,
                    {
                        "ok": res["ok"],
                        "decision": res["decision"],
                        "receipt_id": res["receipt_id"],
                        "receipt_hash": res["receipt_hash"],
                        "receipt_signature": res["receipt_signature"],
                        "approved_amount": res.get("approved_amount"),
                        "withheld_amount": res.get("withheld_amount"),
                        "idempotent": res.get("idempotent", False),
                    },
                )
            except ToolError as exc:
                code = 403 if exc.code == 4 else 400
                self._send_json(code, {"detail": str(exc)})
            return

        # 7. Export Case Audit Package
        m_exp = re.match(r"^/api/v1/cases/([^/]+)/export-audit$", path)
        if m_exp:
            case_id = m_exp.group(1)
            user = self._authenticate(PERM_CASE_READ)
            if not user:
                return
            try:
                res = _case_service.export_audit_package(case_id)
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "case_id": res["case_id"],
                        "target_package_directory": res["target_package_directory"],
                        "package_integrity_digest": res["package_integrity_digest"],
                        "package_verified": res["package_verified"],
                        "verification_issues": res["verification_issues"],
                    },
                )
            except ToolError as exc:
                self._send_json(400, {"detail": str(exc)})
            return

        # 8. Create Payment Instruction
        m_pay = re.match(r"^/api/v1/cases/([^/]+)/payment-instruction$", path)
        if m_pay:
            case_id = m_pay.group(1)
            user = self._authenticate(PERM_PAYMENT_EXPORT)
            if not user:
                return
            idem_key = body.get("idempotency_key")
            try:
                inst = _case_service.create_payment_instruction(
                    case_id=case_id,
                    operator=user,
                    idempotency_key=str(idem_key) if idem_key is not None else None,
                )
                self._send_json(
                    200,
                    {
                        "instruction_id": inst.instruction_id,
                        "case_id": inst.case_id,
                        "approval_receipt_id": inst.approval_receipt_id,
                        "approved_amount": inst.approved_amount,
                        "currency": inst.currency,
                        "vendor_id": inst.vendor_id,
                        "destination_reference": inst.destination_reference,
                        "destination_verified": inst.destination_verified,
                        "status": inst.status,
                        "created_at": inst.created_at,
                        "expires_at": inst.expires_at,
                        "idempotency_key": inst.idempotency_key,
                        "exported_at": inst.exported_at,
                        "exported_by": inst.exported_by,
                    },
                )
            except ToolError as exc:
                code = 403 if exc.code == 4 else 400
                self._send_json(code, {"detail": str(exc)})
            return

        # 9. Audit Ledger Checkpoint
        if path == "/api/v1/audit/ledger/checkpoint":
            user = self._authenticate(PERM_AUDIT_CHECKPOINT)
            if not user:
                return
            key_path = get_default_key_path()
            key_bytes = load_signing_key(key_path) if key_path.exists() else b"0123456789abcdef0123456789abcdef"
            try:
                chk = create_checkpoint(key_bytes=key_bytes)
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "checkpoint_id": chk["checkpoint_id"],
                        "highest_sequence": chk["highest_sequence"],
                        "head_event_hash": chk["head_event_hash"],
                        "chain_digest": chk["chain_digest"],
                        "signature": chk.get("signature"),
                    },
                )
            except ToolError as exc:
                self._send_json(400, {"detail": str(exc)})
            return

        self._send_json(404, {"detail": f"Endpoint '{path}' not found"})


def main() -> None:
    ensure_demo_initialized()
    port = int(os.environ.get("PORT", "3000"))
    host = os.environ.get("HOST", "0.0.0.0")
    server = ReusableThreadingHTTPServer((host, port), OverchargeDeskHandler)
    print(f"Overcharge Desk server listening on http://{host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
