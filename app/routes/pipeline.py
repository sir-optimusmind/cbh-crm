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

# CRM-066: Google Drive Picker Konfiguration
GOOGLE_PICKER_API_KEY  = os.getenv("GOOGLE_PICKER_API_KEY", "")
GOOGLE_PROJECT_NUMBER  = os.getenv("GOOGLE_PROJECT_NUMBER", "")
from typing import Optional, List

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.db import get_connection, write_audit_log, now_iso
from app.template_utils import tmpl_ctx
from app.shared.cvr import get_cvr_matrix, cvr_pct, cvr_entry, get_cvr_label_class, invalidate_cvr_cache

router = APIRouter()
_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")
templates = Jinja2Templates(directory=_TEMPLATE_DIR)

STAGE_ORDER = ["opportunity", "new", "discovery", "proposal_sent", "won", "lost"]
PRODUCTS_FILTER = ["RACE", "EmpowerOS", "Innovation Cell", "OKR", "PM-Training", "Blindspot", "T&M"]

# Spalten-Config fuer Tabellen-Ansicht (CRM-052)
TABLE_COLUMNS = [
    {"key": "titel",           "label": "Name",          "sortable": True},
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
    "titel": "d.titel",
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

# STORY-6: Owner-Map fuer Filter-UI (Chip-Labels + Initialen)
OWNERS = [
    {"key": "alle",      "label": "Alle",     "initials": "—"},
    {"key": "christian", "label": "Christian","initials": "CH"},
    {"key": "andre",     "label": "André",    "initials": "AN"},
    {"key": "marco",     "label": "Marco",    "initials": "MA"},
    {"key": "michi",     "label": "Michi",    "initials": "MI"},
    {"key": "tim",       "label": "Tim",      "initials": "TI"},
]
VALID_OWNER_KEYS = {o["key"] for o in OWNERS}


@router.get("/pipeline", response_class=HTMLResponse)
async def pipeline_kanban(request: Request):
    prefix = request.scope.get("root_path", "")

    # CRM-051: view-Mode aus Query-Param (default: kanban)
    view_mode = request.query_params.get("view", "kanban")
    if view_mode not in ("kanban", "table"):
        view_mode = "kanban"

    # CRM-053: Multi-Produkt-Filter
    active_filters = request.query_params.getlist("produkt")

    # STORY-6: Owner-Filter (?owner=marco) – default: alle
    active_owner = request.query_params.get("owner", "alle")
    if active_owner not in VALID_OWNER_KEYS:
        active_owner = "alle"

    if view_mode == "table":
        return await _pipeline_table_view(request, prefix, active_filters, active_owner)
    else:
        return await _pipeline_kanban_view(request, prefix, active_filters, view_mode, active_owner)


async def _pipeline_kanban_view(request: Request, prefix: str, active_filters: list, view_mode: str, active_owner: str = "alle"):
    """CRM-011 + CRM-053 + STORY-6: Kanban-Ansicht mit Produkt- und Owner-Filter."""
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

        # STORY-6: Owner-Filter – bei 'alle' kein Filter, sonst WHERE d.owner = ?
        if active_owner and active_owner != "alle":
            base_sql += " AND d.owner = ?"
            params.append(active_owner)

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

        # CRM-056 / BUG-B: CVR aus deal_stage_history, Cohort-Nenner (A2-Fix Sprint 5)
        cvr_matrix = get_cvr_matrix()
        active_stages = ["opportunity", "new", "discovery", "proposal_sent"]
        for i, stage in enumerate(active_stages):
            next_stage = active_stages[i + 1] if i + 1 < len(active_stages) else "won"
            entry = cvr_entry(stage, next_stage)
            rate = entry.get("rate_pct")
            stages_data[stage]["cvr"] = rate
            stages_data[stage]["cvr_class"] = get_cvr_label_class(rate)
            stages_data[stage]["cvr_low_data"] = entry.get("low_data_flag", False)
            stages_data[stage]["cvr_total_in"] = entry.get("total_in", 0)

        stages_data["won"]["cvr"] = None
        stages_data["won"]["ytd_label"] = True
        stages_data["lost"]["cvr"] = None

        # STORY-5: Stage-Definitionen fuer Tooltips aus bestehender stage_definition-Tabelle
        stage_def_rows = conn.execute(
            "SELECT stage, label, trigger_condition, notes FROM stage_definition"
        ).fetchall()
        stage_defs_map = {
            row["stage"]: {
                "display_name": row["label"],
                "definition":   row["trigger_condition"],
                "required_fields": row["notes"] or "",
            }
            for row in stage_def_rows
        }

    finally:
        conn.close()

    # Filter-URL-Builder fuer Template
    def build_filter_url(product):
        return _build_filter_url(active_filters, product)

    # Saved Views fuer aktuellen User laden (BUG-007)
    user_id = _current_user_id(request)
    sv_conn = get_connection()
    try:
        saved_views_rows = sv_conn.execute(
            "SELECT * FROM saved_view WHERE user_id=? ORDER BY created_at DESC", (user_id,)
        ).fetchall()
        saved_views = [dict(r) for r in saved_views_rows]
    finally:
        sv_conn.close()

    return templates.TemplateResponse(request, "pipeline.html", tmpl_ctx(request, {
        "request": request,
        "prefix": prefix,
        "stages": STAGE_ORDER,
        "stages_data": stages_data,
        "view_mode": view_mode,
        "active_filters": active_filters,
        "products_filter": PRODUCTS_FILTER,
        "build_filter_url": build_filter_url,
        "saved_views": saved_views,
        # STORY-5: Stage-Definitionen fuer Tooltips
        "stage_defs_map": stage_defs_map,
        # STORY-6: Owner-Filter
        "owners": OWNERS,
        "active_owner": active_owner,
        # CRM-066: Google Drive Picker Vars fuer Template-JS
        "google_picker_api_key": GOOGLE_PICKER_API_KEY,
        "google_project_number": GOOGLE_PROJECT_NUMBER,
    }))


async def _pipeline_table_view(request: Request, prefix: str, active_filters: list, active_owner: str = "alle"):
    """CRM-052 + STORY-6: Tabellen-Ansicht mit Sort + Pagination + Owner-Filter."""
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

        # STORY-6: Owner-Filter in Tabellen-Ansicht
        if active_owner and active_owner != "alle":
            count_sql += " AND d.owner = ?"
            count_params.append(active_owner)

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

        # STORY-6: Owner-Filter
        if active_owner and active_owner != "alle":
            data_sql += " AND d.owner = ?"
            data_params.append(active_owner)

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
        # STORY-6: Owner-Filter
        "owners": OWNERS,
        "active_owner": active_owner,
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



# ─── GET /pipeline/funnel (CRM-057) ──────────────────────────────────────────

@router.get("/pipeline/funnel", response_class=HTMLResponse)
async def pipeline_funnel(request: Request):
    """CRM-057: Funnel-Report-Page mit CVR, Verweildauer, Lost-Breakdown."""
    prefix = request.scope.get("root_path", "")
    zeitraum = request.query_params.get("zeitraum", "all")

    conn = get_connection()
    try:
        # History-Daten vorhanden?
        history_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM deal_stage_history"
        ).fetchone()["cnt"]
        has_history_data = history_count >= 5

        # Deal-Counts pro Stage
        stage_rows = conn.execute(
            """SELECT stage, COUNT(*) as cnt, COALESCE(SUM(acv),0) as vol
               FROM deal WHERE deleted_at IS NULL GROUP BY stage"""
        ).fetchall()
        stage_counts = {r["stage"]: {"count": r["cnt"], "vol": r["vol"]} for r in stage_rows}

        # Zeitraum-Filter fuer Verweildauer-Abfrage
        ts_filter = ""
        if zeitraum == "30d":
            ts_filter = "AND moved_at >= datetime('now', '-30 days')"
        elif zeitraum == "90d":
            ts_filter = "AND moved_at >= datetime('now', '-90 days')"
        elif zeitraum == "q1":
            ts_filter = "AND moved_at >= '2026-01-01' AND moved_at < '2026-04-01'"
        elif zeitraum == "q2":
            ts_filter = "AND moved_at >= '2026-04-01' AND moved_at < '2026-07-01'"

        # Durchschnittliche Verweildauer pro Stage
        dwell_rows = conn.execute(f"""
            SELECT h1.from_stage as stage,
                   AVG(julianday(h2.moved_at) - julianday(h1.moved_at)) as avg_days
            FROM deal_stage_history h1
            JOIN deal_stage_history h2 ON h2.deal_id = h1.deal_id
                AND h2.id = (
                    SELECT MIN(id) FROM deal_stage_history
                    WHERE deal_id = h1.deal_id AND id > h1.id
                )
            WHERE h1.from_stage IS NOT NULL {ts_filter}
            GROUP BY h1.from_stage
        """).fetchall()
        dwell = {r["stage"]: round(r["avg_days"], 0) if r["avg_days"] else None for r in dwell_rows}

        # Lost-Breakdown nach verlust_reason_enum
        lost_enum_rows = conn.execute(
            """SELECT verlust_reason_enum, COUNT(*) as cnt
               FROM deal WHERE stage='lost' AND deleted_at IS NULL
               GROUP BY verlust_reason_enum ORDER BY cnt DESC"""
        ).fetchall()
        total_lost = sum(r["cnt"] for r in lost_enum_rows)
        lost_reasons = []
        for r in lost_enum_rows:
            pct = round(100.0 * r["cnt"] / total_lost, 0) if total_lost > 0 else 0
            lost_reasons.append({
                "label": r["verlust_reason_enum"] or "Ohne Angabe",
                "count": r["cnt"],
                "pct": pct,
            })

    finally:
        conn.close()

    # CVR-Matrix (aus Cache) – BUG-B: Cohort-Nenner A2-Fix
    cvr_matrix = get_cvr_matrix()

    # Stages fuer Funnel aufbauen
    funnel_stages = []
    _funnel_order = ["opportunity", "new", "discovery", "proposal_sent", "won"]
    for i, stage in enumerate(_funnel_order):
        stage_info = stage_counts.get(stage, {"count": 0, "vol": 0})
        next_stage = _funnel_order[i + 1] if i < len(_funnel_order) - 1 else None
        if next_stage:
            entry = cvr_entry(stage, next_stage)
            rate = entry.get("rate_pct")
            low_data = entry.get("low_data_flag", False)
            total_in = entry.get("total_in", 0)
        else:
            rate = None
            low_data = False
            total_in = 0
        funnel_stages.append({
            "stage": stage,
            "label": stage.replace("_", " ").title(),
            "count": stage_info["count"],
            "vol": stage_info["vol"],
            "dwell_days": dwell.get(stage),
            "cvr_to_next": rate,
            "cvr_class": get_cvr_label_class(rate),
            "next_stage": next_stage,
            "cvr_low_data": low_data,
            "cvr_total_in": total_in,
        })

    return templates.TemplateResponse(request, "pipeline_funnel.html", tmpl_ctx(request, {
        "request": request,
        "prefix": prefix,
        "has_history_data": has_history_data,
        "history_count": history_count,
        "funnel_stages": funnel_stages,
        "lost_reasons": lost_reasons,
        "total_lost": total_lost,
        "zeitraum": zeitraum,
        "stage_counts": stage_counts,
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
