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
    NAV_ITEMS, _resolve_active, _build_breadcrumb, _get_current_user, APP_PREFIX
)


def tmpl_ctx(request: Request, ctx: dict) -> dict:
    """
    Ergaenzt Template-Context um:
    - current_user (aus Session)
    - prefix (APP_PREFIX via root_path)
    - nav_items, active_key, breadcrumb (fuer Shell-Komponenten)

    Alle TemplateResponse-Aufrufe nutzen diesen Wrapper.
    """
    path = request.url.path
    active_key = _resolve_active(path)
    extra_label = ctx.pop("extra_breadcrumb_label", None)
    breadcrumb = _build_breadcrumb(path, active_key, extra_label)
    current_user = _get_current_user(request)
    prefix = request.scope.get("root_path", APP_PREFIX)

    merged = {
        "prefix":      prefix,
        "nav_items":   NAV_ITEMS,
        "active_key":  active_key,
        "breadcrumb":  breadcrumb,
        "current_user": current_user,
    }
    merged.update(ctx)
    return merged
