"""
modules/projects/routes.py – Projects-Modul APIRouter
Stories: CRM-036 (Modul-Trennung)

Aggregiert: Projects
URL-Prefix: gesetzt in main.py
"""

from fastapi import APIRouter
from app.modules.projects.projects import router as projects_router

router = APIRouter()
router.include_router(projects_router)
