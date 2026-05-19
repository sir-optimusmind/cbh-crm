"""
modules/crm/routes.py – CRM-Modul APIRouter
Stories: CRM-035 (Modul-Trennung)

Aggregiert: Personen + Unternehmen + Touchpoints
URL-Prefix: /crm (wird in main.py gesetzt)
"""

from fastapi import APIRouter
from app.modules.crm.personen import router as personen_router
from app.modules.crm.unternehmen import router as unternehmen_router
from app.modules.crm.touchpoints import router as touchpoints_router

router = APIRouter()
router.include_router(personen_router)
router.include_router(unternehmen_router)
router.include_router(touchpoints_router)
