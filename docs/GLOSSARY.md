# Overcharge Desk Glossary & Domain Terminology

> **Authority**: Overcharge Desk Financial & Cryptographic Terminology

---

### Credit Note States
- **PROMISED**: A credit note verbally agreed to or mentioned in email correspondence, but no formal legal document has been received.
- **RECEIVED**: A formal credit note artifact is in possession and cryptographically fingerprinted.
- **APPLIED**: A received credit note has been deducted from an authorized disbursement run.
- **OUTSTANDING**: A credit note that is either PROMISED or RECEIVED but has not yet been APPLIED to a payment run.

### Financial Amounts
- **Stated Total**: The raw grand total indicated on the supplier's source invoice.
- **Reconciled Goods Subtotal**: The mathematically verified total for items matched against contracted terms.
- **Withheld Amount**: The total variance deducted from payment due to rate overcharges or quarantined items.
- **Payable Amount**: The final disbursement sum authorized for payment after deductions.

### Security & Operational Terms
- **Fail-Closed**: An architectural principle where any error, missing file, hash mismatch, or ambiguity immediately halts execution rather than falling back to permissive defaults.
- **Tamper-Evident**: A storage guarantee wherein any alteration, deletion, or insertion of data breaks a cryptographic hash chain and is immediately flagged upon audit.
- **Interactive TTY Gate**: An enforcement mechanism (`sys.stdin.isatty()`) requiring a live human terminal session for entering approval credentials.
- **Separation of Duties**: An organizational security control ensuring agents who analyze invoices cannot approve disbursements.
- **Schedule A**: The contractual item catalog detailing authorized SKUs, descriptions, unit rates, and pricing tiers.
