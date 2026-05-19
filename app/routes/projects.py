"""
routes/projects.py – CRM-015: Projekt-Übersicht + Detail + Update
                     CRM-028: Rechnungsgrad

Regeln:
  - GET /projects: Übersicht mit Rechnungsgrad-Spalte (9 Spalten Vision 5.3)
  - GET /projects/{id}: Projekt-Detail
  - PUT /projects/{id}: Status + Felder aktualisieren
  - Audit-Log bei JEDEM UPDATE
"""

import os
from typing import Optional

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.db import get_connection, write_audit_log, now_iso
from app.template_utils import tmpl_ctx

router = APIRouter()
_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")
templates = Jinja2Templates(directory=_TEMPLATE_DIR)

OWNERS = ["christian", "andre", "michi", "marco", "tim"]
PROJECT_STATUSES = ["active", "on_hold", "completed", "cancelled"]


def get_user(request: Request) -> str:
    return request.headers.get("X-Forwarded-User", "system")


def get_client_ip(request: Request) -> Optional[str]:
    return request.headers.get("X-Forwarded-For", request.client.host if request.client else None)


def _calc_rechnungsgrad(contract_value, ist_rechnungen) -> Optional[float]:
    """Berechnet Rechnungsgrad in Prozent. None wenn contract_value=0 oder NULL."""
    if not contract_value or contract_value == 0:
        return None
    return round((ist_rechnungen or 0) / contract_value * 100, 1)


def _enrich_project(row, conn) -> dict:
    p = dict(row)
    p["rechnungsgrad"] = _calc_rechnungsgrad(p.get("contract_value"), p.get("ist_rechnungen"))
    # Deal-Info laden
    if p.get("deal_id"):
        deal = conn.execute(
            "SELECT titel, stage, person_id, unternehmen_id FROM deal WHERE id=?",
            (p["deal_id"],)
        ).fetchone()
        if deal:
            p["deal_titel"] = deal["titel"]
            p["deal_stage"] = deal["stage"]
            # Unternehmen-Name
            if deal["unternehmen_id"]:
                u = conn.execute(
                    "SELECT name FROM unternehmen WHERE id=?", (deal["unternehmen_id"],)
                ).fetchone()
                p["kunde_name"] = u["name"] if u else None
            elif deal["person_id"]:
                per = conn.execute(
                    "SELECT vorname, nachname FROM person WHERE id=?", (deal["person_id"],)
                ).fetchone()
                p["kunde_name"] = f"{per['vorname']} {per['nachname']}" if per else None
            else:
                p["kunde_name"] = None
        else:
            p["deal_titel"] = None
            p["deal_stage"] = None
            p["kunde_name"] = None
    else:
        p["deal_titel"] = None
        p["deal_stage"] = None
        p["kunde_name"] = None
    return p


# ─── GET /projects ─────────────────────────────────────────────────────────────

@router.get("/projects", response_class=HTMLResponse)
async def projects_liste(request: Request, status: Optional[str] = None):
    prefix = request.scope.get("root_path", "")
    conn = get_connection()
    try:
        where = "deleted_at IS NULL"
        params = []
        if status:
            where += " AND status = ?"
            params.append(status)
        rows = conn.execute(
            f"SELECT * FROM project WHERE {where} ORDER BY created_at DESC", params
        ).fetchall()
        projects = [_enrich_project(r, conn) for r in rows]
    finally:
        conn.close()

    return templates.TemplateResponse(request, "projects_liste.html", tmpl_ctx(request, {
        "request": request,
        "prefix": prefix,
        "projects": projects,
        "statuses": PROJECT_STATUSES,
        "filter_status": status,
    }))



# ─── GET /projects/{id} ────────────────────────────────────────────────────────

@router.get("/projects/{proj_id}", response_class=HTMLResponse)
async def project_detail(request: Request, proj_id: int):
    prefix = request.scope.get("root_path", "")
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM project WHERE id=? AND deleted_at IS NULL", (proj_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Projekt nicht gefunden")
        project = _enrich_project(row, conn)
    finally:
        conn.close()

    return templates.TemplateResponse(request, "project_detail.html", tmpl_ctx(request, {
        "request": request,
        "prefix": prefix,
        "project": project,
        "owners": OWNERS,
        "statuses": PROJECT_STATUSES,
    }))



# ─── GET /projects/{id}/edit ──────────────────────────────────────────────────

@router.get("/projects/{proj_id}/edit", response_class=HTMLResponse)
async def project_edit_form(request: Request, proj_id: int):
    prefix = request.scope.get("root_path", "")
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM project WHERE id=? AND deleted_at IS NULL", (proj_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Projekt nicht gefunden")
        project = _enrich_project(row, conn)
    finally:
        conn.close()

    return templates.TemplateResponse(request, "project_form.html", tmpl_ctx(request, {
        "request": request,
        "prefix": prefix,
        "project": project,
        "owners": OWNERS,
        "statuses": PROJECT_STATUSES,
    }))



# ─── PUT /projects/{id} ───────────────────────────────────────────────────────

@router.put("/projects/{proj_id}")
async def project_update(
    request: Request,
    proj_id: int,
    name: str = Form(...),
    delivery_owner: str = Form(...),
    status: str = Form(...),
    start_date: Optional[str] = Form(None),
    end_date_planned: Optional[str] = Form(None),
    contract_value: Optional[float] = Form(None),
    ist_rechnungen: Optional[float] = Form(None),
    outcome_definition: Optional[str] = Form(None),
    dok_link: Optional[str] = Form(None),
    ausblick: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
):
    prefix = request.scope.get("root_path", "")
    user = get_user(request)
    ip = get_client_ip(request)

    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT id FROM project WHERE id=? AND deleted_at IS NULL", (proj_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Projekt nicht gefunden")

        ts = now_iso()
        conn.execute(
            """UPDATE project SET name=?, delivery_owner=?, status=?, start_date=?,
               end_date_planned=?, contract_value=?, ist_rechnungen=?,
               outcome_definition=?, dok_link=?, ausblick=?, notes=?, updated_at=?
               WHERE id=?""",
            (name, delivery_owner, status,
             start_date or None, end_date_planned or None,
             contract_value, ist_rechnungen or 0,
             outcome_definition or None, dok_link or None,
             ausblick or None, notes or None, ts, proj_id)
        )
        write_audit_log(conn, user=user, entity_type="project", entity_id=proj_id,
                        action="UPDATE",
                        changed_fields={"name": name, "status": status,
                                        "delivery_owner": delivery_owner,
                                        "ist_rechnungen": ist_rechnungen},
                        ip_address=ip)
        conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

    return RedirectResponse(url=f"{prefix}/projects/{proj_id}", status_code=303)
