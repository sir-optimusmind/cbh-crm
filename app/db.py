"""
db.py – CRM Datenbankschicht
Verantwortlich fuer:
  - DB-Verbindung mit WAL + Foreign Keys
  - Automatische Schema-Anlage beim App-Start (idempotent via CREATE TABLE IF NOT EXISTS)
  - audit_log-Hilfsfunktion fuer alle Schreib-Operationen
  - Migration 002: stimmung + last_contact_at (idempotent via PRAGMA table_info)
"""

import os
import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path


# ─── Pfad-Konfiguration ───────────────────────────────────────────────────────
# CRM_DB_PATH kommt aus .env (nie hardcoden).
# Fallback: neben diesem Script – sicher fuer lokale Entwicklung.
_DEFAULT_DB_PATH = Path(__file__).parent.parent / "crm.db"
DB_PATH = os.getenv("CRM_DB_PATH", str(_DEFAULT_DB_PATH))

# Pfad zu den Migrations-Files (relativ zu diesem Modul)
_MIGRATION_001 = Path(__file__).parent.parent / "migrations" / "001_initial_schema.sql"
_MIGRATION_002 = Path(__file__).parent.parent / "migrations" / "002_stimmung_field.sql"


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


def _run_migration_002(conn: sqlite3.Connection) -> None:
    """
    Migration 002: Fügt stimmung + last_contact_at zur person-Tabelle hinzu.
    Idempotent: prüft via PRAGMA table_info ob Spalten bereits existieren.
    Guard-Tabelle verhindert mehrfaches Anlegen von Indizes.
    """
    # Guard prüfen
    guard_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='_migration_002_guard'"
    ).fetchone()

    already_applied = False
    if guard_exists:
        already_applied = conn.execute(
            "SELECT 1 FROM _migration_002_guard WHERE applied='002_stimmung_last_contact'"
        ).fetchone() is not None

    # Spalte stimmung hinzufügen (falls fehlt)
    if not _column_exists(conn, "person", "stimmung"):
        conn.execute(
            "ALTER TABLE person ADD COLUMN stimmung TEXT NOT NULL DEFAULT 'kalt' "
            "CHECK(stimmung IN ('kalt', 'warm', 'heiss'))"
        )

    # Spalte last_contact_at hinzufügen (falls fehlt)
    if not _column_exists(conn, "person", "last_contact_at"):
        conn.execute(
            "ALTER TABLE person ADD COLUMN last_contact_at TEXT"  # NULL = nie Kontakt
        )

    # Migration-File ausführen (Indizes + Guard-Tabelle anlegen)
    if _MIGRATION_002.exists():
        conn.executescript(_MIGRATION_002.read_text(encoding="utf-8"))

    # Guard setzen
    conn.execute(
        "INSERT OR IGNORE INTO _migration_002_guard (applied) VALUES ('002_stimmung_last_contact')"
    )
    conn.commit()


def init_db() -> None:
    """
    Legt alle Tabellen an falls noch nicht vorhanden.
    Idempotent – kann bei jedem App-Start aufgerufen werden.
    Liest das Migrations-File und fuehrt es aus.
    """
    if not _MIGRATION_001.exists():
        raise RuntimeError(f"Migrations-File nicht gefunden: {_MIGRATION_001}")

    migration_sql = _MIGRATION_001.read_text(encoding="utf-8")
    conn = get_connection()
    try:
        conn.executescript(migration_sql)
        conn.commit()
        # Migration 002 ausführen
        _run_migration_002(conn)
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

    Wird aus jeder Route aufgerufen die Daten schreibt (CREATE/UPDATE/DELETE).
    PFLICHT gemaess ISO-Anforderung und CRM-001 Akzeptanzkriterien.

    Args:
        conn:           Aktive DB-Verbindung (innerhalb einer Transaktion nutzbar)
        user:           Identitaet des ausfuehrenden Nutzers (aus Session/Auth)
        entity_type:    'person' | 'unternehmen' | 'person_unternehmen'
        entity_id:      PK des betroffenen Datensatzes
        action:         'CREATE' | 'UPDATE' | 'DELETE'
        changed_fields: Dict mit geaenderten Feldern (bei CREATE: vollstaendiger Datensatz)
        ip_address:     Client-IP aus Request (optional)
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
