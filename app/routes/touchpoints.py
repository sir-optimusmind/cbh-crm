"""
routes/touchpoints.py – CRM-013: Touchpoint Timeline + POST

Regeln:
  - POST /touchpoints: Touchpoint anlegen (person_id oder deal_id Pflicht)
  - Append-Only: kein Edit, kein UI-Delete in Sprint 2
  - Audit-Log bei CREATE
  - HTMX-kompatibel: POST gibt HTML-Fragment zurueck fuer inline-Update
"""

import os
from typing import Optional, List

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.db import get_connection, write_audit_log, now_iso

router = APIRouter()
_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")
templates = Jinja2Templates(directory=_TEMPLATE_DIR)

TOUCHPOINT_ARTEN = ["anruf", "email", "meeting", "linkedin", "notiz", "other"]
OWNERS = ["christian", "andre", "michi", "marco", "tim"]


def get_user(request: Request) -> str:
    return request.headers.get("X-Forwarded-User", "system")


def get_client_ip(request: Request) -> Optional[str]:
    return request.headers.get("X-Forwarded-For", request.client.host if request.client else None)


# ─── POST: Touchpoint anlegen ─────────────────────────────────────────────────

@router.post("/touchpoints")
async def touchpoint_create(
    request: Request,
    person_id: Optional[int] = Form(None),
    deal_id: Optional[int] = Form(None),
    art: str = Form(...),
    datum: str = Form(...),
    erstellt_von: str = Form(...),
    inhalt: str = Form(...),
    naechster_schritt: Optional[str] = Form(None),
):
    prefix = request.scope.get("root_path", "")
    user = get_user(request)
    ip = get_client_ip(request)

    person_id = person_id or None
    deal_id = deal_id or None
    naechster_schritt = naechster_schritt.strip() if naechster_schritt else None
    inhalt = inhalt.strip()

    if not person_id and not deal_id:
        return JSONResponse({"error": "Entweder person_id oder deal_id muss gesetzt sein"}, status_code=422)
    if not inhalt:
        return JSONResponse({"error": "Inhalt ist Pflichtfeld"}, status_code=422)

    conn = get_connection()
    try:
        ts = now_iso()
        cur = conn.execute(
            """INSERT INTO touchpoint (deal_id, person_id, art, datum, erstellt_von, inhalt,
               naechster_schritt, created_at, created_by)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (deal_id, person_id, art, datum, erstellt_von, inhalt, naechster_schritt, ts, user)
        )
        tp_id = cur.lastrowid

        write_audit_log(conn, user=user, entity_type="touchpoint", entity_id=tp_id,
                        action="CREATE",
                        changed_fields={"person_id": person_id, "deal_id": deal_id,
                                        "art": art, "datum": datum, "erstellt_von": erstellt_von},
                        ip_address=ip)
        conn.commit()
    except Exception as e:
        conn.rollback()
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        conn.close()

    # Redirect zurueck zu Person oder Deal
    if person_id:
        return RedirectResponse(url=f"{prefix}/personen/{person_id}", status_code=303)
    else:
        return RedirectResponse(url=f"{prefix}/deals/{deal_id}", status_code=303)


# ─── GET: Touchpoints fuer Person (HTMX-Fragment) ────────────────────────────

@router.get("/personen/{person_id}/touchpoints", response_class=HTMLResponse)
async def person_touchpoints_fragment(request: Request, person_id: int):
    """Liefert nur die Touchpoint-Liste als HTML-Fragment fuer HTMX-Swap."""
    prefix = request.scope.get("root_path", "")
    conn = get_connection()
    try:
        # Alle Touchpoints dieser Person (direkt oder via Deal)
        touchpoints = conn.execute(
            """SELECT t.*, d.titel as deal_titel
               FROM touchpoint t
               LEFT JOIN deal d ON d.id = t.deal_id
               WHERE (t.person_id = ? OR
                      t.deal_id IN (SELECT id FROM deal WHERE person_id=? AND deleted_at IS NULL))
                 AND t.deleted_at IS NULL
               ORDER BY t.datum DESC, t.created_at DESC""",
            (person_id, person_id)
        ).fetchall()
        touchpoints = [dict(t) for t in touchpoints]

        # Aktive Deals dieser Person fuer Verknüpfungs-Dropdown
        active_deals = conn.execute(
            """SELECT id, titel FROM deal
               WHERE person_id=? AND deleted_at IS NULL AND stage NOT IN ('won','lost')
               ORDER BY created_at DESC""",
            (person_id,)
        ).fetchall()
    finally:
        conn.close()

    return templates.TemplateResponse(request, "touchpoint_timeline_fragment.html", {
        "request": request,
        "prefix": prefix,
        "touchpoints": touchpoints,
        "person_id": person_id,
        "active_deals": active_deals,
        "arten": TOUCHPOINT_ARTEN,
        "owners": OWNERS,
    })
