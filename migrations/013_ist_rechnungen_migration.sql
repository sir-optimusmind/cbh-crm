-- ============================================================
-- CRM MISSION CTRL – Migration 013: ist_rechnungen Datenmigration
-- Kenny-Backlog Item 4 | Sprint 4 | 2026-05-20
-- Autor: Finn
-- ============================================================
-- Für jedes Projekt mit ist_rechnungen > 0 und noch keinen
-- project_rechnung-Einträgen: Legacy-Wert als einmaligen Eintrag migrieren.
-- Idempotent: INSERT OR IGNORE + Unique-Prüfung via Subquery.
-- ============================================================

-- Audit-Note: Wird per Python-Migration in db.py ausgeführt (nicht als SQL-Script),
-- da wir project_rechnung-Existenz prüfen müssen und Audit-Log schreiben wollen.
-- Dieser SQL-File dient nur als Referenz / manuelle Fallback-Ausführung.

INSERT INTO project_rechnung (project_id, datum, betrag, notiz, status, created_at)
SELECT
    p.id,
    STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'),
    p.ist_rechnungen,
    'Migration aus Legacy-Feld ist_rechnungen',
    'offen',
    STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
FROM project p
WHERE p.ist_rechnungen > 0
  AND p.deleted_at IS NULL
  AND NOT EXISTS (
      SELECT 1 FROM project_rechnung pr WHERE pr.project_id = p.id
  );
