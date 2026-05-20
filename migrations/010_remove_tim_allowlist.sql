-- ============================================================
-- CRM MISSION CTRL – Migration 010: Tim aus crm_user entfernen
-- Sprint 4 | CRM-101 | 2026-05-20
-- Begründung: Tim ist nicht in HubSpot, kein aktiver CBH-Account
-- Reversibel via DOWN-Migration unten
-- ============================================================

-- UP
DELETE FROM crm_user WHERE email = 'tim@cbh.ai';

-- ============================================================
-- DOWN (Rollback):
-- INSERT OR IGNORE INTO crm_user (email, name, user_id, role, color_hex)
-- VALUES ('tim@cbh.ai', 'Tim', 'tim', 'user', '#D97706');
-- ============================================================
