"""
routes/unternehmen.py – CRM-005/006/007 + CRM-022 (Vision-Felder)

Regeln: analog zu personen.py
CRM-022: sense_of_urgency, sense_of_opportunity, financials, news_json,
         produkt_empfehlung, cbh_umsatz_gesamt (aggregiert oder manuell)
"""

import json
import os
from typing import Optional

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.db import get_connection, write_audit_log, now_iso
from app.template_utils import tmpl_ctx

router = APIRouter()

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")
templates = Jinja2Templates(directory=_TEMPLATE_DIR)

BRANCHEN = ["Automotive", "Maschinenbau", "Fertigende-Industrie", "IT-Digital", "Energiewirtschaft", "Other"]
PRODUKTE = ["race", "blindspot", "okr_training", "pm_training", "innovation_cell", "visionsworkshop", "empower_os", "tm", "other"]


def get_user(request: Request) -> str:
    return request.headers.get("X-Forwarded-User", "system")


def get_client_ip(request: Request) -> Optional[str]:
    return request.headers.get("X-Forwarded-For", request.client.host if request.client else None)


def _parse_groesse(groesse_ma: Optional[str]) -> Optional[int]:
    if groesse_ma and groesse_ma.strip():
        try:
            return int(groesse_ma.strip())
        except ValueError:
            return None
    return None


def _parse_float(val: Optional[str]) -> Optional[float]:
    if val and str(val).strip():
        try:
            return float(str(val).strip())
        except ValueError:
            return None
    return None


# ─── Listen-View ─────────────────────────────────────────────────────────────

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

    return templates.TemplateResponse(request, "unternehmen_liste.html", tmpl_ctx(request, {
        "prefix": prefix,
        "unternehmen_list": [dict(r) for r in rows],
        "q": q,
        "branche_filter": branche,
        "branchen": BRANCHEN,
    }))



# ─── Anlegen-Form ─────────────────────────────────────────────────────────────

@router.get("/unternehmen/neu", response_class=HTMLResponse)
def unternehmen_neu_form(request: Request):
    prefix = request.scope.get("root_path", "")
    return templates.TemplateResponse(request, "unternehmen_form.html", tmpl_ctx(request, {
        "prefix": prefix,
        "unternehmen": None,
        "branchen": BRANCHEN,
        "produkte": PRODUKTE,
    }))



# ─── POST Anlegen ─────────────────────────────────────────────────────────────

@router.post("/unternehmen")
async def unternehmen_erstellen(
    request: Request,
    name: str = Form(...),
    branche: Optional[str] = Form(None),
    groesse_ma: Optional[str] = Form(None),
    website: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    hauptsitz: Optional[str] = Form(None),
    muttergesellschaft: Optional[str] = Form(None),
    sense_of_urgency: Optional[str] = Form(None),
    sense_of_opportunity: Optional[str] = Form(None),
    umsatz_mio: Optional[str] = Form(None),
    rentabilitaet_notiz: Optional[str] = Form(None),
    wachstum_notiz: Optional[str] = Form(None),
    news_json: Optional[str] = Form(None),
    produkt_empfehlung: Optional[str] = Form(None),
    produkt_empfehlung_sekundaer: Optional[str] = Form(None),
    eigentuemerstruktur: Optional[str] = Form(None),
    cbh_umsatz_gesamt: Optional[str] = Form(None),
):
    prefix = request.scope.get("root_path", "")
    user = get_user(request)
    ip = get_client_ip(request)

    branche = branche or None
    website = website.strip() or None if website else None
    notes = notes.strip() or None if notes else None
    groesse_int = _parse_groesse(groesse_ma)
    umsatz_mio_f = _parse_float(umsatz_mio)
    cbh_umsatz_f = _parse_float(cbh_umsatz_gesamt)
    hauptsitz = hauptsitz.strip() or None if hauptsitz else None
    muttergesellschaft = muttergesellschaft.strip() or None if muttergesellschaft else None
    sense_of_urgency = sense_of_urgency.strip() or None if sense_of_urgency else None
    sense_of_opportunity = sense_of_opportunity.strip() or None if sense_of_opportunity else None
    rentabilitaet_notiz = rentabilitaet_notiz.strip() or None if rentabilitaet_notiz else None
    wachstum_notiz = wachstum_notiz.strip() or None if wachstum_notiz else None
    news_json = news_json.strip() or None if news_json else None
    produkt_empfehlung = produkt_empfehlung if produkt_empfehlung in PRODUKTE else None
    produkt_empfehlung_sekundaer = produkt_empfehlung_sekundaer if produkt_empfehlung_sekundaer in PRODUKTE else None
    eigentuemerstruktur = eigentuemerstruktur.strip() or None if eigentuemerstruktur else None

    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT id FROM unternehmen WHERE name=? AND deleted_at IS NULL", (name,)
        ).fetchone()
        if existing:
            return JSONResponse(
                {"detail": [{"loc": ["body", "name"], "msg": f"Unternehmen '{name}' existiert bereits", "type": "value_error"}]},
                status_code=422
            )

        ts = now_iso()
        cur = conn.execute(
            """INSERT INTO unternehmen (name, branche, groesse_ma, website, notes,
               hauptsitz, muttergesellschaft, sense_of_urgency, sense_of_opportunity,
               umsatz_mio, rentabilitaet_notiz, wachstum_notiz, news_json,
               produkt_empfehlung, produkt_empfehlung_sekundaer, eigentuemerstruktur,
               cbh_umsatz_gesamt, created_by, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (name, branche, groesse_int, website, notes,
             hauptsitz, muttergesellschaft, sense_of_urgency, sense_of_opportunity,
             umsatz_mio_f, rentabilitaet_notiz, wachstum_notiz, news_json,
             produkt_empfehlung, produkt_empfehlung_sekundaer, eigentuemerstruktur,
             cbh_umsatz_f, user, ts, ts)
        )
        new_id = cur.lastrowid
        write_audit_log(conn,
            user=user, entity_type="unternehmen", entity_id=new_id, action="CREATE",
            changed_fields={"name": name, "branche": branche},
            ip_address=ip
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        return JSONResponse({"error": str(e)}, status_code=400)
    finally:
        conn.close()

    return JSONResponse({"redirect": f"{prefix}/unternehmen/{new_id}"})


# ─── Detail-View (CRM-022) ───────────────────────────────────────────────────

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

        # Verknüpfte Personen mit aktueller Stage (CRM-022 "Bekannte Personen")
        verknuepfungen_raw = conn.execute(
            """SELECT pu.person_id, pu.rolle, pu.primary_company, p.vorname, p.nachname,
                      p.stimmung
               FROM person_unternehmen pu
               JOIN person p ON p.id = pu.person_id
               WHERE pu.unternehmen_id = ? AND p.deleted_at IS NULL
               ORDER BY pu.primary_company DESC, p.nachname""",
            (unternehmen_id,)
        ).fetchall()
        verknuepfungen = [dict(v) for v in verknuepfungen_raw]

        # Aktuellen Deal-Stage pro Person nachladen
        for v in verknuepfungen:
            deal_row = conn.execute(
                """SELECT stage FROM deal WHERE person_id=? AND deleted_at IS NULL
                   ORDER BY created_at DESC LIMIT 1""",
                (v["person_id"],)
            ).fetchone()
            v["aktueller_stage"] = deal_row["stage"] if deal_row else None

        # Alle Personen für Dropdown
        alle_p = conn.execute(
            "SELECT id, vorname, nachname FROM person WHERE deleted_at IS NULL ORDER BY nachname, vorname"
        ).fetchall()
        alle_personen = [dict(p) for p in alle_p]

        person_count = conn.execute(
            "SELECT COUNT(*) FROM person_unternehmen WHERE unternehmen_id=?",
            (unternehmen_id,)
        ).fetchone()[0]

        # CBH-Umsatz: entweder manuell aus cbh_umsatz_gesamt oder aggregiert aus won-Deals
        cbh_umsatz = unternehmen.get("cbh_umsatz_gesamt")
        cbh_umsatz_source = "manuell"
        if cbh_umsatz is None:
            agg = conn.execute(
                """SELECT SUM(acv) FROM deal
                   WHERE unternehmen_id=? AND stage='won' AND deleted_at IS NULL AND acv IS NOT NULL""",
                (unternehmen_id,)
            ).fetchone()[0]
            if agg:
                cbh_umsatz = agg
                cbh_umsatz_source = "aggregiert"

        # News JSON parsen
        news_list = []
        if unternehmen.get("news_json"):
            try:
                news_list = json.loads(unternehmen["news_json"])
                if not isinstance(news_list, list):
                    news_list = []
            except (json.JSONDecodeError, TypeError):
                news_list = []

    finally:
        conn.close()

    return templates.TemplateResponse(request, "unternehmen_detail.html", tmpl_ctx(request, {
        "prefix": prefix,
        "unternehmen": unternehmen,
        "verknuepfungen": verknuepfungen,
        "alle_personen": alle_personen,
        "person_count": person_count,
        "cbh_umsatz": cbh_umsatz,
        "cbh_umsatz_source": cbh_umsatz_source,
        "news_list": news_list,
        "branchen": BRANCHEN,
        "produkte": PRODUKTE,
    }))



# ─── Edit-Form ────────────────────────────────────────────────────────────────

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

    return templates.TemplateResponse(request, "unternehmen_form.html", tmpl_ctx(request, {
        "prefix": prefix,
        "unternehmen": unternehmen,
        "branchen": BRANCHEN,
        "produkte": PRODUKTE,
    }))



# ─── PUT Full Replacement (CRM-022) ──────────────────────────────────────────

@router.put("/unternehmen/{unternehmen_id}")
async def unternehmen_aktualisieren(
    request: Request,
    unternehmen_id: int,
    name: str = Form(...),
    branche: Optional[str] = Form(None),
    groesse_ma: Optional[str] = Form(None),
    website: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    hauptsitz: Optional[str] = Form(None),
    muttergesellschaft: Optional[str] = Form(None),
    sense_of_urgency: Optional[str] = Form(None),
    sense_of_opportunity: Optional[str] = Form(None),
    umsatz_mio: Optional[str] = Form(None),
    rentabilitaet_notiz: Optional[str] = Form(None),
    wachstum_notiz: Optional[str] = Form(None),
    news_json: Optional[str] = Form(None),
    produkt_empfehlung: Optional[str] = Form(None),
    produkt_empfehlung_sekundaer: Optional[str] = Form(None),
    eigentuemerstruktur: Optional[str] = Form(None),
    cbh_umsatz_gesamt: Optional[str] = Form(None),
):
    prefix = request.scope.get("root_path", "")
    user = get_user(request)
    ip = get_client_ip(request)

    branche = branche or None
    website = website.strip() or None if website else None
    notes = notes.strip() or None if notes else None
    groesse_int = _parse_groesse(groesse_ma)
    umsatz_mio_f = _parse_float(umsatz_mio)
    cbh_umsatz_f = _parse_float(cbh_umsatz_gesamt)
    hauptsitz = hauptsitz.strip() or None if hauptsitz else None
    muttergesellschaft = muttergesellschaft.strip() or None if muttergesellschaft else None
    sense_of_urgency = sense_of_urgency.strip() or None if sense_of_urgency else None
    sense_of_opportunity = sense_of_opportunity.strip() or None if sense_of_opportunity else None
    rentabilitaet_notiz = rentabilitaet_notiz.strip() or None if rentabilitaet_notiz else None
    wachstum_notiz = wachstum_notiz.strip() or None if wachstum_notiz else None
    news_json = news_json.strip() or None if news_json else None
    produkt_empfehlung = produkt_empfehlung if produkt_empfehlung in PRODUKTE else None
    produkt_empfehlung_sekundaer = produkt_empfehlung_sekundaer if produkt_empfehlung_sekundaer in PRODUKTE else None
    eigentuemerstruktur = eigentuemerstruktur.strip() or None if eigentuemerstruktur else None

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
            """UPDATE unternehmen SET name=?, branche=?, groesse_ma=?, website=?, notes=?,
               hauptsitz=?, muttergesellschaft=?, sense_of_urgency=?, sense_of_opportunity=?,
               umsatz_mio=?, rentabilitaet_notiz=?, wachstum_notiz=?, news_json=?,
               produkt_empfehlung=?, produkt_empfehlung_sekundaer=?, eigentuemerstruktur=?,
               cbh_umsatz_gesamt=?, updated_at=?
               WHERE id=?""",
            (name, branche, groesse_int, website, notes,
             hauptsitz, muttergesellschaft, sense_of_urgency, sense_of_opportunity,
             umsatz_mio_f, rentabilitaet_notiz, wachstum_notiz, news_json,
             produkt_empfehlung, produkt_empfehlung_sekundaer, eigentuemerstruktur,
             cbh_umsatz_f, ts, unternehmen_id)
        )

        new_vals = {
            "name": name, "branche": branche, "groesse_ma": groesse_int, "website": website,
            "notes": notes, "sense_of_urgency": sense_of_urgency,
            "sense_of_opportunity": sense_of_opportunity, "umsatz_mio": umsatz_mio_f,
            "produkt_empfehlung": produkt_empfehlung,
        }
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


# ─── DELETE (Soft-Delete) ─────────────────────────────────────────────────────

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

        linked_count = conn.execute(
            "SELECT COUNT(*) FROM person_unternehmen WHERE unternehmen_id=?",
            (unternehmen_id,)
        ).fetchone()[0]
        if linked_count > 0:
            return JSONResponse({"error": "Erst Personen-Verknüpfungen lösen"}, status_code=422)

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


# ─── CRM-007: Verknüpfung lösen ──────────────────────────────────────────────

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
