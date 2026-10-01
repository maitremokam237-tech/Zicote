import os


# ============================================================
# PROXY UNIQUE WEBSHARE (optionnel)
# ============================================================

def webshare_proxy():
    """Construit la configuration Playwright pour un proxy Webshare unique."""
    host = os.getenv("WEBSHARE_HOST", "").strip()
    port = os.getenv("WEBSHARE_PORT", "").strip()
    username = os.getenv("WEBSHARE_USERNAME", "").strip()
    password = os.getenv("WEBSHARE_PASSWORD", "").strip()

    if not host or not port:
        return None

    settings = {"server": f"http://{host}:{port}"}
    if username:
        settings["username"] = username
    if password:
        settings["password"] = password
    return settings


# ============================================================
# LIMITES POUR ECONOMISER LA BANDE PASSANTE
# ============================================================

MAX_MATCHES_PER_SITE = int(
    os.getenv("MAX_MATCHES_PER_SITE", "25")
)


# ============================================================
# PARALLELISATION
# ============================================================

MAX_PARALLEL_BOOKMAKERS = int(
    os.getenv("MAX_PARALLEL_BOOKMAKERS", "4")
)


# ============================================================
# BOOKMAKERS
# ============================================================

BOOKMAKERS = {

    "betwinner": {
        "url": "https://betwinner.cm/fr/line/football",
    },

    "melbet": {
        "url": "https://melbet-cm.com/en/line/football",
    },

    "megapari": {
        "url": "https://5572183mp.pro/en/line/football",
    },

    "1win": {
        "url": "https://1win.com/betting/prematch",
    },

    "winwin": {
        "url": "https://winwin.bet/en/line/football",
    },

    "1xbet": {
        "url": "https://1xbet.cm/fr/line/football",
    },

    "africa-bizbet": {
        "url": "https://africa-bizbet.com/en/line/football",
    },
}


BOOKMAKERS_LIST = list(BOOKMAKERS.keys())
