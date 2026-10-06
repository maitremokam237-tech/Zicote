"""
win_api.py - sonde de l'API publique utilisee par le site 1win
(api-gateway.top-parser.com). Pour l'instant : DIAGNOSTIC SEULEMENT.
Elle affiche le statut et la structure de la reponse dans le log, sans
modifier les resultats, afin d'ecrire ensuite la lecture directe.
"""
import json
import os

import requests

BASE = "https://api-gateway.top-parser.com"
PARTENAIRE = os.getenv("WIN1_P", "44ba10e5-7df2-47ab-a44d-dc93803c7a6e")
UA = ("Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36")
# 919 = Premier League, 39437 = Ligue des champions (identifiants des URL 1win)
TOURNOIS_SONDE = ("919", "39437")


def _forme(valeur, profondeur=0):
    """Resume la structure d'un JSON (cles et types), sans les valeurs."""
    if profondeur > 3:
        return "..."
    if isinstance(valeur, dict):
        return {k: _forme(v, profondeur + 1) for k, v in list(valeur.items())[:25]}
    if isinstance(valeur, list):
        return [f"{len(valeur)} elements", _forme(valeur[0], profondeur + 1)] if valeur else []
    return type(valeur).__name__


def sonder(proxy_url=None):
    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
    headers = {"User-Agent": UA, "Accept": "application/json",
               "Origin": "https://1win.com", "Referer": "https://1win.com/"}
    appels = [("tournaments/get", {"tournamentId": t, "l": "fr-CI", "p": PARTENAIRE})
              for t in TOURNOIS_SONDE]
    for chemin, params in appels:
        try:
            r = requests.get(f"{BASE}/{chemin}", params=params, headers=headers,
                             proxies=proxies, timeout=30)
            print(f"[1win-api] {chemin} {params.get('tournamentId') or params.get('sportId')}"
                  f" -> statut {r.status_code}, {len(r.content)} octets")
            if r.status_code == 200:
                data = r.json()
                print(f"[1win-api] structure : {json.dumps(_forme(data), ensure_ascii=False)[:1500]}")
                print(f"[1win-api] extrait : {r.text[:1200]}")
            else:
                print(f"[1win-api] reponse : {r.text[:200]}")
        except Exception as e:
            print(f"[1win-api] {chemin} erreur : {type(e).__name__}: {str(e)[:120]}")
