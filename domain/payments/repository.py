"""Payment Instruction repository backed by SQLite."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Dict, List, Optional

from common import ToolError, utc_now_iso
from domain.payments.models import PaymentInstruction, PaymentInstructionStatus

DEFAULT_PAYMENT_DB = Path("payments.db")


class PaymentRepository:
    def __init__(self, db_path: Path | str = DEFAULT_PAYMENT_DB):
        self.db_path = Path(db_path)
        self.init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    def init_db(self) -> None:
        conn = self._get_connection()
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS payment_instructions (
                    instruction_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    approval_receipt_id TEXT UNIQUE NOT NULL,
                    approved_amount TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    vendor_id TEXT NOT NULL,
                    destination_reference TEXT NOT NULL,
                    destination_verified INTEGER NOT NULL,
                    idempotency_key TEXT UNIQUE NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    exported_at TEXT,
                    exported_by TEXT,
                    cancelled_at TEXT,
                    cancellation_reason TEXT
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pi_case ON payment_instructions (case_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pi_idem ON payment_instructions (idempotency_key);")
        conn.close()

    def create_instruction(self, inst: PaymentInstruction) -> PaymentInstruction:
        conn = self._get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO payment_instructions (
                        instruction_id, case_id, approval_receipt_id, approved_amount,
                        currency, vendor_id, destination_reference, destination_verified,
                        idempotency_key, status, created_at, expires_at, exported_at,
                        exported_by, cancelled_at, cancellation_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        inst.instruction_id,
                        inst.case_id,
                        inst.approval_receipt_id,
                        inst.approved_amount,
                        inst.currency,
                        inst.vendor_id,
                        inst.destination_reference,
                        1 if inst.destination_verified else 0,
                        inst.idempotency_key,
                        inst.status,
                        inst.created_at,
                        inst.expires_at,
                        inst.exported_at,
                        inst.exported_by,
                        inst.cancelled_at,
                        inst.cancellation_reason,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ToolError(f"Payment instruction creation failed: unique constraint violated ({exc})", 2)
        finally:
            conn.close()
        return inst

    def get_by_id(self, instruction_id: str) -> Optional[PaymentInstruction]:
        conn = self._get_connection()
        try:
            cur = conn.execute("SELECT * FROM payment_instructions WHERE instruction_id = ?", (instruction_id,))
            row = cur.fetchone()
            if not row:
                return None
            return self._row_to_obj(row)
        finally:
            conn.close()

    def get_by_approval_receipt_id(self, receipt_id: str) -> Optional[PaymentInstruction]:
        conn = self._get_connection()
        try:
            cur = conn.execute("SELECT * FROM payment_instructions WHERE approval_receipt_id = ?", (receipt_id,))
            row = cur.fetchone()
            if not row:
                return None
            return self._row_to_obj(row)
        finally:
            conn.close()

    def get_by_idempotency_key(self, idempotency_key: str) -> Optional[PaymentInstruction]:
        conn = self._get_connection()
        try:
            cur = conn.execute("SELECT * FROM payment_instructions WHERE idempotency_key = ?", (idempotency_key,))
            row = cur.fetchone()
            if not row:
                return None
            return self._row_to_obj(row)
        finally:
            conn.close()

    def list_all(self) -> List[PaymentInstruction]:
        conn = self._get_connection()
        try:
            cur = conn.execute("SELECT * FROM payment_instructions ORDER BY created_at DESC")
            rows = cur.fetchall()
            return [self._row_to_obj(r) for r in rows]
        finally:
            conn.close()

    def mark_exported(self, instruction_id: str, exported_by: str) -> PaymentInstruction:
        now = utc_now_iso()
        conn = self._get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    UPDATE payment_instructions
                    SET status = ?, exported_at = ?, exported_by = ?
                    WHERE instruction_id = ?
                    """,
                    (PaymentInstructionStatus.EXPORTED, now, exported_by, instruction_id),
                )
        finally:
            conn.close()
        inst = self.get_by_id(instruction_id)
        if not inst:
            raise ToolError(f"Instruction '{instruction_id}' not found", 2)
        return inst

    def mark_cancelled(self, instruction_id: str, reason: str) -> PaymentInstruction:
        now = utc_now_iso()
        conn = self._get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    UPDATE payment_instructions
                    SET status = ?, cancelled_at = ?, cancellation_reason = ?
                    WHERE instruction_id = ?
                    """,
                    (PaymentInstructionStatus.CANCELLED, now, reason, instruction_id),
                )
        finally:
            conn.close()
        inst = self.get_by_id(instruction_id)
        if not inst:
            raise ToolError(f"Instruction '{instruction_id}' not found", 2)
        return inst

    def _row_to_obj(self, row: sqlite3.Row) -> PaymentInstruction:
        return PaymentInstruction(
            instruction_id=row["instruction_id"],
            case_id=row["case_id"],
            approval_receipt_id=row["approval_receipt_id"],
            approved_amount=row["approved_amount"],
            currency=row["currency"],
            vendor_id=row["vendor_id"],
            destination_reference=row["destination_reference"],
            destination_verified=bool(row["destination_verified"]),
            idempotency_key=row["idempotency_key"],
            status=row["status"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            exported_at=row["exported_at"],
            exported_by=row["exported_by"],
            cancelled_at=row["cancelled_at"],
            cancellation_reason=row["cancellation_reason"],
        )

