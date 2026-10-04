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
COUNT = int(os.getenv("ONEX_COUNT", "300"))
COUNT_REPLI = 100  # valeur utilisee si l'API refuse la grosse demande

# Championnats gardes en priorite (les memes que BetPawa), pour que les
# bookmakers listent les memes matchs meme quand le lot est tronque.
PRIORITY_KEYWORDS = (
    "champions league", "ligue des champions", "europa league",
    "ligue europa", "conference league", "premier league", "la liga",
    "laliga", "liga espagnole", "ligue 1", "serie a", "bundesliga",
    "league cup", "coupe de la ligue",
)


def _priority(match):
    noms = " ".join(
        str(match.get(k, "")) for k in ("competition_en", "competition")
    ).lower()
    return 0 if any(k in noms for k in PRIORITY_KEYWORDS) else 1
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
        out.append(((_priority(match), ev.get("S") or 0), match))
    # championnats prioritaires d'abord, puis par date de debut
    out.sort(key=lambda x: x[0])
    return [m for _, m in out[:limit]]


def _get_events(bookmaker, base, proxy, count):
    params = {"sports": 1, "count": count, "lng": "fr", "mode": 4, "getEmpty": "true"}
    for pair in filter(None, os.getenv("ONEX_EXTRA", "").split("&")):  # ex: ONEX_EXTRA="partner=51"
        k, _, v = pair.partition("=")
        params[k] = v
    proxies = {"http": proxy, "https": proxy} if proxy else None
    r = requests.get(base + ENDPOINT, params=params, proxies=proxies, timeout=60,
                     headers={"User-Agent": UA, "Accept": "application/json",
                              "Referer": base + "/fr/line/football"})
    print(f"[{bookmaker}] API statut {r.status_code} (count={count})")
    if r.status_code != 200:
        return []
    return r.json().get("Value") or []


def fetch_events(bookmaker, proxy=None, count=COUNT):
    base = ALL_DOMAINS[bookmaker]
    events = []
    try:
        events = _get_events(bookmaker, base, proxy, count)
    except Exception as e:
        print(f"[{bookmaker}] erreur count={count}: {type(e).__name__}: {str(e)[:80]}")
    # Si l'API refuse ou ne renvoie rien pour un gros lot, on retente en petit.
    if not events and count > COUNT_REPLI:
        events = _get_events(bookmaker, base, proxy, COUNT_REPLI)
    print(f"[{bookmaker}] {len(events)} evenements recus")
    return base, events


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

