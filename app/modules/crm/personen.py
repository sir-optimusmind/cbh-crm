"""
routes/personen.py – CRM-003/004/007 + CRM-QW-02/03 + CRM-021 (Vision-Felder) + CRM-029 (LinkedIn-Trigger)

Regeln:
  - APP_PREFIX kommt via root_path
  - Audit-Log bei JEDEM Create/Update/Delete
  - PUT = Full Replacement
  - user aus X-Forwarded-User Header, Fallback "system"
  - Soft-Delete via deleted_at
  - stimmung: kalt/warm/heiss (CRM-QW-02)
  - stimmung_cbh: sehr_positiv/positiv/neutral/skeptisch/negativ (CRM-021 Mood-Meter)
  - karriere_stationen: JSON-Text (CRM-021)
  - persoenlichkeit_notizen: Freitext (CRM-021)
  - linkedin_trigger_notiz + linkedin_trigger_datum (CRM-029)
"""

import os
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.db import get_connection, write_audit_log, now_iso
from app.template_utils import tmpl_ctx

_EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_email(email: Optional[str]) -> Optional[str]:
    if not email:
        return None
    cleaned = email.strip()
    if not cleaned:
        return None
    if not _EMAIL_REGEX.match(cleaned):
        raise ValueError(f"Ungültiges E-Mail-Format: {cleaned}")
    return cleaned


router = APIRouter()
_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")
templates = Jinja2Templates(directory=_TEMPLATE_DIR)

OWNERS = ["christian", "andre", "michi", "marco", "tim"]
PROSPECT_LEVELS = ["Owner", "CxO", "Head", "Manager", "Other"]
STIMMUNGEN = ["kalt", "warm", "heiss"]
STIMMUNGEN_CBH = ["sehr_positiv", "positiv", "neutral", "skeptisch", "negativ"]


def get_user(request: Request) -> str:
    return request.headers.get("X-Forwarded-User", "system")


def get_client_ip(request: Request) -> Optional[str]:
    return request.headers.get("X-Forwarded-For", request.client.host if request.client else None)


def _enrich_person(row) -> dict:
    p = dict(row)
    conn = get_connection()
    try:
        pu = conn.execute(
            """SELECT pu.unternehmen_id, u.name
               FROM person_unternehmen pu
               JOIN unternehmen u ON u.id = pu.unternehmen_id
               WHERE pu.person_id = ? AND pu.primary_company = 1
               LIMIT 1""",
            (p["id"],)
        ).fetchone()
        if pu:
            p["primary_company_id"] = pu["unternehmen_id"]
            p["primary_company_name"] = pu["name"]
        else:
            p["primary_company_id"] = None
            p["primary_company_name"] = None
    finally:
        conn.close()
    return p


def _last_contact_sql_condition(letzter_kontakt: str) -> tuple[str, list]:
    now = datetime.now(timezone.utc)
    if letzter_kontakt == "heute":
        cutoff = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        return " AND p.last_contact_at >= ?", [cutoff]
    elif letzter_kontakt == "7tage":
        cutoff = (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        return " AND p.last_contact_at >= ?", [cutoff]
    elif letzter_kontakt == "30tage":
        cutoff = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        return " AND p.last_contact_at >= ?", [cutoff]
    elif letzter_kontakt == "90tage":
        cutoff = (now - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        return " AND p.last_contact_at >= ?", [cutoff]
    elif letzter_kontakt == "aelter90":
        cutoff = (now - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        return " AND p.last_contact_at < ? AND p.last_contact_at IS NOT NULL", [cutoff]
    elif letzter_kontakt == "nie":
        return " AND p.last_contact_at IS NULL", []
    else:
        return "", []


# ─── Listen-View ─────────────────────────────────────────────────────────────

@router.get("/personen", response_class=HTMLResponse)
def personen_liste(
    request: Request,
    q: str = "",
    owner: str = "",
    stimmung: str = "",
    letzter_kontakt: str = "",
):
    prefix = request.scope.get("root_path", "")
    conn = get_connection()
    try:
        sql = "SELECT p.* FROM person p WHERE p.deleted_at IS NULL"
        params = []
        if q:
            sql += " AND (p.vorname || ' ' || p.nachname LIKE ? OR p.email LIKE ?)"
            params += [f"%{q}%", f"%{q}%"]
        if owner:
            sql += " AND p.created_by = ?"
            params.append(owner)
        if stimmung:
            sql += " AND p.stimmung = ?"
            params.append(stimmung)
        lk_sql, lk_params = _last_contact_sql_condition(letzter_kontakt)
        sql += lk_sql
        params += lk_params
        sql += " ORDER BY p.nachname, p.vorname"
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    personen = [_enrich_person(r) for r in rows]
    return templates.TemplateResponse(request, "personen_liste.html", tmpl_ctx(request, {
        "prefix": prefix,
        "personen": personen,
        "q": q,
        "owner_filter": owner,
        "owners": OWNERS,
        "stimmungen": STIMMUNGEN,
        "stimmung_filter": stimmung,
        "letzter_kontakt_filter": letzter_kontakt,
    }))



# ─── Anlegen-Form ─────────────────────────────────────────────────────────────

@router.get("/personen/neu", response_class=HTMLResponse)
def person_neu_form(request: Request):
    prefix = request.scope.get("root_path", "")
    return templates.TemplateResponse(request, "person_form.html", tmpl_ctx(request, {
        "prefix": prefix,
        "person": None,
        "owners": OWNERS,
        "stimmungen": STIMMUNGEN,
        "stimmungen_cbh": STIMMUNGEN_CBH,
    }))



# ─── POST Anlegen ─────────────────────────────────────────────────────────────

@router.post("/personen")
async def person_erstellen(
    request: Request,
    vorname: str = Form(...),
    nachname: str = Form(...),
    email: Optional[str] = Form(None),
    telefon: Optional[str] = Form(None),
    position: Optional[str] = Form(None),
    prospect_level: Optional[str] = Form(None),
    stimmung: Optional[str] = Form(None),
    last_contact_at: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    created_by: Optional[str] = Form(None),
    linkedin_url: Optional[str] = Form(None),
    karriere_stationen: Optional[str] = Form(None),
    stimmung_cbh: Optional[str] = Form(None),
    persoenlichkeit_notizen: Optional[str] = Form(None),
    linkedin_trigger_notiz: Optional[str] = Form(None),
    linkedin_trigger_datum: Optional[str] = Form(None),
):
    prefix = request.scope.get("root_path", "")
    user = get_user(request)
    ip = get_client_ip(request)

    try:
        email = _validate_email(email)
    except ValueError as ve:
        return JSONResponse(
            {"detail": [{"loc": ["body", "email"], "msg": str(ve), "type": "value_error"}]},
            status_code=422
        )

    telefon = telefon.strip() or None if telefon else None
    position = position.strip() or None if position else None
    prospect_level = prospect_level or None
    stimmung = stimmung if stimmung in STIMMUNGEN else "kalt"
    stimmung_cbh = stimmung_cbh if stimmung_cbh in STIMMUNGEN_CBH else None
    last_contact_at = last_contact_at.strip() or None if last_contact_at else None
    notes = notes.strip() or None if notes else None
    created_by = created_by or user
    linkedin_url = linkedin_url.strip() or None if linkedin_url else None
    karriere_stationen = karriere_stationen.strip() or None if karriere_stationen else None
    persoenlichkeit_notizen = persoenlichkeit_notizen.strip() or None if persoenlichkeit_notizen else None
    linkedin_trigger_notiz = linkedin_trigger_notiz.strip() or None if linkedin_trigger_notiz else None
    linkedin_trigger_datum = linkedin_trigger_datum.strip() or None if linkedin_trigger_datum else None

    conn = get_connection()
    try:
        ts = now_iso()
        cur = conn.execute(
            """INSERT INTO person (vorname, nachname, email, telefon, position, prospect_level,
               stimmung, last_contact_at, notes, created_by, created_at, updated_at,
               linkedin_url, karriere_stationen, stimmung_cbh, persoenlichkeit_notizen,
               linkedin_trigger_notiz, linkedin_trigger_datum)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (vorname, nachname, email, telefon, position, prospect_level,
             stimmung, last_contact_at, notes, created_by, ts, ts,
             linkedin_url, karriere_stationen, stimmung_cbh, persoenlichkeit_notizen,
             linkedin_trigger_notiz, linkedin_trigger_datum)
        )
        new_id = cur.lastrowid
        write_audit_log(conn,
            user=user, entity_type="person", entity_id=new_id, action="CREATE",
            changed_fields={
                "vorname": vorname, "nachname": nachname, "email": email,
                "telefon": telefon, "position": position, "prospect_level": prospect_level,
                "stimmung": stimmung, "stimmung_cbh": stimmung_cbh,
                "last_contact_at": last_contact_at, "notes": notes, "created_by": created_by,
            },
            ip_address=ip
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        return JSONResponse({"error": str(e)}, status_code=400)
    finally:
        conn.close()

    return JSONResponse({"redirect": f"{prefix}/personen/{new_id}"})


# ─── Detail-View ──────────────────────────────────────────────────────────────

@router.get("/personen/{person_id}", response_class=HTMLResponse)
def person_detail(request: Request, person_id: int):
    prefix = request.scope.get("root_path", "")
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM person WHERE id = ? AND deleted_at IS NULL", (person_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Person nicht gefunden")

        person = dict(row)

        verknuepfungen = conn.execute(
            """SELECT pu.unternehmen_id, pu.rolle, pu.primary_company, u.name
               FROM person_unternehmen pu
               JOIN unternehmen u ON u.id = pu.unternehmen_id
               WHERE pu.person_id = ? AND u.deleted_at IS NULL
               ORDER BY pu.primary_company DESC, u.name""",
            (person_id,)
        ).fetchall()
        verknuepfungen = [dict(v) for v in verknuepfungen]

        alle_unt = conn.execute(
            "SELECT id, name FROM unternehmen WHERE deleted_at IS NULL ORDER BY name"
        ).fetchall()
        alle_unternehmen = [dict(u) for u in alle_unt]

        touchpoints_raw = conn.execute(
            """SELECT t.*, d.titel as deal_titel
               FROM touchpoint t
               LEFT JOIN deal d ON d.id = t.deal_id
               WHERE (t.person_id = ? OR
                      t.deal_id IN (SELECT id FROM deal WHERE person_id=? AND deleted_at IS NULL))
                 AND t.deleted_at IS NULL
               ORDER BY t.datum DESC, t.created_at DESC""",
            (person_id, person_id)
        ).fetchall()
        touchpoints = [dict(tp) for tp in touchpoints_raw]

        aktive_deals_raw = conn.execute(
            """SELECT id, titel FROM deal
               WHERE person_id=? AND deleted_at IS NULL AND stage NOT IN ('won','lost')
               ORDER BY created_at DESC""",
            (person_id,)
        ).fetchall()
        aktive_deals = [dict(d) for d in aktive_deals_raw]

        # Aktueller Deal-Stage für Pipeline-Status Block (neuester aktiver Deal)
        aktueller_deal = conn.execute(
            """SELECT d.id, d.titel, d.stage, d.followup_datum
               FROM deal d
               WHERE d.person_id=? AND d.deleted_at IS NULL
               ORDER BY d.created_at DESC LIMIT 1""",
            (person_id,)
        ).fetchone()
        aktueller_deal = dict(aktueller_deal) if aktueller_deal else None

    finally:
        conn.close()

    return templates.TemplateResponse(request, "person_detail.html", tmpl_ctx(request, {
        "prefix": prefix,
        "person": person,
        "verknuepfungen": verknuepfungen,
        "alle_unternehmen": alle_unternehmen,
        "stimmungen": STIMMUNGEN,
        "stimmungen_cbh": STIMMUNGEN_CBH,
        "touchpoints": touchpoints,
        "aktive_deals": aktive_deals,
        "aktueller_deal": aktueller_deal,
    }))



# ─── Edit-Form ────────────────────────────────────────────────────────────────

@router.get("/personen/{person_id}/edit", response_class=HTMLResponse)
def person_edit_form(request: Request, person_id: int):
    prefix = request.scope.get("root_path", "")
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM person WHERE id = ? AND deleted_at IS NULL", (person_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Person nicht gefunden")
        person = dict(row)
    finally:
        conn.close()

    return templates.TemplateResponse(request, "person_form.html", tmpl_ctx(request, {
        "prefix": prefix,
        "person": person,
        "owners": OWNERS,
        "stimmungen": STIMMUNGEN,
        "stimmungen_cbh": STIMMUNGEN_CBH,
    }))



# ─── PUT Full Replacement ─────────────────────────────────────────────────────

@router.put("/personen/{person_id}")
async def person_aktualisieren(
    request: Request,
    person_id: int,
    vorname: str = Form(...),
    nachname: str = Form(...),
    email: Optional[str] = Form(None),
    telefon: Optional[str] = Form(None),
    position: Optional[str] = Form(None),
    prospect_level: Optional[str] = Form(None),
    stimmung: Optional[str] = Form(None),
    last_contact_at: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    created_by: Optional[str] = Form(None),
    linkedin_url: Optional[str] = Form(None),
    karriere_stationen: Optional[str] = Form(None),
    stimmung_cbh: Optional[str] = Form(None),
    persoenlichkeit_notizen: Optional[str] = Form(None),
    umsatz_gesamt_cbh: Optional[float] = Form(None),
    linkedin_trigger_notiz: Optional[str] = Form(None),
    linkedin_trigger_datum: Optional[str] = Form(None),
):
    prefix = request.scope.get("root_path", "")
    user = get_user(request)
    ip = get_client_ip(request)

    try:
        email = _validate_email(email)
    except ValueError as ve:
        return JSONResponse(
            {"detail": [{"loc": ["body", "email"], "msg": str(ve), "type": "value_error"}]},
            status_code=422
        )

    telefon = telefon.strip() or None if telefon else None
    position = position.strip() or None if position else None
    prospect_level = prospect_level or None
    stimmung = stimmung if stimmung in STIMMUNGEN else "kalt"
    stimmung_cbh = stimmung_cbh if stimmung_cbh in STIMMUNGEN_CBH else None
    last_contact_at = last_contact_at.strip() or None if last_contact_at else None
    notes = notes.strip() or None if notes else None
    created_by = created_by or user
    linkedin_url = linkedin_url.strip() or None if linkedin_url else None
    karriere_stationen = karriere_stationen.strip() or None if karriere_stationen else None
    persoenlichkeit_notizen = persoenlichkeit_notizen.strip() or None if persoenlichkeit_notizen else None
    linkedin_trigger_notiz = linkedin_trigger_notiz.strip() or None if linkedin_trigger_notiz else None
    linkedin_trigger_datum = linkedin_trigger_datum.strip() or None if linkedin_trigger_datum else None

    conn = get_connection()
    try:
        old = conn.execute(
            "SELECT * FROM person WHERE id = ? AND deleted_at IS NULL", (person_id,)
        ).fetchone()
        if not old:
            raise HTTPException(status_code=404, detail="Person nicht gefunden")
        old = dict(old)

        ts = now_iso()
        conn.execute(
            """UPDATE person SET vorname=?, nachname=?, email=?, telefon=?, position=?,
               prospect_level=?, stimmung=?, last_contact_at=?, notes=?, created_by=?,
               updated_at=?, linkedin_url=?, karriere_stationen=?, stimmung_cbh=?,
               persoenlichkeit_notizen=?, umsatz_gesamt_cbh=?,
               linkedin_trigger_notiz=?, linkedin_trigger_datum=?
               WHERE id = ?""",
            (vorname, nachname, email, telefon, position, prospect_level,
             stimmung, last_contact_at, notes, created_by, ts,
             linkedin_url, karriere_stationen, stimmung_cbh,
             persoenlichkeit_notizen, umsatz_gesamt_cbh,
             linkedin_trigger_notiz, linkedin_trigger_datum,
             person_id)
        )

        new_vals = {
            "vorname": vorname, "nachname": nachname, "email": email,
            "telefon": telefon, "position": position, "prospect_level": prospect_level,
            "stimmung": stimmung, "stimmung_cbh": stimmung_cbh,
            "last_contact_at": last_contact_at, "notes": notes, "created_by": created_by,
            "linkedin_url": linkedin_url, "karriere_stationen": karriere_stationen,
            "persoenlichkeit_notizen": persoenlichkeit_notizen,
            "umsatz_gesamt_cbh": umsatz_gesamt_cbh,
            "linkedin_trigger_notiz": linkedin_trigger_notiz,
            "linkedin_trigger_datum": linkedin_trigger_datum,
        }
        diff = {k: {"old": old.get(k), "new": v} for k, v in new_vals.items() if old.get(k) != v}

        write_audit_log(conn,
            user=user, entity_type="person", entity_id=person_id, action="UPDATE",
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

    return JSONResponse({"redirect": f"{prefix}/personen/{person_id}"})


# ─── DELETE (Soft-Delete) ─────────────────────────────────────────────────────

@router.delete("/personen/{person_id}")
async def person_loeschen(request: Request, person_id: int):
    prefix = request.scope.get("root_path", "")
    user = get_user(request)
    ip = get_client_ip(request)

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM person WHERE id = ? AND deleted_at IS NULL", (person_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Person nicht gefunden")

        ts = now_iso()
        conn.execute(
            "UPDATE person SET deleted_at = ?, updated_at = ? WHERE id = ?",
            (ts, ts, person_id)
        )
        write_audit_log(conn,
            user=user, entity_type="person", entity_id=person_id, action="DELETE",
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

    return JSONResponse({"redirect": f"{prefix}/personen"})


# ─── CRM-007: Person↔Unternehmen verknüpfen ──────────────────────────────────

@router.post("/personen/{person_id}/unternehmen")
async def person_unternehmen_verknuepfen(
    request: Request,
    person_id: int,
    unternehmen_id: int = Form(...),
    rolle: Optional[str] = Form(None),
    primary_company: Optional[str] = Form(None),
):
    prefix = request.scope.get("root_path", "")
    user = get_user(request)
    ip = get_client_ip(request)
    is_primary = 1 if primary_company else 0

    conn = get_connection()
    try:
        p = conn.execute("SELECT id FROM person WHERE id=? AND deleted_at IS NULL", (person_id,)).fetchone()
        u = conn.execute("SELECT id FROM unternehmen WHERE id=? AND deleted_at IS NULL", (unternehmen_id,)).fetchone()
        if not p or not u:
            raise HTTPException(status_code=404, detail="Person oder Unternehmen nicht gefunden")

        existing_link = conn.execute(
            "SELECT 1 FROM person_unternehmen WHERE person_id=? AND unternehmen_id=?",
            (person_id, unternehmen_id)
        ).fetchone()
        if existing_link:
            return JSONResponse(
                {"detail": [{"loc": ["body", "unternehmen_id"], "msg": "Verknüpfung bereits vorhanden", "type": "value_error"}]},
                status_code=422
            )

        if is_primary:
            conn.execute(
                "UPDATE person_unternehmen SET primary_company=0 WHERE person_id=?",
                (person_id,)
            )

        conn.execute(
            """INSERT INTO person_unternehmen (person_id, unternehmen_id, rolle, primary_company, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (person_id, unternehmen_id, rolle or None, is_primary, now_iso())
        )

        write_audit_log(conn,
            user=user, entity_type="person_unternehmen", entity_id=person_id, action="CREATE",
            changed_fields={"unternehmen_id": unternehmen_id, "rolle": rolle, "primary_company": is_primary},
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

    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"{prefix}/personen/{person_id}", status_code=303)


@router.post("/personen/{person_id}/unternehmen/{unternehmen_id}/set-primary")
async def person_unternehmen_set_primary(request: Request, person_id: int, unternehmen_id: int):
    prefix = request.scope.get("root_path", "")
    user = get_user(request)
    ip = get_client_ip(request)

    conn = get_connection()
    try:
        conn.execute(
            "UPDATE person_unternehmen SET primary_company=0 WHERE person_id=?",
            (person_id,)
        )
        conn.execute(
            "UPDATE person_unternehmen SET primary_company=1 WHERE person_id=? AND unternehmen_id=?",
            (person_id, unternehmen_id)
        )
        write_audit_log(conn,
            user=user, entity_type="person_unternehmen", entity_id=person_id, action="UPDATE",
            changed_fields={"primary_company": unternehmen_id},
            ip_address=ip
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
    finally:
        conn.close()

    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"{prefix}/personen/{person_id}", status_code=303)


@router.delete("/personen/{person_id}/unternehmen/{unternehmen_id}")
async def person_unternehmen_loesen(request: Request, person_id: int, unternehmen_id: int):
    prefix = request.scope.get("root_path", "")
    user = get_user(request)
    ip = get_client_ip(request)

    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM person_unternehmen WHERE person_id=? AND unternehmen_id=?",
            (person_id, unternehmen_id)
        )
        write_audit_log(conn,
            user=user, entity_type="person_unternehmen", entity_id=person_id, action="DELETE",
            changed_fields={"unternehmen_id": unternehmen_id},
            ip_address=ip
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
    finally:
        conn.close()

    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"{prefix}/personen/{person_id}", status_code=303)
