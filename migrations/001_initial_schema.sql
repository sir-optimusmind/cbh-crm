-- ============================================================
-- CRM MISSION CTRL – Migration 001: Initial Schema
-- Sprint 1 | 19.05.2026
-- Story: CRM-001
-- ============================================================
-- Konventionen:
--   - WAL-Mode und Foreign Keys werden beim App-Start via PRAGMA gesetzt
--   - Enums als CHECK CONSTRAINTS (kein separates Lookup-Table)
--   - Soft-Delete via deleted_at (kein physisches Löschen)
--   - audit_log wird aus der App befüllt (nicht via DB-Trigger, transparenter)
--   - Alle created_at/updated_at DEFAULT CURRENT_TIMESTAMP (ISO8601)
-- ============================================================

-- ─── Tabelle: unternehmen ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS unternehmen (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    branche     TEXT    CHECK(branche IN (
                    'Automotive',
                    'Maschinenbau',
                    'Fertigende-Industrie',
                    'IT-Digital',
                    'Energiewirtschaft',
                    'Other'
                )),
    groesse_ma  INTEGER,                        -- Anzahl Mitarbeiter, nullable
    website     TEXT,
    notes       TEXT,
    deleted_at  TEXT,                           -- ISO8601, NULL = aktiv (Soft-Delete)
    created_by  TEXT    NOT NULL DEFAULT 'system',
    created_at  TEXT    NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at  TEXT    NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ─── Tabelle: person ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS person (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    vorname         TEXT    NOT NULL,
    nachname        TEXT    NOT NULL,
    email           TEXT    UNIQUE,             -- nullable, unique wenn gesetzt
    telefon         TEXT,
    position        TEXT,
    prospect_level  TEXT    CHECK(prospect_level IN (
                        'Owner',
                        'CxO',
                        'Head',
                        'Manager',
                        'Other'
                    )),
    notes           TEXT,
    deleted_at      TEXT,                       -- ISO8601, NULL = aktiv (Soft-Delete)
    created_by      TEXT    NOT NULL DEFAULT 'system',
    created_at      TEXT    NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT    NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ─── Tabelle: person_unternehmen (n:m Verknüpfung) ───────────────────────────
-- ON DELETE RESTRICT: Löschen von Person/Unternehmen erst nach Auflösung
-- der Verknüpfungen möglich (kein kaskadierendes Löschen).
CREATE TABLE IF NOT EXISTS person_unternehmen (
    person_id       INTEGER NOT NULL REFERENCES person(id)      ON DELETE RESTRICT,
    unternehmen_id  INTEGER NOT NULL REFERENCES unternehmen(id) ON DELETE RESTRICT,
    rolle           TEXT,                       -- Freitext, nullable
    primary_company INTEGER NOT NULL DEFAULT 0 CHECK(primary_company IN (0, 1)),
    created_at      TEXT    NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (person_id, unternehmen_id)
);

-- ─── Tabelle: audit_log ───────────────────────────────────────────────────────
-- PFLICHT ISO-Anforderung.
-- Jede CREATE/UPDATE/DELETE aus der App schreibt hier einen Eintrag.
-- Eintraege werden NIE geloescht (append-only).
CREATE TABLE IF NOT EXISTS audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
    user            TEXT    NOT NULL DEFAULT 'system',
    entity_type     TEXT    NOT NULL,           -- 'person' | 'unternehmen' | 'person_unternehmen'
    entity_id       INTEGER NOT NULL,
    action          TEXT    NOT NULL CHECK(action IN ('CREATE', 'UPDATE', 'DELETE')),
    changed_fields  TEXT,                       -- JSON-String, bei CREATE vollstaendiger Datensatz
    ip_address      TEXT                        -- nullable, aus Request-Context
);

-- ─── Indizes ──────────────────────────────────────────────────────────────────
-- Performance fuer haeufige Queries: Suche, Listen, Verknuepfungs-Lookups
CREATE INDEX IF NOT EXISTS idx_person_nachname    ON person(nachname);
CREATE INDEX IF NOT EXISTS idx_person_email       ON person(email);
CREATE INDEX IF NOT EXISTS idx_person_deleted_at  ON person(deleted_at);
CREATE INDEX IF NOT EXISTS idx_unt_name           ON unternehmen(name);
CREATE INDEX IF NOT EXISTS idx_unt_deleted_at     ON unternehmen(deleted_at);
CREATE INDEX IF NOT EXISTS idx_pu_person_id       ON person_unternehmen(person_id);
CREATE INDEX IF NOT EXISTS idx_pu_unt_id          ON person_unternehmen(unternehmen_id);
CREATE INDEX IF NOT EXISTS idx_audit_entity       ON audit_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp    ON audit_log(timestamp);
