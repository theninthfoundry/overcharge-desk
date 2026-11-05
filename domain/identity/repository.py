"""Persistent identity repository using SQLite (with PostgreSQL compatibility design)."""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from common import ToolError, utc_now_iso

DEFAULT_IDENTITY_DB = Path("identity.db")


@dataclass
class UserRecord:
    user_id: str
    username: str
    email: str
    full_name: str
    role: str
    password_hash: str
    is_active: bool = True
    is_demo: bool = False
    password_changed_at: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
    version: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SessionRecord:
    session_id: str
    user_id: str
    token_hash: str
    created_at: str
    expires_at: str
    last_used_at: str
    revoked_at: Optional[str] = None

    @property
    def is_valid(self) -> bool:
        if self.revoked_at is not None:
            return False
        return utc_now_iso() < self.expires_at


class IdentityRepository:
    """Manages persistent users and cryptographically hashed sessions."""

    def __init__(self, db_path: Path | str = DEFAULT_IDENTITY_DB):
        self.db_path = Path(db_path)
        self.init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Obtain a transactional SQLite connection with WAL mode and foreign key integrity.
        
        Guarantees:
        - PRAGMA foreign_keys = ON: Ensures session records reference valid users.
        - PRAGMA journal_mode = WAL: Write-Ahead Logging allows concurrent readers and writers without lock contention.
        - timeout = 30.0: Bounded wait time prevents indefinite blocking on busy locks.
        """
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    def init_db(self) -> None:
        """Create users and sessions tables."""
        conn = self._get_connection()
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    full_name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    is_demo INTEGER NOT NULL DEFAULT 0,
                    password_changed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users (username);")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    token_hash TEXT UNIQUE NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    last_used_at TEXT NOT NULL,
                    revoked_at TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions (token_hash);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions (user_id);")
        conn.close()

    def create_user(
        self,
        user_id: str,
        username: str,
        email: str,
        full_name: str,
        role: str,
        password_hash: str,
        is_active: bool = True,
        is_demo: bool = False,
    ) -> UserRecord:
        now = utc_now_iso()
        conn = self._get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO users (
                        user_id, username, email, full_name, role, password_hash,
                        is_active, is_demo, password_changed_at, created_at, updated_at, version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        user_id,
                        username.lower(),
                        email.lower(),
                        full_name,
                        role,
                        password_hash,
                        1 if is_active else 0,
                        1 if is_demo else 0,
                        now,
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ToolError(f"User creation failed: username or email already exists ({exc})", 2)
        finally:
            conn.close()

        return UserRecord(
            user_id=user_id,
            username=username.lower(),
            email=email.lower(),
            full_name=full_name,
            role=role,
            password_hash=password_hash,
            is_active=is_active,
            is_demo=is_demo,
            password_changed_at=now,
            created_at=now,
            updated_at=now,
            version=1,
        )

    def get_user_by_username(self, username: str) -> Optional[UserRecord]:
        conn = self._get_connection()
        try:
            cur = conn.execute("SELECT * FROM users WHERE username = ?", (username.lower(),))
            row = cur.fetchone()
            if not row:
                return None
            return UserRecord(
                user_id=row["user_id"],
                username=row["username"],
                email=row["email"],
                full_name=row["full_name"],
                role=row["role"],
                password_hash=row["password_hash"],
                is_active=bool(row["is_active"]),
                is_demo=bool(row["is_demo"]),
                password_changed_at=row["password_changed_at"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                version=row["version"],
            )
        finally:
            conn.close()

    def get_user_by_id(self, user_id: str) -> Optional[UserRecord]:
        conn = self._get_connection()
        try:
            cur = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
            if not row:
                return None
            return UserRecord(
                user_id=row["user_id"],
                username=row["username"],
                email=row["email"],
                full_name=row["full_name"],
                role=row["role"],
                password_hash=row["password_hash"],
                is_active=bool(row["is_active"]),
                is_demo=bool(row["is_demo"]),
                password_changed_at=row["password_changed_at"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                version=row["version"],
            )
        finally:
            conn.close()

    def update_password(self, user_id: str, new_password_hash: str) -> None:
        """Update password and invalidate existing sessions."""
        now = utc_now_iso()
        conn = self._get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    UPDATE users
                    SET password_hash = ?, password_changed_at = ?, updated_at = ?, version = version + 1
                    WHERE user_id = ?
                    """,
                    (new_password_hash, now, now, user_id),
                )
                # Invalidate all existing sessions on password change
                conn.execute(
                    "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                    (now, user_id),
                )
        finally:
            conn.close()

    def set_user_active(self, user_id: str, is_active: bool) -> None:
        now = utc_now_iso()
        conn = self._get_connection()
        try:
            with conn:
                conn.execute(
                    "UPDATE users SET is_active = ?, updated_at = ?, version = version + 1 WHERE user_id = ?",
                    (1 if is_active else 0, now, user_id),
                )
                if not is_active:
                    conn.execute(
                        "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                        (now, user_id),
                    )
        finally:
            conn.close()

    def create_session(
        self,
        session_id: str,
        user_id: str,
        token_hash: str,
        expires_at: str,
    ) -> SessionRecord:
        now = utc_now_iso()
        conn = self._get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO sessions (
                        session_id, user_id, token_hash, created_at, expires_at, last_used_at, revoked_at
                    ) VALUES (?, ?, ?, ?, ?, ?, NULL)
                    """,
                    (session_id, user_id, token_hash, now, expires_at, now),
                )
        finally:
            conn.close()

        return SessionRecord(
            session_id=session_id,
            user_id=user_id,
            token_hash=token_hash,
            created_at=now,
            expires_at=expires_at,
            last_used_at=now,
        )

    def get_session_by_token_hash(self, token_hash: str) -> Optional[SessionRecord]:
        conn = self._get_connection()
        try:
            cur = conn.execute("SELECT * FROM sessions WHERE token_hash = ?", (token_hash,))
            row = cur.fetchone()
            if not row:
                return None
            return SessionRecord(
                session_id=row["session_id"],
                user_id=row["user_id"],
                token_hash=row["token_hash"],
                created_at=row["created_at"],
                expires_at=row["expires_at"],
                last_used_at=row["last_used_at"],
                revoked_at=row["revoked_at"],
            )
        finally:
            conn.close()

    def touch_session(self, session_id: str) -> None:
        now = utc_now_iso()
        conn = self._get_connection()
        try:
            with conn:
                conn.execute("UPDATE sessions SET last_used_at = ? WHERE session_id = ?", (now, session_id))
        finally:
            conn.close()

    def revoke_session(self, session_id: str) -> None:
        now = utc_now_iso()
        conn = self._get_connection()
        try:
            with conn:
                conn.execute("UPDATE sessions SET revoked_at = ? WHERE session_id = ?", (now, session_id))
        finally:
            conn.close()

    def revoke_all_user_sessions(self, user_id: str) -> None:
        now = utc_now_iso()
        conn = self._get_connection()
        try:
            with conn:
                conn.execute(
                    "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                    (now, user_id),
                )
        finally:
            conn.close()

    def check_production_safety(self, app_env: str = "development") -> None:
        """Refuse startup in production if active demo accounts exist."""
        if app_env.lower() == "production":
            conn = self._get_connection()
            try:
                cur = conn.execute("SELECT COUNT(*) AS cnt FROM users WHERE is_demo = 1 AND is_active = 1")
                row = cur.fetchone()
                if row and row["cnt"] > 0:
                    raise ToolError(
                        f"FATAL: Production startup refused: {row['cnt']} active demo account(s) detected in database. "
                        "Demo accounts are prohibited in production environment.",
                        4,
                    )
            finally:
                conn.close()

