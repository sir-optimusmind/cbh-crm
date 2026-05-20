"""
routes/deals.py – CRM-010: Deal CRUD + CRM-014: Deal Detail View
                  CRM-015: Won→Projekt-Übergang

Regeln:
  - APP_PREFIX via root_path
  - Audit-Log bei JEDEM Create/Update/Delete
  - PUT = Full Replacement
  - user aus X-Forwarded-User Header, Fallback "system"
  - Soft-Delete via deleted_at
  - Backup-Owner PFLICHT ab stage=opportunity (HART: 422)
  - Stage-spezifische Pflichtfelder (server-side, HART: 422)
  - PATCH /deals/{id}/stage fuer Kanban-Drag&Drop
"""

import os
from datetime import datetime, timezone, date as date_type
from typing import Optional, List

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.db import get_connection, write_audit_log, now_iso
from app.shared.stage_history import log_stage_history
from app.template_utils import tmpl_ctx

router = APIRouter()

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")
templates = Jinja2Templates(directory=_TEMPLATE_DIR)

# ─── Konstanten ───────────────────────────────────────────────────────────────
OWNERS = ["christian", "andre", "michi", "marco", "tim"]
STAGES = ["new", "opportunity", "discovery", "proposal_sent", "won", "lost"]
STAGES_REQUIRING_BACKUP = ["new", "opportunity", "discovery", "proposal_sent", "won", "lost"]
PRODUCTS = ["race", "blindspot", "okr_training", "pm_training", "innovation_cell", "visionsworkshop", "empower_os", "tm", "other"]
LEAD_SOURCES = ["linkedin", "email", "telefon", "lemlist", "cognism", "apollo", "networking", "referral", "other"]
LEAD_TYPES = ["unknown_unknown", "lucky_deal", "inbound"]
# CRM-054: Strukturierte Verlustgrunde (Enum)
VERLUST_REASON_ENUM = [
    "Budget zu klein",
    "Konkurrenz gewonnen",
    "Kein Fit",
    "Timing schlecht",
    "Intern entschieden",
    "Kein Entscheider erreicht",
    "Andere",
]
ICP_PERSONAS = ["forward_thinking_owner", "transformation_leader", "speed_optimizer", "rebels", "other"]


def get_user(request: Request) -> str:
    return request.headers.get("X-Forwarded-User", "system")


def get_client_ip(request: Request) -> Optional[str]:
    return request.headers.get("X-Forwarded-For", request.client.host if request.client else None)


def _validate_deal(
    stage: str,
    owner: str,
    backup_owner: Optional[str],
    followup_datum: Optional[str],
    unterschrift_datum: Optional[str],
    projekt_start_datum: Optional[str],
    verlust_grund: Optional[str],
) -> Optional[str]:
    """
    Server-seitige Validierung fuer Deals.
    Gibt Fehlermeldung zurueck oder None bei Erfolg.
    """
    # Backup-Owner-Regel: ab opportunity Pflicht
    if stage in STAGES_REQUIRING_BACKUP:
        if not backup_owner:
            return "Backup-Owner erforderlich ab Stage Opportunity"
        if backup_owner == owner:
            return "Owner und Backup-Owner müssen verschiedene Personen sein"

    # Auch bei new: wenn backup_owner gesetzt, darf er nicht gleich owner sein
    if backup_owner and backup_owner == owner:
        return "Owner und Backup-Owner müssen verschiedene Personen sein"

    # Stage-spezifische Pflichtfelder
    if stage == "opportunity" and not followup_datum:
        return "Follow-up-Datum ist Pflichtfeld bei Stage Opportunity"
    if stage == "won":
        if not unterschrift_datum:
            return "Unterschriftsdatum ist Pflichtfeld bei Stage Won"
        if not projekt_start_datum:
            return "Projektstartdatum ist Pflichtfeld bei Stage Won"
    if stage == "lost":
        if not verlust_grund:
            return "Verlustgrund ist Pflichtfeld bei Stage Lost"
        if len(verlust_grund) < 10:
            return "Verlustgrund muss mindestens 10 Zeichen lang sein"

    return None


def _enrich_deal(row, conn) -> dict:
    """Reichert Deal-Row mit Produkten und Verknüpfungen an."""
    d = dict(row)
    # Produkte laden
    prods = conn.execute(
        "SELECT product FROM deal_product WHERE deal_id=?", (d["id"],)
    ).fetchall()
    d["products"] = [p["product"] for p in prods]

    # Person-Name laden wenn verknüpft
    if d.get("person_id"):
        p = conn.execute(
            "SELECT vorname, nachname FROM person WHERE id=?", (d["person_id"],)
        ).fetchone()
        d["person_name"] = f"{p['vorname']} {p['nachname']}" if p else None
    else:
        d["person_name"] = None

    # Unternehmen-Name laden wenn verknüpft
    if d.get("unternehmen_id"):
        u = conn.execute(
            "SELECT name FROM unternehmen WHERE id=?", (d["unternehmen_id"],)
        ).fetchone()
        d["unternehmen_name"] = u["name"] if u else None
    else:
        d["unternehmen_name"] = None

    # Projekt laden wenn vorhanden
    proj = conn.execute(
        "SELECT id, name, status FROM project WHERE deal_id=? AND deleted_at IS NULL", (d["id"],)
    ).fetchone()
    d["project"] = dict(proj) if proj else None

    return d


# ─── CRM-010: Deal-Liste ──────────────────────────────────────────────────────

@router.get("/deals", response_class=HTMLResponse)
async def deals_liste(
    request: Request,
    stage: Optional[str] = None,
    owner: Optional[str] = None,
    product: Optional[str] = None,
):
    prefix = request.scope.get("root_path", "")
    conn = get_connection()
    try:
        where_clauses = ["deleted_at IS NULL"]
        params = []
        if stage:
            where_clauses.append("stage = ?")
            params.append(stage)
        if owner:
            where_clauses.append("owner = ?")
            params.append(owner)
        if product:
            where_clauses.append(
                "EXISTS (SELECT 1 FROM deal_product dp WHERE dp.deal_id=id AND dp.product=?)"
            )
            params.append(product)

        where_sql = " AND ".join(where_clauses)
        rows = conn.execute(
            f"SELECT * FROM deal WHERE {where_sql} ORDER BY created_at DESC",
            params
        ).fetchall()

        deals = [_enrich_deal(r, conn) for r in rows]
    finally:
        conn.close()

    return templates.TemplateResponse(request, "deals_liste.html", tmpl_ctx(request, {
        "request": request,
        "prefix": prefix,
        "deals": deals,
        "stages": STAGES,
        "owners": OWNERS,
        "products": PRODUCTS,
        "filter_stage": stage,
        "filter_owner": owner,
        "filter_product": product,
    }))



# ─── CRM-010: Deal anlegen (Formular) ────────────────────────────────────────

@router.get("/deals/new", response_class=HTMLResponse)
async def deal_new_form(request: Request, stage: str = ""):
    prefix = request.scope.get("root_path", "")
    # stage Query-Param: pre-fill Stage wenn vom Pipeline-Header-Plus-Button aufgerufen
    preselected_stage = stage if stage in STAGES else "new"
    conn = get_connection()
    try:
        personen = conn.execute(
            "SELECT id, vorname, nachname FROM person WHERE deleted_at IS NULL ORDER BY nachname"
        ).fetchall()
        unternehmen = conn.execute(
            "SELECT id, name FROM unternehmen WHERE deleted_at IS NULL ORDER BY name"
        ).fetchall()
    finally:
        conn.close()

    return templates.TemplateResponse(request, "deal_form.html", tmpl_ctx(request, {
        "request": request,
        "prefix": prefix,
        "deal": None,
        "personen": personen,
        "unternehmen": unternehmen,
        "stages": STAGES,
        "owners": OWNERS,
        "products": PRODUCTS,
        "lead_sources": LEAD_SOURCES,
        "lead_types": LEAD_TYPES,
        "icp_personas": ICP_PERSONAS,
        "selected_products": [],
        "preselected_stage": preselected_stage,
    }))



# ─── CRM-010: Deal anlegen (POST) ─────────────────────────────────────────────

@router.post("/deals")
async def deal_create(
    request: Request,
    titel: str = Form(...),
    stage: str = Form("new"),
    owner: str = Form(...),
    backup_owner: Optional[str] = Form(None),
    person_id: Optional[int] = Form(None),
    unternehmen_id: Optional[int] = Form(None),
    acv: Optional[float] = Form(None),
    discount_pct: Optional[float] = Form(None),
    risk_reversal: Optional[str] = Form(None),
    deal_cost: Optional[float] = Form(None),
    lead_source: Optional[str] = Form(None),
    lead_type: Optional[str] = Form(None),
    icp_persona: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    followup_datum: Optional[str] = Form(None),
    unterschrift_datum: Optional[str] = Form(None),
    projekt_start_datum: Optional[str] = Form(None),
    verlust_grund: Optional[str] = Form(None),
    retry_datum: Optional[str] = Form(None),
    products: List[str] = Form(default=[]),
):
    prefix = request.scope.get("root_path", "")
    user = get_user(request)
    ip = get_client_ip(request)

    # Leere Strings normalisieren
    backup_owner = backup_owner or None
    person_id = person_id or None
    unternehmen_id = unternehmen_id or None
    lead_source = lead_source or None
    lead_type = lead_type or None
    icp_persona = icp_persona or None
    followup_datum = followup_datum or None
    unterschrift_datum = unterschrift_datum or None
    projekt_start_datum = projekt_start_datum or None
    verlust_grund = verlust_grund.strip() if verlust_grund else None
    retry_datum = retry_datum or None
    notes = notes.strip() if notes else None
    rr = 1 if risk_reversal else 0

    # Validierung
    err = _validate_deal(stage, owner, backup_owner, followup_datum, unterschrift_datum, projekt_start_datum, verlust_grund)
    if err:
        conn = get_connection()
        try:
            personen = conn.execute("SELECT id, vorname, nachname FROM person WHERE deleted_at IS NULL ORDER BY nachname").fetchall()
            unternehmen_list = conn.execute("SELECT id, name FROM unternehmen WHERE deleted_at IS NULL ORDER BY name").fetchall()
        finally:
            conn.close()
        return templates.TemplateResponse(request, "deal_form.html", tmpl_ctx(request, {
            "request": request, "prefix": prefix, "deal": None,
            "personen": personen, "unternehmen": unternehmen_list,
            "stages": STAGES, "owners": OWNERS, "products": PRODUCTS,
            "lead_sources": LEAD_SOURCES, "lead_types": LEAD_TYPES,
            "icp_personas": ICP_PERSONAS, "selected_products": products,
            "flash_error": err,
        }), status_code=422)

    conn = get_connection()
    try:
        ts = now_iso()
        cur = conn.execute(
            """INSERT INTO deal (titel, stage, person_id, unternehmen_id, owner, backup_owner,
               acv, discount_pct, risk_reversal, deal_cost, lead_source, lead_type, icp_persona,
               notes, followup_datum, unterschrift_datum, projekt_start_datum, verlust_grund,
               retry_datum, created_by, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (titel, stage, person_id, unternehmen_id, owner, backup_owner,
             acv, discount_pct, rr, deal_cost, lead_source, lead_type, icp_persona,
             notes, followup_datum, unterschrift_datum, projekt_start_datum, verlust_grund,
             retry_datum, user, ts, ts)
        )
        deal_id = cur.lastrowid

        # Produkte speichern
        for prod in products:
            if prod in PRODUCTS:
                conn.execute(
                    "INSERT OR IGNORE INTO deal_product (deal_id, product) VALUES (?,?)",
                    (deal_id, prod)
                )

        write_audit_log(conn, user=user, entity_type="deal", entity_id=deal_id,
                        action="CREATE", changed_fields={"titel": titel, "stage": stage,
                        "owner": owner, "products": products}, ip_address=ip)
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

    return RedirectResponse(url=f"{prefix}/deals/{deal_id}", status_code=303)


# ─── CRM-014: Deal-Detail ─────────────────────────────────────────────────────

@router.get("/deals/{deal_id}", response_class=HTMLResponse)
async def deal_detail(request: Request, deal_id: int):
    prefix = request.scope.get("root_path", "")
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM deal WHERE id=? AND deleted_at IS NULL", (deal_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Deal nicht gefunden")

        deal = _enrich_deal(row, conn)

        # Touchpoints fuer diesen Deal
        touchpoints = conn.execute(
            """SELECT * FROM touchpoint
               WHERE deal_id=? AND deleted_at IS NULL
               ORDER BY datum DESC, created_at DESC""",
            (deal_id,)
        ).fetchall()
        touchpoints = [dict(t) for t in touchpoints]

        # Aktive Personen fuer Touchpoint-Form
        personen = conn.execute(
            "SELECT id, vorname, nachname FROM person WHERE deleted_at IS NULL ORDER BY nachname"
        ).fetchall()

    finally:
        conn.close()

    return templates.TemplateResponse(request, "deal_detail.html", tmpl_ctx(request, {
        "request": request,
        "prefix": prefix,
        "deal": deal,
        "touchpoints": touchpoints,
        "personen": personen,
        "stages": STAGES,
    }))



# ─── CRM-010: Deal bearbeiten (Formular) ──────────────────────────────────────

@router.get("/deals/{deal_id}/edit", response_class=HTMLResponse)
async def deal_edit_form(request: Request, deal_id: int):
    prefix = request.scope.get("root_path", "")
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM deal WHERE id=? AND deleted_at IS NULL", (deal_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Deal nicht gefunden")

        deal = _enrich_deal(row, conn)
        personen = conn.execute(
            "SELECT id, vorname, nachname FROM person WHERE deleted_at IS NULL ORDER BY nachname"
        ).fetchall()
        unternehmen_list = conn.execute(
            "SELECT id, name FROM unternehmen WHERE deleted_at IS NULL ORDER BY name"
        ).fetchall()
    finally:
        conn.close()

    return templates.TemplateResponse(request, "deal_form.html", tmpl_ctx(request, {
        "request": request,
        "prefix": prefix,
        "deal": deal,
        "personen": personen,
        "unternehmen": unternehmen_list,
        "stages": STAGES,
        "owners": OWNERS,
        "products": PRODUCTS,
        "lead_sources": LEAD_SOURCES,
        "lead_types": LEAD_TYPES,
        "icp_personas": ICP_PERSONAS,
        "selected_products": deal["products"],
    }))



# ─── CRM-010: Deal bearbeiten (PUT) ───────────────────────────────────────────

@router.put("/deals/{deal_id}")
async def deal_update(
    request: Request,
    deal_id: int,
    titel: str = Form(...),
    stage: str = Form(...),
    owner: str = Form(...),
    backup_owner: Optional[str] = Form(None),
    person_id: Optional[int] = Form(None),
    unternehmen_id: Optional[int] = Form(None),
    acv: Optional[float] = Form(None),
    discount_pct: Optional[float] = Form(None),
    risk_reversal: Optional[str] = Form(None),
    deal_cost: Optional[float] = Form(None),
    lead_source: Optional[str] = Form(None),
    lead_type: Optional[str] = Form(None),
    icp_persona: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    followup_datum: Optional[str] = Form(None),
    unterschrift_datum: Optional[str] = Form(None),
    projekt_start_datum: Optional[str] = Form(None),
    verlust_grund: Optional[str] = Form(None),
    retry_datum: Optional[str] = Form(None),
    products: List[str] = Form(default=[]),
):
    prefix = request.scope.get("root_path", "")
    user = get_user(request)
    ip = get_client_ip(request)

    backup_owner = backup_owner or None
    person_id = person_id or None
    unternehmen_id = unternehmen_id or None
    lead_source = lead_source or None
    lead_type = lead_type or None
    icp_persona = icp_persona or None
    followup_datum = followup_datum or None
    unterschrift_datum = unterschrift_datum or None
    projekt_start_datum = projekt_start_datum or None
    verlust_grund = verlust_grund.strip() if verlust_grund else None
    retry_datum = retry_datum or None
    notes = notes.strip() if notes else None
    rr = 1 if risk_reversal else 0

    err = _validate_deal(stage, owner, backup_owner, followup_datum, unterschrift_datum, projekt_start_datum, verlust_grund)
    if err:
        conn = get_connection()
        try:
            row = conn.execute("SELECT * FROM deal WHERE id=? AND deleted_at IS NULL", (deal_id,)).fetchone()
            deal = _enrich_deal(row, conn) if row else None
            personen = conn.execute("SELECT id, vorname, nachname FROM person WHERE deleted_at IS NULL ORDER BY nachname").fetchall()
            unternehmen_list = conn.execute("SELECT id, name FROM unternehmen WHERE deleted_at IS NULL ORDER BY name").fetchall()
        finally:
            conn.close()
        return templates.TemplateResponse(request, "deal_form.html", tmpl_ctx(request, {
            "request": request, "prefix": prefix, "deal": deal,
            "personen": personen, "unternehmen": unternehmen_list,
            "stages": STAGES, "owners": OWNERS, "products": PRODUCTS,
            "lead_sources": LEAD_SOURCES, "lead_types": LEAD_TYPES,
            "icp_personas": ICP_PERSONAS, "selected_products": products,
            "flash_error": err,
        }), status_code=422)

    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT stage FROM deal WHERE id=? AND deleted_at IS NULL", (deal_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Deal nicht gefunden")

        old_stage = existing["stage"]
        ts = now_iso()

        conn.execute(
            """UPDATE deal SET titel=?, stage=?, person_id=?, unternehmen_id=?, owner=?,
               backup_owner=?, acv=?, discount_pct=?, risk_reversal=?, deal_cost=?,
               lead_source=?, lead_type=?, icp_persona=?, notes=?, followup_datum=?,
               unterschrift_datum=?, projekt_start_datum=?, verlust_grund=?, retry_datum=?,
               updated_at=? WHERE id=?""",
            (titel, stage, person_id, unternehmen_id, owner, backup_owner, acv, discount_pct,
             rr, deal_cost, lead_source, lead_type, icp_persona, notes, followup_datum,
             unterschrift_datum, projekt_start_datum, verlust_grund, retry_datum, ts, deal_id)
        )

        # Produkte aktualisieren (Full Replacement)
        conn.execute("DELETE FROM deal_product WHERE deal_id=?", (deal_id,))
        for prod in products:
            if prod in PRODUCTS:
                conn.execute(
                    "INSERT OR IGNORE INTO deal_product (deal_id, product) VALUES (?,?)",
                    (deal_id, prod)
                )

        changed = {"stage": {"from": old_stage, "to": stage}} if old_stage != stage else {}
        changed.update({"titel": titel, "owner": owner, "products": products})
        write_audit_log(conn, user=user, entity_type="deal", entity_id=deal_id,
                        action="UPDATE", changed_fields=changed, ip_address=ip)
        conn.commit()

        # Won → Projekt-Übergang (CRM-015): wenn stage zu won gewechselt
        if old_stage != "won" and stage == "won":
            existing_proj = conn.execute(
                "SELECT id FROM project WHERE deal_id=? AND deleted_at IS NULL", (deal_id,)
            ).fetchone()
            if not existing_proj:
                # Projekt-Form anzeigen statt redirect
                conn.close()
                return RedirectResponse(
                    url=f"{prefix}/deals/{deal_id}/create-project", status_code=303
                )

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return RedirectResponse(url=f"{prefix}/deals/{deal_id}", status_code=303)


# ─── CRM-010: Deal löschen (Soft-Delete) ─────────────────────────────────────

@router.delete("/deals/{deal_id}")
async def deal_delete(request: Request, deal_id: int):
    prefix = request.scope.get("root_path", "")
    user = get_user(request)
    ip = get_client_ip(request)

    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT id FROM deal WHERE id=? AND deleted_at IS NULL", (deal_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Deal nicht gefunden")

        conn.execute(
            "UPDATE deal SET deleted_at=? WHERE id=?",
            (now_iso(), deal_id)
        )
        write_audit_log(conn, user=user, entity_type="deal", entity_id=deal_id,
                        action="DELETE", changed_fields={"deleted": True}, ip_address=ip)
        conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

    return JSONResponse({"redirect": f"{prefix}/deals"}, status_code=200)


# ─── CRM-010: Deal löschen (POST-Override für HTMX/Browser-Forms) ───────────

@router.post("/deals/{deal_id}/delete")
async def deal_delete_post(request: Request, deal_id: int):
    """POST-Override fuer Soft-Delete (Browser-Forms koennen kein DELETE senden)."""
    return await deal_delete(request, deal_id)


# ─── CRM-011: Stage-Wechsel via PATCH (Kanban Drag&Drop) ─────────────────────

@router.patch("/deals/{deal_id}/stage")
async def deal_stage_patch(request: Request, deal_id: int):
    """Stage-Wechsel fuer Kanban Drag&Drop.
    Body: JSON {"stage": "discovery"} oder {"stage": "lost", "verlust_grund": "..."}"""
    prefix = request.scope.get("root_path", "")
    user = get_user(request)
    ip = get_client_ip(request)

    body = await request.json()
    new_stage = body.get("stage", "")
    # CRM-030: verlust_grund aus Body wenn stage=lost (Drag&Drop Modal)
    verlust_grund_body = body.get("verlust_grund", None)
    # CRM-054: strukturierter Verlustgrund (Enum)
    verlust_reason_enum_body = body.get("verlust_reason_enum", None)
    # Validation: nur erlaubte Enum-Werte
    if verlust_reason_enum_body is not None and verlust_reason_enum_body not in VERLUST_REASON_ENUM:
        return JSONResponse({"error": f"Ungültiger verlust_reason_enum-Wert: {verlust_reason_enum_body}"}, status_code=422)

    if new_stage not in STAGES:
        return JSONResponse({"error": f"Ungültige Stage: {new_stage}"}, status_code=422)

    conn = get_connection()
    try:
        # CRM-055: BEGIN IMMEDIATE – serialisiert parallele Stage-Wechsel (Niko-Pattern Sektion 6.2)
        conn.execute("BEGIN IMMEDIATE")

        row = conn.execute(
            "SELECT * FROM deal WHERE id=? AND deleted_at IS NULL", (deal_id,)
        ).fetchone()
        if not row:
            conn.rollback()
            return JSONResponse({"error": "Deal nicht gefunden"}, status_code=404)

        deal = dict(row)
        old_stage = deal["stage"]

        if old_stage in ("won", "lost"):
            conn.rollback()
            return JSONResponse(
                {"error": "Finalisierte Deals können nicht per Drag&Drop verschoben werden"},
                status_code=422
            )

        # Verlust-Grund: aus Body (Modal) oder bestehender DB-Wert
        effective_verlust_grund = verlust_grund_body if verlust_grund_body else deal["verlust_grund"]

        # Backup-Owner-Validierung fuer neue Stage
        err = _validate_deal(
            new_stage, deal["owner"], deal["backup_owner"],
            deal["followup_datum"], deal["unterschrift_datum"],
            deal["projekt_start_datum"], effective_verlust_grund
        )
        if err:
            conn.rollback()
            return JSONResponse({"error": err}, status_code=422)

        ts = now_iso()
        if new_stage == "lost":
            # CRM-030 + CRM-054: verlust_grund + verlust_reason_enum persistieren
            conn.execute(
                "UPDATE deal SET stage=?, verlust_grund=?, verlust_reason_enum=?, updated_at=? WHERE id=?",
                (new_stage, effective_verlust_grund, verlust_reason_enum_body, ts, deal_id)
            )
        else:
            conn.execute(
                "UPDATE deal SET stage=?, updated_at=? WHERE id=?",
                (new_stage, ts, deal_id)
            )

        # CRM-055: History-Eintrag in DERSELBEN Transaktion (atomar)
        log_stage_history(conn, deal_id, old_stage, new_stage, user, ts)

        write_audit_log(conn, user=user, entity_type="deal", entity_id=deal_id,
                        action="UPDATE",
                        changed_fields={"stage": {"from": old_stage, "to": new_stage}},
                        ip_address=ip)
        conn.commit()
    except Exception as e:
        conn.rollback()
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        conn.close()

    # Won → Projekt prüfen
    if new_stage == "won":
        conn2 = get_connection()
        existing_proj = conn2.execute(
            "SELECT id FROM project WHERE deal_id=? AND deleted_at IS NULL", (deal_id,)
        ).fetchone()
        conn2.close()
        if not existing_proj:
            return JSONResponse({"redirect": f"{prefix}/deals/{deal_id}/create-project"}, status_code=200)

    return JSONResponse({"ok": True, "stage": new_stage}, status_code=200)


# ─── CRM-015: Projekt-Anlage nach Won ────────────────────────────────────────

@router.get("/deals/{deal_id}/create-project", response_class=HTMLResponse)
async def deal_create_project_form(request: Request, deal_id: int):
    prefix = request.scope.get("root_path", "")
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM deal WHERE id=? AND deleted_at IS NULL", (deal_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Deal nicht gefunden")
        deal = dict(row)

        # Prüfen ob Projekt schon existiert
        existing_proj = conn.execute(
            "SELECT id FROM project WHERE deal_id=? AND deleted_at IS NULL", (deal_id,)
        ).fetchone()
        if existing_proj:
            return RedirectResponse(
                url=f"{prefix}/projects/{existing_proj['id']}", status_code=303
            )
    finally:
        conn.close()

    return templates.TemplateResponse(request, "project_create.html", tmpl_ctx(request, {
        "request": request,
        "prefix": prefix,
        "deal": deal,
        "owners": OWNERS,
    }))



@router.post("/deals/{deal_id}/create-project")
async def deal_create_project_post(
    request: Request,
    deal_id: int,
    name: str = Form(...),
    delivery_owner: str = Form(...),
    start_date: Optional[str] = Form(None),
    end_date_planned: Optional[str] = Form(None),
    outcome_definition: Optional[str] = Form(None),
    dok_link: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
):
    prefix = request.scope.get("root_path", "")
    user = get_user(request)
    ip = get_client_ip(request)

    conn = get_connection()
    try:
        # Prüfen ob Deal existiert und won ist
        deal_row = conn.execute(
            "SELECT * FROM deal WHERE id=? AND deleted_at IS NULL", (deal_id,)
        ).fetchone()
        if not deal_row:
            raise HTTPException(status_code=404, detail="Deal nicht gefunden")
        deal = dict(deal_row)

        # Doppelter Won-Trigger-Check
        existing_proj = conn.execute(
            "SELECT id FROM project WHERE deal_id=? AND deleted_at IS NULL", (deal_id,)
        ).fetchone()
        if existing_proj:
            return RedirectResponse(
                url=f"{prefix}/projects/{existing_proj['id']}", status_code=303
            )

        ts = now_iso()
        cur = conn.execute(
            """INSERT INTO project (deal_id, name, delivery_owner, status, start_date,
               end_date_planned, contract_value, outcome_definition, dok_link, notes,
               created_by, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (deal_id, name, delivery_owner, "active",
             start_date or deal.get("projekt_start_datum"),
             end_date_planned, deal.get("acv"), outcome_definition, dok_link, notes,
             user, ts, ts)
        )
        proj_id = cur.lastrowid

        write_audit_log(conn, user=user, entity_type="project", entity_id=proj_id,
                        action="CREATE",
                        changed_fields={"deal_id": deal_id, "name": name,
                                        "delivery_owner": delivery_owner,
                                        "contract_value": deal.get("acv"),
                                        "source_deal": deal.get("titel")},
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
