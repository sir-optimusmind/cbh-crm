"""
shared/stage_history.py – Helper-Funktion fuer deal_stage_history-Eintrag.
Niko-Pattern (Sektion 6.2): in dieselbe Transaktion wie Stage-UPDATE eingebettet.
Wiederverwendbar in CRM-055 (Stage-Patch), CRM-059 (Won<->Lost), CRM-060 (Won-Modal).
"""
import sqlite3


def log_stage_history(
    conn: sqlite3.Connection,
    deal_id: int,
    from_stage: str | None,
    to_stage: str,
    moved_by: str,
    moved_at: str,
) -> None:
    """
    Schreibt einen Eintrag in deal_stage_history.
    MUSS innerhalb einer laufenden Transaktion aufgerufen werden (BEGIN IMMEDIATE).
    Wirft bei Fehler eine Exception -> Aufrufer rollt zurueck.
    """
    conn.execute(
        "INSERT INTO deal_stage_history (deal_id, from_stage, to_stage, moved_at, moved_by) "
        "VALUES (?, ?, ?, ?, ?)",
        (deal_id, from_stage, to_stage, moved_at, moved_by),
    )
