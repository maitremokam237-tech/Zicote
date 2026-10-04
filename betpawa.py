"""BetPawa Cameroun — lecture de l'API sportsbook (pas de scraping d'écran).

La page betpawa.cm est une application Next.js : les matchs viennent de
/api/sportsbook/v4/events/lists/by-queries (en-tête x-pawa-brand requis).
On ouvre une vraie page Chromium (cookies Cloudflare, proxy Webshare) puis
on appelle l'API avec fetch() depuis cette page.

Marchés lus : 1X2 (id 3743) et Plus/Moins de buts (id 5000).
Les autres marchés (double chance, BTTS, handicap...) pourront être
ajoutés quand leurs identifiants seront connus.
"""
import datetime
import json
import os
import re
from urllib.parse import quote

BASE = "https://www.betpawa.cm"
BRAND = "betpawa-cameroon"
API = BASE + "/api/sportsbook/v4/events/lists/by-queries"
LISTING_URL = BASE + "/events?categoryId=2&marketId=1X2"
WARMUP_URL = BASE + "/manifest.json"

MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
)

MARKET_1X2 = "3743"
MARKET_TOTAL = "5000"

PAGE_SIZE = 100
MAX_PAGES = int(os.getenv("BETPAWA_MAX_PAGES", "6"))
MAX_MATCHES = int(os.getenv("BETPAWA_MAX_MATCHES", "40"))

# Compétitions de l'URL d'origine (championnats suivis en priorité).
WANTED_COMPETITIONS = {"12039", "11965", "12110", "12667", "12541"}

PRIORITY_KEYWORDS = (
    "champions league", "ligue des champions", "europa league",
    "ligue europa", "conference league", "premier league", "la liga",
    "laliga", "liga espagnole", "ligue 1", "serie a", "bundesliga",
    "league cup", "coupe de la ligue",
)

JS_FETCH = """
async ({url, brand}) => {
    try {
        const r = await fetch(url, {
            headers: {"x-pawa-brand": brand, "accept": "application/json"},
            credentials: "include"
        });
        return {status: r.status, body: await r.text()};
    } catch (e) {
        return {status: 0, body: String(e)};
    }
}
"""


def _query_url(skip):
    q = {
        "queries": [{
            "query": {
                "eventType": "UPCOMING",
                "categories": ["2"],
                "zones": {},
                "hasOdds": True,
            },
            "view": {"marketTypes": [MARKET_1X2, MARKET_TOTAL]},
            "skip": skip,
            "take": PAGE_SIZE,
        }]
    }
    return API + "?q=" + quote(json.dumps(q, separators=(",", ":")))


async def _fetch_json(page, url):
    res = await page.evaluate(JS_FETCH, {"url": url, "brand": BRAND})
    if res.get("status") != 200:
        return res.get("status"), None
    try:
        return 200, json.loads(res["body"])
    except Exception:
        return 200, None


def _events_of(data):
    try:
        return data["responses"][0]["responses"] or []
    except Exception:
        return []


# ------------------------------------------------------------------
# Lecture des marchés
# ------------------------------------------------------------------

def _market(event, market_id):
    for m in event.get("markets", []) or []:
        if str((m.get("marketType") or {}).get("id")) == market_id:
            return m
    return None


def _odds(price):
    try:
        value = float(price.get("odds"))
    except (TypeError, ValueError):
        return None
    return value if value > 1.0 else None


def parse_1x2(event):
    market = _market(event, MARKET_1X2)
    if not market or not market.get("row"):
        return None
    wanted = {"1": "V1", "X": "X", "2": "V2"}
    result = {}
    for price in market["row"][0].get("prices", []):
        key = wanted.get(str(price.get("name")).strip())
        odds = _odds(price)
        if key and odds:
            result[key] = str(odds)
    return result if len(result) == 3 else None


LINE_KEYS = ("handicap", "line", "total", "value", "specialValue", "points")


def _line_of(row, price):
    """Ligne (ex. 2.5) d'une cote Plus/Moins. Renvoie None si elle ne
    peut pas être identifiée avec certitude : mieux vaut ne rien
    afficher que d'attribuer une cote à la mauvaise ligne."""
    sources = []
    for holder in (price.get("additionalInfo"), row.get("additionalInfo"), row, price):
        if isinstance(holder, dict):
            sources.append(holder)
    for src in sources:
        for key in LINE_KEYS:
            if key in src and isinstance(src[key], (str, int, float)):
                try:
                    line = float(str(src[key]).replace(",", "."))
                except ValueError:
                    continue
                if line > 20:        # ex. 250 pour 2.5
                    line /= 100
                if 0.5 <= line <= 12 and (line * 4) == int(line * 4):
                    return line
    # Libellé du type "Plus de 2.5"
    label = f"{price.get('displayName', '')} {price.get('name', '')}"
    found = re.search(r"(\d+(?:[.,]\d+)?)", label)
    if found:
        line = float(found.group(1).replace(",", "."))
        if 0.5 <= line <= 12 and (line * 4) == int(line * 4):
            return line
    return None


def parse_totals(event):
    market = _market(event, MARKET_TOTAL)
    if not market:
        return {}
    totals = {}
    for row in market.get("row", []) or []:
        for price in row.get("prices", []) or []:
            name = str(price.get("name")).strip()
            if name not in ("Plus de", "Moins de"):
                continue
            odds = _odds(price)
            line = _line_of(row, price)
            if odds is None or line is None:
                continue
            key = f"{line:g}"
            totals.setdefault(key, {})[name] = str(odds)
    return {k: v for k, v in totals.items() if len(v) == 2}


# ------------------------------------------------------------------
# Choix des matchs
# ------------------------------------------------------------------

def _priority(event):
    comp = event.get("competition") or {}
    name = str(comp.get("name", "")).lower()
    if str(comp.get("id")) in WANTED_COMPETITIONS:
        return 0
    if any(k in name for k in PRIORITY_KEYWORDS):
        return 1
    return 2


def build_matches(events):
    candidates = []
    for event in events:
        teams = sorted(event.get("participants") or [], key=lambda p: p.get("position", 0))
        if len(teams) != 2:
            continue
        one_x_two = parse_1x2(event)
        if not one_x_two:
            continue
        candidates.append((_priority(event), event.get("startTime", ""), event, teams, one_x_two))

    candidates.sort(key=lambda c: (c[0], c[1]))
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    result = []

    for _, _, event, teams, one_x_two in candidates[:MAX_MATCHES]:
        totals = parse_totals(event)
        t25 = totals.get("2.5", {})
        match = {
            "bookmaker": "betpawa",
            "equipe_1": str(teams[0].get("name", "")).strip(),
            "equipe_2": str(teams[1].get("name", "")).strip(),
            "1X2": one_x_two,
            "Total_2.5": {
                "Plus de": t25.get("Plus de"),
                "Moins de": t25.get("Moins de"),
            },
            "url": LISTING_URL,
            "derniere_maj": now,
            "statut": "ok",
        }
        if totals:
            match["Totals"] = totals
        result.append(match)

    return result


# ------------------------------------------------------------------
# Point d'entrée
# ------------------------------------------------------------------

async def scrape_betpawa(browser, proxy=None):
    if os.getenv("BETPAWA_NO_PROXY"):
        proxy = None

    context = None
    try:
        context = await browser.new_context(
            viewport={"width": 390, "height": 844},
            user_agent=MOBILE_UA,
            is_mobile=True,
            has_touch=True,
            locale="fr-FR",
            service_workers="block",
            **({"proxy": proxy} if proxy else {}),
        )
        print(f"[betpawa] contexte créé (proxy Webshare: {'actif' if proxy else 'désactivé'})")
        page = await context.new_page()
        await page.goto(WARMUP_URL, timeout=60000, wait_until="domcontentloaded")

        events = []
        seen = set()

        for index in range(MAX_PAGES):
            status, data = await _fetch_json(page, _query_url(index * PAGE_SIZE))

            if status != 200 and index == 0:
                # Cloudflare a peut-être demandé un contrôle : on charge
                # la vraie page une fois puis on réessaie.
                print(f"[betpawa] API statut {status}, nouvel essai via la page événements")
                await page.goto(LISTING_URL, timeout=90000, wait_until="domcontentloaded")
                await page.wait_for_timeout(8000)
                status, data = await _fetch_json(page, _query_url(0))

            if status != 200 or data is None:
                print(f"[betpawa] API indisponible (statut {status}), page {index + 1}")
                break

            batch = _events_of(data)
            for event in batch:
                if event.get("id") not in seen:
                    seen.add(event.get("id"))
                    events.append(event)

            if len(batch) < PAGE_SIZE:
                break

        print(f"[betpawa] {len(events)} match(s) lus dans l'API")
        result = build_matches(events)

        n_tot = sum(1 for m in result if m["Total_2.5"]["Plus de"])
        print(f"[betpawa] {len(result)} matchs enregistrés ({n_tot} avec Plus/Moins 2,5)")

        if events and not any("Totals" in m for m in result):
            sample = next((_market(e, MARKET_TOTAL) for e in events if _market(e, MARKET_TOTAL)), None)
            if sample and sample.get("row"):
                print("[betpawa] Plus/Moins non reconnu, exemple brut : "
                      + json.dumps(sample["row"][0], ensure_ascii=False)[:600])

        return result

    except Exception as error:
        print(f"[betpawa] erreur : {error}")
        return []

    finally:
        if context:
            try:
                await context.close()
            except Exception:
                pass

