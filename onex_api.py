"""
onex_api.py - lecture des cotes via l'API LineFeed (plateforme 1xBet :
betwinner, melbet, 1xbet...). Remplace le scraping Chromium par de simples
requetes HTTP, au meme format que les autres <bookmaker>.json.

Usage dans scraper.py :
    from onex_api import scrape_onex
    result = await scrape_onex("betwinner", webshare_proxy_url)   # liste de matchs

Test en ligne de commande (Termux) :
    python onex_api.py betwinner
"""
import asyncio
import datetime
import os
import sys

import requests

from championnats import priorite

DOMAINS = {
    "betwinner": "https://betwinner.cm",
    "melbet": "https://melbet-cm.com",
    "winwin": "https://winwin.bet",
    "africa-bizbet": "https://africa-bizbet.com",
    "megapari": "https://5572183mp.pro",
    # "1xbet": cotes differentes sur le vrai site (marge propre) : l'API sans
    # parametres renvoie les memes cotes que betwinner -> laisse sur Chromium
    # tant que le parametre n'est pas trouve (voir DIAG ci-dessous).
}
# Domaines testes seulement par "python onex_api.py compare"
DIAG = {"1xbet": "https://1xbet.cm"}
ALL_DOMAINS = {**DOMAINS, **DIAG}
ENDPOINT = "/service-api/LineFeed/Get1x2_VZip"
# Nombre d'evenements demandes a l'API, puis nombre de matchs gardes par bookmaker.
COUNT = int(os.getenv("ONEX_COUNT", "300"))
MAX_GARDES = int(os.getenv("ONEX_MAX_MATCHES", "150"))
UA = ("Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36")


def _fmt_line(p):
    """2.0 -> '2', 2.5 -> '2.5', -1.0 -> '-1'."""
    p = float(p)
    return str(int(p)) if p == int(p) else str(p)


def _signed(p):
    s = _fmt_line(p)
    return s if s.startswith("-") or s == "0" else "+" + s


def _iso_utc(ts):
    """Timestamp Unix (secondes) -> ISO 8601 UTC, ou None."""
    try:
        ts = int(ts)
        if ts <= 0:
            return None
        return datetime.datetime.fromtimestamp(
            ts, datetime.timezone.utc
        ).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def parse_event(ev):
    """Transforme un evenement de l'API en dictionnaire de marches."""
    rows = list(ev.get("E") or [])
    for group in ev.get("AE") or []:
        for me in group.get("ME") or []:
            row = dict(me)
            row.setdefault("G", group.get("G"))
            rows.append(row)

    one_x_two, double, btts, totals, handicap = {}, {}, {}, {}, {}
    for r in rows:
        g, t, c, p = r.get("G"), r.get("T"), r.get("C"), r.get("P")
        if c is None:
            continue
        c = str(c)
        if g == 1:
            name = {1: "V1", 2: "X", 3: "V2"}.get(t)
            if name:
                one_x_two[name] = c
        elif g == 8:
            name = {4: "1X", 5: "12", 6: "2X"}.get(t)
            if name:
                double[name] = c
        elif g == 19:
            name = {180: "Oui", 181: "Non"}.get(t)
            if name:
                btts[name] = c
        elif g == 17 and p is not None:
            name = {9: "Plus de", 10: "Moins de"}.get(t)
            if name:
                totals.setdefault(_fmt_line(p), {})[name] = c
        elif g == 2:
            if t == 7:
                handicap[f"1 ({_signed(p or 0)})"] = c
            elif t == 8:
                handicap[f"2 ({_signed(p or 0)})"] = c
    totals = {k: v for k, v in totals.items() if len(v) == 2}
    return one_x_two, double, btts, totals, handicap


def build_matches(bookmaker, events, base, limit):
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    out = []
    for ev in events:
        o1, o2 = ev.get("O1"), ev.get("O2")
        if not o1 or not o2:
            continue
        one_x_two, double, btts, totals, handicap = parse_event(ev)
        if len(one_x_two) != 3:
            continue
        t25 = totals.get("2.5", {})
        match = {
            "bookmaker": bookmaker,
            "equipe_1": str(o1).strip(),
            "equipe_2": str(o2).strip(),
            "1X2": one_x_two,
            "Total_2.5": {"Plus de": t25.get("Plus de"), "Moins de": t25.get("Moins de")},
            "url": f"{base}/fr/line/football",
            "derniere_maj": now,
            "statut": "ok",
        }
        # Infos servant a rapprocher le meme match chez les autres bookmakers
        # (heure de coup d'envoi, championnat, noms anglais des equipes).
        debut = _iso_utc(ev.get("S"))
        if debut:
            match["debut"] = debut
        if ev.get("L"):
            match["competition"] = str(ev["L"]).strip()
        if ev.get("LE"):
            match["competition_en"] = str(ev["LE"]).strip()
        if ev.get("LI") is not None:
            match["competition_id"] = ev["LI"]
        if ev.get("O1E") and ev.get("O2E"):
            match["equipe_1_en"] = str(ev["O1E"]).strip()
            match["equipe_2_en"] = str(ev["O2E"]).strip()
        if double:
            match["Double_Chance"] = double
        if btts:
            match["BTTS"] = btts
        if totals:
            match["Totals"] = totals
        if handicap:
            match["Handicap"] = handicap
        # Championnats prioritaires d'abord (les memes chez tous les bookmakers,
        # pour qu'ils se recoupent), puis par date de debut.
        out.append(((priorite(ev.get("LE"), ev.get("L")), ev.get("S") or 0), match))
    out.sort(key=lambda x: x[0])
    return [m for _, m in out[:min(limit, MAX_GARDES)]]


def _get(base, endpoint, params, proxy, nom):
    proxies = {"http": proxy, "https": proxy} if proxy else None
    r = requests.get(base + endpoint, params=params, proxies=proxies, timeout=40,
                     headers={"User-Agent": UA, "Accept": "application/json",
                              "Referer": base + "/fr/line/football"})
    if r.status_code != 200:
        print(f"[{nom}] API {endpoint.rsplit('/', 1)[-1]} statut {r.status_code}")
        return None
    return r.json().get("Value") or []


def _params(count, **extra):
    params = {"sports": 1, "count": count, "lng": "fr", "mode": 4, "getEmpty": "true"}
    for pair in filter(None, os.getenv("ONEX_EXTRA", "").split("&")):  # ex: ONEX_EXTRA="partner=51"
        k, _, v = pair.partition("=")
        params[k] = v
    params.update(extra)
    return params


def lister_championnats(base, proxy, nom):
    """Liste des championnats de football (id LI, noms L / LE). [] si indisponible."""
    try:
        valeur = _get(base, "/service-api/LineFeed/GetChampsZip",
                      {"sport": 1, "lng": "en", "mode": 4}, proxy, nom)
    except Exception as e:
        print(f"[{nom}] liste des championnats impossible : {type(e).__name__}")
        return []
    champs = []
    for c in valeur or []:
        # Certains flux regroupent les championnats par pays dans "SC".
        for sous in (c.get("SC") or [c]):
            if sous.get("LI") is not None:
                champs.append({"LI": sous["LI"], "L": sous.get("L"), "LE": sous.get("LE") or sous.get("L")})
    return champs


def fetch_events(bookmaker, proxy=None, count=COUNT):
    base = ALL_DOMAINS[bookmaker]
    evenements = _get(base, ENDPOINT, _params(count), proxy, bookmaker)
    print(f"[{bookmaker}] API statut {'200' if evenements is not None else 'KO'} (count={count})")
    if evenements is None:
        return base, []
    vus = {e.get("I") for e in evenements if e.get("I") is not None}

    # L'API plafonne a ~50 evenements par appel : on va chercher, championnat
    # par championnat, ceux de la liste prioritaire commune (championnats.py).
    try:
        champs = [c for c in lister_championnats(base, proxy, bookmaker)
                  if priorite(c["LE"], c["L"]) == 0]
        deja = {e.get("LI") for e in evenements}
        ids = [str(c["LI"]) for c in champs if c["LI"] not in deja]
        print(f"[{bookmaker}] {len(champs)} championnats prioritaires, {len(ids)} a charger en plus")
        for i in range(0, len(ids), 8):
            lot = _get(base, ENDPOINT, _params(100, champs=",".join(ids[i:i + 8])), proxy, bookmaker)
            for e in lot or []:
                if e.get("I") not in vus:
                    vus.add(e.get("I"))
                    evenements.append(e)
    except Exception as e:
        print(f"[{bookmaker}] pagination par championnat ignoree : {type(e).__name__}: {e}")
    return base, evenements


def index_evenements(events):
    """{id evenement 1xBet: infos d'identification} pour corriger des noms."""
    out = {}
    for ev in events:
        if ev.get("I") is None or not ev.get("O1") or not ev.get("O2"):
            continue
        out[str(ev["I"])] = {
            "equipe_1": str(ev["O1"]).strip(), "equipe_2": str(ev["O2"]).strip(),
            "equipe_1_en": str(ev["O1E"]).strip() if ev.get("O1E") else None,
            "equipe_2_en": str(ev["O2E"]).strip() if ev.get("O2E") else None,
            "debut": _iso_utc(ev.get("S")),
            "competition": str(ev["L"]).strip() if ev.get("L") else None,
            "competition_en": str(ev["LE"]).strip() if ev.get("LE") else None,
            "competition_id": ev.get("LI"),
        }
    return out


def enrichir_1xbet_sync(matches, proxy=None):
    """Garde les cotes Chromium de 1xBet (marge propre) mais corrige noms,
    heure et championnat via l'API, en reliant par l'id d'evenement de l'URL."""
    import re
    base = DIAG["1xbet"]
    try:
        evenements = _get(base, ENDPOINT, _params(300), proxy, "1xbet") or []
        try:
            champs = [c for c in lister_championnats(base, proxy, "1xbet") if priorite(c["LE"], c["L"]) == 0]
            ids = [str(c["LI"]) for c in champs]
            for i in range(0, len(ids), 8):
                evenements += _get(base, ENDPOINT, _params(100, champs=",".join(ids[i:i + 8])), proxy, "1xbet") or []
        except Exception:
            pass
        idx = index_evenements(evenements)
    except Exception as e:
        print(f"[1xbet] enrichissement API impossible : {type(e).__name__}: {e}")
        return matches
    corriges = 0
    for m in matches:
        r = re.search(r"/(\d+)-[^/]*/?$", (m.get("url") or "").split("?")[0])
        info = idx.get(r.group(1)) if r else None
        if not info:
            continue
        corriges += 1
        for k, v in info.items():
            if v is not None:
                m[k] = v
    print(f"[1xbet] {corriges}/{len(matches)} matchs corriges via l'API "
          f"({len(idx)} evenements connus)")
    return matches


async def enrichir_1xbet(matches, proxy=None):
    return await asyncio.to_thread(enrichir_1xbet_sync, matches, proxy)


def scrape_onex_sync(bookmaker, proxy=None, limit=COUNT):
    if bookmaker not in ALL_DOMAINS:
        raise KeyError(bookmaker)
    base, events = fetch_events(bookmaker, proxy, limit)
    matches = build_matches(bookmaker, events, base, limit)
    print(f"[{bookmaker}] {len(events)} matchs lus, {len(matches)} gardes")
    print(
        f"[{bookmaker}] avec heure: {sum('debut' in m for m in matches)}, "
        f"championnat: {sum('competition' in m for m in matches)}, "
        f"noms anglais: {sum('equipe_1_en' in m for m in matches)} "
        f"(sur {len(matches)})"
    )
    return matches


async def scrape_onex(bookmaker, proxy=None, limit=COUNT):
    """proxy : URL du type http://user:pass@host:port (ou None)."""
    return await asyncio.to_thread(scrape_onex_sync, bookmaker, proxy, limit)


def compare(proxy=None):
    """Affiche, pour chaque bookmaker, le 1X2 du meme match (le plus proche en commun)."""
    rows = {}
    for name in ALL_DOMAINS:
        try:
            base, events = fetch_events(name, proxy, 50)
            rows[name] = build_matches(name, events, base, 50)
        except Exception as e:
            print(f"[{name}] erreur: {type(e).__name__}: {str(e)[:80]}")
            rows[name] = []
    keys = None
    for ms in rows.values():
        ks = {(m["equipe_1"], m["equipe_2"]) for m in ms}
        if ms:
            keys = ks if keys is None else keys & ks
    print("\n=== COMPARAISON (meme match) ===")
    for k in list(keys or [])[:3]:
        print(k)
        for name, ms in rows.items():
            m = next((x for x in ms if (x["equipe_1"], x["equipe_2"]) == k), None)
            if m:
                print(f"  {name:14} {m['1X2']}")
    print("\nNb de matchs :", {n: len(ms) for n, ms in rows.items()})


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "betwinner"
    if name == "compare":
        compare(os.getenv("PROXY_URL"))
        sys.exit()
    res = scrape_onex_sync(name, os.getenv("PROXY_URL"), 20)
    if res:
        import json
        print(json.dumps(res[0], ensure_ascii=False, indent=2)[:1800])
