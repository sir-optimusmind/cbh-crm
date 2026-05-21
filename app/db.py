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
_MIGRATION_007 = Path(__file__).parent.parent / "migrations" / "006_stage_history.sql"
_MIGRATION_008 = Path(__file__).parent.parent / "migrations" / "007_verlust_reason_enum.sql"
_MIGRATION_009 = Path(__file__).parent.parent / "migrations" / "008_saved_view.sql"
_MIGRATION_010 = Path(__file__).parent.parent / "migrations" / "009_lost_competitor.sql"
_MIGRATION_012 = Path(__file__).parent.parent / "migrations" / "012_drive_folder_foundation.sql"
_MIGRATION_013 = Path(__file__).parent.parent / "migrations" / "013_ist_rechnungen_migration.sql"
_MIGRATION_012 = Path(__file__).parent.parent / "migrations" / "012_drive_folder_foundation.sql"
_MIGRATION_013 = Path(__file__).parent.parent / "migrations" / "013_ist_rechnungen_migration.sql"


def get_connection() -> sqlite3.Connection:
    """
    Gibt eine SQLite-Verbindung zurueck.
    WAL-Mode und Foreign Keys sind aktiviert.
    row_factory = sqlite3.Row fuer dict-aehnlichen Zugriff.
    busy_timeout=5000: wartet bis zu 5s bei locked DB, statt sofort OperationalError.
    """
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
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


def _run_migration_stage_history(conn: sqlite3.Connection) -> None:
    """
    Migration 006: deal_stage_history Tabelle + Indizes.
    CRM-055 | Sprint 3 Wave 3b.
    Idempotent via _table_exists-Check.
    """
    if _table_exists(conn, "deal_stage_history"):
        return
    if _MIGRATION_007.exists():
        conn.executescript(_MIGRATION_007.read_text(encoding="utf-8"))
        conn.commit()


def _run_migration_verlust_enum(conn: sqlite3.Connection) -> None:
    """
    Migration 007: verlust_reason_enum Spalte in deal.
    CRM-054 | Sprint 3 Wave 3b.
    Idempotent via _column_exists.
    """
    if not _column_exists(conn, "deal", "verlust_reason_enum"):
        conn.execute("ALTER TABLE deal ADD COLUMN verlust_reason_enum TEXT")
        conn.commit()



def _run_migration_saved_view(conn: sqlite3.Connection) -> None:
    """
    Migration 008: saved_view Tabelle + Index + UNIQUE constraint.
    CRM-061 | Sprint 3 Wave 3b.
    Idempotent via _table_exists.
    """
    if _table_exists(conn, "saved_view"):
        return
    if _MIGRATION_009.exists():
        conn.executescript(_MIGRATION_009.read_text(encoding="utf-8"))
        conn.commit()



def _run_migration_lost_competitor(conn: sqlite3.Connection) -> None:
    """
    Migration 009: lost_competitor Spalte in deal.
    CRM-BUG-006 | Sprint 3 Wave 3b.
    Idempotent via _column_exists.
    """
    if not _column_exists(conn, "deal", "lost_competitor"):
        conn.execute("ALTER TABLE deal ADD COLUMN lost_competitor TEXT")
        conn.commit()




def _run_migration_projekte_polish(conn: sqlite3.Connection) -> None:
    """
    Migration 011: Projekte-Polish – project_rechnung Tabelle,
    project.risiko_status, project.phase, touchpoint.project_id.
    CRM-072 + CRM-073 | Sprint 4 | 2026-05-20.
    Idempotent via _table_exists + _column_exists.
    """
    _MIGRATION_011 = Path(__file__).parent.parent / "migrations" / "011_projekte_polish.sql"

    # project_rechnung Tabelle anlegen
    if not _table_exists(conn, "project_rechnung"):
        if _MIGRATION_011.exists():
            conn.executescript(_MIGRATION_011.read_text(encoding="utf-8"))
            conn.commit()
        else:
            conn.execute("""CREATE TABLE IF NOT EXISTS project_rechnung (
              id          INTEGER PRIMARY KEY AUTOINCREMENT,
              project_id  INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
              datum       TEXT    NOT NULL,
              betrag      REAL    NOT NULL,
              notiz       TEXT,
              status      TEXT    NOT NULL DEFAULT 'offen'
                          CHECK(status IN ('offen','bezahlt','storniert')),
              created_at  TEXT    NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ','now'))
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_rechnung_project ON project_rechnung(project_id)")
            conn.commit()

    # project.risiko_status
    if not _column_exists(conn, "project", "risiko_status"):
        conn.execute("ALTER TABLE project ADD COLUMN risiko_status TEXT "
                     "CHECK(risiko_status IN ('gruen','gelb','rot') OR risiko_status IS NULL)")
        conn.commit()

    # project.phase
    if not _column_exists(conn, "project", "phase"):
        conn.execute("ALTER TABLE project ADD COLUMN phase TEXT "
                     "CHECK(phase IN ('kick_off','in_arbeit','review','abgeschlossen') OR phase IS NULL)")
        conn.commit()

    # touchpoint.project_id (CRM-073)
    if not _column_exists(conn, "touchpoint", "project_id"):
        conn.execute("ALTER TABLE touchpoint ADD COLUMN project_id INTEGER REFERENCES project(id) ON DELETE SET NULL")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_touchpoint_project ON touchpoint(project_id)")
        conn.commit()


# CRM-070 guard column for audit_log rebuild
def _audit_log_has_link_drive(conn: sqlite3.Connection) -> bool:
    """Prüft ob LINK_DRIVE bereits im audit_log CHECK-Constraint steht."""
    try:
        conn.execute("INSERT INTO audit_log (user, entity_type, entity_id, action) VALUES ('_test','_test',0,'LINK_DRIVE')")
        conn.execute("DELETE FROM audit_log WHERE entity_type='_test' AND action='LINK_DRIVE'")
        return True
    except sqlite3.IntegrityError:
        return False


def _run_migration_drive_folder_foundation(conn: sqlite3.Connection) -> None:
    """
    Migration 012: Drive-Folder-Felder in project + audit_log LINK_DRIVE Erweiterung.
    CRM-062 + CRM-070 | Sprint 4 | 2026-05-20.
    Idempotent via _column_exists + _audit_log_has_link_drive.
    """
    _MIGRATION_012 = Path(__file__).parent.parent / "migrations" / "012_drive_folder_foundation.sql"

    changed = False

    # CRM-062: Drive-Spalten in project
    if not _column_exists(conn, "project", "drive_folder_id"):
        conn.execute("ALTER TABLE project ADD COLUMN drive_folder_id   TEXT")
        changed = True
    if not _column_exists(conn, "project", "drive_folder_name"):
        conn.execute("ALTER TABLE project ADD COLUMN drive_folder_name TEXT")
        changed = True
    if not _column_exists(conn, "project", "drive_folder_url"):
        conn.execute("ALTER TABLE project ADD COLUMN drive_folder_url  TEXT")
        changed = True

    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_drive_folder_id ON project(drive_folder_id)")
    if changed:
        conn.commit()

    # CRM-070: audit_log CHECK-Constraint erweitern (Table-Rebuild wenn nötig)
    if not _audit_log_has_link_drive(conn):
        conn.executescript("""
CREATE TABLE audit_log_new (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
    user            TEXT    NOT NULL DEFAULT 'system',
    entity_type     TEXT    NOT NULL,
    entity_id       INTEGER NOT NULL,
    action          TEXT    NOT NULL CHECK(action IN ('CREATE', 'UPDATE', 'DELETE', 'LINK_DRIVE', 'WON_CELEBRATION')),
    changed_fields  TEXT,
    ip_address      TEXT,
    created_at      TEXT
);
INSERT INTO audit_log_new
    (id, timestamp, user, entity_type, entity_id, action, changed_fields, ip_address)
SELECT id, timestamp, user, entity_type, entity_id, action, changed_fields, ip_address
FROM audit_log;
DROP TABLE audit_log;
ALTER TABLE audit_log_new RENAME TO audit_log;
CREATE INDEX IF NOT EXISTS idx_audit_entity    ON audit_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
        """)
        conn.commit()


def _run_migration_ist_rechnungen(conn: sqlite3.Connection) -> None:
    """
    Migration 013: ist_rechnungen Legacy-Werte in project_rechnung migrieren.
    Kenny-Backlog Item 4 | Sprint 4 | 2026-05-20.
    Idempotent: nur Projekte ohne existierende project_rechnung-Einträge.
    Setzt Migration 011 (project_rechnung Tabelle) voraus.
    """
    if not _table_exists(conn, "project_rechnung"):
        return  # Migration 011 noch nicht gelaufen

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    rows = conn.execute(
        """SELECT id, ist_rechnungen FROM project
           WHERE ist_rechnungen > 0 AND deleted_at IS NULL
             AND NOT EXISTS (SELECT 1 FROM project_rechnung pr WHERE pr.project_id = project.id)"""
    ).fetchall()

    for row in rows:
        conn.execute(
            """INSERT INTO project_rechnung (project_id, datum, betrag, notiz, status, created_at)
               VALUES (?, ?, ?, 'Migration aus Legacy-Feld ist_rechnungen', 'offen', ?)""",
            (row["id"], ts, row["ist_rechnungen"], ts)
        )
        # Audit-Log für jede Migration (LINK_DRIVE noch nicht verfügbar, UPDATE verwenden)
        conn.execute(
            """INSERT INTO audit_log (user, entity_type, entity_id, action, changed_fields, ip_address)
               VALUES ('system', 'project_rechnung', ?, 'CREATE', ?, NULL)""",
            (row["id"],
             json.dumps({"migration": "013_ist_rechnungen",
                         "betrag": row["ist_rechnungen"],
                         "project_id": row["id"]}, ensure_ascii=False))
        )

    if rows:
        conn.commit()




def _audit_log_has_link_drive(conn):
    """Prüft ob LINK_DRIVE bereits im audit_log CHECK-Constraint steht (idempotent)."""
    try:
        conn.execute(
            "INSERT INTO audit_log (user, entity_type, entity_id, action) VALUES (?, ?, ?, ?)",
            ('_probe', '_probe', 0, 'LINK_DRIVE')
        )
        conn.execute("DELETE FROM audit_log WHERE entity_type='_probe' AND action='LINK_DRIVE'")
        return True
    except Exception:
        return False


def _run_migration_drive_folder_foundation(conn):
    """
    Migration 012: Drive-Folder-Felder in project + audit_log LINK_DRIVE Erweiterung.
    CRM-062 + CRM-070 | Sprint 4 | 2026-05-20.
    Idempotent via _column_exists + probe-Insert.
    """
    changed = False

    # CRM-062: Drive-Spalten in project
    if not _column_exists(conn, "project", "drive_folder_id"):
        conn.execute("ALTER TABLE project ADD COLUMN drive_folder_id   TEXT")
        changed = True
    if not _column_exists(conn, "project", "drive_folder_name"):
        conn.execute("ALTER TABLE project ADD COLUMN drive_folder_name TEXT")
        changed = True
    if not _column_exists(conn, "project", "drive_folder_url"):
        conn.execute("ALTER TABLE project ADD COLUMN drive_folder_url  TEXT")
        changed = True

    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_drive_folder_id ON project(drive_folder_id)")
    if changed:
        conn.commit()

    # CRM-070: audit_log CHECK-Constraint um LINK_DRIVE erweitern (Table-Rebuild wenn nötig)
    if not _audit_log_has_link_drive(conn):
        conn.executescript("""
CREATE TABLE audit_log_new (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
    user            TEXT    NOT NULL DEFAULT 'system',
    entity_type     TEXT    NOT NULL,
    entity_id       INTEGER NOT NULL,
    action          TEXT    NOT NULL CHECK(action IN ('CREATE', 'UPDATE', 'DELETE', 'LINK_DRIVE', 'WON_CELEBRATION')),
    changed_fields  TEXT,
    ip_address      TEXT,
    created_at      TEXT
);
INSERT INTO audit_log_new
    (id, timestamp, user, entity_type, entity_id, action, changed_fields, ip_address)
SELECT id, timestamp, user, entity_type, entity_id, action, changed_fields, ip_address
FROM audit_log;
DROP TABLE audit_log;
ALTER TABLE audit_log_new RENAME TO audit_log;
CREATE INDEX IF NOT EXISTS idx_audit_entity    ON audit_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
""")
        conn.commit()


def _run_migration_ist_rechnungen(conn):
    """
    Migration 013: ist_rechnungen Legacy-Werte in project_rechnung migrieren.
    Kenny-Backlog Item 4 | Sprint 4 | 2026-05-20.
    Idempotent: nur Projekte ohne existierende project_rechnung-Einträge.
    Setzt Migration 011 (project_rechnung Tabelle) voraus.
    """
    import json as _json
    from datetime import datetime, timezone

    if not _table_exists(conn, "project_rechnung"):
        return  # Migration 011 noch nicht gelaufen

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    rows = conn.execute(
        """SELECT id, ist_rechnungen FROM project
           WHERE ist_rechnungen > 0 AND deleted_at IS NULL
             AND NOT EXISTS (SELECT 1 FROM project_rechnung pr WHERE pr.project_id = project.id)"""
    ).fetchall()

    for row in rows:
        conn.execute(
            """INSERT INTO project_rechnung (project_id, datum, betrag, notiz, status, created_at)
               VALUES (?, ?, ?, ?, 'offen', ?)""",
            (row["id"], ts, row["ist_rechnungen"],
             "Migration aus Legacy-Feld ist_rechnungen", ts)
        )
        conn.execute(
            """INSERT INTO audit_log (user, entity_type, entity_id, action, changed_fields, ip_address)
               VALUES ('system', 'project_rechnung', ?, 'CREATE', ?, NULL)""",
            (row["id"],
             _json.dumps({"migration": "013_ist_rechnungen",
                          "betrag": row["ist_rechnungen"],
                          "project_id": row["id"]}, ensure_ascii=False))
        )

    if rows:
        conn.commit()



def _run_migration_kanban(conn: sqlite3.Connection) -> None:
    """
    Migration 014: MVG Bewerber-Kanban.
    Legt kanban_config, kanban_columns, applicants, applicant_comments,
    applicant_audit, magic_link Tabellen an (CREATE TABLE IF NOT EXISTS = idempotent).
    Erweitert crm_user um allowed_modules und external_role.
    """
    # crm_user: allowed_modules (Modul-Scope für externe Partner)
    if not _column_exists(conn, "crm_user", "allowed_modules"):
        conn.execute("ALTER TABLE crm_user ADD COLUMN allowed_modules TEXT DEFAULT ''")
        conn.commit()

    # crm_user: external_role (NULL = CBH-intern, 'external_partner' = MVG-Partner)
    # Umgeht CHECK-Constraint-Konflikt auf role-Spalte
    if not _column_exists(conn, "crm_user", "external_role"):
        conn.execute("ALTER TABLE crm_user ADD COLUMN external_role TEXT DEFAULT NULL")
        conn.commit()

    # crm_user: last_seen_at (falls noch nicht vorhanden – Migration 005/006 evtl. nicht gelaufen)
    if not _column_exists(conn, "crm_user", "last_seen_at"):
        conn.execute("ALTER TABLE crm_user ADD COLUMN last_seen_at TEXT DEFAULT NULL")
        conn.commit()

    # Kanban-Tabellen aus SQL-File
    _MIGRATION_014 = Path(__file__).parent.parent / "migrations" / "014_kanban.sql"
    if _MIGRATION_014.exists():
        conn.executescript(_MIGRATION_014.read_text(encoding="utf-8"))
        conn.commit()
    else:
        import logging
        logging.getLogger(__name__).warning("Migration 014 SQL nicht gefunden: %s", _MIGRATION_014)

def _run_migration_kanban_hardening(conn: sqlite3.Connection) -> None:
    """
    Migration 015: Kanban Audit Hardening.
    K-BUG-004: DELETE-Trigger auf applicants (ISO append-only Garantie).
    K-BUG-005: user_email Spalte in applicant_audit (Doku-Konsistenz).
    Idempotent: CREATE TRIGGER IF NOT EXISTS + _column_exists.
    """
    _MIGRATION_015 = Path(__file__).parent.parent / "migrations" / "015_kanban_audit_hardening.sql"
    if _MIGRATION_015.exists():
        conn.executescript(_MIGRATION_015.read_text(encoding="utf-8"))
        conn.commit()

    # K-BUG-005: user_email Spalte in applicant_audit ergänzen
    if not _column_exists(conn, "applicant_audit", "user_email"):
        conn.execute("ALTER TABLE applicant_audit ADD COLUMN user_email TEXT")
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
        _run_migration_stage_history(conn)
        _run_migration_verlust_enum(conn)
        _run_migration_saved_view(conn)
        _run_migration_lost_competitor(conn)
        _run_migration_projekte_polish(conn)
        _run_migration_drive_folder_foundation(conn)
        _run_migration_ist_rechnungen(conn)
        _run_migration_kanban(conn)
        _run_migration_kanban_hardening(conn)
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
