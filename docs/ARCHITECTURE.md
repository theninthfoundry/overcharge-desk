# System Architecture & Component Interactions

> **System**: Overcharge Desk — Evidence-First Vendor Reconciliation & Autonomous Control  
> **Classification**: Core Architectural Specification

---

## 1. High-Level Architectural Layers

Overcharge Desk is structured in four decoupled layers:

```
┌────────────────────────────────────────────────────────────┐
│                    Collaboration Layer                     │
│  Switch Multi-Agent Chatroom (#overcharge-desk) & Web UI   │
└─────────────────────────────┬──────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│                     Application Gateway                    │
│   Unified Agent CLI (tools/desk.py) & REST API (FastAPI)   │
└─────────────────────────────┬──────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│                     Domain Core Engine                     │
│  100% Deterministic Financial Engine (decimal.Decimal)     │
│  Evidence Manifest Verification & Invariant Checking       │
└─────────────────────────────┬──────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│                     Persistence Layer                      │
│   Tamper-Evident SQLite Ledger (`ledger.db`) & Storage     │
└────────────────────────────────────────────────────────────┘
```

---

## 2. Component Decoupling & Invariants

1. **Collaboration vs Execution**:
   - The collaboration layer (Switch room) handles agent dialogue, notification, and human review.
   - It possesses zero calculation logic.
2. **Deterministic Domain Core**:
   - The core reconciliation engine depends only on Python standard library modules (`decimal`, `hashlib`, `json`, `pathlib`).
   - Requires zero network calls or third-party web services to evaluate financial truth.
3. **Tamper-Evident Ledger**:
   - The SQLite database records state transitions as cryptographic hash links.
   - Any external tampering or record deletion is detected instantly via `python tools/audit_ledger.py verify`.
