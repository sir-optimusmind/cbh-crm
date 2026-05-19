-- ============================================================
-- CRM MISSION CTRL – Migration 002: Stimmung + Last Contact
-- Quick Wins: CRM-QW-02 + CRM-QW-03
-- 
-- SQLite hat kein "ALTER TABLE ... IF NOT EXISTS".
-- Idempotenz wird durch db.py / run_migration_002() sichergestellt:
-- Python prüft ob Spalten bereits existieren (PRAGMA table_info).
-- Dieses File ist Dokumentation + wird via executescript in init_db geladen.
-- 
-- Migration Guard: Tabelle _migration_002_guard verhindert Doppelläufe.
-- ============================================================

CREATE TABLE IF NOT EXISTS _migration_002_guard (
    applied TEXT PRIMARY KEY
);

-- Indizes für neue Felder (idempotent)
CREATE INDEX IF NOT EXISTS idx_person_stimmung        ON person(stimmung);
CREATE INDEX IF NOT EXISTS idx_person_last_contact_at ON person(last_contact_at);
