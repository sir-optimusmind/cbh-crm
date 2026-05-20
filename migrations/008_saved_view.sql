-- Migration 008: saved_view Tabelle
-- CRM-061 | Sprint 3 Wave 3b | 20.05.2026
-- Niko N4-Pattern: user_id = Email-Adresse oder "default" (kein FK, SSO-stabil)

CREATE TABLE IF NOT EXISTS saved_view (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,
    name        TEXT NOT NULL,
    query_json  TEXT NOT NULL,
    view_type   TEXT NOT NULL DEFAULT 'kanban',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, name)
);

CREATE INDEX IF NOT EXISTS idx_sv_user_id ON saved_view(user_id);
