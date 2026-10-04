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


def construire_matchs(store, url, limit=100):
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    out = []
    for mid in sorted(store):
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
        if double:
            m["Double_Chance"] = double
        if btts:
            m["BTTS"] = btts
        if totals:
            m["Totals"] = totals
        if handicap:
            m["Handicap"] = handicap
        out.append(m)
    return out[:limit]
