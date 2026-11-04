# Architecture Specification: Overcharge Desk

**Version**: 1.1 (Phase 1 Canonical Architecture)  
**System Type**: Evidence-First Deterministic Vendor Reconciliation System  
**Target Environment**: Python 3.9+ (Standard Library Runtime), Switch/Mattermost Collaboration Gateway

---

## 1. Product Purpose

Overcharge Desk is an evidence-first vendor reconciliation and dispute management system. It enables businesses to systematically cross-examine inbound vendor invoices against contractual Master Service Agreements (MSAs), cross-reference persistent historical dispute records, obtain cryptographically bound human-in-the-loop approvals, and produce deterministic dispute resolution packages.

### Primary Objectives
- **Zero Hallucination Arithmetic**: Prevent language models from executing or modifying financial mathematics.
- **Traceable Evidentiary Chain**: Bind every variance, rate discrepancy, or credit note claim to an explicit file and line locator.
- **Fail-Closed Human Governance**: Guarantee that no funds are disbursed, no dispute emails are transmitted, and no vendor ledgers are altered without authentic human supervisor approval.

---

## 2. System Architecture & Boundaries

The architecture strictly decouples **probabilistic semantic extraction** (performed by LLMs) from **deterministic computation and state management** (performed by Python CLI tools):

```
                        ┌──────────────────────────────────────┐
                        │   INCOMING RAW INVOICE (Text/JSON)   │
                        └──────────────────┬───────────────────┘
                                           │
                                           ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                SWITCH COLLABORATION ROOM                               │
│                                                                                        │
│   ┌─────────────────────┐      ┌─────────────────────┐      ┌─────────────────────┐   │
│   │    READER Agent     │      │    AUDITOR Agent    │      │    WRITER Agent     │   │
│   │    (Claude Code)    │      │   (OpenAI Codex)    │      │    (Claude Code)    │   │
│   └──────────┬──────────┘      └──────────┬──────────┘      └──────────┬──────────┘   │
│              │                            │                            │              │
│       1. Ingests file              3. Matches vendor            5. Checks signature   │
│       2. Validates schema             & active rates            6. Emits dispute      │
│       3. Hashes source             4. Queries history              package drafts     │
└──────────────┼────────────────────────────┼────────────────────────────┼──────────────┘
               │                            │                            │
               ▼                            ▼                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        LOCAL DETERMINISTIC CLI TOOLING LAYER                           │
│                                                                                        │
│   ┌──────────────────────┐     ┌──────────────────────┐     ┌──────────────────────┐   │
│   │ check_invoice.py     │     │ compare.py           │     │ ledger.py            │   │
│   │ - Schema validation  │     │ - Decimal math (q2)  │     │ - Append-only ledger │   │
│   │ - Math parity check  │     │ - Rate lifecycle     │     │ - Outcome tracking   │   │
│   │ - Fingerprinting     │     │ - Variance isolation │     │ - Duplicate rejection│   │
│   └──────────────────────┘     └──────────────────────┘     └──────────────────────┘   │
│   ┌──────────────────────┐     ┌──────────────────────┐     ┌──────────────────────┐   │
│   │ sha.py               │     │ next_case_id.py      │     │ payment_sheet.py     │   │
│   │ - SHA-256 digests    │     │ - Sequential IDs     │     │ - Formula escaping   │   │
│   │ - Artifact hashes    │     │ - Format: OC-Date-NN │     │ - Tabular CSV output │   │
│   └──────────────────────┘     └──────────────────────┘     └──────────────────────┘   │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │
                                            ▼
                         ┌─────────────────────────────────────┐
                         │      CASES ARTIFACT REPOSITORY      │
                         │ cases/<id>/invoice.json             │
                         │ cases/<id>/compare.json             │
                         │ cases/<id>/audit.json               │
                         │ cases/<id>/ledger_record.json       │
                         │ cases/<id>/dispute_email.md         │
                         │ cases/<id>/corrected_payment.csv    │
                         └─────────────────────────────────────┘
```

---

## 3. Canonical Directory Structure

Following the Phase 1 canonical consolidation, the single authoritative repository layout is:

```
overcharge-desk/
├── AGENTS.md                   # Permanent engineering and operational invariants
├── Makefile                    # Root test and demo-reset automation
├── pytest.ini                  # Authoritative pytest discovery configuration
├── requirements-dev.txt        # Development dependencies (pytest)
├── README.md                   # Project overview and executive specification
├── SWITCH_SETUP.md             # Integration guide for Switch and Mattermost
├── DEMO_SCRIPT.md              # 2-minute verification script and memory proof runbook
│
├── agents/                     # Agent system prompts and operational rules
│   ├── READER.md               # Intake, text extraction, and schema enforcement rules
│   ├── AUDITOR.md              # Contract cross-referencing and rate-matching rules
│   └── WRITER.md               # Approval verification and artifact generation rules
│
├── tools/                      # Deterministic Python 3.9+ standard library tools
│   ├── common.py               # Shared Decimal helpers, atomic IO, custom error types
│   ├── check_invoice.py        # Invoice schema and mathematical parity validator
│   ├── compare.py              # Exact Decimal variance and contract reconciliation engine
│   ├── ledger.py               # Vendor history manager and atomic transaction logger
│   ├── next_case_id.py         # Daily sequential case ID generator (OC-YYYYMMDD-NN)
│   ├── now.py                  # Standardized ISO-8601 UTC timestamp utility
│   ├── payment_sheet.py        # Formula-safe CSV payment sheet generator
│   └── sha.py                  # Cryptographic SHA-256 fingerprinting utility
│
├── contracts/                  # Active vendor contracts and rate schedules
│   └── acme-contract.md        # Acme Supplies Master Service Agreement and Schedule A
│
├── vendors/                    # Authoritative vendor ledger & historical memory
│   └── acme.json               # Contract rate definitions and historical case entries
│
├── seed/                       # Pristine reference vendor database
│   └── acme.json               # Seed ledger for `make reset-demo`
│
├── invoices/                   # Synthetic test invoices
│   ├── acme-inv-0914.txt       # Case 1 baseline invoice (historical dispute)
│   └── acme-inv-1103.txt       # Case 2 demo invoice (repeat overcharge scenario)
│
├── cases/                      # Output directory for investigated case folders
│   └── .gitkeep                # One folder per investigation: cases/<case_id>/
│
├── tests/                      # Authoritative test suite
│   ├── conftest.py             # Shared fixtures and sandboxed environment helpers
│   ├── test_compare.py         # Rate matching, rounding, and variance unit tests
│   ├── test_tools.py           # CLI tools, ledger append-only, and safety tests
│   └── fixtures/               # Test mocks (example_invoice.json)
│
└── docs/                       # Core architectural and forensic documentation
    ├── FORENSIC_AUDIT.md       # Phase 0 comprehensive audit findings
    ├── ARCHITECTURE.md         # System architecture and data flow (this document)
    ├── SECURITY_MODEL.md       # Threat boundaries, attack vectors, and mitigations
    └── TEST_STRATEGY.md        # Comprehensive verification and test methodology
```

---

## 4. Actor Responsibilities & Boundaries

| Actor | Engine / Runtime | Operational Scope | Permitted Writes | Strict Prohibitions |
|---|---|---|---|---|
| **`READER`** | Claude Code | Ingests raw invoices, extracts structured data, runs pre-flight checks. | `cases/<id>/invoice.json` | Cannot calculate contract variance; cannot write to `vendors/` or `contracts/`; cannot fill missing data with guesses. |
| **`AUDITOR`** | OpenAI Codex | Matches contract rates by date and SKU; queries vendor ledger history; drafts audit findings. | `cases/<id>/audit.json`<br>`cases/<id>/compare.json` | **Zero mental arithmetic** (must call `compare.py`); cannot authorize disputes; cannot mutate the ledger. |
| **`WRITER`** | Claude Code | Verifies owner signature; commits decision to ledger; drafts dispute artifacts. | `cases/<id>/ledger_record.json`<br>`cases/<id>/dispute_email.md`<br>`cases/<id>/corrected_payment.csv`<br>`vendors/<id>.json` | Cannot act without verified owner command; mutates ledger **only** through `tools/ledger.py`; no outbound communications. |
| **`OWNER`** | Human Supervisor | Authorizes or rejects dispute recommendations. | Mattermost chat command | Holds exclusive business authority via `APPROVE` / `REJECT`. |

---

## 5. End-to-End Data & Artifact Flow

```
[Raw Invoice] 
      │ (tools/sha.py & tools/next_case_id.py)
      ▼
cases/<id>/invoice.json 
      │ (tools/check_invoice.py --update)
      ▼
[Validated Invoice] + vendors/<vendor>.json
      │ (tools/compare.py)
      ▼
cases/<id>/compare.json 
      │ (Auditor cross-references vendor history)
      ▼
cases/<id>/audit.json
      │ (tools/sha.py computes audit_sha256)
      ▼
[Owner APPROVE Command]
      │ (Writer verifies identity & full 64-char hash)
      ▼
cases/<id>/ledger_record.json ──► (tools/ledger.py add-case) ──► vendors/<vendor>.json
      │
      ├──► cases/<id>/dispute_email.md (DRAFT - NOT SENT)
      └──► cases/<id>/corrected_payment.csv (tools/payment_sheet.py)
```

---

## 6. Execution Entry Points

All operations are executable directly from the repository root:

1. **Calculate Invoice Variance**:
   ```bash
   python tools/compare.py cases/<case_id>/invoice.json vendors/acme.json --out cases/<case_id>/compare.json
   ```
2. **Validate Invoice Structure & Math**:
   ```bash
   python tools/check_invoice.py cases/<case_id>/invoice.json --update
   ```
3. **Generate Corrected Payment Sheet**:
   ```bash
   python tools/payment_sheet.py cases/<case_id>/compare.json cases/<case_id>/corrected_payment.csv
   ```
4. **Append Authorized Ledger Case**:
   ```bash
   python tools/ledger.py add-case vendors/acme.json --record cases/<case_id>/ledger_record.json
   ```
5. **Run Authoritative Test Suite**:
   ```bash
   make test
   # or: python -m pytest
   ```

---

## 7. Current vs. Planned Architecture

| Architectural Capability | Current Status (Phase 1) | Planned State (Phase 2–4) |
|---|---|---|
| **Monetary Arithmetic** | Implemented (`Decimal`, `q2`, half-up) | Enhanced: strict handling of tax/freight exclusions |
| **Line-Item Verification Statuses** | Binary (`matched` / `unmatched`) | Multi-state (`VERIFIED_MATCH`, `VERIFIED_OVERCHARGE`, `SOURCE_DISCREPANCY`, `UNMATCHED`, etc.) |
| **Payment Sheet Discrepancy Gate** | Warning only; computes payable amount | Hard block: `SOURCE_DISCREPANCY` halts automated payment calculation |
| **Approval Hash Validation** | 64-char regex check in ledger tool | End-to-end cryptographic binding to disk artifact and verified identity |
| **Ledger Storage** | Atomic JSON file replacement | SQLite database with transactional constraints and event hash chaining |
| **Case State Machine** | Implicit file existence | Explicit orchestrator states (`RECEIVED` ➔ `VALIDATED` ➔ `REVIEW` ➔ `RESOLVED`) |
| **Traceable Decision Receipt** | None (separate markdown/CSV files) | Single verifiable `receipt.json` summarizing all artifact hashes |

