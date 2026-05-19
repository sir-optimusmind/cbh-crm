"""
routes/unternehmen.py – CRM-005 (Unternehmen CRUD) + CRM-006 (Detail) + CRM-007 (n:m)

Regeln: analog zu personen.py
"""

import os
from typing import Optional

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.db import get_connection, write_audit_log, now_iso

router = APIRouter()

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")
templates = Jinja2Templates(directory=_TEMPLATE_DIR)

BRANCHEN = ["Automotive", "Maschinenbau", "Fertigende-Industrie", "IT-Digital", "Energiewirtschaft", "Other"]


def get_user(request: Request) -> str:
    return request.headers.get("X-Forwarded-User", "system")


def get_client_ip(request: Request) -> Optional[str]:
    return request.headers.get("X-Forwarded-For", request.client.host if request.client else None)


# ─── CRM-005: Listen-View ────────────────────────────────────────────────────

@router.get("/unternehmen", response_class=HTMLResponse)
def unternehmen_liste(request: Request, q: str = "", branche: str = ""):
    prefix = request.scope.get("root_path", "")
    conn = get_connection()
    try:
        sql = "SELECT * FROM unternehmen WHERE deleted_at IS NULL"
        params = []
        if q:
            sql += " AND name LIKE ?"
            params.append(f"%{q}%")
        if branche:
            sql += " AND branche = ?"
            params.append(branche)
        sql += " ORDER BY name"
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    return templates.TemplateResponse(request, "unternehmen_liste.html", {
        "prefix": prefix,
        "unternehmen_list": [dict(r) for r in rows],
        "q": q,
        "branche_filter": branche,
        "branchen": BRANCHEN,
    })


# ─── CRM-005: Anlegen-Form ───────────────────────────────────────────────────

@router.get("/unternehmen/neu", response_class=HTMLResponse)
def unternehmen_neu_form(request: Request):
    prefix = request.scope.get("root_path", "")
    return templates.TemplateResponse(request, "unternehmen_form.html", {
        "prefix": prefix,
        "unternehmen": None,
    })


# ─── CRM-005: POST Anlegen ───────────────────────────────────────────────────

@router.post("/unternehmen")
async def unternehmen_erstellen(
    request: Request,
    name: str = Form(...),
    branche: Optional[str] = Form(None),
    groesse_ma: Optional[str] = Form(None),
    website: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
):
    prefix = request.scope.get("root_path", "")
    user = get_user(request)
    ip = get_client_ip(request)

    branche = branche or None
    website = website.strip() or None if website else None
    notes = notes.strip() or None if notes else None
    groesse_int = int(groesse_ma) if groesse_ma and groesse_ma.strip() else None

    conn = get_connection()
    try:
        ts = now_iso()
        cur = conn.execute(
            """INSERT INTO unternehmen (name, branche, groesse_ma, website, notes, created_by, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, branche, groesse_int, website, notes, user, ts, ts)
        )
        new_id = cur.lastrowid
        write_audit_log(conn,
            user=user, entity_type="unternehmen", entity_id=new_id, action="CREATE",
            changed_fields={"name": name, "branche": branche, "groesse_ma": groesse_int, "website": website, "notes": notes},
            ip_address=ip
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        return JSONResponse({"error": str(e)}, status_code=400)
    finally:
        conn.close()

    return JSONResponse({"redirect": f"{prefix}/unternehmen/{new_id}"})


# ─── CRM-006: Detail-View ────────────────────────────────────────────────────

@router.get("/unternehmen/{unternehmen_id}", response_class=HTMLResponse)
def unternehmen_detail(request: Request, unternehmen_id: int):
    prefix = request.scope.get("root_path", "")
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM unternehmen WHERE id = ? AND deleted_at IS NULL", (unternehmen_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Unternehmen nicht gefunden")
        unternehmen = dict(row)

        # Verknüpfte Personen
        verknuepfungen = conn.execute(
            """SELECT pu.person_id, pu.rolle, pu.primary_company, p.vorname, p.nachname
               FROM person_unternehmen pu
               JOIN person p ON p.id = pu.person_id
               WHERE pu.unternehmen_id = ? AND p.deleted_at IS NULL
               ORDER BY pu.primary_company DESC, p.nachname""",
            (unternehmen_id,)
        ).fetchall()
        verknuepfungen = [dict(v) for v in verknuepfungen]

        # Alle aktiven Personen für Dropdown
        alle_p = conn.execute(
            "SELECT id, vorname, nachname FROM person WHERE deleted_at IS NULL ORDER BY nachname, vorname"
        ).fetchall()
        alle_personen = [dict(p) for p in alle_p]

    finally:
        conn.close()

    return templates.TemplateResponse(request, "unternehmen_detail.html", {
        "prefix": prefix,
        "unternehmen": unternehmen,
        "verknuepfungen": verknuepfungen,
        "alle_personen": alle_personen,
    })


# ─── CRM-005: Edit-Form ──────────────────────────────────────────────────────

@router.get("/unternehmen/{unternehmen_id}/edit", response_class=HTMLResponse)
def unternehmen_edit_form(request: Request, unternehmen_id: int):
    prefix = request.scope.get("root_path", "")
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM unternehmen WHERE id = ? AND deleted_at IS NULL", (unternehmen_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Unternehmen nicht gefunden")
        unternehmen = dict(row)
    finally:
        conn.close()

    return templates.TemplateResponse(request, "unternehmen_form.html", {
        "prefix": prefix,
        "unternehmen": unternehmen,
    })


# ─── CRM-005: PUT Full Replacement ───────────────────────────────────────────

@router.put("/unternehmen/{unternehmen_id}")
async def unternehmen_aktualisieren(
    request: Request,
    unternehmen_id: int,
    name: str = Form(...),
    branche: Optional[str] = Form(None),
    groesse_ma: Optional[str] = Form(None),
    website: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
):
    prefix = request.scope.get("root_path", "")
    user = get_user(request)
    ip = get_client_ip(request)

    branche = branche or None
    website = website.strip() or None if website else None
    notes = notes.strip() or None if notes else None
    groesse_int = int(groesse_ma) if groesse_ma and groesse_ma.strip() else None

    conn = get_connection()
    try:
        old = conn.execute(
            "SELECT * FROM unternehmen WHERE id = ? AND deleted_at IS NULL", (unternehmen_id,)
        ).fetchone()
        if not old:
            raise HTTPException(status_code=404, detail="Unternehmen nicht gefunden")
        old = dict(old)

        ts = now_iso()
        conn.execute(
            """UPDATE unternehmen SET name=?, branche=?, groesse_ma=?, website=?, notes=?, updated_at=?
               WHERE id=?""",
            (name, branche, groesse_int, website, notes, ts, unternehmen_id)
        )

        new_vals = {"name": name, "branche": branche, "groesse_ma": groesse_int, "website": website, "notes": notes}
        diff = {k: {"old": old.get(k), "new": v} for k, v in new_vals.items() if old.get(k) != v}

        write_audit_log(conn,
            user=user, entity_type="unternehmen", entity_id=unternehmen_id, action="UPDATE",
            changed_fields=diff if diff else {"no_change": True},
            ip_address=ip
        )
        conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        return JSONResponse({"error": str(e)}, status_code=400)
    finally:
        conn.close()

    return JSONResponse({"redirect": f"{prefix}/unternehmen/{unternehmen_id}"})


# ─── CRM-005: DELETE (Soft-Delete) ───────────────────────────────────────────

@router.delete("/unternehmen/{unternehmen_id}")
async def unternehmen_loeschen(request: Request, unternehmen_id: int):
    prefix = request.scope.get("root_path", "")
    user = get_user(request)
    ip = get_client_ip(request)

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM unternehmen WHERE id=? AND deleted_at IS NULL", (unternehmen_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Unternehmen nicht gefunden")

        ts = now_iso()
        conn.execute(
            "UPDATE unternehmen SET deleted_at=?, updated_at=? WHERE id=?",
            (ts, ts, unternehmen_id)
        )
        write_audit_log(conn,
            user=user, entity_type="unternehmen", entity_id=unternehmen_id, action="DELETE",
            changed_fields={"deleted_at": ts},
            ip_address=ip
        )
        conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        return JSONResponse({"error": str(e)}, status_code=400)
    finally:
        conn.close()

    return JSONResponse({"redirect": f"{prefix}/unternehmen"})


# ─── CRM-007: Person von Unternehmen-Seite verknüpfen ────────────────────────

@router.post("/unternehmen/{unternehmen_id}/personen")
async def unternehmen_person_verknuepfen(
    request: Request,
    unternehmen_id: int,
    person_id: int = Form(...),
    rolle: Optional[str] = Form(None),
):
    prefix = request.scope.get("root_path", "")
    user = get_user(request)
    ip = get_client_ip(request)

    conn = get_connection()
    try:
        p = conn.execute("SELECT id FROM person WHERE id=? AND deleted_at IS NULL", (person_id,)).fetchone()
        u = conn.execute("SELECT id FROM unternehmen WHERE id=? AND deleted_at IS NULL", (unternehmen_id,)).fetchone()
        if not p or not u:
            raise HTTPException(status_code=404, detail="Person oder Unternehmen nicht gefunden")

        conn.execute(
            """INSERT OR REPLACE INTO person_unternehmen (person_id, unternehmen_id, rolle, primary_company, created_at)
               VALUES (?, ?, ?, 0, ?)""",
            (person_id, unternehmen_id, rolle or None, now_iso())
        )
        write_audit_log(conn,
            user=user, entity_type="person_unternehmen", entity_id=unternehmen_id, action="CREATE",
            changed_fields={"person_id": person_id, "rolle": rolle},
            ip_address=ip
        )
        conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
    finally:
        conn.close()

    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"{prefix}/unternehmen/{unternehmen_id}", status_code=303)


# ─── CRM-007: Verknüpfung lösen (von Unternehmen-Seite) ──────────────────────

@router.delete("/unternehmen/{unternehmen_id}/personen/{person_id}")
async def unternehmen_person_loesen(request: Request, unternehmen_id: int, person_id: int):
    prefix = request.scope.get("root_path", "")
    user = get_user(request)
    ip = get_client_ip(request)

    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM person_unternehmen WHERE unternehmen_id=? AND person_id=?",
            (unternehmen_id, person_id)
        )
        write_audit_log(conn,
            user=user, entity_type="person_unternehmen", entity_id=unternehmen_id, action="DELETE",
            changed_fields={"person_id": person_id},
            ip_address=ip
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
    finally:
        conn.close()

    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"{prefix}/unternehmen/{unternehmen_id}", status_code=303)
