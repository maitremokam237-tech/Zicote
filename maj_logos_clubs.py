"""Remplit logos_clubs.json avec les logos de clubs depuis TheSportsDB.

TheSportsDB : base communautaire gratuite, cle publique de test "3" (limitee a
environ 30 requetes par minute). Aucune inscription necessaire.
Usage (workflow, avant comparateur.py) :  python maj_logos_clubs.py

- Lit les noms anglais d'equipes dans les JSON des bookmakers.
- Ignore les equipes qui ont deja un logo (drapeau ou entree de logos_clubs.json).
- Cherche chaque club (searchteams.php), compare avec le nom officiel ET les noms
  alternatifs, n'accepte qu'une correspondance sure, telecharge l'image (version
  reduite si disponible) dans docs/logos/clubs/.
- Les clubs non trouves vont dans logos_clubs_introuvables.json (re-essai apres
  RETRY_JOURS jours).

Variables : THESPORTSDB_KEY (defaut "3"), MAX_LOGOS_PAR_RUN (defaut 60),
LOGOS_TELECHARGER (1 = copie locale, defaut), RETRY_JOURS (defaut 30).
"""
import datetime
import difflib
import glob
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import quote

import requests

from logos import CLUBS_PATH, logo_equipe, normaliser

CLE = os.getenv("THESPORTSDB_KEY", "3").strip() or "3"
API = f"https://www.thesportsdb.com/api/v1/json/{CLE}/searchteams.php"
INTROUVABLES = Path("logos_clubs_introuvables.json")
DOSSIER_IMG = Path("docs/logos/clubs")
LIBELLES = {"home", "away", "draw", "x", "domicile", "exterieur", "a domicile", "a l exterieur"}
MAX_PAR_RUN = int(os.getenv("MAX_LOGOS_PAR_RUN", "60"))
TELECHARGER = os.getenv("LOGOS_TELECHARGER", "1") != "0"
RETRY_JOURS = int(os.getenv("RETRY_JOURS", "30"))
PAUSE = 2.2   # secondes entre deux requetes (limite gratuite ~30/min)


def _lire(chemin):
    try:
        return json.loads(Path(chemin).read_text(encoding="utf-8"))
    except Exception:
        return {}


# Equipes de jeunes, feminines ou reserves : rarement dans TheSportsDB, on ne gaspille pas le quota.
HORS_CIBLE = re.compile(r"\bu ?(1[5-9]|2[0-3])\b|\bwomen\b|\(w\)|\bw$|\bii$|\biii$|\bres$|reserves?", re.I)


def equipes_a_traiter():
    """{nom_normalise: nom_a_chercher} des equipes sans logo, les plus presentes d'abord.

    Une equipe listee par beaucoup de bookmakers est celle d'un match important
    (donc affiche sur le site) : on la traite avant les petits championnats."""
    trouvees, compte = {}, {}
    for fichier in sorted(glob.glob("*.json")):
        if fichier.startswith(("logos_", "maj_")):
            continue
        try:
            data = json.loads(Path(fichier).read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, list):
            continue
        vus_ici = set()
        for m in data:
            if not isinstance(m, dict):
                continue
            for i in (1, 2):
                # Uniquement les noms anglais fournis par les API des bookmakers
                # (les noms issus des liens de page sont coupes au hasard).
                en, fr = m.get(f"equipe_{i}_en"), m.get(f"equipe_{i}")
                if not en or logo_equipe(en, fr):
                    continue
                nom = en.strip()
                cle = normaliser(nom)
                if cle in LIBELLES or len(cle) < 3 or HORS_CIBLE.search(nom):
                    continue
                trouvees.setdefault(cle, nom)
                if cle not in vus_ici:
                    vus_ici.add(cle)
                    compte[cle] = compte.get(cle, 0) + 1
    ordre = sorted(trouvees, key=lambda c: (-compte[c], c))
    return {c: trouvees[c] for c in ordre}


def _noms_equipe(e):
    """Nom officiel + noms alternatifs d'une equipe TheSportsDB (normalises)."""
    noms = {normaliser(e.get("strTeam"))}
    for alt in re.split(r"[,;/]", e.get("strTeamAlternate") or ""):
        noms.add(normaliser(alt))
    noms.discard("")
    return noms


def _sans_prefixe(n):
    """'fc bayern munich' -> 'bayern munich' (retire fc/cf/afc/sc... en tete et en fin)."""
    return re.sub(r"^(fc|cf|afc|sc|ac|as|ssc|rc|us|sv|vfb|vfl|1 fc)\s+|\s+(fc|cf|afc|sc)$", "", n).strip()


def choisir(nom, equipes, seuil=0.88):
    """Meilleure correspondance sure parmi les resultats, ou None."""
    cible = normaliser(nom)
    cible2 = _sans_prefixe(cible)
    foot = [e for e in equipes
            if isinstance(e, dict) and e.get("strBadge")
            and (e.get("strSport") or "Soccer") == "Soccer"]
    for e in foot:
        noms = _noms_equipe(e)
        if cible in noms or cible2 in {_sans_prefixe(n) for n in noms}:
            return e
    meilleur, score = None, 0.0
    for e in foot:
        for n in _noms_equipe(e):
            s = difflib.SequenceMatcher(None, cible2, _sans_prefixe(n)).ratio()
            if s > score:
                meilleur, score = e, s
    return meilleur if score >= seuil else None


def telecharger(equipe):
    url = equipe["strBadge"]
    if not TELECHARGER:
        return url
    try:
        # Version reduite si le service la propose (pages plus legeres), sinon l'originale.
        r = requests.get(url + "/small", timeout=20)
        if r.status_code != 200 or not r.content:
            r = requests.get(url, timeout=20)
        r.raise_for_status()
        ext = Path(url.split("?")[0]).suffix or ".png"
        DOSSIER_IMG.mkdir(parents=True, exist_ok=True)
        (DOSSIER_IMG / f"{equipe['idTeam']}{ext}").write_bytes(r.content)
        return f"/logos/clubs/{equipe['idTeam']}{ext}"
    except Exception as e:
        print(f"[logos] telechargement impossible ({e}), URL distante conservee")
        return url


def main():
    # Les deux fichiers doivent toujours exister (le workflow les ajoute avec git add).
    for chemin in (CLUBS_PATH, INTROUVABLES):
        if not chemin.exists():
            chemin.write_text("{}", encoding="utf-8")

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

    ajoutes, rates = 0, []
    for cle, nom in a_faire[:MAX_PAR_RUN]:
        try:
            r = requests.get(API, params={"t": nom}, timeout=20)
        except requests.RequestException as e:
            print(f"[logos] reseau : {e}")
            break
        if r.status_code == 429:
            print("[logos] limite de requetes atteinte : on reprendra au prochain run.")
            break
        if r.status_code != 200:
            print(f"[logos] {nom} : statut {r.status_code}")
            time.sleep(PAUSE)
            continue
        try:
            equipes = r.json().get("teams") or []
        except ValueError:
            print(f"[logos] {nom} : reponse non JSON (limite atteinte ?)")
            break
        equipe = choisir(nom, equipes)
        if not equipe:
            variante = re.sub(r"\s+", " ", re.sub(r"[-.]", " ", nom)).strip()
            variante = re.sub(r"^(club|fc|cf|ca|cd|sc|ac|as|esporte clube|associacao atletica)\s+", "",
                              variante, flags=re.I)
            if variante and variante.lower() != nom.lower():
                time.sleep(PAUSE)
                try:
                    r2 = requests.get(API, params={"t": variante}, timeout=20)
                    if r2.status_code == 200:
                        equipe = choisir(nom, r2.json().get("teams") or [])
                except (requests.RequestException, ValueError):
                    pass
        if equipe:
            clubs[cle] = telecharger(equipe)
            ajoutes += 1
            print(f"[logos] OK : {nom} -> {equipe.get('strTeam')}")
        else:
            rates.append(cle)
            print(f"[logos] introuvable : {nom}")
        time.sleep(PAUSE)

    # Rien n'a marche : probablement un probleme d'acces, pas des clubs inexistants.
    if ajoutes == 0 and len(rates) >= 5:
        print("[logos] AUCUN resultat : acces API ou limite probable ; clubs non mis de cote.")
    else:
        for cle in rates:
            introuvables[cle] = aujourdhui.isoformat()

    CLUBS_PATH.write_text(json.dumps(clubs, ensure_ascii=False, indent=1, sort_keys=True),
                          encoding="utf-8")
    INTROUVABLES.write_text(json.dumps(introuvables, ensure_ascii=False, indent=1,
                                       sort_keys=True), encoding="utf-8")
    print(f"[logos] {ajoutes} logo(s) ajoute(s), {len(clubs)} au total")


if __name__ == "__main__":
    main()

