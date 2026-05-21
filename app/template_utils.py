"""
template_utils.py – Gemeinsame Template-Context-Helpers
Sprint 1: current_user aus Session
Sprint 3 Wave 2: nav_items, active_key, breadcrumb, prefix injizieren

Nutzung (unveraendert):
    from app.template_utils import tmpl_ctx
    return templates.TemplateResponse(request, "foo.html", tmpl_ctx(request, {"key": "val"}))
"""

from fastapi import Request
from app.shared.templating import (
    NAV_ITEMS, _resolve_active, _build_breadcrumb, _get_current_user,
    APP_PREFIX, get_all_users, get_presence_dict
)
from app.db import get_connection


def tmpl_ctx(request: Request, ctx: dict) -> dict:
    """
    Ergaenzt Template-Context um:
    - current_user (aus Session)
    - prefix (APP_PREFIX via root_path)
    - nav_items, active_key, breadcrumb (fuer Shell-Komponenten)
    - all_users, presence (fuer Sidebar Team-Block)
    - crm_tab (fuer CRM Sub-Nav aktiver Tab)

    Alle TemplateResponse-Aufrufe nutzen diesen Wrapper.
    """
    path = request.url.path
    active_key = _resolve_active(path)
    extra_label = ctx.pop("extra_breadcrumb_label", None)
    breadcrumb = _build_breadcrumb(path, active_key, extra_label)
    current_user = _get_current_user(request)
    prefix = request.scope.get("root_path", APP_PREFIX)

    # crm_tab
    if f"{APP_PREFIX}/unternehmen" in path:
        crm_tab = "unternehmen"
    elif f"{APP_PREFIX}/personen" in path or f"{APP_PREFIX}/touchpoints" in path:
        crm_tab = "personen"
    else:
        crm_tab = "personen"

    # Presence + User-Liste
    all_users: list[dict] = []
    presence: dict[str, str] = {}
    try:
        conn = get_connection()
        try:
            presence = get_presence_dict(conn)
            all_users = get_all_users(conn, current_user.get("email", ""), prefix)
        finally:
            conn.close()
    except Exception:
        pass

    merged = {
        "prefix":       prefix,
        "nav_items":    NAV_ITEMS,
        "active_key":   active_key,
        "crm_tab":      crm_tab,
        "breadcrumb":   breadcrumb,
        "current_user": current_user,
        "all_users":    all_users,
        "presence":     presence,
    }
    merged.update(ctx)
    return merged
