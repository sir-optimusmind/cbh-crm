"""
shared/kpis.py – KPI-Aggregation fuer Home-Dashboard
Sprint 3 Wave 2: CRM-046

Pattern (Niko-Spec):
- In-Memory TTL-Cache 60s
- 4 Fetcher (1x HTTP fuer ColdCall, 3x lokale SQL)
- 500ms Timeout pro Fetcher
- Stale-Fallback bei Fehler
- Niemals 500 zurueckgeben
"""

import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

import httpx
import sqlite3

DB_PATH          = os.getenv("CRM_DB_PATH", "/home/cbh/crm/data/crm.db")
COLDCALL_PORT    = int(os.getenv("COLDCALL_PORT", "8504"))
INTERNAL_TOKEN   = os.getenv("INTERNAL_TOKEN", "")

_TTL   = 60
_LOCK  = threading.Lock()
_CACHE = {"ts": 0, "data": None}
_LAST_GOOD: dict = {}   # tool_key → dict (Stale-Fallback)


def get_kpi_summary() -> dict:
    """Gibt KPI-Zusammenfassung aus Cache oder frisch aggregiert zurueck."""
    now = time.time()
    with _LOCK:
        if _CACHE["data"] and (now - _CACHE["ts"]) < _TTL:
            return _CACHE["data"]

    data = _build_summary()

    with _LOCK:
        _CACHE["ts"] = now
        _CACHE["data"] = data

    return data


def _build_summary() -> dict:
    fetchers = {
        "coldcall": _fetch_coldcall_kpis,
        "crm":      _fetch_crm_kpis,
        "pipeline": _fetch_pipeline_kpis,
        "projects": _fetch_projects_kpis,
    }
    out: dict = {}

    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {name: ex.submit(fn) for name, fn in fetchers.items()}
        for name, fut in futures.items():
            try:
                result = fut.result(timeout=0.5)
                out[name] = {**result, "stale": False}
                _LAST_GOOD[name] = out[name]
            except (FutureTimeoutError, Exception):
                fallback = _LAST_GOOD.get(name, {})
                out[name] = {**fallback, "stale": True}

    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ttl_seconds": _TTL,
        "tools": out,
    }


def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def _fetch_coldcall_kpis() -> dict:
    """HTTP-Call an ColdCall /internal/kpis (127.0.0.1)."""
    if not INTERNAL_TOKEN:
        return {"calls_today": 0, "appointments_today": 0}
    r = httpx.get(
        f"http://127.0.0.1:{COLDCALL_PORT}/internal/kpis",
        headers={"X-Internal-Token": INTERNAL_TOKEN},
        timeout=0.5,
    )
    r.raise_for_status()
    return r.json()


def _fetch_crm_kpis() -> dict:
    """Lokale SQL: Personen + Hot Contacts."""
    conn = _get_db()
    try:
        persons_total = conn.execute(
            "SELECT COUNT(*) as cnt FROM person WHERE deleted_at IS NULL"
        ).fetchone()["cnt"]

        hot_contacts = conn.execute(
            "SELECT COUNT(*) as cnt FROM person WHERE stimmung = 'heiss' AND deleted_at IS NULL"
        ).fetchone()["cnt"]

        return {
            "persons_total": persons_total,
            "hot_contacts":  hot_contacts,
        }
    finally:
        conn.close()


def _fetch_pipeline_kpis() -> dict:
    """Lokale SQL: Offene Deals + Pipeline-Volumen (acv)."""
    conn = _get_db()
    try:
        open_deals = conn.execute(
            "SELECT COUNT(*) as cnt FROM deal WHERE stage NOT IN ('Won','Lost') AND deleted_at IS NULL"
        ).fetchone()["cnt"]

        vol_row = conn.execute(
            "SELECT COALESCE(SUM(acv), 0) as vol FROM deal WHERE stage NOT IN ('Won','Lost') AND deleted_at IS NULL"
        ).fetchone()
        pipeline_volume_eur = int(vol_row["vol"]) if vol_row["vol"] else 0

        return {
            "open_deals":          open_deals,
            "pipeline_volume_eur": pipeline_volume_eur,
        }
    finally:
        conn.close()


def _fetch_projects_kpis() -> dict:
    """Lokale SQL: Aktive Projekte + Rechnungsgrad-Average."""
    conn = _get_db()
    try:
        active = conn.execute(
            "SELECT COUNT(*) as cnt FROM project WHERE status = 'active' AND deleted_at IS NULL"
        ).fetchone()["cnt"]

        # avg_invoice_pct: ist_rechnungen / contract_value * 100 (nur wenn contract_value > 0)
        rows = conn.execute(
            "SELECT contract_value, ist_rechnungen FROM project WHERE deleted_at IS NULL AND contract_value > 0"
        ).fetchall()

        if rows:
            pcts = []
            for row in rows:
                cv = row["contract_value"] or 0
                ir = row["ist_rechnungen"] or 0
                if cv > 0:
                    pcts.append((ir / cv) * 100)
            avg_invoice_pct = round(sum(pcts) / len(pcts), 1) if pcts else 0.0
        else:
            avg_invoice_pct = 0.0

        return {
            "active":          active,
            "avg_invoice_pct": avg_invoice_pct,
        }
    finally:
        conn.close()
