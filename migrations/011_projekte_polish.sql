-- ============================================================
-- CRM MISSION CTRL – Migration 011: Projekte Polish
-- Sprint 4 | CRM-072 + CRM-073 | 2026-05-20
-- Autor: Finn (Build) / Maria-Luise (Spec)
-- ============================================================

-- CRM-072: project_rechnung Tabelle
CREATE TABLE IF NOT EXISTS project_rechnung (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id  INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
  datum       TEXT    NOT NULL,
  betrag      REAL    NOT NULL,
  notiz       TEXT,
  status      TEXT    NOT NULL DEFAULT 'offen'
              CHECK(status IN ('offen','bezahlt','storniert')),
  created_at  TEXT    NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_rechnung_project ON project_rechnung(project_id);

-- CRM-073: touchpoint Tabelle rebuild um project_id + relaxten CHECK
-- (SQLite erlaubt kein ALTER TABLE ... DROP/MODIFY CONSTRAINT)
-- Nur ausführen wenn project_id noch nicht existiert
CREATE TABLE IF NOT EXISTS touchpoint_new (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id         INTEGER REFERENCES deal(id) ON DELETE RESTRICT,
    person_id       INTEGER REFERENCES person(id) ON DELETE RESTRICT,
    project_id      INTEGER REFERENCES project(id) ON DELETE SET NULL,
    art             TEXT    NOT NULL
                    CHECK(art IN ('anruf','email','meeting','linkedin','notiz','other')),
    datum           TEXT    NOT NULL,
    erstellt_von    TEXT    NOT NULL
                    CHECK(erstellt_von IN ('christian','andre','michi','marco','tim')),
    inhalt          TEXT    NOT NULL,
    naechster_schritt TEXT,
    created_at      TEXT    NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
    created_by      TEXT    NOT NULL DEFAULT 'system',
    deleted_at      TEXT,
    details         TEXT,
    -- person_id oder deal_id oder project_id muss gesetzt sein
    CHECK (person_id IS NOT NULL OR deal_id IS NOT NULL OR project_id IS NOT NULL)
);

INSERT INTO touchpoint_new
    (id, deal_id, person_id, art, datum, erstellt_von, inhalt,
     naechster_schritt, created_at, created_by, deleted_at, details)
SELECT id, deal_id, person_id, art, datum, erstellt_von, inhalt,
       naechster_schritt, created_at, created_by, deleted_at, details
FROM touchpoint;

DROP TABLE touchpoint;
ALTER TABLE touchpoint_new RENAME TO touchpoint;

CREATE INDEX IF NOT EXISTS idx_tp_deal    ON touchpoint(deal_id);
CREATE INDEX IF NOT EXISTS idx_tp_person  ON touchpoint(person_id);
CREATE INDEX IF NOT EXISTS idx_tp_project ON touchpoint(project_id);
CREATE INDEX IF NOT EXISTS idx_tp_datum   ON touchpoint(datum);

-- ============================================================
-- DOWN: nicht trivial reversibel (Tabellen-Rebuild nötig)
-- ============================================================
