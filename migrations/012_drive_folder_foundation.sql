-- ============================================================
-- CRM MISSION CTRL – Migration 012: Drive Folder Foundation
-- Sprint 4 | CRM-062 + CRM-070 | 2026-05-20
-- Autor: Finn (Build) / Maria-Luise (Spec) / Niko (Architektur)
-- ============================================================

-- CRM-062: Drive-Felder in project-Tabelle
ALTER TABLE project ADD COLUMN drive_folder_id   TEXT;
ALTER TABLE project ADD COLUMN drive_folder_name TEXT;
ALTER TABLE project ADD COLUMN drive_folder_url  TEXT;

CREATE INDEX IF NOT EXISTS idx_project_drive_folder_id ON project(drive_folder_id);

-- CRM-070: audit_log.action CHECK-Constraint auf LINK_DRIVE erweitern
-- SQLite erlaubt kein ALTER CONSTRAINT → Table-Rebuild
-- Bestehende Daten bleiben vollständig erhalten.
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

-- ============================================================
-- DOWN: nicht trivial reversibel (Table-Rebuild + Column-Drop)
-- ============================================================
