-- ============================================================
-- CRM MISSION CTRL – Migration 004: User-Allowlist (SSO Sprint 3)
-- Sprint 3 | 19.05.2026
-- Story: CRM-031, CRM-033
-- ============================================================

-- ─── Guard-Tabelle ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS _migration_004_guard (
    applied TEXT PRIMARY KEY
);

-- ─── Tabelle: crm_user ───────────────────────────────────────────────────────
-- Allowlist fuer SSO-Zugang zu MISSION CTRL.
-- role: admin = voller Zugang + /admin/audit; user = normal; readonly = nur lesen
CREATE TABLE IF NOT EXISTS crm_user (
    email       TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'user'
                CHECK(role IN ('admin', 'user', 'readonly')),
    color_hex   TEXT,
    active      INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
    created_at  TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
    last_login  TEXT
);

CREATE INDEX IF NOT EXISTS idx_crm_user_user_id ON crm_user(user_id);

-- Seed (idempotent)
INSERT OR IGNORE INTO crm_user (email, name, user_id, role, color_hex) VALUES
    ('christian@cbh.ai',        'Christian Zingg', 'christian', 'admin', '#5870E2'),
    ('christian.zingg@cbh.ai',  'Christian Zingg', 'christian', 'admin', '#5870E2'),
    ('andre@cbh.ai',            'Andre',           'andre',     'admin', '#7C3AED'),
    ('michi@cbh.ai',            'Michael',         'michael',   'admin', '#0891B2'),
    ('michael@cbh.ai',          'Michael',         'michael',   'admin', '#0891B2'),
    ('marco@cbh.ai',            'Marco',           'marco',     'user',  '#059669'),
    ('tim@cbh.ai',              'Tim',             'tim',       'user',  '#D97706');

INSERT OR IGNORE INTO _migration_004_guard (applied) VALUES ('004_user_allowlist');

-- ─── Tabelle: session_log (Login/Logout/Denied Audit) ───────────────────────
-- Separat von audit_log wegen unterschiedlichem Action-Schema (ISO-relevant)
CREATE TABLE IF NOT EXISTS session_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT    NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
    email       TEXT    NOT NULL,
    action      TEXT    NOT NULL CHECK(action IN ('LOGIN', 'LOGOUT', 'LOGIN_DENIED')),
    ip_address  TEXT
);

CREATE INDEX IF NOT EXISTS idx_session_log_email ON session_log(email, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_session_log_action ON session_log(action, timestamp DESC);
