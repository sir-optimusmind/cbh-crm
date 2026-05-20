"""
modules/pipeline/routes.py – Pipeline-Modul APIRouter
Stories: CRM-035 (Modul-Trennung)

FIX CRM-2b (2026-05-20): Auf vollstaendige app.routes umgestellt.
app.modules.pipeline.pipeline hatte kein view_mode/filter/funnel/won-modal.
app.routes.pipeline + app.routes.deals enthalten alles inkl. stage_history.

Aggregiert: Deals (CRUD + Stage-Patch + Won-Modal + Stage-History) + Pipeline-Kanban
            (Toggle, Filter, Funnel, Saved Views, Lost-All)
"""

from fastapi import APIRouter
from app.routes.deals import router as deals_router
from app.routes.pipeline import router as pipeline_router

router = APIRouter()
router.include_router(deals_router)
router.include_router(pipeline_router)
