-- Migration 007: verlust_reason_enum Spalte in deal-Tabelle
-- CRM-054 | Sprint 3 Wave 3b | 20.05.2026
-- Idempotent: Spalte nur hinzufuegen wenn nicht vorhanden (guard in db.py)

-- Neue Spalte: verlust_reason_enum TEXT NULL
-- Enum-Werte werden server-seitig validiert (Python), nicht via SQLite-Constraint
-- Bestehende Deals: NULL (kein Rueckwaerts-Mapping)
