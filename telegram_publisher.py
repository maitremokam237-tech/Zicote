#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Zicote — Publication automatique Telegram

Publie 5 matchs sur le canal Telegram 3 fois par jour.

Le script :
- lit docs/comparison.json
- sélectionne des matchs à venir
- privilégie les matchs avec plusieurs bookmakers
- évite de publier des matchs sans comparaison intéressante
- génère un message Telegram propre
- ajoute un bouton vers Zicote.site
- ajoute un bouton vers la page individuelle du match
"""

import html
import json
import os
import sys
from datetime import datetime, timezone

import requests


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

COMPARISON_FILE = os.path.join(
    BASE_DIR,
    "docs",
    "comparison.json"
)

TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN",
    ""
)

TELEGRAM_CHAT_ID = os.environ.get(
    "TELEGRAM_CHAT_ID",
    "-1003545879698"
)

SITE_URL = "https://zicote.site"

MAX_MATCHES = 5

TELEGRAM_API = (
    "https://api.telegram.org/bot"
    + TELEGRAM_BOT_TOKEN
)


# ============================================================
# UTILITAIRES
# ============================================================

def log(message):
    print(f"[telegram] {message}")


def esc(value):
    """
    Échappe le texte pour Telegram HTML.
    """
    return html.escape(str(value or ""))


def parse_date(value):
    """
    Convertit une date ISO en datetime UTC.
    """
    if not value:
        return None

    try:
        value = str(value)

        if value.endswith("Z"):
            value = value[:-1] + "+00:00"

        dt = datetime.fromisoformat(value)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc)

    except Exception:
        return None


def match_slug(match):
    """
    Reproduit le système de slug utilisé par comparateur.py.
    """

    import re
    import unicodedata

    def slugify(value):
        value = unicodedata.normalize(
            "NFKD",
            str(value or "")
        )

        value = value.encode(
            "ascii",
            "ignore"
        ).decode("ascii")

        value = value.lower()

        value = re.sub(
            r"[^a-z0-9]+",
            "-",
            value
        )

        return value.strip("-")

    return (
        slugify(match.get("equipe_1"))
        + "-"
        + slugify(match.get("equipe_2"))
    )


# ============================================================
# CHARGEMENT DES MATCHS
# ============================================================

def load_matches():
    if not os.path.exists(COMPARISON_FILE):
        raise FileNotFoundError(
            f"Fichier introuvable : {COMPARISON_FILE}"
        )

    with open(
        COMPARISON_FILE,
        "r",
        encoding="utf-8"
    ) as f:
        data = json.load(f)

    matches = data.get("matchs", [])

    if not isinstance(matches, list):
        raise ValueError(
            "comparison.json : 'matchs' n'est pas une liste."
        )

    return matches


# ============================================================
# SÉLECTION DES MATCHS
# ============================================================

def score_match(match):
    """
    Donne un score au match pour favoriser :
    - plusieurs bookmakers
    - plusieurs marchés
    - les compétitions connues
    """

    bookmakers = match.get("bookmakers") or []
    markets = match.get("marches") or []

    score = 0

    # Plusieurs bookmakers = très intéressant
    score += min(len(bookmakers), 8) * 20

    # Plusieurs marchés
    score += min(len(markets), 20)

    # Match avec une heure connue
    if match.get("debut"):
        score += 10

    competition = str(
        match.get("competition") or ""
    ).lower()

    # Favoriser légèrement les grandes compétitions
    popular = [
        "premier league",
        "champions league",
        "liga",
        "la liga",
        "serie a",
        "bundesliga",
        "ligue 1",
        "europa",
        "conference",
        "world cup",
        "coupe du monde",
        "africa",
        "caf",
    ]

    for keyword in popular:
        if keyword in competition:
            score += 30
            break

    return score


def select_matches(matches):
    """
    Sélectionne exactement jusqu'à 5 matchs.

    La rotation dépend de l'heure UTC afin que les 3 publications
    quotidiennes ne prennent pas systématiquement les mêmes matchs.
    """

    now = datetime.now(timezone.utc)

    upcoming = []

    for match in matches:
        kickoff = parse_date(match.get("debut"))

        if kickoff is None:
            continue

        # On ignore les matchs déjà commencés
        if kickoff <= now:
            continue

        bookmakers = match.get("bookmakers") or []
        markets = match.get("marches") or []

        # On veut une vraie comparaison
        if len(bookmakers) < 2:
            continue

        if not markets:
            continue

        item = {
            "match": match,
            "kickoff": kickoff,
            "score": score_match(match),
        }

        upcoming.append(item)

    if not upcoming:
        return []

    # Tri :
    # 1. qualité du match
    # 2. date du match
    upcoming.sort(
        key=lambda x: (
            -x["score"],
            x["kickoff"]
        )
    )

    # Rotation quotidienne.
    #
    # 3 créneaux :
    # 0 = matin
    # 1 = après-midi
    # 2 = soir
    #
    # Cela évite de reprendre systématiquement les mêmes 5 matchs.

    hour = now.hour

    if hour < 12:
        slot = 0
    elif hour < 17:
        slot = 1
    else:
        slot = 2

    day_number = now.timetuple().tm_yday

    offset = (
        (day_number * 3 + slot)
        * MAX_MATCHES
    )

    if len(upcoming) > MAX_MATCHES:
        start = offset % len(upcoming)

        rotated = (
            upcoming[start:]
            + upcoming[:start]
        )
    else:
        rotated = upcoming

    selected = rotated[:MAX_MATCHES]

    return selected


# ============================================================
# MESSAGE TELEGRAM
# ============================================================

def format_kickoff(dt):
    """
    Affiche l'heure en heure locale du Cameroun :
    UTC+1.
    """

    from datetime import timedelta

    local_dt = dt + timedelta(hours=1)

    return local_dt.strftime(
        "%d/%m à %H:%M"
    )


def best_market(match):
    """
    Trouve une meilleure cote intéressante à afficher.
    """

    markets = match.get("marches") or []

    preferred_types = [
        "1X2",
        "Double_Chance",
        "BTTS",
        "Total_2.5",
        "Totals",
        "Handicap",
    ]

    # D'abord les marchés principaux
    for preferred in preferred_types:
        for market in markets:
            if market.get("type") != preferred:
                continue

            odd = market.get("meilleure_cote")
            bookmaker = market.get("meilleur_site")

            if odd is None:
                continue

            return market, odd, bookmaker

    # Sinon premier marché exploitable
    for market in markets:
        odd = market.get("meilleure_cote")
        bookmaker = market.get("meilleur_site")

        if odd is not None:
            return market, odd, bookmaker

    return None, None, None


def build_message(selected):
    """
    Construit le message principal.
    """

    lines = []

    lines.append(
        "⚽ <b>LES 5 MATCHS À SURVEILLER</b>"
    )

    lines.append("")
    lines.append(
        "📊 <b>Zicote compare les cotes</b> "
        "de plusieurs bookmakers pour vous aider "
        "à repérer les meilleures cotes disponibles."
    )

    lines.append("")

    for index, item in enumerate(selected, start=1):

        match = item["match"]
        kickoff = item["kickoff"]

        equipe1 = esc(
            match.get("equipe_1", "?")
        )

        equipe2 = esc(
            match.get("equipe_2", "?")
        )

        competition = esc(
            match.get(
                "competition",
                "Football"
            )
        )

        bookmakers = match.get(
            "bookmakers"
        ) or []

        market, odd, bookmaker = best_market(
            match
        )

        slug = match_slug(match)

        match_url = (
            f"{SITE_URL}/{slug}/"
        )

        lines.append(
            f"<b>{index}. {equipe1} 🆚 {equipe2}</b>"
        )

        lines.append(
            f"🏆 {competition}"
        )

        lines.append(
            f"🕐 {format_kickoff(kickoff)}"
        )

        lines.append(
            f"📊 {len(bookmakers)} bookmakers comparés"
        )

        if odd is not None:

            bookmaker_name = esc(
                bookmaker or "meilleur bookmaker"
            )

            lines.append(
                f"🔥 Meilleure cote repérée : "
                f"<b>{odd}</b> "
                f"({bookmaker_name})"
            )

        lines.append(
            f'👉 <a href="{match_url}">'
            f"Comparer ce match"
            f"</a>"
        )

        lines.append("")

    lines.append(
        "━━━━━━━━━━━━━━━━━━"
    )

    lines.append(
        "🔎 <b>Comparez toutes les cotes sur Zicote</b>"
    )

    lines.append(
        f'👉 <a href="{SITE_URL}">'
        f"<b>ACCÉDER À ZICOTE.SITE</b>"
        f"</a>"
    )

    lines.append("")

    lines.append(
        "⚠️ Les cotes peuvent changer rapidement. "
        "Comparez toujours les conditions du bookmaker "
        "avant toute décision."
    )

    return "\n".join(lines)


# ============================================================
# ENVOI TELEGRAM
# ============================================================

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN n'est pas configuré."
        )

    url = (
        TELEGRAM_API
        + "/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }

    response = requests.post(
        url,
        json=payload,
        timeout=30
    )

    try:
        data = response.json()
    except Exception:
        data = {}

    if not response.ok or not data.get("ok"):
        raise RuntimeError(
            "Telegram API a refusé le message : "
            + response.text
        )

    return data


# ============================================================
# MAIN
# ============================================================

def main():

    log("Démarrage de la publication Telegram...")

    matches = load_matches()

    log(
        f"{len(matches)} matchs disponibles "
        "dans comparison.json."
    )

    selected = select_matches(matches)

    if not selected:
        log(
            "Aucun match approprié à publier."
        )

        # On ne fait pas échouer tout le workflow.
        return 0

    log(
        f"{len(selected)} matchs sélectionnés."
    )

    message = build_message(
        selected
    )

    print("\n" + "=" * 60)
    print(message)
    print("=" * 60 + "\n")

    result = send_telegram(
        message
    )

    message_id = (
        result.get("result", {})
        .get("message_id")
    )

    log(
        f"Publication Telegram réussie. "
        f"message_id={message_id}"
    )

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())

    except Exception as exc:

        print(
            f"[telegram] ERREUR : {exc}",
            file=sys.stderr
        )

        # Une erreur Telegram ne doit pas casser
        # le reste du système.
        sys.exit(1)
