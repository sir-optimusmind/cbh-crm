"""
main.py – CBH MISSION CTRL CRM Module
FastAPI App – Sprint 1 + Sprint 2 + Sprint 3 (SSO + Modul-Trennung)
Sprint 3 Wave 2: Sidebar + Breadcrumb + Command-Palette + Home-Dashboard

APP_PREFIX kommt aus .env (PFLICHT, nie hardcoden).
SSO via Google OAuth (CRM-031/032/033/034).
Modul-Trennung: CRM / Pipeline / Projects (CRM-035/036).
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.db import init_db
from app.auth import router as auth_router, SECRET_KEY, SESSION_MAX_AGE
from app.shared.templating import render

# ─── Modul-Router ─────────────────────────────────────────────────────────────
from app.modules.crm.routes import router as crm_router
from app.modules.pipeline.routes import router as pipeline_router
from app.modules.projects.routes import router as projects_router
from app.shared.drive_auth import router as drive_auth_router

# ─── Konfiguration aus .env ───────────────────────────────────────────────────
APP_PREFIX = os.getenv("APP_PREFIX", "/mission-ctrl/crm-staging").rstrip("/")
CRM_ENV    = os.getenv("CRM_ENV", "staging")


# ─── Startup / Shutdown ───────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


# ─── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="CBH MISSION CTRL – CRM",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
    # root_path entfernt – kommt jetzt via uvicorn --root-path
)

# ─── Static Files ─────────────────────────────────────────────────────────────
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


# ─── Auth-Guard Middleware ────────────────────────────────────────────────────
class AuthGuardMiddleware(BaseHTTPMiddleware):
    """
    Prueft Session bei jedem Request.
    Oeffentliche Pfade: /health, /auth/*, /static/*
    Alle anderen: Session-Check, sonst Redirect zu /auth/login.

    Middleware-Reihenfolge (LIFO):
    SessionMiddleware wird NACH AuthGuardMiddleware registriert →
    SessionMiddleware laeuft ZUERST (verarbeitet Cookie) →
    AuthGuardMiddleware hat request.session verfuegbar.
    """

    PUBLIC_PATHS = ("/health", "/auth/login", "/auth/callback", "/auth/logout", "/auth/magic", "/static")

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        root = APP_PREFIX
        relative = path[len(root):] if path.startswith(root) else path
        if not relative:
            relative = "/"

        # Oeffentliche Pfade (inkl. Static)
        if any(relative == p or relative.startswith(p) for p in self.PUBLIC_PATHS):
            return await call_next(request)

        # Session pruefen
        user = request.session.get("user")
        if not user:
            request.session["next"] = path if path.startswith(root) else f"{root}{path}"
            return RedirectResponse(url=f"{root}/auth/login", status_code=302)

        request.state.crm_user = user
        return await call_next(request)


# ─── Middleware registrieren (LIFO) ───────────────────────────────────────────
app.add_middleware(AuthGuardMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie="cbh_session",
    max_age=SESSION_MAX_AGE,
    same_site="lax",
    https_only=True,
    domain="hook.srv960331.hstgr.cloud",
)

# ─── Router einbinden ─────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(crm_router)
app.include_router(pipeline_router)
app.include_router(projects_router)
app.include_router(drive_auth_router)


# ─── Health-Check (oeffentlich) ───────────────────────────────────────────────
@app.get("/health")
async def health():
    return JSONResponse({
        "status": "ok",
        "env": CRM_ENV,
        "auth": "sso",
        "modules": ["crm", "pipeline", "projects"]
    })


# ─── Home-Dashboard (Sprint 3 Wave 2: CRM-046) ────────────────────────────────
@app.get("/")
async def home_dashboard(request: Request):
    """
    Home-Dashboard: 5 Tool-Kacheln mit KPI-Platzhaltern.
    KPI-Werte werden via HTMX nachgeladen (GET /api/kpis/summary).
    """
    return render(request, "home.html")


# ─── Settings-Route (Stub, Sprint 3 Wave 2: CRM-045) ─────────────────────────
@app.get("/settings")
async def settings(request: Request):
    return render(request, "settings.html")


# ─── KPI-Summary-Endpoint (Sprint 3 Wave 2: CRM-046) ─────────────────────────
from app.shared.kpis import get_kpi_summary as _get_kpi_summary
from app.shared.templating import templates as _templates

@app.get("/api/kpis/summary")
async def kpis_summary(request: Request):
    """
    GET /api/kpis/summary – Aggregierte KPIs fuer Home-Dashboard.
    In-Memory TTL-Cache 60s. Stale-Fallback bei Fehler.
    Kann als JSON oder als HTMX-Partial gerendert werden.
    """
    kpi_data = _get_kpi_summary()

    # HTMX-Request: HTML-Partial zurueckgeben
    accept = request.headers.get("accept", "")
    hx_request = request.headers.get("hx-request", "")

    if hx_request:
        from fastapi.responses import HTMLResponse
        from app.shared.templating import render
        return render(request, "_kpi_summary.html", kpi_data=kpi_data)

    return JSONResponse(kpi_data)
