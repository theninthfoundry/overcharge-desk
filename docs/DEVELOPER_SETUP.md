# Developer Onboarding & Contribution Guide

> **Environment**: Python 3.9 – 3.13  
> **Platforms Supported**: Ubuntu Linux, macOS, Windows (PowerShell)

---

## 1. Local Environment Setup

### 1.1 Clone Repository & Create Virtual Environment
```bash
git clone https://github.com/theninthfoundry/overcharge-desk.git
cd overcharge-desk

# Create virtual environment
python3 -m venv .venv

# Activate (Linux / macOS)
source .venv/bin/activate

# Activate (Windows PowerShell)
.venv\Scripts\Activate.ps1
```

### 1.2 Install Dependencies
```bash
pip install -r requirements-dev.txt
```

---

## 2. Running Verification & Diagnostics

### 2.1 Full Automated Test Suite
```bash
python -m pytest -q
```
*Expected: 237 passed, 0 failures.*

### 2.2 System Health Probe
```bash
python tools/health_check.py
```

### 2.3 Run 1-Command Benchmark & Ledger Audit
```bash
python tools/quickstart.py
```

### 2.4 Run Switch Multi-Agent Terminal Simulator
```bash
python tools/simulate_switch.py --fast
```

---

## 3. Engineering Guidelines & Coding Invariants

1. **Mandatory Exact Decimals**:
   - Always import and use `decimal.Decimal` for any financial quantity, rate, or total.
   - Never use `float`.
2. **Fail-Closed Architecture**:
   - Any failure (missing file, hash mismatch, incorrect credential) must terminate with a non-zero exit code.
   - Never suppress or silently catch exceptions.
3. **Conventional Commits**:
   - Follow standard prefixes: `feat:`, `fix:`, `test:`, `docs:`, `build:`.
