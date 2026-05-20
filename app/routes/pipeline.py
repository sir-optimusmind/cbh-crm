"""
routes/pipeline.py – CRM-011: Pipeline-Kanban mit 6 Stages + CVR-Header
                     CRM-012: Stage-Definitionen-Seite
                     CRM-027: Opportunity-Spalte mit followup_datum-Sortierung
                     CRM-051: Kanban/Tabellen-Toggle (view=kanban|table)
                     CRM-052: Tabellen-Ansicht mit Sort + Pagination
                     CRM-053: Multi-Produkt-Filter (?produkt=RACE,OKR)
                     CRM-061: Saved Views (GET/POST/DELETE)

Regeln:
  - APP_PREFIX nie hardcoden
  - Audit-Log fuer alle Schreib-Operationen
  - Staging-First: kein direkter Production-Deploy
"""

import os
import json
from typing import Optional, List

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.db import get_connection, write_audit_log, now_iso
from app.template_utils import tmpl_ctx

router = APIRouter()
_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")
templates = Jinja2Templates(directory=_TEMPLATE_DIR)

STAGE_ORDER = ["opportunity", "new", "discovery", "proposal_sent", "won", "lost"]
PRODUCTS_FILTER = ["RACE", "EmpowerOS", "Innovation Cell", "OKR", "PM-Training", "Blindspot", "T&M"]

# Spalten-Config fuer Tabellen-Ansicht (CRM-052)
TABLE_COLUMNS = [
    {"key": "name",           "label": "Name",          "sortable": True},
    {"key": "unternehmen",    "label": "Unternehmen",   "sortable": True},
    {"key": "stage",          "label": "Stage",         "sortable": True},
    {"key": "owner",          "label": "Owner",         "sortable": True},
    {"key": "backup_owner",   "label": "Backup",        "sortable": True},
    {"key": "acv",            "label": "ACV (€)",       "sortable": True},
    {"key": "produkte",       "label": "Produkte",      "sortable": False},
    {"key": "created_at",     "label": "Erstellt",      "sortable": True},
    {"key": "followup_datum", "label": "Follow-up",     "sortable": True},
    {"key": "verlust_reason_enum", "label": "Verlustgrund", "sortable": False},
    {"key": "stage_status",   "label": "Status",        "sortable": True},
]

SORT_FIELD_MAP = {
    "name": "d.name",
    "unternehmen": "u.name",
    "stage": "d.stage",
    "owner": "d.owner",
    "backup_owner": "d.backup_owner",
    "acv": "d.acv",
    "created_at": "d.created_at",
    "followup_datum": "d.followup_datum",
    "stage_status": "d.stage",
}
PAGE_SIZE = 50


def get_user(request: Request) -> str:
    return request.headers.get("X-Forwarded-User", "system")


def _current_user_id(request: Request) -> str:
    """Niko N4-Pattern: Email aus Session, sonst 'default'. SSO CRM-031 ersetzt das hier."""
    user = request.session.get("user") if hasattr(request, "session") else None
    if user and isinstance(user, dict):
        return user.get("email") or "default"
    return "default"


def _build_filter_url(active_filters: list, toggled_product: str) -> str:
    """Baut den Query-String fuer Filter-Toggle. OR-Logik."""
    new_filters = list(active_filters)
    if toggled_product in new_filters:
        new_filters.remove(toggled_product)
    else:
        new_filters.append(toggled_product)
    if not new_filters:
        return ""
    return "&".join(f"produkt={p}" for p in new_filters)


# ─── GET /pipeline ─────────────────────────────────────────────────────────────

@router.get("/pipeline", response_class=HTMLResponse)
async def pipeline_kanban(request: Request):
    prefix = request.scope.get("root_path", "")

    # CRM-051: view-Mode aus Query-Param (default: kanban)
    view_mode = request.query_params.get("view", "kanban")
    if view_mode not in ("kanban", "table"):
        view_mode = "kanban"

    # CRM-053: Multi-Produkt-Filter
    active_filters = request.query_params.getlist("produkt")

    if view_mode == "table":
        return await _pipeline_table_view(request, prefix, active_filters)
    else:
        return await _pipeline_kanban_view(request, prefix, active_filters, view_mode)


async def _pipeline_kanban_view(request: Request, prefix: str, active_filters: list, view_mode: str):
    """CRM-011 + CRM-053: Kanban-Ansicht mit optionalem Produkt-Filter."""
    conn = get_connection()
    try:
        # Basis-Query
        base_sql = """SELECT d.*,
                          p.vorname || ' ' || p.nachname AS person_name,
                          u.name AS unternehmen_name
                   FROM deal d
                   LEFT JOIN person p ON p.id = d.person_id
                   LEFT JOIN unternehmen u ON u.id = d.unternehmen_id
                   WHERE d.deleted_at IS NULL"""
        params = []

        # Produkt-Filter (OR-Logik via deal_product JOIN)
        if active_filters:
            placeholders = ",".join(["?"] * len(active_filters))
            base_sql += f""" AND d.id IN (
                SELECT deal_id FROM deal_product WHERE product IN ({placeholders})
            )"""
            params.extend(active_filters)

        base_sql += """ ORDER BY
                 CASE d.stage
                   WHEN 'opportunity' THEN 1 WHEN 'new' THEN 2 WHEN 'discovery' THEN 3
                   WHEN 'proposal_sent' THEN 4 WHEN 'won' THEN 5 WHEN 'lost' THEN 6
                 END,
                 CASE WHEN d.stage = 'opportunity' THEN d.followup_datum END ASC,
                 d.created_at DESC"""

        rows = conn.execute(base_sql, params).fetchall()

        all_deals = []
        for row in rows:
            d = dict(row)
            prods = conn.execute(
                "SELECT product FROM deal_product WHERE deal_id=?", (d["id"],)
            ).fetchall()
            d["products"] = [p["product"] for p in prods]
            all_deals.append(d)

        # Deals nach Stage gruppieren
        stages_data = {}
        for stage in STAGE_ORDER:
            stage_deals = [d for d in all_deals if d["stage"] == stage]
            # CRM-058: Lost-Spalte max 10 sichtbar
            if stage == "lost":
                total_lost = len(stage_deals)
                visible_deals = sorted(stage_deals, key=lambda d: d.get("updated_at") or "", reverse=True)[:10]
                stages_data[stage] = {
                    "deals": visible_deals,
                    "count": total_lost,
                    "visible_count": len(visible_deals),
                    "has_more": total_lost > 10,
                    "acv_sum": sum(d["acv"] for d in stage_deals if d.get("acv")),
                }
            else:
                acv_sum = sum(d["acv"] for d in stage_deals if d.get("acv"))
                stages_data[stage] = {
                    "deals": stage_deals,
                    "count": len(stage_deals),
                    "visible_count": len(stage_deals),
                    "has_more": False,
                    "acv_sum": acv_sum,
                }

        # CVR: Tech-Debt-Note bleibt bis CRM-056 historische Daten hat
        # Nach CRM-055-Daten-Sammlung wird hier shared/cvr.py verwendet
        active_stages = ["opportunity", "new", "discovery", "proposal_sent"]
        for i, stage in enumerate(active_stages):
            next_stage = active_stages[i + 1] if i + 1 < len(active_stages) else "won"
            curr_count = stages_data[stage]["count"]
            next_count = stages_data[next_stage]["count"]
            if curr_count > 0:
                raw_cvr = round(next_count / curr_count * 100, 0)
                stages_data[stage]["cvr"] = min(raw_cvr, 100)
            else:
                stages_data[stage]["cvr"] = 0

        stages_data["won"]["cvr"] = None
        stages_data["won"]["ytd_label"] = True
        stages_data["lost"]["cvr"] = None

    finally:
        conn.close()

    # Filter-URL-Builder fuer Template
    def build_filter_url(product):
        return _build_filter_url(active_filters, product)

    return templates.TemplateResponse(request, "pipeline.html", tmpl_ctx(request, {
        "request": request,
        "prefix": prefix,
        "stages": STAGE_ORDER,
        "stages_data": stages_data,
        "view_mode": view_mode,
        "active_filters": active_filters,
        "products_filter": PRODUCTS_FILTER,
        "build_filter_url": build_filter_url,
    }))


async def _pipeline_table_view(request: Request, prefix: str, active_filters: list):
    """CRM-052: Tabellen-Ansicht mit Sort + Pagination."""
    sort_field = request.query_params.get("sort", "created_at")
    sort_dir = request.query_params.get("dir", "desc")
    page = max(1, int(request.query_params.get("page", "1")))

    if sort_field not in SORT_FIELD_MAP:
        sort_field = "created_at"
    if sort_dir not in ("asc", "desc"):
        sort_dir = "desc"

    sql_sort = SORT_FIELD_MAP[sort_field]

    conn = get_connection()
    try:
        # COUNT fuer Pagination
        count_sql = """SELECT COUNT(*) as cnt
                        FROM deal d
                        LEFT JOIN person p ON p.id = d.person_id
                        LEFT JOIN unternehmen u ON u.id = d.unternehmen_id
                        WHERE d.deleted_at IS NULL"""
        count_params = []

        if active_filters:
            placeholders = ",".join(["?"] * len(active_filters))
            count_sql += f""" AND d.id IN (
                SELECT deal_id FROM deal_product WHERE product IN ({placeholders})
            )"""
            count_params.extend(active_filters)

        total = conn.execute(count_sql, count_params).fetchone()["cnt"]

        # Daten-Query
        data_sql = f"""SELECT d.*,
                          p.vorname || ' ' || p.nachname AS person_name,
                          u.name AS unternehmen_name
                   FROM deal d
                   LEFT JOIN person p ON p.id = d.person_id
                   LEFT JOIN unternehmen u ON u.id = d.unternehmen_id
                   WHERE d.deleted_at IS NULL"""
        data_params = []

        if active_filters:
            placeholders = ",".join(["?"] * len(active_filters))
            data_sql += f""" AND d.id IN (
                SELECT deal_id FROM deal_product WHERE product IN ({placeholders})
            )"""
            data_params.extend(active_filters)

        data_sql += f" ORDER BY {sql_sort} {sort_dir.upper()} NULLS LAST"
        data_sql += f" LIMIT {PAGE_SIZE} OFFSET {(page-1)*PAGE_SIZE}"

        rows = conn.execute(data_sql, data_params).fetchall()

        deals = []
        for row in rows:
            d = dict(row)
            prods = conn.execute(
                "SELECT product FROM deal_product WHERE deal_id=?", (d["id"],)
            ).fetchall()
            d["products"] = [p["product"] for p in prods]
            deals.append(d)

    finally:
        conn.close()

    # Filter-Params fuer Paginierung-Links
    filter_params = "&".join(f"produkt={p}" for p in active_filters)

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    return templates.TemplateResponse(request, "pipeline_table.html", tmpl_ctx(request, {
        "request": request,
        "prefix": prefix,
        "deals": deals,
        "columns": TABLE_COLUMNS,
        "sort_field": sort_field,
        "sort_dir": sort_dir,
        "page": page,
        "total": total,
        "total_pages": total_pages,
        "active_filters": active_filters,
        "products_filter": PRODUCTS_FILTER,
        "filter_params": filter_params,
        "view_mode": "table",
        "build_filter_url": lambda p: _build_filter_url(active_filters, p),
    }))


# ─── GET /pipeline/stages ──────────────────────────────────────────────────────

@router.get("/pipeline/stages", response_class=HTMLResponse)
async def pipeline_stages(request: Request):
    prefix = request.scope.get("root_path", "")
    conn = get_connection()
    try:
        stage_defs = conn.execute(
            """SELECT * FROM stage_definition
               ORDER BY CASE stage
                 WHEN 'opportunity' THEN 1 WHEN 'new' THEN 2 WHEN 'discovery' THEN 3
                 WHEN 'proposal_sent' THEN 4 WHEN 'won' THEN 5 WHEN 'lost' THEN 6
                 ELSE 99 END"""
        ).fetchall()
        stage_defs = [dict(s) for s in stage_defs]
    finally:
        conn.close()

    return templates.TemplateResponse(request, "pipeline_stages.html", tmpl_ctx(request, {
        "request": request,
        "prefix": prefix,
        "stage_defs": stage_defs,
    }))


# ─── GET /pipeline/lost (CRM-058: Vollständige Lost-Liste) ───────────────────

@router.get("/pipeline/lost", response_class=HTMLResponse)
async def pipeline_lost_all(request: Request):
    prefix = request.scope.get("root_path", "")
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT d.*,
                      p.vorname || ' ' || p.nachname AS person_name,
                      u.name AS unternehmen_name
               FROM deal d
               LEFT JOIN person p ON p.id = d.person_id
               LEFT JOIN unternehmen u ON u.id = d.unternehmen_id
               WHERE d.deleted_at IS NULL AND d.stage='lost'
               ORDER BY d.updated_at DESC"""
        ).fetchall()
        lost_deals = []
        for row in rows:
            d = dict(row)
            prods = conn.execute(
                "SELECT product FROM deal_product WHERE deal_id=?", (d["id"],)
            ).fetchall()
            d["products"] = [p["product"] for p in prods]
            lost_deals.append(d)
    finally:
        conn.close()

    return templates.TemplateResponse(request, "pipeline_lost_all.html", tmpl_ctx(request, {
        "request": request,
        "prefix": prefix,
        "lost_deals": lost_deals,
        "total": len(lost_deals),
    }))


# ─── Saved Views API (CRM-061) ────────────────────────────────────────────────

@router.get("/pipeline/saved-views")
async def saved_views_list(request: Request):
    """GET: Alle Saved Views des aktuellen Users."""
    user_id = _current_user_id(request)
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM saved_view WHERE user_id=? ORDER BY created_at DESC",
            (user_id,)
        ).fetchall()
        views = [dict(r) for r in rows]
    finally:
        conn.close()
    return JSONResponse({"views": views, "user_id": user_id})


@router.post("/pipeline/saved-views")
async def saved_views_create(request: Request):
    """POST: Neue Saved View anlegen."""
    user_id = _current_user_id(request)
    body = await request.json()
    name = (body.get("name") or "").strip()
    query_json = body.get("query_json") or "{}"
    view_type = body.get("view_type", "kanban")

    if not name:
        return JSONResponse({"error": "Name ist Pflicht"}, status_code=400)
    if view_type not in ("kanban", "table"):
        view_type = "kanban"

    # Sicherstellen dass query_json valides JSON ist
    if isinstance(query_json, dict):
        query_json = json.dumps(query_json)

    conn = get_connection()
    try:
        # Max 20 Views pro User
        count = conn.execute(
            "SELECT COUNT(*) as cnt FROM saved_view WHERE user_id=?", (user_id,)
        ).fetchone()["cnt"]
        if count >= 20:
            return JSONResponse({"error": "Maximal 20 gespeicherte Views erlaubt"}, status_code=400)

        conn.execute(
            "INSERT INTO saved_view (user_id, name, query_json, view_type, created_at) VALUES (?,?,?,?,?)",
            (user_id, name, query_json, view_type, now_iso())
        )
        conn.commit()
        new_id = conn.execute("SELECT last_insert_rowid() as id").fetchone()["id"]
    except Exception as e:
        conn.rollback()
        if "UNIQUE constraint failed" in str(e):
            return JSONResponse({"error": f"View-Name '{name}' existiert bereits"}, status_code=409)
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        conn.close()

    return JSONResponse({"ok": True, "id": new_id, "name": name}, status_code=201)


@router.delete("/pipeline/saved-views/{view_id}")
async def saved_views_delete(request: Request, view_id: int):
    """DELETE: Saved View loeschen."""
    user_id = _current_user_id(request)
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id FROM saved_view WHERE id=? AND user_id=?", (view_id, user_id)
        ).fetchone()
        if not row:
            return JSONResponse({"error": "View nicht gefunden"}, status_code=404)
        conn.execute("DELETE FROM saved_view WHERE id=?", (view_id,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        conn.close()
    return JSONResponse({"ok": True})
