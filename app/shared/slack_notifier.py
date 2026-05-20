"""
slack_notifier.py – CRM Won-Celebration Slack-Notifications
Joker-Persona: zufaellige Celebration-Phrase bei jedem Deal-Abschluss.

Fire-and-forget: Errors werden geloggt, nie geraist.
Channel: C0B5DBN1E2U (CBH-Team)
"""

import os
import random
import logging
import requests

logger = logging.getLogger(__name__)

# ── User-IDs (Slack) ─────────────────────────────────────────────────────────
SLACK_USER_IDS = {
    "christian": "U6R8MS601",
    "andre":     "U4LGQ5RV3",
    "michi":     "U8Q2JJVCP",
    "marco":     "U09DHA8EW3U",
    "tim":       "U09H057AF99",
}

# ── Won-Phrases (Joker) ───────────────────────────────────────────────────────
WON_PHRASES = [
    "🚀 {owner_tag} hat *{deal_titel}* geschlossen. Einfach so. Nächster bitte.",
    "🏆 GEWONNEN!\n{owner_tag} bringt *{deal_titel}* rein – *€{acv}*.\nDas war kein Zufall. Das war Handwerk.",
    "🎉🎉🎉\n{owner_tag} hat *{deal_titel}* gewonnen!\n{unternehmen} ist jetzt im Boot. Respect.",
    "Ach schau an. {owner_tag} hat wieder zugeschlagen.\n*{deal_titel}* – geschlossen. Sauber.\nManche nennen das Glück. Wir nennen es System. 🎯",
    "💪 *{produkte}* verkauft. *{deal_titel}* gewonnen.\n{owner_tag} weiß was er tut. Case closed.",
    "🏏 Six! {owner_tag} schlägt *{deal_titel}* aus dem Park.\n{unternehmen} ist dabei – *€{acv}* auf dem Board.\nSpieler des Tages: nicht zur Diskussion.",
    "🔥 {owner_tag} × *{deal_titel}* = DEAL.\nKurz, sauber, fertig.",
    "Ship it. Sign it. Cash it. 🤑\n{owner_tag} hat *{deal_titel}* deployed.\n{unternehmen} ist live. *€{acv}*. Merge approved.",
    "Stille im Raum.\n\nDann: die Unterschrift.\n\n{owner_tag} hat *{deal_titel}* gewonnen. *€{acv}*.\n\nIhr wisst was das bedeutet. 🏆",
    "Das Team steht auf, wenn {owner_tag} reinkommt.\n*{deal_titel}* ist durch. 💪\nWeiter so.",
    "🚀 Neuer Win!\n{owner_tag} hat {unternehmen} mit *{produkte}* überzeugt.\nDeal: *{deal_titel}* – *€{acv}*.\nGenau dafür bauen wir das hier auf.",
    "🏈 Touchdown! {owner_tag} bringt *{deal_titel}* in die Endzone.\n{unternehmen} an Bord. *€{acv}* auf der Uhr.\nHigh five – für sich selbst.",
    "{owner_tag}. *{deal_titel}*. Gewonnen. ✅\nSonst nichts.",
    "🎆🎆🎆 DEAL CLOSED 🎆🎆🎆\n{owner_tag} × {unternehmen}\n*{deal_titel}* – *€{acv}*\nDas Ding ist durch. Feiern ist erlaubt.",
    "Wir hatten erwartet, dass {owner_tag} *{deal_titel}* gewinnt.\nTrotzdem: respekt. 🎯\n*€{acv}* – nicht schlecht für einen Montag.",
]


def notify_won(
    deal_titel: str,
    owner: str,
    unternehmen: str = "",
    acv=None,
    products: list = None,
) -> None:
    """
    Sendet eine zufaellige Won-Celebration-Nachricht an den CBH-Slack-Channel.
    Fire-and-forget: Exceptions werden geloggt, nie nach oben gegeben.
    """
    try:
        token = os.environ.get("CBH_SLACK_BOT_TOKEN", "")
        channel = os.environ.get("CRM_WON_SLACK_CHANNEL", "C0B5DBN1E2U")

        if not token:
            logger.error("[slack_notifier] CBH_SLACK_BOT_TOKEN nicht gesetzt – Notification übersprungen")
            return

        # Owner-Tag aufloesen
        owner_tag = f"<@{SLACK_USER_IDS[owner]}>" if owner in SLACK_USER_IDS else owner

        # ACV formatieren
        acv_str = f"{float(acv):,.0f}" if acv is not None else "—"

        # Produkte als lesbare Liste
        produkte_str = ", ".join(products).upper().replace("_", " ") if products else "—"

        # Unternehmen-Fallback
        unternehmen_str = unternehmen if unternehmen else "—"

        # Zufaellige Phrase – graceful bei fehlenden Variablen
        phrase = random.choice(WON_PHRASES)
        try:
            text = phrase.format(
                owner_tag=owner_tag,
                deal_titel=deal_titel or "Neuer Deal",
                unternehmen=unternehmen_str,
                acv=acv_str,
                produkte=produkte_str,
            )
        except KeyError as e:
            # Fallback: sichere Basisnachricht wenn Phrase unbekannte Variable hat
            logger.warning(f"[slack_notifier] Format-Fehler in Phrase: {e} – Fallback-Text")
            text = f"🚀 {owner_tag} hat *{deal_titel}* gewonnen!"

        payload = {
            "channel": channel,
            "text": text,
            "username": "Joker",
            "icon_emoji": ":rocket:",
        }

        resp = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=5,
        )
        data = resp.json()
        if not data.get("ok"):
            logger.error(f"[slack_notifier] Slack API Fehler: {data.get('error', 'unknown')}")
        else:
            logger.info(f"[slack_notifier] Won-Notification gesendet für Deal '{deal_titel}'")

    except Exception as exc:
        # Fire-and-forget: niemals raisen
        logger.exception(f"[slack_notifier] Unerwarteter Fehler: {exc}")
