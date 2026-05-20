-- ============================================================
-- CRM MISSION CTRL – Migration 005: Presence (last_seen_at)
-- Sprint 3 Wave 3 | 2026-05-20
-- Story: CRM-051
-- ============================================================

-- ─── Guard ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS _migration_005_guard (
    applied TEXT PRIMARY KEY
);

-- Note: last_seen_at wird via ALTER TABLE in db.py hinzugefügt (_column_exists Check)
-- Diese Datei setzt nur den Guard für idempotente Wiederholbarkeit.

INSERT OR IGNORE INTO _migration_005_guard (applied) VALUES ('005_presence');
