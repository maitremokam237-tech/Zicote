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
MAX_GARDES = int(os.getenv("ONEX_MAX_MATCHES", "250"))
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


def _get(base, endpoint, params, proxy, nom, extra_headers=None):
    proxies = {"http": proxy, "https": proxy} if proxy else None
    headers = {"User-Agent": UA, "Accept": "application/json",
               "Referer": base + "/fr/line/football"}
    headers.update(extra_headers or {})
    r = requests.get(base + endpoint, params=params, proxies=proxies, timeout=25,
                     headers=headers)
    if r.status_code != 200:
        print(f"[{nom}] API {endpoint.rsplit('/', 1)[-1]} statut {r.status_code} "
              f"(params: {sorted(params)}) corps: {r.text[:150]!r}")
        return None
    return r.json().get("Value") or []


def _params(count, **extra):
    params = {"sports": 1, "count": count, "lng": "fr", "mode": 4, "getEmpty": "true"}
    for pair in filter(None, os.getenv("ONEX_EXTRA", "").split("&")):  # ex: ONEX_EXTRA="partner=51"
        k, _, v = pair.partition("=")
        params[k] = v
    params.update(extra)
    return params


# Identifiants (LI) des grands championnats sur la plateforme 1xBet. Sert quand
# la liste des championnats est refusee par l'API (statut 406). Modifiable via
# ONEX_CHAMPS="id1,id2,..." sans toucher au code.
CHAMPS_CONNUS = [
    ("1706694", "Nations League"),
    ("118587", "Champions League"), ("118593", "Europa League"),
    ("88637", "Premier League"), ("127733", "La Liga"), ("12821", "Ligue 1"),
    ("110163", "Serie A"), ("96463", "Bundesliga"),
]


def lister_championnats(base, proxy, nom):
    """Liste des championnats de football (id LI, noms L / LE). [] si indisponible."""
    try:
        valeur = _get(base, "/service-api/LineFeed/GetChampsZip",
                      {"sport": 1, "lng": "en", "mode": 4}, proxy, nom)
    except Exception as e:
        print(f"[{nom}] liste des championnats impossible : {type(e).__name__}")
        return []
    champs = []
    if not valeur:
        env = [x.strip() for x in os.getenv("ONEX_CHAMPS", "").split(",") if x.strip()]
        connus = [(i, "?") for i in env] if env else CHAMPS_CONNUS
        print(f"[{nom}] liste indisponible : utilisation de {len(connus)} championnats connus")
        return [{"LI": int(i), "L": n, "LE": "Champions League"} for i, n in connus]
    for c in valeur or []:
        # Certains flux regroupent les championnats par pays dans "SC".
        for sous in (c.get("SC") or [c]):
            if sous.get("LI") is not None:
                champs.append({"LI": sous["LI"], "L": sous.get("L"), "LE": sous.get("LE") or sous.get("L")})
    return champs


ENDPOINT_V3 = "/service-api/main-line-feed/v3/games1x2"


def _num(valeur):
    import re
    m = re.search(r"-?\d+(?:\.\d+)?", str(valeur or ""))
    return float(m.group()) if m else None


def convertir_jeu_v3(g):
    """Un match du nouveau format (liga / opponent1 / eventGroups) -> evenement au
    format LineFeed (O1, O2, S, E=[{G,T,C,P}]) que build_matches sait lire."""
    lignes = []
    for bloc in (g.get("eventGroups") or []) + (g.get("centralBlockEventGroups") or []):
        gid = bloc.get("groupId")
        for colonne in bloc.get("events") or []:
            for e in colonne:
                if e.get("cf") is None or e.get("blocked"):
                    continue
                p = e.get("parameter")
                if p is None:
                    prm = (e.get("eventParams") or {}).get("params") or []
                    p = _num(prm[0]) if prm else None
                lignes.append({"G": gid, "T": e.get("type"), "C": e.get("cfView") or e.get("cf"), "P": p})
    o1, o2 = g.get("opponent1") or {}, g.get("opponent2") or {}
    liga = g.get("liga") or {}
    ev = {
        "I": g.get("id"), "S": g.get("startTs"),
        "O1": o1.get("fullName"), "O2": o2.get("fullName"),
        "O1E": o1.get("fullNameEng"), "O2E": o2.get("fullNameEng"),
        "L": liga.get("name"), "LE": liga.get("nameEng"), "LI": liga.get("id"),
        "E": lignes,
    }
    for cle in ("constId", "mainConstId", "num", "mainGameId"):
        if g.get(cle) is not None:
            ev[cle] = g[cle]
    return ev


# En-tetes que le site envoie depuis le navigateur. Ajustables sans toucher au
# code via ONEX_HEADERS='{"nom": "valeur"}' (copies depuis "Copy as cURL").
EN_TETES_NAVIGATEUR = {
    "Accept": "*/*", "Accept-Language": "fr-FR,fr;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
    "x-app-n": "__BETTING_APP__", "x-svc-source": "__BETTING_APP__",
}


def _evenements_championnat_v3(base, proxy, nom, liga_id, etat):
    """Matchs d'UN championnat par l'API officielle du site (selectedMs=2.1.<id>)."""
    import json as _json
    commun = {"cfView": 3, "countryFirst": "true", "grMode": 4, "lng": "fr",
              "selectedMs": f"2.1.{liga_id}"}
    avec_ref = {**commun, "count": 50, "gr": 2364, "ref": 192, "fcountry": 84}
    perso = {}
    try:
        perso = _json.loads(os.getenv("ONEX_HEADERS", "") or "{}")
    except ValueError:
        pass
    variantes = [
        ({**commun, "count": 50}, None),
        (avec_ref, None),
        ({**commun, "count": 50}, {**EN_TETES_NAVIGATEUR, **perso}),
        (avec_ref, {**EN_TETES_NAVIGATEUR, **perso}),
    ]
    essais = [etat["v"]] if etat.get("v") is not None else range(len(variantes))
    for v in essais:
        params, entetes = variantes[v]
        try:
            res = _get(base, ENDPOINT_V3, params, proxy, nom, entetes)
        except Exception as e:
            print(f"[{nom}] championnat {liga_id} variante {v} : {type(e).__name__}")
            res = None
        if res is not None:
            etat["v"] = v
            return [convertir_jeu_v3(g) for g in res if isinstance(g, dict)]
    return []


def _evenements_championnats(base, proxy, nom, ids):
    etat = {}
    sortie = []
    for liga_id in ids:
        sortie += _evenements_championnat_v3(base, proxy, nom, liga_id, etat)
        if etat.get("v") is None:
            # Aucune variante n'est acceptee : inutile d'insister sur les autres championnats.
            print(f"[{nom}] API par championnat refusee, abandon (voir messages ci-dessus)")
            break
    if etat.get("v") is not None:
        print(f"[{nom}] API par championnat : variante {etat['v']} retenue, {len(sortie)} matchs")
    return sortie


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
        if not os.getenv("ONEX_HTTP_CHAMPS"):
            return base, evenements   # refusee sans l'en-tete x-hd : voir onex_navigateur.py
        champs = [c for c in lister_championnats(base, proxy, bookmaker)
                  if priorite(c["LE"], c["L"]) == 0]
        deja = {e.get("LI") for e in evenements}
        ids = [str(c["LI"]) for c in champs if c["LI"] not in deja]
        # Championnats prioritaires vus dans les evenements de base : on les complete aussi
        # (la requete de base est plafonnee a ~50 matchs).
        for e in list(evenements):
            if e.get("LI") is not None and str(e["LI"]) not in ids \
                    and priorite(e.get("LE"), e.get("L")) == 0:
                ids.append(str(e["LI"]))
        print(f"[{bookmaker}] {len(champs)} championnats prioritaires, {len(ids)} a charger en plus")
        nouveaux = 0
        for e in _evenements_championnats(base, proxy, bookmaker, ids):
            if e.get("I") not in vus:
                vus.add(e.get("I"))
                evenements.append(e)
                nouveaux += 1
        print(f"[{bookmaker}] {nouveaux} evenements ajoutes par championnat")
    except Exception as e:
        print(f"[{bookmaker}] pagination par championnat ignoree : {type(e).__name__}: {e}")
    return base, evenements


def index_evenements(events):
    """{identifiant: infos} pour corriger des noms. On indexe TOUS les champs
    numeriques d'un evenement (l'id de l'URL du site n'est pas forcement 'I')."""
    out = {}
    for ev in events:
        if not ev.get("O1") or not ev.get("O2"):
            continue
        info = {
            "equipe_1": str(ev["O1"]).strip(), "equipe_2": str(ev["O2"]).strip(),
            "equipe_1_en": str(ev["O1E"]).strip() if ev.get("O1E") else None,
            "equipe_2_en": str(ev["O2E"]).strip() if ev.get("O2E") else None,
            "debut": _iso_utc(ev.get("S")),
            "competition": str(ev["L"]).strip() if ev.get("L") else None,
            "competition_en": str(ev["LE"]).strip() if ev.get("LE") else None,
            "competition_id": ev.get("LI"),
        }
        for cle, val in ev.items():
            if isinstance(val, int) and not isinstance(val, bool) and val >= 1_000_000 \
                    and cle not in ("S", "LI"):
                out.setdefault(str(val), info)
    return out


def _mots(texte):
    import re
    import unicodedata
    t = unicodedata.normalize("NFKD", str(texte or "")).lower()
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", t))


def trouver_par_nom(url, evenements):
    """Repli : relie un match 1xBet a l'API par le slug de l'URL
    (ex. 'galatasaray-barcelona') et les noms anglais O1E/O2E."""
    import difflib
    import re
    r = re.search(r"/(\d+)-[^/]*/(\d+)-([^/?]+)/?$", url or "")
    if not r:
        return None
    slug = _mots(r.group(3).replace("-", " "))
    meilleur, score = None, 0.0
    for ev in evenements:
        o1 = ev.get("O1E") or ev.get("O1") or ""
        o2 = ev.get("O2E") or ev.get("O2") or ""
        cible = _mots(f"{o1} {o2}")
        sc = difflib.SequenceMatcher(None, slug, cible).ratio()
        if sc > score:
            meilleur, score = ev, sc
    if meilleur is not None and score >= 0.8:
        return index_evenements([meilleur]).get(next(
            (str(v) for k, v in meilleur.items() if isinstance(v, int) and v >= 1_000_000
             and k not in ("S", "LI")), ""))
    return None


def enrichir_1xbet_sync(matches, proxy=None):
    """Garde les cotes Chromium de 1xBet (marge propre) mais corrige noms,
    heure et championnat via l'API, en reliant par l'id d'evenement de l'URL."""
    import re
    base = DIAG["1xbet"]
    try:
        evenements = _get(base, ENDPOINT, _params(300), proxy, "1xbet") or []
        try:
            if not os.getenv("ONEX_HTTP_CHAMPS"):
                raise RuntimeError("API par championnat reservee au navigateur")
            champs = [c for c in lister_championnats(base, proxy, "1xbet") if priorite(c["LE"], c["L"]) == 0]
            ids = [str(c["LI"]) for c in champs]
            evenements += _evenements_championnats(base, proxy, "1xbet", ids)
        except Exception:
            pass
        idx = index_evenements(evenements)
        brut = evenements
    except Exception as e:
        print(f"[1xbet] enrichissement API impossible : {type(e).__name__}: {e}")
        return matches
    corriges = par_nom = 0
    for m in matches:
        r = re.search(r"/(\d+)-[^/]*/?$", (m.get("url") or "").split("?")[0])
        info = idx.get(r.group(1)) if r else None
        if not info:
            info = trouver_par_nom(m.get("url"), brut)
            if info:
                par_nom += 1
        if not info:
            continue
        corriges += 1
        for k, v in info.items():
            if v is not None:
                m[k] = v
    if not corriges:
        ex = [m.get("url", "")[-50:] for m in matches[:2]]
        print(f"[1xbet] diagnostic : urls {ex} ; ids API {list(idx)[:3]}")
        if brut:
            print(f"[1xbet] champs d'un evenement API : "
                  f"{ {k: v for k, v in brut[0].items() if not isinstance(v, (list, dict))} }")
    print(f"[1xbet] {corriges}/{len(matches)} matchs corriges via l'API "
          f"(dont {par_nom} par le nom) "
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
