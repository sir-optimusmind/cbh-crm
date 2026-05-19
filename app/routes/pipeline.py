"""
routes/pipeline.py – CRM-011: Pipeline-Kanban mit 6 Stages + CVR-Header
                     CRM-012: Stage-Definitionen-Seite
                     CRM-027: Opportunity-Spalte mit followup_datum-Sortierung

Regeln:
  - GET /pipeline: Kanban 6 Spalten
  - GET /pipeline/stages: Stage-Definitionen
  - Drag&Drop via SortableJS → PATCH /deals/{id}/stage (in deals.py)
  - Won/Lost finalisiert (kein Drag)
  - Performance: SQLite-Subqueries fuer ACV-Summen
"""

import os
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.db import get_connection

router = APIRouter()
_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")
templates = Jinja2Templates(directory=_TEMPLATE_DIR)

STAGE_ORDER = ["opportunity", "new", "discovery", "proposal_sent", "won", "lost"]


def get_user(request: Request) -> str:
    return request.headers.get("X-Forwarded-User", "system")


# ─── GET /pipeline ─────────────────────────────────────────────────────────────

@router.get("/pipeline", response_class=HTMLResponse)
async def pipeline_kanban(request: Request):
    prefix = request.scope.get("root_path", "")
    conn = get_connection()
    try:
        # Alle aktiven Deals mit Produkt-Liste + Person + Unternehmen
        rows = conn.execute(
            """SELECT d.*,
                      p.vorname || ' ' || p.nachname AS person_name,
                      u.name AS unternehmen_name
               FROM deal d
               LEFT JOIN person p ON p.id = d.person_id
               LEFT JOIN unternehmen u ON u.id = d.unternehmen_id
               WHERE d.deleted_at IS NULL
               ORDER BY
                 CASE d.stage
                   WHEN 'opportunity' THEN 1 WHEN 'new' THEN 2 WHEN 'discovery' THEN 3
                   WHEN 'proposal_sent' THEN 4 WHEN 'won' THEN 5 WHEN 'lost' THEN 6
                 END,
                 -- Opportunity: nach followup_datum aufsteigend (überfällige zuerst)
                 CASE WHEN d.stage = 'opportunity' THEN d.followup_datum END ASC,
                 d.created_at DESC"""
        ).fetchall()

        # Produkte nachladen
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
            acv_sum = sum(d["acv"] for d in stage_deals if d.get("acv"))
            stages_data[stage] = {
                "deals": stage_deals,
                "count": len(stage_deals),
                "acv_sum": acv_sum,
            }

        # CVR zur naechsten Stage berechnen
        # Formel: COUNT(stage n+1) / COUNT(stage n) * 100, max 100%
        # [TECH-DEBT] Snapshot-Naehrung, nicht historischer Flow. Gilt solange kein Stage-History-Log existiert.
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

        # Won: kein CVR, stattdessen YTD-Volumen
        stages_data["won"]["cvr"] = None
        stages_data["won"]["ytd_label"] = True
        stages_data["lost"]["cvr"] = None

    finally:
        conn.close()

    return templates.TemplateResponse(request, "pipeline.html", tmpl_ctx(request, {
        "request": request,
        "prefix": prefix,
        "stages": STAGE_ORDER,
        "stages_data": stages_data,
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

