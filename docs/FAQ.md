# Frequently Asked Questions (FAQ)

> **Project**: Overcharge Desk — Evidence-First Vendor Reconciliation

---

### Q: Why use Switch and Mattermost for multi-agent coordination?
**A**: Switch / Mattermost provides an auditable, real-time communication fabric where autonomous agents (Intake, Auditor, Settlement) post structured findings and the human finance owner can supervise workflows transparently. It eliminates black-box automation while providing webhook-based agent automation.

---

### Q: Can an AI agent approve a payment if given a clever prompt or injection?
**A**: **No.** LLM prompts are not security boundaries. The agent CLI (`tools/desk.py`) does not have an `approve` subcommand under any flag or syntax. Approval requires executing `tools/approve.py` in an interactive terminal (TTY) with a human entering their Argon2id-hashed credentials. Without this cryptographic receipt, the settlement agent cannot release payment.

---

### Q: Why is binary floating point (`float`) strictly forbidden?
**A**: IEEE 754 floating point arithmetic introduces binary representation errors ($0.1 + 0.2 = 0.30000000000000004$). In high-volume accounts payable, these fractional discrepancies accumulate across thousands of line items, triggering false variances or masking small overcharges. Overcharge Desk enforces 100% `decimal.Decimal`.

---

### Q: What happens if an invoice has internal math errors (e.g. $10 \times 5,000 = 55,000$)?
**A**: Under Invariant Rule 1.4, the system never silently recalculates or corrects the vendor's numbers. It flags the line as `SOURCE_DISCREPANCY` and blocks automated payment fail-closed until an amended invoice is submitted.

---

### Q: How does the historical vendor memory feature work?
**A**: Historical memory is completely deterministic. When the Auditor Agent evaluates an invoice, it queries the SQLite ledger via `python tools/desk.py history --vendor <name>`. This recalls prior settled cases, dispute outcomes, and withheld amounts, alerting the owner if a vendor repeats an overcharge pattern.

