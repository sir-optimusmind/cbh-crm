"""
routes/projects.py – CRM-015: Projekt-Übersicht + Detail + Update
                     CRM-028: Rechnungsgrad
                     CRM-072: project_rechnung Tabelle + Rechnungs-Route
                     CRM-073: touchpoint.project_id
                     CRM-074: Rechnungs-Block
                     CRM-075: Phasen-Timeline
                     CRM-076: Risiko-Ampel
                     CRM-077: Touchpoint-Block am Projekt
                     CRM-078: Filter + Sort in Liste
                     CRM-079: Outcomes-Block
                     CRM-080: Deal-Link Header
                     CRM-081: Drive-Folder-Field

Regeln:
  - GET /projects: Uebersicht mit Filter (status, owner, q) + Sort
  - GET /projects/{id}: Projekt-Detail (Rechnungen, Touchpoints, Timeline, Ampel)
  - PUT /projects/{id}: Update (risiko_status, phase, neue Felder)
  - POST /projects/{id}/rechnungen: Rechnungs-Eingang anlegen
  - POST /projects/{id}/touchpoints: Touchpoint am Projekt anlegen
  - Audit-Log bei JEDEM UPDATE/CREATE
"""

import os
from typing import Optional

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.db import get_connection, write_audit_log, now_iso
from app.template_utils import tmpl_ctx

router = APIRouter()
_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")
templates = Jinja2Templates(directory=_TEMPLATE_DIR)

OWNERS = ["christian", "andre", "michi", "marco"]
PROJECT_STATUSES = ["active", "on_hold", "completed", "cancelled"]
TOUCHPOINT_ARTEN = ["anruf", "email", "meeting", "linkedin", "notiz", "other"]

# Whitelist fuer Sort-Parameter (SQL-Injection-Schutz, CRM-078)
SORTABLE_COLS = {"name", "kunde_name", "status", "contract_value", "ist_rechnungen", "rechnungsgrad"}


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
            if deal["unternehmen_id"]:
                u = conn.execute(
                    "SELECT name FROM unternehmen WHERE id=?", (deal["unternehmen_id"],)
                ).fetchone()
                if u and not p.get("kunde_name"):
                    p["kunde_name"] = u["name"]
            elif deal["person_id"]:
                per = conn.execute(
                    "SELECT vorname, nachname FROM person WHERE id=?", (deal["person_id"],)
                ).fetchone()
                if per and not p.get("kunde_name"):
                    p["kunde_name"] = f"{per['vorname']} {per['nachname']}"
        else:
            # Deal geloescht – Link ausblenden
            p["deal_titel"] = None
            p["deal_id"] = None
    else:
        p["deal_titel"] = None
    # kunde_name Fallback
    if "kunde_name" not in p:
        p["kunde_name"] = None
    return p


# --- GET /projects -----------------------------------------------------------

@router.get("/projects", response_class=HTMLResponse)
async def projects_liste(
    request: Request,
    status: Optional[str] = None,
    owner: Optional[str] = None,
    q: Optional[str] = None,
    sort: Optional[str] = None,
    dir: Optional[str] = None,
):
    prefix = request.scope.get("root_path", "")
    conn = get_connection()
    try:
        # Whitelist sort
        sort_col = sort if sort in SORTABLE_COLS else "name"
        sort_dir = "DESC" if dir and dir.lower() == "desc" else "ASC"

        where_parts = ["deleted_at IS NULL"]
        params = []
        if status and status in PROJECT_STATUSES:
            where_parts.append("status = ?")
            params.append(status)
        if owner and owner in OWNERS:
            where_parts.append("delivery_owner = ?")
            params.append(owner)
        if q:
            where_parts.append("(LOWER(name) LIKE ? OR LOWER(COALESCE(kunde_name,'')) LIKE ?)")
            params.extend([f"%{q.lower()}%", f"%{q.lower()}%"])

        where = " AND ".join(where_parts)

        if sort_col == "rechnungsgrad":
            order_clause = f"CASE WHEN contract_value > 0 THEN (COALESCE(ist_rechnungen,0) * 100.0 / contract_value) ELSE NULL END {sort_dir} NULLS LAST"
        else:
            order_clause = f"{sort_col} {sort_dir} NULLS LAST"

        rows = conn.execute(
            f"SELECT * FROM project WHERE {where} ORDER BY {order_clause}", params
        ).fetchall()
        projects = [_enrich_project(r, conn) for r in rows]
    finally:
        conn.close()

    return templates.TemplateResponse(request, "projects_liste.html", tmpl_ctx(request, {
        "request": request,
        "prefix": prefix,
        "projects": projects,
        "statuses": PROJECT_STATUSES,
        "owners": OWNERS,
        "filter_status": status or "",
        "filter_owner": owner or "",
        "filter_q": q or "",
        "sort_col": sort_col,
        "sort_dir": (dir or "asc").lower(),
    }))


# --- GET /projects/{id} ------------------------------------------------------

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

        # Rechnungen laden (CRM-074)
        rechnungen = conn.execute(
            "SELECT * FROM project_rechnung WHERE project_id=? ORDER BY datum ASC, created_at ASC",
            (proj_id,)
        ).fetchall()
        rechnungen = [dict(r) for r in rechnungen]
        ist_bezahlt = sum(r["betrag"] for r in rechnungen if r["status"] == "bezahlt")

        # Touchpoints laden (CRM-077)
        touchpoints = conn.execute(
            """SELECT t.*, d.titel as deal_titel
               FROM touchpoint t
               LEFT JOIN deal d ON d.id = t.deal_id
               WHERE t.project_id = ? AND t.deleted_at IS NULL
               ORDER BY t.datum DESC, t.created_at DESC""",
            (proj_id,)
        ).fetchall()
        touchpoints = [dict(t) for t in touchpoints]

    finally:
        conn.close()

    return templates.TemplateResponse(request, "project_detail.html", tmpl_ctx(request, {
        "request": request,
        "prefix": prefix,
        "project": project,
        "owners": OWNERS,
        "statuses": PROJECT_STATUSES,
        "rechnungen": rechnungen,
        "ist_bezahlt": ist_bezahlt,
        "touchpoints": touchpoints,
        "arten": TOUCHPOINT_ARTEN,
        "phasen_order": ["kick_off", "in_arbeit", "review", "abgeschlossen"],
    }))


# --- GET /projects/{id}/edit -------------------------------------------------

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


# --- PUT /projects/{id} ------------------------------------------------------

@router.put("/projects/{proj_id}")
async def project_update(
    request: Request,
    proj_id: int,
    name: str = Form(...),
    delivery_owner: str = Form(...),
    status: str = Form(...),
    start_date: Optional[str] = Form(None),
    end_date_planned: Optional[str] = Form(None),
    kickoff_date: Optional[str] = Form(None),
    contract_value: Optional[float] = Form(None),
    outcome_definition: Optional[str] = Form(None),
    dok_link: Optional[str] = Form(None),
    ausblick: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    risiko_status: Optional[str] = Form(None),
    phase: Optional[str] = Form(None),
):
    prefix = request.scope.get("root_path", "")
    user = get_user(request)
    ip = get_client_ip(request)

    risiko_status = risiko_status if risiko_status else None
    phase = phase if phase else None

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
               end_date_planned=?, kickoff_date=?, contract_value=?,
               outcome_definition=?, dok_link=?, ausblick=?, notes=?,
               risiko_status=?, phase=?, updated_at=?
               WHERE id=?""",
            (name, delivery_owner, status,
             start_date or None, end_date_planned or None, kickoff_date or None,
             contract_value,
             outcome_definition or None, dok_link or None,
             ausblick or None, notes or None,
             risiko_status, phase,
             ts, proj_id)
        )
        write_audit_log(conn, user=user, entity_type="project", entity_id=proj_id,
                        action="UPDATE",
                        changed_fields={"name": name, "status": status,
                                        "delivery_owner": delivery_owner,
                                        "risiko_status": risiko_status,
                                        "phase": phase},
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


# --- POST /projects/{id}/rechnungen (CRM-074) --------------------------------

@router.post("/projects/{proj_id}/rechnungen")
async def projekt_rechnung_create(
    request: Request,
    proj_id: int,
    datum: str = Form(...),
    betrag: float = Form(...),
    status: str = Form("offen"),
    notiz: Optional[str] = Form(None),
):
    prefix = request.scope.get("root_path", "")
    user = get_user(request)
    ip = get_client_ip(request)

    if betrag <= 0:
        raise HTTPException(status_code=422, detail="Betrag muss > 0 sein")
    if status not in ("offen", "bezahlt", "storniert"):
        status = "offen"

    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT id FROM project WHERE id=? AND deleted_at IS NULL", (proj_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Projekt nicht gefunden")

        ts = now_iso()
        cur = conn.execute(
            """INSERT INTO project_rechnung (project_id, datum, betrag, notiz, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (proj_id, datum, betrag, notiz or None, status, ts)
        )
        rechnung_id = cur.lastrowid

        # Cache-Update: ist_rechnungen = SUM bezahlter Rechnungen
        conn.execute(
            """UPDATE project SET ist_rechnungen = (
               SELECT COALESCE(SUM(betrag), 0) FROM project_rechnung
               WHERE project_id = ? AND status = 'bezahlt'
               ), updated_at = ? WHERE id = ?""",
            (proj_id, ts, proj_id)
        )

        write_audit_log(conn, user=user, entity_type="project_rechnung", entity_id=rechnung_id,
                        action="CREATE",
                        changed_fields={"project_id": proj_id, "datum": datum,
                                        "betrag": betrag, "status": status},
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


# --- POST /projects/{id}/touchpoints (CRM-077) --------------------------------

@router.post("/projects/{proj_id}/touchpoints")
async def projekt_touchpoint_create(
    request: Request,
    proj_id: int,
    art: str = Form(...),
    datum: str = Form(...),
    erstellt_von: str = Form(...),
    inhalt: str = Form(...),
    naechster_schritt: Optional[str] = Form(None),
    details: Optional[str] = Form(None),
):
    prefix = request.scope.get("root_path", "")
    user = get_user(request)
    ip = get_client_ip(request)

    inhalt = inhalt.strip()
    naechster_schritt = naechster_schritt.strip() if naechster_schritt else None
    details = details.strip() if details else None

    if not inhalt:
        raise HTTPException(status_code=422, detail="Inhalt ist Pflichtfeld")

    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT id FROM project WHERE id=? AND deleted_at IS NULL", (proj_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Projekt nicht gefunden")

        ts = now_iso()
        cur = conn.execute(
            """INSERT INTO touchpoint (project_id, art, datum, erstellt_von,
               inhalt, naechster_schritt, details, created_at, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (proj_id, art, datum, erstellt_von,
             inhalt, naechster_schritt, details, ts, user)
        )
        tp_id = cur.lastrowid

        write_audit_log(conn, user=user, entity_type="touchpoint", entity_id=tp_id,
                        action="CREATE",
                        changed_fields={"project_id": proj_id, "art": art,
                                        "datum": datum, "erstellt_von": erstellt_von},
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
