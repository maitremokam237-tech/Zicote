"""Remplit logos_clubs.json avec les logos de clubs de l'API Sportmonks.

Usage (dans le workflow, avant comparateur.py) :
    SPORTMONKS_TOKEN=... python maj_logos_clubs.py

- Lit les noms d'equipes dans les JSON des bookmakers.
- Ignore les equipes qui ont deja un logo (drapeau ou entree de logos_clubs.json).
- Cherche chaque club par nom (teams/search), n'accepte qu'une correspondance
  sure (nom identique ou tres proche), telecharge l'image dans docs/logos/clubs/.
- Les clubs non trouves sont notes dans logos_clubs_introuvables.json et ne sont
  re-essayes qu'apres RETRY_JOURS jours (economise le quota de l'API).

Variables : SPORTMONKS_TOKEN (obligatoire), MAX_LOGOS_PAR_RUN (defaut 40),
LOGOS_TELECHARGER (1 = copie locale, defaut ; 0 = garde l'URL Sportmonks),
RETRY_JOURS (defaut 30).
"""
import datetime
import difflib
import glob
import json
import os
import time
from pathlib import Path
from urllib.parse import quote

import requests

from logos import CLUBS_PATH, logo_equipe, normaliser

API = "https://api.sportmonks.com/v3/football/teams/search/"
INTROUVABLES = Path("logos_clubs_introuvables.json")
DOSSIER_IMG = Path("docs/logos/clubs")
TOKEN = os.getenv("SPORTMONKS_TOKEN", "").strip()
MAX_PAR_RUN = int(os.getenv("MAX_LOGOS_PAR_RUN", "40"))
TELECHARGER = os.getenv("LOGOS_TELECHARGER", "1") != "0"
RETRY_JOURS = int(os.getenv("RETRY_JOURS", "30"))


def _lire(chemin):
    try:
        return json.loads(Path(chemin).read_text(encoding="utf-8"))
    except Exception:
        return {}


def equipes_a_traiter():
    """{nom_normalise: nom_a_chercher} des equipes sans logo."""
    trouvees = {}
    for fichier in glob.glob("*.json"):
        if fichier.startswith(("logos_", "maj_")):
            continue
        try:
            data = json.loads(Path(fichier).read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, list):
            continue
        for m in data:
            if not isinstance(m, dict):
                continue
            for i in (1, 2):
                en, fr = m.get(f"equipe_{i}_en"), m.get(f"equipe_{i}")
                if not (en or fr) or logo_equipe(en, fr):
                    continue
                nom = (en or fr).strip()
                trouvees.setdefault(normaliser(nom), nom)
    return trouvees


def choisir(nom, resultats):
    """Meilleure correspondance sure parmi les resultats, ou None."""
    cible = normaliser(nom)
    candidats = [r for r in resultats
                 if isinstance(r, dict) and r.get("image_path")
                 and r.get("gender", "male") == "male" and not r.get("placeholder")]
    for r in candidats:
        if normaliser(r.get("name")) == cible:
            return r
    meilleur, score = None, 0.0
    for r in candidats:
        s = difflib.SequenceMatcher(None, cible, normaliser(r.get("name"))).ratio()
        if s > score:
            meilleur, score = r, s
    return meilleur if score >= 0.9 else None


def telecharger(equipe):
    url = equipe["image_path"]
    if not TELECHARGER:
        return url
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        ext = Path(url.split("?")[0]).suffix or ".png"
        DOSSIER_IMG.mkdir(parents=True, exist_ok=True)
        (DOSSIER_IMG / f"{equipe['id']}{ext}").write_bytes(r.content)
        return f"/logos/clubs/{equipe['id']}{ext}"
    except Exception as e:
        print(f"[logos] telechargement impossible ({e}), URL distante conservee")
        return url


def main():
    # Les deux fichiers doivent toujours exister (le workflow les ajoute avec git add).
    for chemin in (CLUBS_PATH, INTROUVABLES):
        if not chemin.exists():
            chemin.write_text("{}", encoding="utf-8")
    if not TOKEN:
        print("[logos] SPORTMONKS_TOKEN absent : etape ignoree.")
        return
    clubs = _lire(CLUBS_PATH)
    introuvables = _lire(INTROUVABLES)
    aujourdhui = datetime.date.today()
    limite = aujourdhui - datetime.timedelta(days=RETRY_JOURS)

    a_faire = []
    for cle, nom in equipes_a_traiter().items():
        vu = introuvables.get(cle)
        if vu and datetime.date.fromisoformat(vu) > limite:
            continue
        a_faire.append((cle, nom))
    print(f"[logos] {len(a_faire)} club(s) a chercher (max {MAX_PAR_RUN} par run)")

    ajoutes = 0
    for cle, nom in a_faire[:MAX_PAR_RUN]:
        try:
            r = requests.get(API + quote(nom), params={"api_token": TOKEN}, timeout=20)
        except requests.RequestException as e:
            print(f"[logos] reseau : {e}")
            break
        if r.status_code in (401, 403):
            print(f"[logos] acces refuse ({r.status_code}) : verifie le token et ton plan Sportmonks.")
            break
        if r.status_code == 429:
            print("[logos] limite de requetes atteinte : on reprendra au prochain run.")
            break
        if r.status_code != 200:
            print(f"[logos] {nom} : statut {r.status_code}")
            continue
        equipe = choisir(nom, r.json().get("data") or [])
        if equipe:
            clubs[cle] = telecharger(equipe)
            ajoutes += 1
            print(f"[logos] OK : {nom} -> {equipe.get('name')}")
        else:
            introuvables[cle] = aujourdhui.isoformat()
            print(f"[logos] introuvable : {nom}")
        time.sleep(0.4)

    CLUBS_PATH.write_text(json.dumps(clubs, ensure_ascii=False, indent=1, sort_keys=True),
                          encoding="utf-8")
    INTROUVABLES.write_text(json.dumps(introuvables, ensure_ascii=False, indent=1,
                                       sort_keys=True), encoding="utf-8")
    print(f"[logos] {ajoutes} logo(s) ajoute(s), {len(clubs)} au total")


if __name__ == "__main__":
    main()
