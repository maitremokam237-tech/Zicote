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
    vus_api = {}  # DIAGNOSTIC : (fragment d'URL, statut) -> nombre d'appels
    courant = {"liga": None}   # championnat dont la page est en cours de chargement
    diag = {"fait": False}     # un seul exemple de reponse est decrit dans le log

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
                # DIAGNOSTIC : on note les appels de donnees vus, pour savoir si le
                # site a change d'URL quand "0 match(s)" revient pour tous les championnats.
                if any(k in reponse.url for k in ("line-feed", "LineFeed", "games1x2", "/service-api/")):
                    cle = (reponse.url.split("?")[0].split("/service-api/")[-1][:60], reponse.status)
                    vus_api[cle] = vus_api.get(cle, 0) + 1
                if "games1x2" not in reponse.url or "topgames" in reponse.url.lower():
                    return
                if reponse.status != 200:
                    return
                # CORRECTION : si l'URL ne contient plus selectedMs=2.1.<id>, on se
                # rabat sur le championnat dont la page est en cours de chargement.
                liga = id_depuis_url(reponse.url) or courant["liga"]
                corps = await reponse.json()
                if not diag["fait"]:
                    diag["fait"] = True
                    requete = reponse.url.split("?", 1)[1][:160] if "?" in reponse.url else ""
                    forme = (f"liste de {len(corps)}" if isinstance(corps, list)
                             else f"dict cles={list(corps)[:8]}" if isinstance(corps, dict)
                             else type(corps).__name__)
                    print(f"[{bookmaker}] navigateur diag games1x2 : requete={requete} | corps={forme} | liga={liga}")
                # CORRECTION : accepte aussi une reponse enveloppee dans un dict.
                if isinstance(corps, dict):
                    for cle in ("Value", "value", "items", "games", "data", "result"):
                        interne = corps.get(cle)
                        if isinstance(interne, dict):
                            interne = interne.get("items") or interne.get("games") or interne.get("data")
                        if isinstance(interne, list):
                            corps = interne
                            break
                if liga is not None and isinstance(corps, list):
                    recus.setdefault(liga, []).extend(corps)
            except Exception:
                pass

        page.on("response", lambda r: asyncio.ensure_future(lire(r)))

        for liga in ids:
            courant["liga"] = liga
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
        if vus_api and not recus:
            print(f"[{bookmaker}] navigateur : aucun games1x2 exploitable. Appels vus : "
                  + "; ".join(f"{k[0]} -> {k[1]} x{v}" for k, v in list(vus_api.items())[:12]))
        elif not vus_api:
            print(f"[{bookmaker}] navigateur : aucun appel de donnees detecte "
                  "(page bloquee ? proxy ? Cloudflare ?)")

    # CORRECTION : une meme reponse peut etre captee plusieurs fois (rechargement,
    # reponse tardive attribuee au championnat suivant) -> on dedoublonne par
    # identifiant d'evenement avant de construire les matchs.
    evenements, vus = [], set()
    for jeux in recus.values():
        for g in jeux:
            if not isinstance(g, dict):
                continue
            cle = g.get("id")
            if cle is not None:
                if cle in vus:
                    continue
                vus.add(cle)
            evenements.append(convertir_jeu_v3(g))
    return build_matches(bookmaker, evenements, base, limit)


def fusionner(api_result, extra):
    """Ajoute les matchs de `extra` absents de `api_result` (meme affiche)."""
    deja = {(m["equipe_1"], m["equipe_2"]) for m in api_result}
    ajout = []
    for m in extra:
        cle = (m["equipe_1"], m["equipe_2"])
        if cle in deja:      # CORRECTION : dedoublonne aussi `extra` lui-meme
            continue
        deja.add(cle)
        ajout.append(m)
    return api_result + ajout, len(ajout)

