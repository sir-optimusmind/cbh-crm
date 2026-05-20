-- Migration 006: deal_stage_history Tabelle + Indizes
-- CRM-055 | Sprint 3 Wave 3b | 20.05.2026
-- Idempotent via CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS

CREATE TABLE IF NOT EXISTS deal_stage_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id     INTEGER NOT NULL REFERENCES deal(id) ON DELETE CASCADE,
    from_stage  TEXT,           -- NULL wenn Deal neu angelegt
    to_stage    TEXT NOT NULL,
    moved_at    DATETIME NOT NULL DEFAULT (datetime('now')),
    moved_by    TEXT            -- user_id oder "system"
);

CREATE INDEX IF NOT EXISTS idx_dsh_deal_id ON deal_stage_history(deal_id);
CREATE INDEX IF NOT EXISTS idx_dsh_from_to ON deal_stage_history(from_stage, to_stage);
