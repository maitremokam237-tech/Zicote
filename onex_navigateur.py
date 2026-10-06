"""
onex_navigateur.py - matchs d'un championnat lus dans Chromium.

L'API par championnat des sites 1xBet (games1x2) exige un en-tete `x-hd`
calcule par le JavaScript du site : une requete HTTP simple est refusee (400).
On ouvre donc la page du championnat dans Chromium, le site fait lui-meme
l'appel, et on recupere sa reponse. Les cotes sont identiques a celles de
l'API de base (meme plateforme), on n'a besoin d'ouvrir qu'UN site du groupe.
"""
import asyncio
import re
from urllib.parse import parse_qs, urlparse

from onex_api import DOMAINS, build_matches, convertir_jeu_v3, priorite, CHAMPS_CONNUS

DELAI_PAR_CHAMPIONNAT = 12   # secondes d'attente de la reponse du site
MAX_CHAMPIONNATS = 16


def ids_a_charger(api_result):
    """Championnats prioritaires : liste connue + ceux vus dans les matchs de base."""
    ids = [i for i, _ in CHAMPS_CONNUS]
    for m in api_result:
        li = m.get("competition_id")
        if li is not None and str(li) not in ids \
                and priorite(m.get("competition_en"), m.get("competition")) == 0:
            ids.append(str(li))
    return ids[:MAX_CHAMPIONNATS]


def id_depuis_url(url):
    """selectedMs=2.1.<id> -> '<id>' (ou None)."""
    try:
        ms = parse_qs(urlparse(url).query).get("selectedMs", [""])[0]
    except Exception:
        return None
    m = re.match(r"^\d+\.\d+\.(\d+)$", ms)
    return m.group(1) if m else None


async def scrape_onex_navigateur(browser, proxy, bookmaker, api_result, limit=250):
    base = DOMAINS[bookmaker]
    ids = ids_a_charger(api_result)
    recus = {}   # id championnat -> liste de matchs (format v3)

    context = await browser.new_context(
        viewport={"width": 390, "height": 844}, locale="fr-FR",
        service_workers="block", **({"proxy": proxy} if proxy else {})
    )
    try:
        # Pas d'images / polices : seulement les donnees.
        await context.route(
            "**/*",
            lambda route: asyncio.ensure_future(
                route.abort() if route.request.resource_type in ("image", "media", "font")
                else route.continue_()
            ),
        )
        page = await context.new_page()

        async def lire(reponse):
            try:
                if "games1x2" not in reponse.url:
                    return
                liga = id_depuis_url(reponse.url)
                if liga is None or reponse.status != 200:
                    return
                corps = await reponse.json()
                if isinstance(corps, list):
                    recus.setdefault(liga, []).extend(corps)
            except Exception:
                pass

        page.on("response", lambda r: asyncio.ensure_future(lire(r)))

        for liga in ids:
            for chemin in (f"/fr/line/football/{liga}", f"/fr/line/football/{liga}-x"):
                try:
                    await page.goto(base + chemin, timeout=45000, wait_until="domcontentloaded")
                except Exception as e:
                    print(f"[{bookmaker}] navigateur {liga} : {type(e).__name__}")
                    continue
                for _ in range(DELAI_PAR_CHAMPIONNAT * 2):
                    if liga in recus:
                        break
                    await page.wait_for_timeout(500)
                if liga in recus:
                    break
            print(f"[{bookmaker}] navigateur championnat {liga} : "
                  f"{len(recus.get(liga, []))} match(s)")
    finally:
        await context.close()

    evenements = []
    for jeux in recus.values():
        evenements += [convertir_jeu_v3(g) for g in jeux if isinstance(g, dict)]
    return build_matches(bookmaker, evenements, base, limit)


def fusionner(api_result, extra):
    """Ajoute les matchs de `extra` absents de `api_result` (meme affiche)."""
    deja = {(m["equipe_1"], m["equipe_2"]) for m in api_result}
    ajout = [m for m in extra if (m["equipe_1"], m["equipe_2"]) not in deja]
    return api_result + ajout, len(ajout)
