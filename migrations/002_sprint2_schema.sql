-- ============================================================
-- CRM MISSION CTRL – Migration 002: Sprint 2 Schema
-- Sprint 2 | 19.05.2026
-- Stories: CRM-009
-- Tabellen: deal, deal_product, touchpoint, project, stage_definition
-- ============================================================

-- ─── Tabelle: deal ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS deal (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    titel               TEXT    NOT NULL,
    stage               TEXT    NOT NULL DEFAULT 'new'
                        CHECK(stage IN ('new','opportunity','discovery','proposal_sent','won','lost')),
    person_id           INTEGER REFERENCES person(id) ON DELETE RESTRICT,
    unternehmen_id      INTEGER REFERENCES unternehmen(id) ON DELETE RESTRICT,
    owner               TEXT    NOT NULL
                        CHECK(owner IN ('christian','andre','michi','marco','tim')),
    backup_owner        TEXT
                        CHECK(backup_owner IN ('christian','andre','michi','marco','tim') OR backup_owner IS NULL),
    acv                 REAL,
    discount_pct        REAL    CHECK(discount_pct IS NULL OR (discount_pct >= 0 AND discount_pct <= 100)),
    risk_reversal       INTEGER NOT NULL DEFAULT 0 CHECK(risk_reversal IN (0,1)),
    deal_cost           REAL,
    lead_source         TEXT    CHECK(lead_source IN ('linkedin','email','telefon','lemlist','cognism','apollo','networking','referral','other') OR lead_source IS NULL),
    lead_type           TEXT    CHECK(lead_type IN ('unknown_unknown','lucky_deal','inbound') OR lead_type IS NULL),
    icp_persona         TEXT    CHECK(icp_persona IN ('forward_thinking_owner','transformation_leader','speed_optimizer','rebels','other') OR icp_persona IS NULL),
    notes               TEXT,
    followup_datum      TEXT,
    unterschrift_datum  TEXT,
    projekt_start_datum TEXT,
    verlust_grund       TEXT,
    retry_datum         TEXT,
    created_by          TEXT    NOT NULL DEFAULT 'system',
    created_at          TEXT    NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT    NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
    deleted_at          TEXT,
    -- Backup-Owner != Owner Constraint
    CHECK (backup_owner IS NULL OR backup_owner != owner)
);

-- ─── Tabelle: deal_product (n:m Deal↔Produkt) ────────────────────────────────
CREATE TABLE IF NOT EXISTS deal_product (
    deal_id     INTEGER NOT NULL REFERENCES deal(id) ON DELETE CASCADE,
    product     TEXT    NOT NULL
                CHECK(product IN ('race','blindspot','okr_training','pm_training','innovation_cell','visionsworkshop','empower_os','tm','other')),
    PRIMARY KEY (deal_id, product)
);

-- ─── Tabelle: touchpoint ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS touchpoint (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id         INTEGER REFERENCES deal(id) ON DELETE RESTRICT,
    person_id       INTEGER REFERENCES person(id) ON DELETE RESTRICT,
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
    -- Mindestens person_id oder deal_id muss gesetzt sein
    CHECK (person_id IS NOT NULL OR deal_id IS NOT NULL)
);

-- ─── Tabelle: project ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS project (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id             INTEGER UNIQUE REFERENCES deal(id) ON DELETE RESTRICT,
    name                TEXT    NOT NULL,
    delivery_owner      TEXT    NOT NULL
                        CHECK(delivery_owner IN ('christian','andre','michi','marco','tim')),
    status              TEXT    NOT NULL DEFAULT 'active'
                        CHECK(status IN ('active','on_hold','completed','cancelled')),
    start_date          TEXT,
    end_date_planned    TEXT,
    contract_value      REAL,
    kickoff_date        TEXT,
    outcome_definition  TEXT,
    dok_link            TEXT,
    ist_rechnungen      REAL    NOT NULL DEFAULT 0,
    ausblick            TEXT,
    notes               TEXT,
    created_at          TEXT    NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT    NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
    created_by          TEXT    NOT NULL DEFAULT 'system',
    deleted_at          TEXT
);

-- ─── Tabelle: stage_definition ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS stage_definition (
    stage               TEXT    PRIMARY KEY,
    label               TEXT    NOT NULL,
    trigger_condition   TEXT    NOT NULL,
    owner_role          TEXT    NOT NULL,
    conv_target_pct     REAL,
    avg_duration_days   INTEGER,
    notes               TEXT
);

-- ─── Indizes ──────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_deal_stage       ON deal(stage);
CREATE INDEX IF NOT EXISTS idx_deal_owner       ON deal(owner);
CREATE INDEX IF NOT EXISTS idx_deal_deleted     ON deal(deleted_at);
CREATE INDEX IF NOT EXISTS idx_deal_person      ON deal(person_id);
CREATE INDEX IF NOT EXISTS idx_deal_unt         ON deal(unternehmen_id);
CREATE INDEX IF NOT EXISTS idx_dp_deal          ON deal_product(deal_id);
CREATE INDEX IF NOT EXISTS idx_tp_deal          ON touchpoint(deal_id);
CREATE INDEX IF NOT EXISTS idx_tp_person        ON touchpoint(person_id);
CREATE INDEX IF NOT EXISTS idx_tp_datum         ON touchpoint(datum);
CREATE INDEX IF NOT EXISTS idx_project_deal     ON project(deal_id);
CREATE INDEX IF NOT EXISTS idx_project_status   ON project(status);

-- ─── Seed: stage_definition (6 Stages – Vision-konform) ──────────────────────
INSERT OR IGNORE INTO stage_definition (stage, label, trigger_condition, owner_role, conv_target_pct, avg_duration_days, notes) VALUES
('opportunity', 'Opportunity',
 'Interesse signalisiert, kein Termin. Follow-up-Datum gesetzt. Warme Leads im Aufwärmbecken.',
 'Lead-Owner (Christian/André/Michi) oder Solo-fähige Partner mit Backup-Owner',
 NULL, 14,
 'Pflichtfelder: followup_datum, letzter Touchpoint, Kanal. Backup-Owner Pflicht.'),

('new', 'New – Erster Termin',
 'Erster Discovery-Termin fix vereinbart + Teilnehmer bestätigt.',
 'Lead-Owner (Christian/André/Michi) oder Solo-fähige Partner mit Backup-Owner',
 65, 7,
 'Pflichtfelder: Termin-Datum (followup_datum als Proxy), CBH-Ansprechpartner (owner), Bedarfsnotiz (notes). Conv-Target: 60–70%.'),

('discovery', 'Discovery',
 'Zweittermin / Pitch / Lösungsvorschlag. Bedarf klar.',
 'Lead-Owner mit Backup-Owner',
 70, 14,
 'Pflichtfelder: Pitch-Datum, Produkt-Zuordnung (deal_product). Conv-Target: ~70%. Backup-Owner Pflicht.'),

('proposal_sent', 'Proposal Sent',
 'Angebot raus, Nachfass-Phase. Mehrere Folge-Termine bleiben hier.',
 'Lead-Owner mit Backup-Owner',
 15, 21,
 'Pflichtfelder: Angebotsdatum, Angebotsbetrag (acv), ACV gesetzt. Conv-Target: 10–20%. Kein eigener Deal-Conversion-Stage.'),

('won', 'Won',
 'Vertrag unterschrieben / mündliche Bestätigung + Projektstart vereinbart.',
 'Lead-Owner → übergibt an Delivery-Owner',
 NULL, NULL,
 'Pflichtfelder: unterschrift_datum, projekt_start_datum, delivery_owner (auf Projekt). Automatische Projekt-Anlage via CRM-015.'),

('lost', 'Lost',
 'Endgültige Absage mit Verlustgrund dokumentiert.',
 'Lead-Owner',
 NULL, NULL,
 'Pflichtfelder: verlust_grund, Verlustdatum. Optional: retry_datum für spätere Reaktivierung.');

-- ─── Guard: Migration 002 als angewendet markieren ───────────────────────────
CREATE TABLE IF NOT EXISTS _migration_002_guard (
    applied TEXT PRIMARY KEY
);
INSERT OR IGNORE INTO _migration_002_guard (applied) VALUES ('002_sprint2_schema');
