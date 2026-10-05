"""
championnats.py - liste UNIQUE des championnats suivis en priorite.

Tous les bookmakers (API 1xBet, BetPawa, 1win, 1xBet/Chromium) utilisent cette
meme liste pour choisir quels matchs garder. Ainsi ils gardent les MEMES
championnats, donc les memes matchs, et on peut les comparer entre eux.
Les mots-cles sont bilingues (FR/EN) car chaque bookmaker a sa propre langue.
"""
import re
import unicodedata

PRIORITY_KEYWORDS = (
    # Coupes d'Europe
    "champions league", "ligue des champions",
    "europa league", "ligue europa",
    "conference league", "ligue conference",
    # Selections nationales
    "nations league", "ligue des nations",
    "world cup", "coupe du monde",
    "european championship", "championnat d'europe", "euro 20",
    "qualification", "qualifier", "qualifying",
    "friendl", "amical",
    # Grands championnats
    "premier league", "la liga", "laliga", "liga espagnole", "primera division",
    "ligue 1", "serie a", "bundesliga",
    "league cup", "coupe de la ligue",
    "championship",
)


def _norm(texte):
    texte = unicodedata.normalize("NFKD", str(texte or "")).lower()
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texte).strip()


_MOTS = tuple(_norm(k) for k in PRIORITY_KEYWORDS)


def priorite(*noms):
    """0 = championnat prioritaire (tous les bookmakers le gardent en premier),
    1 = les autres. Accepte plusieurs noms (francais, anglais...)."""
    for nom in noms:
        n = _norm(nom)
        if n and any(mot in n for mot in _MOTS):
            return 0
    return 1
