"""
modules/pipeline/routes.py – Pipeline-Modul APIRouter
Stories: CRM-035 (Modul-Trennung)

Aggregiert: Deals + Pipeline-Kanban
URL-Prefix: gesetzt in main.py (keine eigenen Sub-Prefixe noetig,
da deals.py + pipeline.py ihre Pfade direkt definieren)
"""

from fastapi import APIRouter
from app.modules.pipeline.deals import router as deals_router
from app.modules.pipeline.pipeline import router as pipeline_router

router = APIRouter()
router.include_router(deals_router)
router.include_router(pipeline_router)
