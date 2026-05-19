"""
db.py – CRM Datenbankschicht
Verantwortlich fuer:
  - DB-Verbindung mit WAL + Foreign Keys
  - Automatische Schema-Anlage beim App-Start (idempotent via CREATE TABLE IF NOT EXISTS)
  - audit_log-Hilfsfunktion fuer alle Schreib-Operationen
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

# Pfad zum Migrations-File (relativ zu diesem Modul)
_MIGRATION_FILE = Path(__file__).parent.parent / "migrations" / "001_initial_schema.sql"


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


def init_db() -> None:
    """
    Legt alle Tabellen an falls noch nicht vorhanden.
    Idempotent – kann bei jedem App-Start aufgerufen werden.
    Liest das Migrations-File und fuehrt es aus.
    """
    if not _MIGRATION_FILE.exists():
        raise RuntimeError(f"Migrations-File nicht gefunden: {_MIGRATION_FILE}")

    migration_sql = _MIGRATION_FILE.read_text(encoding="utf-8")
    conn = get_connection()
    try:
        conn.executescript(migration_sql)
        conn.commit()
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
