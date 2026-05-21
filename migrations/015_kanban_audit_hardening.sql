-- Migration 015 – Kanban Audit Hardening
-- K-BUG-004: DELETE-Trigger auf applicants (ISO-Anforderung, append-only Audit)
-- K-BUG-005: Spalte user_email in applicant_audit ergänzen (Doku-Konsistenz)
-- Erstellt: 2026-05-21 | Finn (Bugfix nach Kenny QA)

-- K-BUG-004: DELETE-Trigger – schreibt in applicant_audit wenn ein Bewerber gelöscht wird
-- Schützt auch direkte DB-Zugriffe (Migrations, Admin-Tools)
CREATE TRIGGER IF NOT EXISTS audit_applicant_delete
AFTER DELETE ON applicants
BEGIN
  INSERT INTO applicant_audit (tenant_slug, applicant_id, action, author, created_at)
  VALUES (OLD.tenant_slug, OLD.id, 'deleted', 'system', datetime('now'));
END;
