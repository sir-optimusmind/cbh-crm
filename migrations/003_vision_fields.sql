-- ============================================================
-- CRM MISSION CTRL – Migration 003: Vision-Felder Sprint 2
-- Stories: CRM-021 (Person-Detail), CRM-022 (Unternehmen-Detail), CRM-029 (LinkedIn-Trigger)
-- 19.05.2026
--
-- SQLite hat kein "ALTER TABLE ... IF NOT EXISTS".
-- Idempotenz: db.py prüft via PRAGMA table_info ob Spalten existieren.
-- Dieses File dient als Dokumentation und wird via executescript geladen
-- (nur die idempotenten Statements wie CREATE INDEX IF NOT EXISTS).
-- ============================================================

-- ─── Guard-Tabelle ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS _migration_003_guard (
    applied TEXT PRIMARY KEY
);

-- ─── Indizes für neue Felder (idempotent) ────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_person_stimmung_cbh  ON person(stimmung_cbh);
CREATE INDEX IF NOT EXISTS idx_unt_produkt_emp      ON unternehmen(produkt_empfehlung);
