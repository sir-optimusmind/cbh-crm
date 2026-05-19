"""
template_utils.py – Gemeinsame Template-Context-Helpers

Injiziert current_user aus Session in alle Template-Responses.
Nutzung:
    from app.template_utils import tmpl_ctx
    return templates.TemplateResponse(request, "foo.html", tmpl_ctx(request, {"key": "val"}))
"""

from fastapi import Request


def tmpl_ctx(request: Request, ctx: dict) -> dict:
    """
    Ergaenzt Template-Context um current_user aus Session.
    Alle TemplateResponse-Aufrufe sollen diesen Wrapper nutzen.
    """
    user = request.session.get("user") if hasattr(request, "session") else None
    merged = {"current_user": user}
    merged.update(ctx)
    return merged
