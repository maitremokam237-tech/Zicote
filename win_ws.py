"""
win_ws.py - lecture des cotes 1win a partir des trames WebSocket (socket.io v4)
recues par Chromium. Aucune requete reseau ici : seulement du parsing.

Usage dans scraper.py (Playwright) :
    store = {}
    page.on("websocket", lambda ws: brancher_websocket(ws, store))
    ... naviguer / defiler ...
    matchs = construire_matchs(store, url, limit)
"""
import datetime
import json

from championnats import priorite

# Groupes de marches 1win (champ "id" de oddsGroups)
G_1X2 = "6257"
G_BTTS = "6280"
G_DOUBLE = "6283"
G_HANDICAP = "6344"
G_TOTAL = "6379"


def _fmt_line(v):
    """'2.0' -> '2', '2.5' -> '2.5', '-1.0' -> '-1'."""
    f = float(v)
    return str(int(f)) if f == int(f) else str(f)


def _signed(v):
    s = _fmt_line(v)
    return s if s.startswith("-") or s == "0" else "+" + s


def collecter_frame(payload, store):
    """Range un 'match-odds-snapshot' dans store[matchId]. Ignore le reste."""
    if isinstance(payload, dict):          # certaines versions donnent {"payload": ...}
        payload = payload.get("payload")
    if isinstance(payload, (bytes, bytearray)):
        try:
            payload = payload.decode("utf-8", "ignore")
        except Exception:
            return
    if not isinstance(payload, str) or not payload.startswith("42"):
        return
    try:
        arr = json.loads(payload[2:])
    except Exception:
        return
    if not (isinstance(arr, list) and len(arr) >= 2 and arr[0] == "u"):
        return
    msg = arr[1]
    if not isinstance(msg, dict) or msg.get("messageType") != "match-odds-snapshot":
        return
    data = msg.get("data") or {}
    if data.get("matchId") is not None:
        store[data["matchId"]] = data


def collecter_reponse_api(corps, meta):
    """Range dans meta[matchId] les infos d'une reponse JSON de l'API liste des
    matchs de 1win ({"result": {"items": [{id, startAt, tournament, ...}]}})."""
    if not isinstance(corps, dict):
        return 0
    items = (corps.get("result") or {}).get("items")
    if not isinstance(items, list):
        return 0
    n = 0
    for it in items:
        if not isinstance(it, dict) or it.get("id") is None:
            continue
        if not (it.get("homeTeam") and it.get("awayTeam") and it.get("startAt")):
            continue
        tournoi = it.get("tournament") or {}
        meta[str(it["id"])] = {
            "debut": _debut_iso(it.get("startAt")),
            "competition": str(tournoi.get("slug") or "").replace("-", " ").strip() or None,
            "competition_id": it.get("tournamentId"),
            "equipe_1": (it["homeTeam"] or {}).get("name"),
            "equipe_2": (it["awayTeam"] or {}).get("name"),
        }
        n += 1
    return n


def brancher_websocket(ws, store):
    """A appeler depuis page.on('websocket', ...)."""
    if "push-server" not in (ws.url or ""):
        return
    ws.on("framereceived", lambda p: collecter_frame(p, store))


def parser_snapshot(data):
    """Un snapshot -> (equipe_1, equipe_2, 1X2, double, btts, totals, handicap)."""
    equipes, x12, double, btts, totals, handicap = {}, {}, {}, {}, {}, {}
    for g in data.get("oddsGroups") or []:
        gid = str(g.get("id"))
        for o in g.get("oddsList") or []:
            cf, out = o.get("cf"), o.get("outcome")
            if cf is None or o.get("status") not in (None, 1):
                continue
            cf = str(cf)
            v1 = (o.get("vars") or {}).get("v1")
            if gid == G_1X2:
                key = {"1": "V1", "x": "X", "2": "V2"}.get(out)
                if key:
                    x12[key] = cf
                if out in ("1", "2"):
                    equipes[out] = (o.get("name") or "").strip()
            elif gid == G_DOUBLE:
                key = {"1x": "1X", "12": "12", "x2": "2X"}.get(out)
                if key:
                    double[key] = cf
            elif gid == G_BTTS:
                key = {"yes": "Oui", "no": "Non"}.get(out)
                if key:
                    btts[key] = cf
            elif gid == G_TOTAL and v1 is not None:
                key = {"over": "Plus de", "under": "Moins de"}.get(out)
                if key:
                    totals.setdefault(_fmt_line(v1), {})[key] = cf
            elif gid == G_HANDICAP and v1 is not None and out in ("1", "2"):
                handicap[f"{out} ({_signed(v1)})"] = cf
    totals = {k: v for k, v in totals.items() if len(v) == 2}
    return equipes.get("1"), equipes.get("2"), x12, double, btts, totals, handicap


CLES_DEBUT = ("startTime", "startDate", "matchStartTime", "startAt",
              "start_time", "kickoff", "date", "time")
CLES_CHAMPIONNAT = ("tournamentName", "leagueName", "competitionName",
                    "tournament", "league", "competition", "categoryName")


def _scalaire(valeur):
    if isinstance(valeur, dict):
        valeur = valeur.get("name") or valeur.get("title")
    return valeur if isinstance(valeur, (str, int, float)) and valeur != "" else None


def _chercher(data, cles):
    """Premiere valeur trouvee parmi `cles`, au premier niveau du snapshot
    ou dans un sous-objet (match / event / tournament...)."""
    for niveau in [data] + [v for v in data.values() if isinstance(v, dict)]:
        for cle in cles:
            valeur = _scalaire(niveau.get(cle))
            if valeur is not None:
                return valeur
    return None


def _debut_iso(valeur):
    """Nombre (secondes ou millisecondes) ou texte ISO -> ISO UTC, sinon None."""
    if valeur is None:
        return None
    try:
        nombre = float(valeur)
        if nombre > 1e11:          # millisecondes
            nombre /= 1000
        return datetime.datetime.fromtimestamp(
            nombre, datetime.timezone.utc
        ).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        pass
    texte = str(valeur).replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(texte)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc).isoformat()


def construire_matchs(store, url, limit=100, meta=None):
    meta = meta or {}
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    out = []
    # Championnats prioritaires d'abord (liste commune a tous les bookmakers).
    def _ordre(mid):
        info = meta.get(str(mid)) or {}
        return (priorite(info.get("competition") or _chercher(store[mid], CLES_CHAMPIONNAT)),
                info.get("debut") or "", str(mid))

    for mid in sorted(store, key=_ordre):
        e1, e2, x12, double, btts, totals, handicap = parser_snapshot(store[mid])
        if not e1 or not e2 or len(x12) != 3:
            continue
        t25 = totals.get("2.5", {})
        m = {
            "bookmaker": "1win",
            "equipe_1": e1,
            "equipe_2": e2,
            "1X2": x12,
            "Total_2.5": {"Plus de": t25.get("Plus de"), "Moins de": t25.get("Moins de")},
            "url": url,
            "derniere_maj": now,
            "statut": "ok",
        }
        debut = _debut_iso(_chercher(store[mid], CLES_DEBUT))
        if debut:
            m["debut"] = debut
        championnat = _chercher(store[mid], CLES_CHAMPIONNAT)
        if championnat:
            m["competition"] = str(championnat).strip()
        info = meta.get(str(mid))
        if info:
            # L'API liste des matchs (heure exacte, championnat) fait foi.
            if info.get("debut"):
                m["debut"] = info["debut"]
            if info.get("competition"):
                m["competition"] = info["competition"]
            if info.get("competition_id") is not None:
                m["competition_id_1win"] = info["competition_id"]
        if double:
            m["Double_Chance"] = double
        if btts:
            m["BTTS"] = btts
        if totals:
            m["Totals"] = totals
        if handicap:
            m["Handicap"] = handicap
        out.append(m)
    if store:
        exemple = store[next(iter(store))]
        print(
            f"[1win] avec heure: {sum('debut' in m for m in out)}, "
            f"championnat: {sum('competition' in m for m in out)} "
            f"(sur {len(out)}) ; champs d'un snapshot: {sorted(exemple.keys())}"
        )
    return out[:limit]
