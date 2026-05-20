#!/usr/bin/env python3
"""
scripts/seed_mega.py – MEGA-Seed fuer CBH CRM Pipeline (Aufgabe 6, 2026-05-20)

Erzeugt:
  - 80 Deals quer durch 6 Stages mit realistischen CBH-Daten
  - deal_product Eintraege (1-3 Produkte pro Deal)
  - 1-5 Touchpoints pro Deal
  - deal_stage_history BACKFILL mit realistischen Conversion-Raten
  - History fuer bestehende 14 Deals (Bonus)

Stage-Verteilung:
  opportunity: 20, new: 15, discovery: 12, proposal_sent: 8, won: 15, lost: 10 = 80

Realistische CVR-Ziele:
  opportunity -> new: ~22%  (braucht: bei 20 opp min 4-5 die zu new uebergingen)
  new -> discovery: ~53%
  discovery -> proposal_sent: ~70%
  proposal_sent -> won: ~65%

Nutzung:
  cd /home/cbh/crm && .venv/bin/python3 scripts/seed_mega.py
"""

import sys
import os
import sqlite3
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Direkte DB-Verbindung (kein App-Import noetig)
DB_PATH = os.environ.get("CRM_DB_PATH", str(Path(__file__).parent.parent / "data" / "crm.db"))

random.seed(42)  # Reproduzierbarer Seed

# ─── Hilfsfunktionen ──────────────────────────────────────────────────────────

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

def days_ago(n: int, jitter_hours: int = 0) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=n, hours=random.randint(0, jitter_hours))
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

def days_from_now(n: int) -> str:
    dt = datetime.now(timezone.utc) + timedelta(days=n)
    return dt.strftime("%Y-%m-%d")

def date_ago(n: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=n)
    return dt.strftime("%Y-%m-%d")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ─── Daten-Pools ──────────────────────────────────────────────────────────────

OWNERS = ["christian", "andre", "michi", "marco", "tim"]
BACKUP_OWNERS = {
    "christian": ["andre", "michi"],
    "andre": ["christian", "marco"],
    "michi": ["christian", "tim"],
    "marco": ["andre", "tim"],
    "tim": ["michi", "marco"],
}

PRODUCTS = ["race", "blindspot", "okr_training", "pm_training", "innovation_cell",
            "visionsworkshop", "empower_os", "tm"]

VERLUST_REASONS = [
    "Budget zu klein", "Konkurrenz gewonnen", "Kein Fit",
    "Timing schlecht", "Intern entschieden", "Kein Entscheider erreicht", "Andere"
]

LEAD_SOURCES = ["linkedin", "telefon", "referral", "networking", "email", "lemlist"]
ICP_PERSONAS = ["forward_thinking_owner", "transformation_leader", "speed_optimizer", "rebels"]

# Realistische Deal-Titel nach Produkt / Branche
DEAL_TITLES = [
    # RACE / OKR / PM
    ("Innovation Cell – Maschinenbau Mittelstand", ["innovation_cell"], 45000),
    ("RACE Workshop – Energie-Sektor", ["race"], 18000),
    ("RACE Deep-Dive – Automotive Tier-1", ["race", "tm"], 32000),
    ("OKR-Einfuehrung – Pharma Scale-up", ["okr_training"], 12000),
    ("OKR Mastery Programm – Logistik", ["okr_training", "pm_training"], 22000),
    ("PM-Training – Bauwesen", ["pm_training"], 8500),
    ("PM Excellence – Software GmbH", ["pm_training", "tm"], 15000),
    # Empower OS
    ("Empower OS Implementierung – Pharma", ["empower_os"], 95000),
    ("Empower OS Implementierung – Automotive", ["empower_os", "race"], 120000),
    ("Empower OS Pilotprojekt – Mittelstand", ["empower_os"], 65000),
    ("Empower OS – Konsumgueter", ["empower_os", "blindspot"], 88000),
    # Blindspot
    ("Blindspot-Analyse – Hidden Champions", ["blindspot"], 25000),
    ("Blindspot + OKR Kombination – Industrieausruestung", ["blindspot", "okr_training"], 35000),
    ("Blindspot Workshop – Digital Native GmbH", ["blindspot"], 18000),
    # Innovation Cell
    ("Innovation Cell Aufbau – Chemieunternehmen", ["innovation_cell", "race"], 55000),
    ("Innovation Lab – Familienunternehmen Bayern", ["innovation_cell"], 42000),
    ("Innovation Cell – Gesundheitswesen", ["innovation_cell", "tm"], 48000),
    # Vision / Strategy
    ("Visions-Workshop Geschaeftsfuehrung", ["visionsworkshop"], 28000),
    ("Strategieklausur + Visions-Workshop", ["visionsworkshop", "race"], 38000),
    ("Visions-Workshop – Wachstumsfirma", ["visionsworkshop"], 22000),
    # T&M
    ("T&M Begleitung Transformationsprogramm", ["tm"], 180000),
    ("T&M Interim Management – Restrukturierung", ["tm"], 240000),
    ("T&M Beratung Digital Transformation", ["tm", "empower_os"], 320000),
    # Mixed
    ("Organisations-Diagnose – Verlags GmbH", ["blindspot", "race"], 29000),
    ("Leadership-Programm – Familienholding", ["race", "pm_training"], 52000),
    ("Strategie + Execution Begleitung", ["race", "okr_training", "tm"], 75000),
    ("Changemanagement-Begleitung – Post-Merger", ["race", "innovation_cell"], 95000),
    ("Fuehrungskraefte-Coaching – Mittelstand", ["tm", "pm_training"], 35000),
    ("Wachstumsstrategie + Empower OS", ["empower_os", "visionsworkshop"], 145000),
    ("KI-Transformations-Roadmap", ["innovation_cell", "tm"], 68000),
]

BRANCHE_UNTERNEHMEN = [
    ("Roche GmbH", "Other"),
    ("Bosch Engineering GmbH", "Automotive"),
    ("Siemens Energy AG", "Energiewirtschaft"),
    ("Trumpf Werkzeugmaschinen GmbH", "Maschinenbau"),
    ("Krones AG", "Maschinenbau"),
    ("Schaeffler Gruppe", "Automotive"),
    ("Fresenius Medical Care", "Other"),
    ("BASF SE", "Fertigende-Industrie"),
    ("MTU Aero Engines AG", "Fertigende-Industrie"),
    ("Rational AG", "Fertigende-Industrie"),
    ("Rohde & Schwarz GmbH", "IT-Digital"),
    ("MAN Truck & Bus SE", "Automotive"),
    ("Linde plc", "Fertigende-Industrie"),
    ("Wacker Chemie AG", "Fertigende-Industrie"),
    ("Kaeser Kompressoren SE", "Maschinenbau"),
    ("Ziehl-Abegg SE", "Fertigende-Industrie"),
    ("Festo SE & Co. KG", "Maschinenbau"),
    ("Steelcase Deutschland GmbH", "Other"),
    ("Voith GmbH & Co. KGaA", "Fertigende-Industrie"),
    ("Knorr-Bremse AG", "Automotive"),
    ("Hubert Burda Media GmbH", "IT-Digital"),
    ("ProSiebenSat.1 Media SE", "IT-Digital"),
    ("Versicherungskammer Bayern", "Other"),
    ("Allianz Partners", "Other"),
    ("Scout24 AG", "IT-Digital"),
    ("Wiesmann GmbH", "Automotive"),
    ("Weber-Ingenieure GmbH", "Maschinenbau"),
    ("Flottweg SE", "Maschinenbau"),
    ("Grenzebach Group", "Fertigende-Industrie"),
    ("easyCredit – TeamBank AG", "Other"),
]

TOUCHPOINT_NOTES = [
    "Erstgespraech durchgefuehrt. Interesse an Empower OS vorhanden. Follow-up vereinbart.",
    "Discovery-Call. Budget-Rahmen geklaert. Entscheidung haengt an CFO-Freigabe.",
    "Proposal versandt. Rueckmeldung in 2 Wochen erwartet.",
    "Follow-up nach 3 Wochen Stille. Ansprechpartner im Urlaub. Termin fuer September.",
    "Workshop-Vorgespraech. Fuehrungsebene sehr aufgeschlossen. Timing passt.",
    "Demo der Empower OS Plattform. Sehr positiv aufgenommen. Konkrete Anforderungen notiert.",
    "Telefonat: Budgetfreigabe ausstehend. Q4 wahrscheinlicher als Q3.",
    "LinkedIn-Nachricht beantwortet. Call vereinbart fuer naechste Woche.",
    "Referenzgespraech mit Bestandskunde vermittelt. Reaktion sehr positiv.",
    "Abschlussdiskussion. Verhandlung laeuft. Konditionen fast final.",
    "Kick-off-Meeting nach Vertragsunterzeichnung. Team begeistert.",
    "Cold-Call: Interessiert, aber kein Timing jetzt. In 6 Monaten Kontakt aufnehmen.",
    "Praesentiert auf Fuehrungsrunde. Fragen zur DSGVO und Datensouveraenitaet.",
    "Nachfass-Mail: keine Reaktion. Zweiter Versuch in 2 Wochen.",
    "Strategiemeeting: Scope fuer Pilotprojekt festgelegt. LOI in Vorbereitung.",
]


# ─── Stage-History Logik ─────────────────────────────────────────────────────

STAGE_SEQUENCE = ["opportunity", "new", "discovery", "proposal_sent", "won"]

# Wie viele Tage verbringt ein Deal typischerweise in einer Stage
STAGE_DWELL_DAYS = {
    "opportunity": (14, 45),
    "new": (7, 21),
    "discovery": (14, 35),
    "proposal_sent": (7, 28),
    "won": (0, 0),
    "lost": (0, 0),
}

def build_stage_history(deal_id: int, final_stage: str, base_days_ago: int, owner: str) -> list[dict]:
    """
    Baut eine realistische Stage-Wechsel-Sequenz fuer einen Deal.

    Fuer jeden Deal: simuliert den Weg von opportunity bis zur finalen Stage.
    Timing: gestreut in den letzten 90 Tagen.

    Returns: Liste von {deal_id, from_stage, to_stage, moved_at, moved_by}
    """
    history = []
    current_ts = datetime.now(timezone.utc) - timedelta(days=base_days_ago)

    if final_stage == "lost":
        # Lost-Deals: random wo sie gestoppt haben
        # Verteilung: 40% direkt aus opportunity, 35% aus new, 25% aus discovery
        r = random.random()
        if r < 0.40:
            stages = ["opportunity"]  # -> lost
        elif r < 0.75:
            stages = ["opportunity", "new"]  # -> lost
        else:
            stages = ["opportunity", "new", "discovery"]  # -> lost

        for i, stage in enumerate(stages):
            dwell_min, dwell_max = STAGE_DWELL_DAYS[stage]
            dwell = random.randint(dwell_min, dwell_max)

            if i == 0:
                # Erstes Entry: opportunity (kein from_stage noetig, nur TO)
                # Wir loggen: NULL -> opportunity als Eintrag
                history.append({
                    "deal_id": deal_id,
                    "from_stage": None,
                    "to_stage": stage,
                    "moved_at": current_ts.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                    "moved_by": owner,
                })
            else:
                prev_stage = stages[i-1]
                history.append({
                    "deal_id": deal_id,
                    "from_stage": prev_stage,
                    "to_stage": stage,
                    "moved_at": current_ts.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                    "moved_by": owner,
                })
            current_ts += timedelta(days=dwell, hours=random.randint(1, 8))

        # Letzter Stage -> lost
        last_active = stages[-1]
        history.append({
            "deal_id": deal_id,
            "from_stage": last_active,
            "to_stage": "lost",
            "moved_at": current_ts.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "moved_by": owner,
        })

    elif final_stage == "won":
        # Won: gesamte Kette durch
        stages = STAGE_SEQUENCE  # opportunity -> new -> discovery -> proposal_sent -> won

        for i, stage in enumerate(stages):
            dwell_min, dwell_max = STAGE_DWELL_DAYS[stage]
            dwell = random.randint(dwell_min, dwell_max)

            if i == 0:
                history.append({
                    "deal_id": deal_id,
                    "from_stage": None,
                    "to_stage": stage,
                    "moved_at": current_ts.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                    "moved_by": owner,
                })
            else:
                prev_stage = stages[i-1]
                history.append({
                    "deal_id": deal_id,
                    "from_stage": prev_stage,
                    "to_stage": stage,
                    "moved_at": current_ts.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                    "moved_by": owner,
                })
            current_ts += timedelta(days=dwell, hours=random.randint(1, 8))

    else:
        # Active stages (opportunity, new, discovery, proposal_sent)
        target_idx = STAGE_SEQUENCE.index(final_stage) if final_stage in STAGE_SEQUENCE else 0
        stages = STAGE_SEQUENCE[:target_idx + 1]

        for i, stage in enumerate(stages):
            dwell_min, dwell_max = STAGE_DWELL_DAYS[stage]
            dwell = random.randint(dwell_min, dwell_max)

            if i == 0:
                history.append({
                    "deal_id": deal_id,
                    "from_stage": None,
                    "to_stage": stage,
                    "moved_at": current_ts.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                    "moved_by": owner,
                })
            else:
                prev_stage = stages[i-1]
                history.append({
                    "deal_id": deal_id,
                    "from_stage": prev_stage,
                    "to_stage": stage,
                    "moved_at": current_ts.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                    "moved_by": owner,
                })
            current_ts += timedelta(days=dwell, hours=random.randint(1, 8))

    return history


# ─── Haupt-Seed ───────────────────────────────────────────────────────────────

def main():
    conn = get_connection()
    ts = now_iso()
    user = "system-seed"

    print(f"Verbinde mit DB: {DB_PATH}")
    print(f"Seed-Timestamp: {ts}")

    try:
        # ── 1. Unternehmen anlegen (falls nicht vorhanden) ────────────────────
        print("\n[1/5] Unternehmen anlegen...")
        existing_unternehmen = {
            r["name"]: r["id"]
            for r in conn.execute("SELECT id, name FROM unternehmen WHERE deleted_at IS NULL").fetchall()
        }

        new_unternehmen_ids = {}
        created_companies = 0
        for name, branche in BRANCHE_UNTERNEHMEN:
            if name not in existing_unternehmen:
                cur = conn.execute(
                    "INSERT INTO unternehmen (name, branche, created_by, created_at, updated_at) VALUES (?,?,?,?,?)",
                    (name, branche, user, ts, ts)
                )
                new_unternehmen_ids[name] = cur.lastrowid
                created_companies += 1
            else:
                new_unternehmen_ids[name] = existing_unternehmen[name]

        conn.commit()
        print(f"  Unternehmen angelegt: {created_companies} neu, {len(existing_unternehmen)} vorhanden")

        # Alle Unternehmen-IDs sammeln
        all_unternehmen = list(new_unternehmen_ids.values())

        # ── 2. Deals + Products erstellen ────────────────────────────────────
        print("\n[2/5] Deals erstellen (80 Deals)...")

        # Stage-Verteilung: opportunity:20, new:15, discovery:12, proposal_sent:8, won:15, lost:10
        stage_distribution = (
            ["opportunity"] * 20 +
            ["new"] * 15 +
            ["discovery"] * 12 +
            ["proposal_sent"] * 8 +
            ["won"] * 15 +
            ["lost"] * 10
        )
        random.shuffle(stage_distribution)

        deal_ids = []
        deal_data_list = []  # fuer History

        for i, stage in enumerate(stage_distribution):
            # Zufaelligen Deal-Titel waehlen
            title_data = random.choice(DEAL_TITLES)
            titel_base, products, base_acv = title_data

            # ACV mit Variation (+-30%)
            variation = random.uniform(0.7, 1.3)
            acv = round(base_acv * variation / 1000) * 1000  # auf 1000 gerundet
            acv = max(5000, min(500000, acv))

            owner = random.choice(OWNERS)
            backup_owner = random.choice(BACKUP_OWNERS[owner])

            unternehmen_id = random.choice(all_unternehmen)

            # Stage-spezifische Felder
            followup_datum = None
            unterschrift_datum = None
            projekt_start_datum = None
            verlust_grund = None
            verlust_reason_enum = None
            retry_datum = None

            if stage == "opportunity":
                followup_datum = days_from_now(random.randint(7, 30))
            elif stage == "won":
                unterschrift_datum = date_ago(random.randint(5, 60))
                projekt_start_datum = date_ago(random.randint(1, 30))
            elif stage == "lost":
                verlust_reason_enum = random.choice(VERLUST_REASONS)
                if verlust_reason_enum == "Andere":
                    verlust_grund = f"Interne Entscheidung: {random.choice(['Budget neu priorisiert', 'Projekt pausiert', 'Anderer Anbieter beauftragt', 'Stakeholder-Wechsel'])}"
                else:
                    verlust_grund = verlust_reason_enum
                retry_datum = days_from_now(random.randint(60, 180)) if random.random() > 0.5 else None

            discount_pct = round(random.choice([0, 0, 0, 5, 10, 15]), 0)
            risk_reversal = 1 if random.random() > 0.7 else 0
            notes = random.choice([
                "Kontaktpflege laeuft. Naechster Schritt: Workshop-Termin.",
                "Entscheidung liegt beim CFO. Timing nach Q3-Budget-Review.",
                "Champions intern: CTO + HR-Leitung sehr aufgeschlossen.",
                "Referenzkunde vermittelt. Feedback ausstehend.",
                None, None,  # 2x None fuer realistische Luecken
            ])
            lead_source = random.choice(LEAD_SOURCES)
            icp_persona = random.choice(ICP_PERSONAS)

            # created_at: Backdate realistisch (neuere Stages = juengere Deals)
            stage_age_days = {
                "opportunity": random.randint(1, 30),
                "new": random.randint(10, 50),
                "discovery": random.randint(20, 70),
                "proposal_sent": random.randint(30, 80),
                "won": random.randint(45, 90),
                "lost": random.randint(15, 90),
            }
            created_age = stage_age_days[stage]
            created_at = days_ago(created_age, jitter_hours=12)

            cur = conn.execute(
                """INSERT INTO deal (
                    titel, stage, unternehmen_id, owner, backup_owner,
                    acv, discount_pct, risk_reversal,
                    lead_source, icp_persona, notes,
                    followup_datum, unterschrift_datum, projekt_start_datum,
                    verlust_grund, verlust_reason_enum, retry_datum,
                    created_by, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (titel_base, stage, unternehmen_id, owner, backup_owner,
                 acv, discount_pct, risk_reversal,
                 lead_source, icp_persona, notes,
                 followup_datum, unterschrift_datum, projekt_start_datum,
                 verlust_grund, verlust_reason_enum, retry_datum,
                 user, created_at, created_at)
            )
            deal_id = cur.lastrowid
            deal_ids.append(deal_id)
            deal_data_list.append({
                "id": deal_id,
                "stage": stage,
                "owner": owner,
                "created_age": created_age,
            })

            # Produkte setzen (1-3)
            deal_products = list(set(products + random.sample(PRODUCTS, k=random.randint(0, 1))))[:3]
            for prod in deal_products:
                conn.execute(
                    "INSERT OR IGNORE INTO deal_product (deal_id, product) VALUES (?,?)",
                    (deal_id, prod)
                )

        conn.commit()
        print(f"  {len(deal_ids)} Deals angelegt.")

        # ── 3. Touchpoints ────────────────────────────────────────────────────
        print("\n[3/5] Touchpoints erstellen...")
        tp_count = 0
        for deal_data in deal_data_list:
            deal_id = deal_data["id"]
            stage = deal_data["stage"]
            deal_owner = deal_data["owner"]

            # Anzahl Touchpoints: Won/Discovery/Proposal: mehr, Opportunity/New: weniger
            if stage in ("won",):
                n_tp = random.randint(3, 5)
            elif stage in ("proposal_sent", "discovery"):
                n_tp = random.randint(2, 4)
            else:
                n_tp = random.randint(1, 2)

            base_age = deal_data["created_age"]
            for j in range(n_tp):
                tp_age = base_age - random.randint(0, base_age)
                tp_age = max(0, tp_age)
                tp_ts = days_ago(tp_age, jitter_hours=8)
                tp_date = (datetime.now(timezone.utc) - timedelta(days=tp_age)).strftime("%Y-%m-%d")
                inhalt = random.choice(TOUCHPOINT_NOTES)
                art = random.choice(["anruf", "email", "meeting", "linkedin", "notiz"])
                conn.execute(
                    """INSERT INTO touchpoint (deal_id, datum, art, inhalt, erstellt_von, created_by, created_at)
                       VALUES (?,?,?,?,?,?,?)""",
                    (deal_id, tp_date, art, inhalt, deal_owner, deal_owner, tp_ts)
                )
                tp_count += 1

        conn.commit()
        print(f"  {tp_count} Touchpoints angelegt.")

        # ── 4. Stage-History BACKFILL ─────────────────────────────────────────
        print("\n[4/5] Stage-History Backfill...")
        history_count = 0

        for deal_data in deal_data_list:
            deal_id = deal_data["id"]
            stage = deal_data["stage"]
            owner = deal_data["owner"]
            base_days_ago = deal_data["created_age"] + random.randint(0, 10)

            history_entries = build_stage_history(deal_id, stage, base_days_ago, owner)

            for entry in history_entries:
                conn.execute(
                    """INSERT INTO deal_stage_history (deal_id, from_stage, to_stage, moved_at, moved_by)
                       VALUES (?,?,?,?,?)""",
                    (entry["deal_id"], entry["from_stage"], entry["to_stage"],
                     entry["moved_at"], entry["moved_by"])
                )
                history_count += 1

        conn.commit()
        print(f"  {history_count} Stage-History-Eintraege (neue Deals) angelegt.")

        # ── 5. Bonus: Bestehende Deals mit History backfillen ─────────────────
        print("\n[5/5] Stage-History fuer bestehende Deals (Bonus)...")

        existing_deals = conn.execute(
            """SELECT d.id, d.stage, d.owner, d.created_at
               FROM deal d
               WHERE d.deleted_at IS NULL
               AND d.id NOT IN ({})
               AND NOT EXISTS (
                   SELECT 1 FROM deal_stage_history h WHERE h.deal_id = d.id
               )""".format(",".join(str(x) for x in deal_ids))
        ).fetchall()

        bonus_count = 0
        for row in existing_deals:
            deal_id = row["id"]
            stage = row["stage"]
            owner = row["owner"] or "christian"

            # Alter des Deals schaetzen aus created_at
            try:
                created = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
                age_days = max(5, (datetime.now(timezone.utc) - created).days)
            except Exception:
                age_days = 30

            base_days_ago = age_days + random.randint(0, 5)
            history_entries = build_stage_history(deal_id, stage, base_days_ago, owner)

            for entry in history_entries:
                conn.execute(
                    """INSERT INTO deal_stage_history (deal_id, from_stage, to_stage, moved_at, moved_by)
                       VALUES (?,?,?,?,?)""",
                    (entry["deal_id"], entry["from_stage"], entry["to_stage"],
                     entry["moved_at"], entry["moved_by"])
                )
                bonus_count += 1

        conn.commit()
        print(f"  {bonus_count} Stage-History-Eintraege (bestehende Deals) angelegt.")

        # ── Zusammenfassung ───────────────────────────────────────────────────
        total_history = history_count + bonus_count

        print("\n" + "="*60)
        print("SEED ABGESCHLOSSEN")
        print("="*60)

        # Stage-Counts verifizieren
        stage_counts = conn.execute(
            "SELECT stage, COUNT(*) as cnt FROM deal WHERE deleted_at IS NULL GROUP BY stage ORDER BY cnt DESC"
        ).fetchall()
        print("\nDeals pro Stage (gesamt inkl. bestehende):")
        for r in stage_counts:
            print(f"  {r['stage']:20s}: {r['cnt']:4d}")

        total_deals = conn.execute("SELECT COUNT(*) as c FROM deal WHERE deleted_at IS NULL").fetchone()["c"]
        print(f"\n  GESAMT Deals: {total_deals}")
        print(f"  NEUE Deals aus Seed: {len(deal_ids)}")
        print(f"  Touchpoints: {tp_count}")
        print(f"  Stage-History gesamt: {total_history}")

        # CVR-Vorschau
        print("\nCVR-Vorschau (direkter Uebergang):")
        transitions = [
            ("opportunity", "new"),
            ("new", "discovery"),
            ("discovery", "proposal_sent"),
            ("proposal_sent", "won"),
        ]
        for from_s, to_s in transitions:
            from_count = conn.execute(
                "SELECT COUNT(*) as c FROM deal_stage_history WHERE from_stage=?", (from_s,)
            ).fetchone()["c"]
            to_count = conn.execute(
                "SELECT COUNT(*) as c FROM deal_stage_history WHERE from_stage=? AND to_stage=?",
                (from_s, to_s)
            ).fetchone()["c"]
            if from_count > 0:
                pct = round(100.0 * to_count / from_count, 1)
                print(f"  {from_s:20s} -> {to_s:20s}: {to_count}/{from_count} = {pct}%")
            else:
                print(f"  {from_s:20s} -> {to_s:20s}: –")

        print("\nSeed erfolgreich. CVR-Cache wird beim naechsten Seitenaufruf neu berechnet.")

    except Exception as e:
        conn.rollback()
        print(f"\nFEHLER: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
