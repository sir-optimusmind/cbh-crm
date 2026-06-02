"""shared/cvr.py – Conversion-Rate-Matrix aus deal_stage_history.
CRM-056 | Sprint 3 Wave 3b | 20.05.2026
Niko-Pattern N2 (Sektion 6.3): TTL-Cache 300s.

BUG-B Fix (Sprint 5, 02.06.2026): Wechsel von "Direkter Uebergang" (A1)
zu "Cohort-Nenner" (A2, Niko-Empfehlung).
Vorher: CVR(A→B) = count(A→B) / count(A→*)  → Stages ohne Lost kollabieren auf 100%
Jetzt:  CVR(A→B) = count(deals die je in B waren, von denen die je in A waren)
                 / count(deals die je in A waren)
        Verbleiber (noch in A) und Lost-Deals zaehlen im Nenner mit.
"""
import time
import threading

from app.db import get_connection

STAGES_ORDER = ["opportunity", "new", "discovery", "proposal_sent", "won", "lost"]
MIN_DATAPOINTS = 3     # < 3 Deals in Stage X => kein valider Wert (NULL, nicht 0%)
_TTL_SEC = 300
_LOCK = threading.Lock()
_CACHE = {"ts": 0.0, "data": None}

# Schwellenwert: CVR >= CVR_HIGH_PCT_THRESHOLD bekommt low_data_flag=True
# wenn keine Lost-Uebergaenge aus dieser Stage existieren (transparente Warnung)
CVR_HIGH_PCT_THRESHOLD = 95.0


def get_cvr_matrix() -> dict:
    """Returns {(from_stage, to_stage): {
        "count": int,           # Deals die je in to_stage waren (Zaehler)
        "total_in": int,        # Deals die je in from_stage waren (Nenner)
        "rate_pct": float|None, # None wenn zu wenig Daten
        "low_data_flag": bool,  # True wenn Rate >= 95% und keine Lost-Datenpunkte aus Stage
    }}."""
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
    """Cohort-Nenner-Query (A2).

    Fuer jedes Stage-Paar (X, Y):
      - Nenner = DISTINCT deal_ids die jemals to_stage=X hatten
                 (d.h. jemals Stage X betreten haben, inkl. Verbleiber)
      - Zaehler = davon: deal_ids die AUCH jemals to_stage=Y hatten
                  (d.h. von X weiter nach Y kamen)

    Stages ohne jegliche to_stage=X-History: Nenner=0, Rate=None (nicht 0%).
    """
    conn = get_connection()
    try:
        # Alle relevanten Stage-Paare aus STAGES_ORDER (jeweils X -> naechste Stage)
        # Wir fragen nur die bekannten Uebergaenge ab, keine Kreuz-Produkt-Explosion
        active_pairs = []
        active_stages_for_cvr = ["opportunity", "new", "discovery", "proposal_sent"]
        for i, stage in enumerate(active_stages_for_cvr):
            next_s = active_stages_for_cvr[i + 1] if i + 1 < len(active_stages_for_cvr) else "won"
            active_pairs.append((stage, next_s))

        # Zaehlt pro Stage: wie viele DISTINCT deals hatten to_stage=X (Nenner)
        # und davon wie viele hatten auch to_stage=Y (Zaehler)
        # Erledigt mit einem JOIN per Paar (sauber, kein Subquery-Hell)
        out: dict = {}

        # Zusaetzlich: welche Stages haben KEINE Lost-Uebergaenge?
        # Fuer low_data_flag-Berechnung
        stages_with_lost = set()
        lost_rows = conn.execute("""
            SELECT DISTINCT from_stage
            FROM deal_stage_history
            WHERE to_stage = 'lost' AND from_stage IS NOT NULL
        """).fetchall()
        for r in lost_rows:
            stages_with_lost.add(r["from_stage"])

        for (from_s, to_s) in active_pairs:
            # Nenner: Distinct deals die je in from_s waren
            nenner_row = conn.execute("""
                SELECT COUNT(DISTINCT deal_id) AS n
                FROM deal_stage_history
                WHERE to_stage = ?
            """, (from_s,)).fetchone()
            total_in = nenner_row["n"] if nenner_row else 0

            if total_in < MIN_DATAPOINTS:
                # Zu wenig Datenpunkte => NULL, nicht 0%
                out[(from_s, to_s)] = {
                    "count": 0,
                    "total_in": total_in,
                    "rate_pct": None,
                    "low_data_flag": False,
                }
                continue

            # Zaehler: davon, die auch to_stage=to_s hatten
            # Schnittpunkt: deals in FROM und in TO
            zaehler_row = conn.execute("""
                SELECT COUNT(DISTINCT a.deal_id) AS n
                FROM deal_stage_history a
                JOIN deal_stage_history b ON a.deal_id = b.deal_id
                WHERE a.to_stage = ?
                  AND b.to_stage = ?
            """, (from_s, to_s)).fetchone()
            count = zaehler_row["n"] if zaehler_row else 0

            rate = round(100.0 * count / total_in, 1)

            # low_data_flag: Rate hoch UND keine Lost-Bewegungen aus dieser Stage
            low_data_flag = (
                rate >= CVR_HIGH_PCT_THRESHOLD
                and from_s not in stages_with_lost
            )

            out[(from_s, to_s)] = {
                "count": count,
                "total_in": total_in,
                "rate_pct": rate,
                "low_data_flag": low_data_flag,
            }

    finally:
        conn.close()

    return out


def cvr_pct(from_stage: str, to_stage: str) -> float | None:
    """Convenience fuer Templates: gibt None zurueck wenn zu wenig Daten."""
    m = get_cvr_matrix()
    entry = m.get((from_stage, to_stage))
    return entry["rate_pct"] if entry else None


def cvr_entry(from_stage: str, to_stage: str) -> dict:
    """Vollstaendigen Matrix-Eintrag zurueckgeben (inkl. low_data_flag).
    Gibt leeren Dict zurueck wenn Stage-Paar nicht in Matrix.
    """
    m = get_cvr_matrix()
    return m.get((from_stage, to_stage), {})


def get_cvr_label_class(rate: float | None) -> str:
    """CSS-Klasse fuer CVR-Connector (Sarah S3 Spec)."""
    if rate is None:
        return "funnel-cvr--empty"
    if rate > 40:
        return "funnel-cvr--good"
    if rate >= 20:
        return "funnel-cvr--medium"
    return "funnel-cvr--low"
