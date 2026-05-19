"""
shared/templating.py – Zentraler Template-Render-Helper
Sprint 3 Wave 2: CRM-050 Active-Route-Sync

Jeder Router nutzt render(request, template, **ctx) statt direkt
templates.TemplateResponse(). Damit ist Active-State strukturell garantiert.

Niko-Pattern: Longest-Prefix-Match fuer active_key.
Jan-Pattern: Breadcrumb-Mapping per active_key + optionaler extra_breadcrumb_label.
"""

import os
from datetime import datetime, timezone
from fastapi import Request
from fastapi.templating import Jinja2Templates

# Template-Verzeichnis: app/templates/
_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")
templates = Jinja2Templates(directory=_TEMPLATE_DIR)

# APP_PREFIX aus .env (nie hardcoden)
APP_PREFIX = os.getenv("APP_PREFIX", "/mission-ctrl/crm-staging").rstrip("/")
COLDCALL_STAGING_PREFIX = os.getenv("COLDCALL_STAGING_PREFIX", "/coldcall-staging")

# ─── NAV_ITEMS ────────────────────────────────────────────────────────────────
# Reihenfolge = Sidebar-Reihenfolge
# key: eindeutiger Bezeichner fuer Active-State
# path: absolute URL fuer Navigation
NAV_ITEMS = [
    {"key": "home",     "label": "Uebersicht",   "path": f"{APP_PREFIX}/",           "icon": "home"},
    {"key": "coldcall", "label": "Cold Calling",  "path": f"{COLDCALL_STAGING_PREFIX}/", "icon": "phone"},
    {"key": "crm",      "label": "CRM",           "path": f"{APP_PREFIX}/personen",   "icon": "users"},
    {"key": "pipeline", "label": "Pipeline",      "path": f"{APP_PREFIX}/pipeline",   "icon": "trending-up"},
    {"key": "projekte", "label": "Projekte",      "path": f"{APP_PREFIX}/projects",   "icon": "folder"},
]

# ─── Breadcrumb-Map ────────────────────────────────────────────────────────────
_BREADCRUMB_MAP = {
    "home":     [{"label": "Home", "path": f"{APP_PREFIX}/"}],
    "coldcall": [{"label": "Home", "path": f"{APP_PREFIX}/"},
                 {"label": "Cold Calling", "path": f"{COLDCALL_STAGING_PREFIX}/"}],
    "crm":      [{"label": "Home", "path": f"{APP_PREFIX}/"},
                 {"label": "CRM",  "path": f"{APP_PREFIX}/personen"}],
    "pipeline": [{"label": "Home", "path": f"{APP_PREFIX}/"},
                 {"label": "Deal Pipeline", "path": f"{APP_PREFIX}/pipeline"}],
    "projekte": [{"label": "Home", "path": f"{APP_PREFIX}/"},
                 {"label": "Projekte", "path": f"{APP_PREFIX}/projects"}],
    "settings": [{"label": "Home", "path": f"{APP_PREFIX}/"},
                 {"label": "Einstellungen", "path": f"{APP_PREFIX}/settings"}],
}


def _resolve_active(path: str) -> str:
    """Longest-Prefix-Match: /crm-staging/personen/123 → 'crm'"""
    # K-BUG-001: Extra-Prefixes fuer Routes die nicht unter dem NAV_ITEMS-Pfad liegen
    EXTRA_PREFIXES = {
        "pipeline": ["/deals"],
        "crm":      ["/unternehmen", "/touchpoints"],
    }
    best = "home"
    best_len = 0
    for item in NAV_ITEMS:
        if path.startswith(item["path"]) and len(item["path"]) > best_len:
            best, best_len = item["key"], len(item["path"])
    # Extra-Prefix-Check: laengster Match gewinnt
    for nav_key, prefixes in EXTRA_PREFIXES.items():
        for prefix in prefixes:
            full_prefix = f"{APP_PREFIX}{prefix}"
            if path.startswith(full_prefix) and len(full_prefix) > best_len:
                best, best_len = nav_key, len(full_prefix)
    # Fallback fuer Settings-Route
    if path.endswith("/settings") or "/settings" in path:
        return "settings"
    return best


def _build_breadcrumb(path: str, active_key: str, extra_label: str = None) -> list:
    """
    Gibt Liste von {label, path, active} zurueck.
    Letzter Eintrag: active=True (kein Link im Template).
    Bei 4+ Ebenen: Mittlere durch '...' ersetzen.
    extra_label: Name einer Detail-Entitaet (z.B. 'Klaus Hartmann').
    """
    base = _BREADCRUMB_MAP.get(active_key, [{"label": "Home", "path": f"{APP_PREFIX}/"}])
    crumbs = [dict(c) for c in base]

    if extra_label:
        crumbs.append({"label": extra_label, "path": None})

    # Truncation bei > 3 Ebenen (Jan-Regel)
    if len(crumbs) > 3:
        crumbs = [crumbs[0], {"label": "...", "path": None}] + crumbs[-2:]

    # Active-Markierung
    for i, c in enumerate(crumbs):
        c["active"] = (i == len(crumbs) - 1)

    return crumbs


def _get_current_user(request: Request) -> dict:
    """User aus Session mit Initialen + Avatar-Farbe berechnen."""
    user = request.session.get("user") if hasattr(request, "session") else None
    if not user:
        return {"name": "Unbekannt", "email": "", "initials": "?", "color_idx": 0}

    name = user.get("name", user.get("email", "?"))
    parts = name.split()
    if len(parts) >= 2:
        initials = parts[0][0].upper() + parts[-1][0].upper()
    elif parts:
        initials = parts[0][:2].upper()
    else:
        initials = "?"

    # user_id fuer Avatar-Farb-Rotation (user.id % 6)
    email = user.get("email", "")
    color_idx = sum(ord(c) for c in email) % 6

    return {
        "name": name,
        "email": email,
        "initials": initials,
        "color_idx": color_idx,
        "id": color_idx,  # fuer Template: current_user.id | int % 6
        "display_name": name,
    }


def render(request: Request, template: str, **ctx):
    """
    Zentraler Render-Helper.
    Injiziert: nav_items, active_key, breadcrumb, current_user, prefix, now_hour.
    Optionaler ctx-Key: extra_breadcrumb_label.
    """
    path = request.url.path
    active_key = _resolve_active(path)
    extra_label = ctx.pop("extra_breadcrumb_label", None)
    breadcrumb = _build_breadcrumb(path, active_key, extra_label)
    current_user = _get_current_user(request)
    now_hour = datetime.now(timezone.utc).hour

    return templates.TemplateResponse(request, template, {
        "request":      request,
        "prefix":       request.scope.get("root_path", APP_PREFIX),
        "nav_items":    NAV_ITEMS,
        "active_key":   active_key,
        "breadcrumb":   breadcrumb,
        "current_user": current_user,
        "now_hour":     now_hour,
        **ctx,
    })
