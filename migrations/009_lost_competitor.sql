-- Migration 009: lost_competitor Spalte in deal-Tabelle
-- CRM-BUG-006 | Sprint 3 Wave 3b | 2026-05-20
-- Idempotent: Spalte nur hinzufuegen wenn nicht vorhanden (guard in db.py)

-- Neue Spalte: lost_competitor TEXT NULL
-- Optionales Freitext-Feld, kein NOT NULL Constraint
-- Bestehende Deals: NULL (kein Rueckwaerts-Mapping noetig)
