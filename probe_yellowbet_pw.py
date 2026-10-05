"""
probe_yellowbet_pw.py - ouvre yellowbet.cm dans un vrai Chromium (Playwright)
et note les appels reseau (XHR/fetch/WebSocket) qui apportent les matchs et
les cotes. A lancer dans GitHub Actions (voir probe-yellowbet.yml), car
Termux n'a pas Playwright et Cloudflare bloque les requetes simples (403).

Sortie : yellowbet_pw_result.txt + yellowbet_pw.png (a telecharger dans
les "artifacts" du run).
Ne touche PAS au lien d'affiliation.
"""
import json
import os
import re
import sys
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

BASE = os.getenv("YB_BASE", "https://yellowbet.cm")
START = BASE + "/fr/sportsbook/upcoming"
UA = ("Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36")
LOG = []
IGNORE = ("google", "gstatic", "facebook", "doubleclick", "cloudflareinsights",
          "sentry", "hotjar", "clarity.ms", "onesignal")


def out(*a):
    line = " ".join(str(x) for x in a)
    print(line)
    LOG.append(line)


def proxy_conf():
    try:
        from config import webshare_proxy
        p = webshare_proxy()
        return p or None
    except Exception as e:
        out(f"(proxy Webshare indisponible: {type(e).__name__})")
        return None


appels, sockets = [], []


def on_response(resp):
    try:
        req = resp.request
        if req.resource_type not in ("xhr", "fetch"):
            return
        url = resp.url
        if any(i in url for i in IGNORE):
            return
        ct = resp.headers.get("content-type", "")
        corps = ""
        if "json" in ct or "text" in ct:
            try:
                corps = resp.text()
            except Exception:
                corps = ""
        appels.append((resp.status, req.method, url, ct, len(corps), corps[:260].replace("\n", " ")))
    except Exception:
        pass


def on_ws(ws):
    info = {"url": ws.url, "recus": [], "envoyes": []}
    sockets.append(info)
    ws.on("framereceived", lambda f: len(info["recus"]) < 4 and info["recus"].append(str(f)[:300]))
    ws.on("framesent", lambda f: len(info["envoyes"]) < 4 and info["envoyes"].append(str(f)[:300]))


proxy = proxy_conf()
out(f"=== {START} (proxy: {'oui' if proxy else 'non'}) ===")
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    ctx = b.new_context(user_agent=UA, locale="fr-FR",
                        viewport={"width": 390, "height": 844},
                        is_mobile=True, has_touch=True,
                        **({"proxy": proxy} if proxy else {}))
    pg = ctx.new_page()
    pg.on("response", on_response)
    pg.on("websocket", on_ws)
    try:
        r = pg.goto(START, wait_until="domcontentloaded", timeout=120000)
        out(f"Statut page: {r.status if r else '?'}")
    except Exception as e:
        out(f"goto: {type(e).__name__}: {str(e)[:120]}")
    for _ in range(6):                      # laisse passer un eventuel controle Cloudflare
        pg.wait_for_timeout(5000)
        titre = pg.title()
        if "moment" not in titre.lower() and "cloudflare" not in titre.lower():
            break
    pg.wait_for_timeout(8000)
    for _ in range(4):                      # fait charger la liste des matchs
        pg.mouse.wheel(0, 1500)
        pg.wait_for_timeout(1500)
    out(f"Titre: {pg.title()!r}  URL: {pg.url}")
    texte = pg.inner_text("body")[:600].replace("\n", " | ")
    out(f"Texte visible: {texte}")
    pg.screenshot(path="yellowbet_pw.png", full_page=False)
    b.close()

out(f"\n[1] Appels XHR/fetch ({len(appels)})")
for st, m, u, ct, n, ap in appels[:60]:
    out(f"  {st} {m} {u[:140]}  [{ct[:25]}] {n} octets")
    if "json" in ct and n:
        out(f"       {ap[:200]}")

out(f"\n[2] WebSockets ({len(sockets)})")
for s in sockets:
    out(f"  {s['url'][:140]}")
    for t in s["envoyes"][:3]:
        out(f"     > {t[:200]}")
    for t in s["recus"][:3]:
        out(f"     < {t[:200]}")

hotes = sorted({urlparse(u).netloc for _, _, u, *_ in appels})
out(f"\n[3] Serveurs contactes: {hotes}")
open("yellowbet_pw_result.txt", "w").write("\n".join(LOG))
