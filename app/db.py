"""
db.py – CRM Datenbankschicht
Verantwortlich fuer:
  - DB-Verbindung mit WAL + Foreign Keys
  - Automatische Schema-Anlage beim App-Start (idempotent via CREATE TABLE IF NOT EXISTS)
  - audit_log-Hilfsfunktion fuer alle Schreib-Operationen
  - Migration 002: stimmung + last_contact_at (idempotent via PRAGMA table_info)
  - Migration 003: Sprint-2-Schema (deal, touchpoint, project, stage_definition)
"""

import os
import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path


# ─── Pfad-Konfiguration ───────────────────────────────────────────────────────
_DEFAULT_DB_PATH = Path(__file__).parent.parent / "crm.db"
DB_PATH = os.getenv("CRM_DB_PATH", str(_DEFAULT_DB_PATH))

_MIGRATION_001 = Path(__file__).parent.parent / "migrations" / "001_initial_schema.sql"
_MIGRATION_002 = Path(__file__).parent.parent / "migrations" / "002_stimmung_field.sql"
_MIGRATION_003 = Path(__file__).parent.parent / "migrations" / "002_sprint2_schema.sql"


def get_connection() -> sqlite3.Connection:
    """
    Gibt eine SQLite-Verbindung zurueck.
    WAL-Mode und Foreign Keys sind aktiviert.
    row_factory = sqlite3.Row fuer dict-aehnlichen Zugriff.
    """
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Prüft via PRAGMA table_info ob eine Spalte existiert. SQLite-sicher."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    """Prüft ob eine Tabelle existiert."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _run_migration_002(conn: sqlite3.Connection) -> None:
    """
    Migration 002: Fügt stimmung + last_contact_at zur person-Tabelle hinzu.
    Idempotent: prüft via PRAGMA table_info ob Spalten bereits existieren.
    """
    guard_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='_migration_002_guard'"
    ).fetchone()

    if guard_exists:
        already_applied = conn.execute(
            "SELECT 1 FROM _migration_002_guard WHERE applied='002_stimmung_last_contact'"
        ).fetchone() is not None
        if already_applied:
            return

    if not _column_exists(conn, "person", "stimmung"):
        conn.execute(
            "ALTER TABLE person ADD COLUMN stimmung TEXT NOT NULL DEFAULT 'kalt' "
            "CHECK(stimmung IN ('kalt', 'warm', 'heiss'))"
        )

    if not _column_exists(conn, "person", "last_contact_at"):
        conn.execute(
            "ALTER TABLE person ADD COLUMN last_contact_at TEXT"
        )

    if _MIGRATION_002.exists():
        conn.executescript(_MIGRATION_002.read_text(encoding="utf-8"))

    conn.execute(
        "INSERT OR IGNORE INTO _migration_002_guard (applied) VALUES ('002_stimmung_last_contact')"
    )
    conn.commit()


def _run_migration_sprint2(conn: sqlite3.Connection) -> None:
    """
    Migration Sprint-2: deal, deal_product, touchpoint, project, stage_definition.
    Idempotent via _migration_002_guard mit Key '002_sprint2_schema'.
    """
    # Guard prüfen
    guard_exists = _table_exists(conn, "_migration_002_guard")
    if guard_exists:
        already = conn.execute(
            "SELECT 1 FROM _migration_002_guard WHERE applied='002_sprint2_schema'"
        ).fetchone()
        if already:
            return

    if _MIGRATION_003.exists():
        conn.executescript(_MIGRATION_003.read_text(encoding="utf-8"))
        conn.commit()


def init_db() -> None:
    """
    Legt alle Tabellen an falls noch nicht vorhanden.
    Idempotent – kann bei jedem App-Start aufgerufen werden.
    """
    if not _MIGRATION_001.exists():
        raise RuntimeError(f"Migrations-File nicht gefunden: {_MIGRATION_001}")

    migration_sql = _MIGRATION_001.read_text(encoding="utf-8")
    conn = get_connection()
    try:
        conn.executescript(migration_sql)
        conn.commit()
        _run_migration_002(conn)
        _run_migration_sprint2(conn)
    finally:
        conn.close()


# ─── audit_log Hilfsfunktion ──────────────────────────────────────────────────

def write_audit_log(
    conn: sqlite3.Connection,
    *,
    user: str,
    entity_type: str,
    entity_id: int,
    action: str,
    changed_fields: dict | None = None,
    ip_address: str | None = None,
) -> None:
    """
    Schreibt einen Eintrag in audit_log.
    PFLICHT gemaess ISO-Anforderung fuer alle Schreib-Operationen.
    """
    conn.execute(
        """
        INSERT INTO audit_log (user, entity_type, entity_id, action, changed_fields, ip_address)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            user,
            entity_type,
            entity_id,
            action,
            json.dumps(changed_fields, ensure_ascii=False, default=str) if changed_fields else None,
            ip_address,
        ),
    )


def now_iso() -> str:
    """Gibt aktuellen UTC-Timestamp als ISO8601-String zurueck."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
