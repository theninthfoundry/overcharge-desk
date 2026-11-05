# Overcharge Desk — API Security & Perimeter Defense

> **Status**: Production Security Baseline (Phase 3.2)  
> **Audience**: Backend Engineers, Penetration Testers, DevSecOps

This document outlines the API security controls, HTTP header hardening, CORS policies, and request-level perimeter defenses implemented across Overcharge Desk.

---

## 1. HTTP Security Headers

Every HTTP response emitted by the API gateway is processed by `SecurityHeadersMiddleware`, applying strict browser security policies:

| Header | Production Value | Purpose |
|---|---|---|
| `Content-Security-Policy` | `default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'` | Prevents Cross-Site Scripting (XSS) and unauthorized resource loading. |
| `X-Content-Type-Options` | `nosniff` | Blocks MIME-type confusion attacks and prevents browsers from interpreting non-script types as executable. |
| `X-Frame-Options` | `DENY` | Completely prevents clickjacking by prohibiting framing inside `<iframe>` elements. |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Protects referrer leakage to third-party endpoints. |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` | Enforces HTTPS transport in production. |
| `X-Request-ID` | 32-character hexadecimal UUID | Guarantees end-to-end request correlation for observability and security auditing. |

---

## 2. Cross-Origin Resource Sharing (CORS) Policy

### 2.1 Explicit Allowlisting
- Permitted origins are configured via the environment variable `CORS_ALLOWED_ORIGINS` (comma-separated list of origins, e.g. `https://finance.internal.company.com`).
- By default in development: `http://localhost:8000,http://127.0.0.1:8000`.

### 2.2 Production Invariants
In production (`APP_ENV=production`):
- **Wildcards Forbidden**: Setting `CORS_ALLOWED_ORIGINS="*"` while `allow_credentials=True` is an invalid and dangerous configuration. Startup fails immediately if a wildcard or empty origin list is detected in production.
- Permitted methods are strictly bounded to `GET`, `POST`, and `OPTIONS`.
- Permitted headers are strictly bounded to `Authorization`, `Content-Type`, and `X-Request-ID`.

---

## 3. Request Boundary Validation & Injection Defenses

### 3.1 Pydantic Schema Enforcement
All endpoints ingest input through strongly-typed Pydantic v2 schemas:
- Extra unexpected fields are stripped or forbidden.
- Identifiers must match explicit regular expressions (`^[a-zA-Z0-9_\-]{3,64}$`).
- Monetary amounts are received as exact strings and validated against `decimal.Decimal` constraints. Floating-point inputs are strictly prohibited.

### 3.2 CSV Formula Injection Neutralization
Exported artifacts (payment preview, corrected payment, payment instructions) sanitize all user-supplied cell values:
- Any cell string beginning with `=`, `+`, `-`, `@`, `\t`, or `\r` is escaped by prepending a single quote (`'`), preventing formula execution when opened in Microsoft Excel or Google Sheets.

---

## 4. Role-Based Access Control (RBAC) Enforcement

Every protected endpoint resolves the caller's session token using `get_current_user` and evaluates role permissions before business logic executes:

```python
@router.post("/{case_id}/approve")
def approve_or_reject_case(
    case_id: str,
    req: ApprovalDecisionRequest,
    user: User = Depends(require_permission(PERM_CASE_APPROVE)),
    ...
):
```

If the authenticated user lacks the required permission, the request is immediately aborted with `HTTP 403 Forbidden` and logged with correlation metadata.

