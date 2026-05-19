"""
landing/app/main.py – CRM-017: CBH Mission CTRL Landing Page

Minimaler FastAPI-Service auf Port 8508.
APP_PREFIX via .env (z.B. /mission-ctrl).
Basic-Auth wird upstream bei Caddy gehandelt.
"""

import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

# Root-Path kommt aus .env (nie hardcoden!)
APP_PREFIX = os.environ.get("LANDING_APP_PREFIX", "/mission-ctrl")

COLDCALL_URL = os.environ.get("COLDCALL_URL", "https://hook.srv960331.hstgr.cloud/coldcall-next/")
CRM_URL = os.environ.get("CRM_URL", "https://hook.srv960331.hstgr.cloud/mission-ctrl/crm-staging/")

app = FastAPI(root_path=APP_PREFIX, title="CBH Mission CTRL Landing")

# Statisches HTML – als String mit URL-Injection, kein Template-System nötig
_LANDING_HTML_PATH = os.path.join(os.path.dirname(__file__), "landing.html")

def _render_landing() -> str:
    with open(_LANDING_HTML_PATH, encoding="utf-8") as f:
        html = f.read()
    html = html.replace("COLDCALL_URL", COLDCALL_URL)
    html = html.replace("CRM_URL", CRM_URL)
    return html


@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    return HTMLResponse(content=_render_landing())


@app.get("/health")
async def health():
    return JSONResponse({"status": "ok", "service": "mission-ctrl-landing"})
