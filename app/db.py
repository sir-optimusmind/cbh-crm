"""
db.py – CRM Datenbankschicht
Verantwortlich fuer:
  - DB-Verbindung mit WAL + Foreign Keys
  - Automatische Schema-Anlage beim App-Start (idempotent via CREATE TABLE IF NOT EXISTS)
  - audit_log-Hilfsfunktion fuer alle Schreib-Operationen
  - Migration 002: stimmung + last_contact_at (idempotent via PRAGMA table_info)
  - Migration Sprint-2: deal, touchpoint, project, stage_definition
  - Migration 003: Vision-Felder Sprint 2 (Person + Unternehmen Detail)
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
_MIGRATION_004 = Path(__file__).parent.parent / "migrations" / "003_vision_fields.sql"
_MIGRATION_005 = Path(__file__).parent.parent / "migrations" / "004_user_allowlist.sql"
_MIGRATION_006 = Path(__file__).parent.parent / "migrations" / "005_presence.sql"


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


def _run_migration_vision(conn: sqlite3.Connection) -> None:
    """
    Migration 003: Vision-Felder fuer Person + Unternehmen.
    Neue Spalten: karriere_stationen, stimmung_cbh, persoenlichkeit_notizen,
                  umsatz_gesamt_cbh, linkedin_url, linkedin_trigger_notiz,
                  linkedin_trigger_datum (Person);
                  sense_of_urgency, sense_of_opportunity, umsatz_mio,
                  rentabilitaet_notiz, wachstum_notiz, news_json,
                  produkt_empfehlung, produkt_empfehlung_sekundaer,
                  eigentuemerstruktur, cbh_umsatz_gesamt (Unternehmen).
    Idempotent via _migration_003_guard.
    """
    guard_exists = _table_exists(conn, "_migration_003_guard")
    if guard_exists:
        already = conn.execute(
            "SELECT 1 FROM _migration_003_guard WHERE applied='003_vision_fields'"
        ).fetchone()
        if already:
            return

    # ── Person: neue Spalten ──────────────────────────────────────────────────
    _person_cols = [
        ("karriere_stationen",     "ALTER TABLE person ADD COLUMN karriere_stationen TEXT"),
        ("stimmung_cbh",           "ALTER TABLE person ADD COLUMN stimmung_cbh TEXT "
                                   "CHECK(stimmung_cbh IN ('sehr_positiv','positiv','neutral','skeptisch','negativ') OR stimmung_cbh IS NULL)"),
        ("persoenlichkeit_notizen","ALTER TABLE person ADD COLUMN persoenlichkeit_notizen TEXT"),
        ("umsatz_gesamt_cbh",      "ALTER TABLE person ADD COLUMN umsatz_gesamt_cbh REAL"),
        ("linkedin_url",           "ALTER TABLE person ADD COLUMN linkedin_url TEXT"),
        ("linkedin_trigger_notiz", "ALTER TABLE person ADD COLUMN linkedin_trigger_notiz TEXT"),
        ("linkedin_trigger_datum", "ALTER TABLE person ADD COLUMN linkedin_trigger_datum TEXT"),
    ]
    for col_name, sql in _person_cols:
        if not _column_exists(conn, "person", col_name):
            conn.execute(sql)

    # ── Unternehmen: neue Spalten ─────────────────────────────────────────────
    _PRODUKT_ENUM = (
        "CHECK(produkt_empfehlung IN ('race','blindspot','okr_training','pm_training',"
        "'innovation_cell','visionsworkshop','empower_os','tm','other') OR produkt_empfehlung IS NULL)"
    )
    _PRODUKT2_ENUM = (
        "CHECK(produkt_empfehlung_sekundaer IN ('race','blindspot','okr_training','pm_training',"
        "'innovation_cell','visionsworkshop','empower_os','tm','other') OR produkt_empfehlung_sekundaer IS NULL)"
    )
    _unt_cols = [
        ("sense_of_urgency",             "ALTER TABLE unternehmen ADD COLUMN sense_of_urgency TEXT"),
        ("sense_of_opportunity",         "ALTER TABLE unternehmen ADD COLUMN sense_of_opportunity TEXT"),
        ("umsatz_mio",                   "ALTER TABLE unternehmen ADD COLUMN umsatz_mio REAL"),
        ("rentabilitaet_notiz",          "ALTER TABLE unternehmen ADD COLUMN rentabilitaet_notiz TEXT"),
        ("wachstum_notiz",               "ALTER TABLE unternehmen ADD COLUMN wachstum_notiz TEXT"),
        ("news_json",                    "ALTER TABLE unternehmen ADD COLUMN news_json TEXT"),
        ("produkt_empfehlung",           f"ALTER TABLE unternehmen ADD COLUMN produkt_empfehlung TEXT {_PRODUKT_ENUM}"),
        ("produkt_empfehlung_sekundaer", f"ALTER TABLE unternehmen ADD COLUMN produkt_empfehlung_sekundaer TEXT {_PRODUKT2_ENUM}"),
        ("eigentuemerstruktur",          "ALTER TABLE unternehmen ADD COLUMN eigentuemerstruktur TEXT"),
        ("cbh_umsatz_gesamt",            "ALTER TABLE unternehmen ADD COLUMN cbh_umsatz_gesamt REAL"),
        ("hauptsitz",                    "ALTER TABLE unternehmen ADD COLUMN hauptsitz TEXT"),
        ("muttergesellschaft",           "ALTER TABLE unternehmen ADD COLUMN muttergesellschaft TEXT"),
    ]
    for col_name, sql in _unt_cols:
        if not _column_exists(conn, "unternehmen", col_name):
            conn.execute(sql)

    # ── touchpoint: details-Feld ──────────────────────────────────────────────
    if not _column_exists(conn, "touchpoint", "details"):
        conn.execute("ALTER TABLE touchpoint ADD COLUMN details TEXT")

    # ── Guard setzen + idempotente Indizes ────────────────────────────────────
    if _MIGRATION_004.exists():
        conn.executescript(_MIGRATION_004.read_text(encoding="utf-8"))

    conn.execute(
        "INSERT OR IGNORE INTO _migration_003_guard (applied) VALUES ('003_vision_fields')"
    )
    conn.commit()



def _run_migration_user_allowlist(conn: sqlite3.Connection) -> None:
    """
    Migration 004: User-Allowlist fuer SSO (Sprint 3 CRM-031/033).
    Tabelle crm_user mit Roles + Initial-Seed.
    Idempotent via _migration_004_guard.
    """
    guard_exists = _table_exists(conn, "_migration_004_guard")
    if guard_exists:
        already = conn.execute(
            "SELECT 1 FROM _migration_004_guard WHERE applied='004_user_allowlist'"
        ).fetchone()
        if already:
            return

    if _MIGRATION_005.exists():
        conn.executescript(_MIGRATION_005.read_text(encoding="utf-8"))
        conn.commit()


def _run_migration_presence(conn: sqlite3.Connection) -> None:
    """
    Migration 005: last_seen_at auf crm_user fuer Presence-Tracking.
    Idempotent via _migration_005_guard + _column_exists.
    """
    guard_exists = _table_exists(conn, "_migration_005_guard")
    if guard_exists:
        already = conn.execute(
            "SELECT 1 FROM _migration_005_guard WHERE applied='005_presence'"
        ).fetchone()
        if already:
            # Guard schon gesetzt – trotzdem Spalte prüfen (Sicherheitsnetz)
            if not _column_exists(conn, "crm_user", "last_seen_at"):
                conn.execute("ALTER TABLE crm_user ADD COLUMN last_seen_at TEXT")
                conn.commit()
            return

    if not _column_exists(conn, "crm_user", "last_seen_at"):
        conn.execute("ALTER TABLE crm_user ADD COLUMN last_seen_at TEXT")

    if _MIGRATION_006.exists():
        conn.executescript(_MIGRATION_006.read_text(encoding="utf-8"))

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
        _run_migration_vision(conn)
        _run_migration_user_allowlist(conn)
        _run_migration_presence(conn)
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
