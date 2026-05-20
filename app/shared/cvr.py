"""shared/cvr.py – Conversion-Rate-Matrix aus deal_stage_history.
CRM-056 | Sprint 3 Wave 3b | 20.05.2026
Niko-Pattern N2 (Sektion 6.3): TTL-Cache 300s, direkter Uebergang.
"""
import time
import threading

from app.db import get_connection

STAGES_ORDER = ["opportunity", "new", "discovery", "proposal_sent", "won", "lost"]
MIN_DATAPOINTS = 5     # < 5 from-Bewegungen => kein valider Wert
_TTL_SEC = 300
_LOCK = threading.Lock()
_CACHE = {"ts": 0.0, "data": None}


def get_cvr_matrix() -> dict:
    """Returns {(from_stage, to_stage): {"count": int, "rate_pct": float | None}}."""
    now = time.time()
    with _LOCK:
        if _CACHE["data"] and (now - _CACHE["ts"]) < _TTL_SEC:
            return _CACHE["data"]

    data = _compute_matrix()
    with _LOCK:
        _CACHE["ts"] = now
        _CACHE["data"] = data
    return data


def invalidate_cvr_cache() -> None:
    """Optional – nach Stage-Wechsel aufrufen fuer Soft-Invalidation."""
    with _LOCK:
        _CACHE["ts"] = 0.0


def _compute_matrix() -> dict:
    """Eine einzige Aggregations-Query, direkter Uebergang (Niko N2)."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT from_stage, to_stage, COUNT(*) AS n
            FROM deal_stage_history
            WHERE from_stage IS NOT NULL
            GROUP BY from_stage, to_stage
        """).fetchall()
    finally:
        conn.close()

    by_from: dict = {}
    by_pair: dict = {}
    for r in rows:
        f, t, n = r["from_stage"], r["to_stage"], r["n"]
        by_from[f] = by_from.get(f, 0) + n
        by_pair[(f, t)] = n

    out: dict = {}
    for (f, t), n in by_pair.items():
        total = by_from[f]
        rate = round(100.0 * n / total, 1) if total >= MIN_DATAPOINTS else None
        out[(f, t)] = {"count": n, "total_from": total, "rate_pct": rate}
    return out


def cvr_pct(from_stage: str, to_stage: str) -> float | None:
    """Convenience fuer Templates: gibt None zurueck wenn zu wenig Daten."""
    m = get_cvr_matrix()
    entry = m.get((from_stage, to_stage))
    return entry["rate_pct"] if entry else None


def get_cvr_label_class(rate: float | None) -> str:
    """CSS-Klasse fuer CVR-Connector (Sarah S3 Spec)."""
    if rate is None:
        return "funnel-cvr--empty"
    if rate > 40:
        return "funnel-cvr--good"
    if rate >= 20:
        return "funnel-cvr--medium"
    return "funnel-cvr--low"
