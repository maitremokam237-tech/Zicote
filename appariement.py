"""
appariement.py - regroupe les matchs des differents bookmakers.

Probleme corrige : un meme match etait ecrit "Roumanie - Suede" chez un
bookmaker et "Romania - Sweden" chez un autre, donc jamais rapproche (63 matchs
sur 114 n'avaient qu'un seul bookmaker). Les regles :

  1. Les faux matchs ("a domicile - a l'exterieur", "Home - Away",
     "Domicile (Paris speciaux)"...) sont elimines.
  2. Deux matchs ne sont rapproches que s'ils sont de la MEME categorie
     (senior / U19 / U21... / femmes).
  3. Si les deux bookmakers donnent l'heure du coup d'envoi ("debut"), elle doit
     etre la meme (a 30 min pres). Meme heure + equipes proches = meme match.
     Sans heure, on exige des noms nettement plus proches.
  4. Les noms de pays sont traduits (Roumanie = Romania) et on utilise aussi les
     noms anglais fournis par l'API quand ils existent (equipe_1_en).
  5. Le championnat ("competition") sert d'indice supplementaire.
  6. Un bookmaker ne peut jamais ecraser un de ses propres matchs dans un groupe.
  7. Si un bookmaker ecrit le match a l'envers (Lituanie - Azerbaidjan), ses cotes
     sont remises dans le bon sens (V1 <-> V2, 1X <-> 2X, handicaps, score exact).
"""
import copy
import datetime
import re
import unicodedata
from difflib import SequenceMatcher


# ============================================================
# NORMALISATION
# ============================================================

def normalize(value):
    value = unicodedata.normalize("NFKD", str(value or "")).lower()
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


# ============================================================
# TRADUCTION DES NOMS DE PAYS  (francais -> anglais, normalises)
# ============================================================

PAYS_FR_EN = {
    # Europe
    "allemagne": "germany", "angleterre": "england", "ecosse": "scotland",
    "pays de galles": "wales", "irlande du nord": "northern ireland",
    "irlande": "ireland", "espagne": "spain", "italie": "italy",
    "belgique": "belgium", "pays bas": "netherlands", "hollande": "netherlands",
    "suisse": "switzerland", "autriche": "austria", "pologne": "poland",
    "hongrie": "hungary", "grece": "greece", "danemark": "denmark",
    "suede": "sweden", "norvege": "norway", "finlande": "finland",
    "islande": "iceland", "chypre": "cyprus", "lettonie": "latvia",
    "lituanie": "lithuania", "estonie": "estonia", "georgie": "georgia",
    "armenie": "armenia", "azerbaidjan": "azerbaijan",
    "bielorussie": "belarus", "moldavie": "moldova", "slovaquie": "slovakia",
    "slovenie": "slovenia", "croatie": "croatia", "serbie": "serbia",
    "bulgarie": "bulgaria", "roumanie": "romania", "albanie": "albania",
    "russie": "russia", "turquie": "turkey", "turkiye": "turkey",
    "republique tcheque": "czech republic", "tchequie": "czech republic",
    "czechia": "czech republic", "macedoine du nord": "north macedonia",
    "bosnie herzegovine": "bosnia and herzegovina", "bosnie": "bosnia and herzegovina",
    "bosnia herzegovina": "bosnia and herzegovina",
    "saint marin": "san marino", "iles feroe": "faroe islands",
    "iles faroe": "faroe islands", "malte": "malta", "andorre": "andorra",
    "luxembourg": "luxembourg", "liechtenstein": "liechtenstein",
    "gibraltar": "gibraltar", "kosovo": "kosovo", "monaco": "monaco",
    # Afrique
    "egypte": "egypt", "maroc": "morocco", "algerie": "algeria",
    "tunisie": "tunisia", "cameroun": "cameroon", "guinee": "guinea",
    "guinee equatoriale": "equatorial guinea", "guinee bissau": "guinea bissau",
    "afrique du sud": "south africa", "rd congo": "dr congo",
    "republique democratique du congo": "dr congo", "cote d ivoire": "ivory coast",
    "cap vert": "cape verde", "zambie": "zambia", "ouganda": "uganda",
    "tanzanie": "tanzania", "ethiopie": "ethiopia", "soudan": "sudan",
    "soudan du sud": "south sudan", "libye": "libya", "comores": "comoros",
    "maurice": "mauritius", "namibie": "namibia", "tchad": "chad",
    "mauritanie": "mauritania", "centrafrique": "central african republic",
    "republique centrafricaine": "central african republic",
    "senegal": "senegal", "gambie": "gambia", "sierra leone": "sierra leone",
    "liberia": "liberia", "mozambique": "mozambique", "madagascar": "madagascar",
    "seychelles": "seychelles", "somalie": "somalia", "erythree": "eritrea",
    "djibouti": "djibouti", "burundi": "burundi", "rwanda": "rwanda",
    # Amériques
    "bresil": "brazil", "argentine": "argentina", "colombie": "colombia",
    "perou": "peru", "chili": "chile", "equateur": "ecuador", "bolivie": "bolivia",
    "mexique": "mexico", "etats unis": "united states", "usa": "united states",
    "jamaique": "jamaica", "salvador": "el salvador",
    "trinite et tobago": "trinidad and tobago", "porto rico": "puerto rico",
    "iles caimans": "cayman islands", "iles cayman": "cayman islands",
    "republique dominicaine": "dominican republic", "guyane": "guyana",
    "surinam": "suriname",
    # Asie / Océanie
    "japon": "japan", "coree du sud": "south korea", "coree du nord": "north korea",
    "chine": "china", "inde": "india", "irak": "iraq",
    "arabie saoudite": "saudi arabia", "emirats arabes unis": "united arab emirates",
    "jordanie": "jordan", "syrie": "syria", "liban": "lebanon",
    "ouzbekistan": "uzbekistan", "thailande": "thailand", "indonesie": "indonesia",
    "malaisie": "malaysia", "australie": "australia",
    "nouvelle zelande": "new zealand", "philippines": "philippines",
    "palestine": "palestine", "koweit": "kuwait", "oman": "oman",
    "bahrein": "bahrain", "yemen": "yemen", "tadjikistan": "tajikistan",
    "turkmenistan": "turkmenistan", "kirghizistan": "kyrgyzstan",
    "birmanie": "myanmar", "singapour": "singapore", "hong kong": "hong kong",
}

# Alias fixes anglais -> forme unique (pour que "Turkiye" = "Turkey", etc.)
ALIAS_EN = {
    "turkiye": "turkey", "czechia": "czech republic", "cabo verde": "cape verde",
    "korea republic": "south korea", "usa": "united states",
    "ir iran": "iran", "cote divoire": "ivory coast",
}

_PAYS_TRIES = sorted(PAYS_FR_EN, key=len, reverse=True)


def traduire(nom_normalise):
    """Remplace les noms de pays francais par l'anglais (mot entier)."""
    out = f" {nom_normalise} "
    for fr in _PAYS_TRIES:
        if f" {fr} " in out:
            out = out.replace(f" {fr} ", f" {PAYS_FR_EN[fr]} ")
    for src, dst in ALIAS_EN.items():
        if f" {src} " in out:
            out = out.replace(f" {src} ", f" {dst} ")
    return out.strip()


# ============================================================
# FAUX MATCHS (intitules de paris recuperes par erreur)
# ============================================================

FAUX_MATCH = re.compile(
    r"\b(domicile|exterieur|home|away|speciaux|special|specials|"
    r"outright|outrights)\b"
)


def est_faux_match(match):
    for cle in ("equipe_1", "equipe_2"):
        nom = normalize(match.get(cle))
        if not nom or len(nom) < 2 or FAUX_MATCH.search(nom):
            return True
    if normalize(match.get("equipe_1")) == normalize(match.get("equipe_2")):
        return True
    return False


# ============================================================
# CATEGORIE (senior / U19 / femmes ...)
# ============================================================

_FEMMES = {"femmes", "femme", "women", "womens", "feminin", "feminine",
           "ladies", "frauen", "lfc", "wfc", "w"}
_AGE = re.compile(r"^u(\d{2})$")


def _tokens(nom_normalise):
    # "u 19" -> "u19"
    return re.sub(r"\bu (\d{2})\b", r"u\1", nom_normalise).split()


def categorie(match):
    cats = set()
    for cle in ("equipe_1", "equipe_2", "equipe_1_en", "equipe_2_en"):
        for tok in _tokens(normalize(match.get(cle))):
            if _AGE.match(tok):
                cats.add(tok)
            elif tok in _FEMMES:
                cats.add("f")
    # La categorie est celle du match, pas de chaque equipe : on ne garde
    # que ce qui apparait.
    return frozenset(cats)


# ============================================================
# SIMILARITE DES NOMS D'EQUIPES
# ============================================================

_BRUIT = {"fc", "cf", "sc", "ac", "afc", "club", "de", "del", "la", "le", "the",
          "sv", "ssd", "ud", "cd", "ca", "rc", "fk", "sk", "as", "us", "ss"}


def _nettoyer(nom):
    toks = _tokens(traduire(normalize(nom)))
    toks = [t for t in toks if not _AGE.match(t) and t not in _FEMMES]
    gardes = [t for t in toks if t not in _BRUIT]
    # Si tout a ete supprime (ex. "AC Milan" -> "milan" ok), on garde l'original
    return " ".join(gardes) if gardes else " ".join(toks)


def _sim_nom(a, b):
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if sorted(a.split()) == sorted(b.split()):
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def _variantes(match, cle):
    noms = [match.get(cle), match.get(cle + "_en")]
    return {_nettoyer(n) for n in noms if n} - {""}


def _sim_equipe(m1, m2, cle1, cle2):
    best = 0.0
    for a in _variantes(m1, cle1):
        for b in _variantes(m2, cle2):
            best = max(best, _sim_nom(a, b))
    return best


# ============================================================
# HEURE ET CHAMPIONNAT
# ============================================================

TOLERANCE_HEURE = datetime.timedelta(minutes=30)


def parse_debut(valeur):
    if not valeur:
        return None
    try:
        dt = datetime.datetime.fromisoformat(str(valeur).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


# Bookmakers qui partagent le meme moteur (memes identifiants de championnat).
MOTEUR_1XBET = {"betwinner", "melbet", "megapari", "winwin", "africa-bizbet", "1xbet"}


def _sim_competition(m1, m2):
    i1, i2 = m1.get("competition_id"), m2.get("competition_id")
    meme_moteur = (
        m1.get("bookmaker") in MOTEUR_1XBET and m2.get("bookmaker") in MOTEUR_1XBET
    )
    # Un identifiant n'a de sens qu'entre bookmakers du meme moteur.
    if meme_moteur and i1 is not None and str(i1) == str(i2):
        return 1.0
    noms1 = {normalize(m1.get("competition")), normalize(m1.get("competition_en"))} - {""}
    noms2 = {normalize(m2.get("competition")), normalize(m2.get("competition_en"))} - {""}
    if not noms1 or not noms2:
        return None
    return max(SequenceMatcher(None, a, b).ratio() for a in noms1 for b in noms2)


# ============================================================
# COMPARAISON DE DEUX MATCHS
# ============================================================

def comparer(a, b):
    """Renvoie (score, inverse) ou None si les deux matchs ne peuvent pas
    etre le meme. `inverse` = b est ecrit a l'envers par rapport a a."""

    if categorie(a) != categorie(b):
        return None

    d1 = _sim_equipe(a, b, "equipe_1", "equipe_1")
    d2 = _sim_equipe(a, b, "equipe_2", "equipe_2")
    i1 = _sim_equipe(a, b, "equipe_1", "equipe_2")
    i2 = _sim_equipe(a, b, "equipe_2", "equipe_1")

    direct = (d1 + d2) / 2, min(d1, d2)
    inverse = (i1 + i2) / 2, min(i1, i2)
    est_inverse = inverse[0] > direct[0]
    score, pire = inverse if est_inverse else direct

    da, db = parse_debut(a.get("debut")), parse_debut(b.get("debut"))
    comp = _sim_competition(a, b)

    if da and db:
        if abs(da - db) > TOLERANCE_HEURE:
            return None
        seuil, seuil_equipe = 0.72, 0.6
    else:
        seuil, seuil_equipe = 0.85, 0.85

    # Un championnat clairement different est un indice contre le rapprochement.
    if comp is not None:
        if comp >= 0.6:
            score += 0.04
        elif comp < 0.2 and not (da and db):
            seuil += 0.05

    if score < seuil or pire < seuil_equipe:
        return None
    return score, est_inverse


# ============================================================
# REMISE A L'ENDROIT D'UN MATCH ECRIT A L'ENVERS
# ============================================================

def _swap_1_2(cle):
    # "1 (-1)" <-> "2 (-1)" ; "1X" <-> "2X" ; "V1" <-> "V2"
    mapping = {"V1": "V2", "V2": "V1", "1X": "2X", "2X": "1X"}
    if cle in mapping:
        return mapping[cle]
    m = re.match(r"^([12])( \(.*\))$", cle)
    if m:
        return ("2" if m.group(1) == "1" else "1") + m.group(2)
    m = re.match(r"^(\d+)-(\d+)$", cle)
    if m:
        return f"{m.group(2)}-{m.group(1)}"
    return cle


def retourner(match):
    m = copy.deepcopy(match)
    m["equipe_1"], m["equipe_2"] = match.get("equipe_2"), match.get("equipe_1")
    if match.get("equipe_1_en") or match.get("equipe_2_en"):
        m["equipe_1_en"], m["equipe_2_en"] = match.get("equipe_2_en"), match.get("equipe_1_en")
    for marche in ("1X2", "Double_Chance", "Handicap", "Score_Exact"):
        if match.get(marche):
            m[marche] = {_swap_1_2(k): v for k, v in match[marche].items()}
    return m


# ============================================================
# REGROUPEMENT
# ============================================================

# Ordre d'affichage du nom du match : d'abord les sources en francais.
ORDRE_AFFICHAGE = ["betwinner", "melbet", "megapari", "winwin", "africa-bizbet",
                   "1win", "1xbet", "betpawa"]


def regrouper(data, bookmakers):
    """data : {bookmaker: [matchs]} -> (groupes, stats). Chaque groupe est un
    dict {bookmaker: match remis dans le sens du premier match du groupe}."""

    groupes = []
    stats = {"faux_matchs": 0, "retournes": 0, "avec_heure": 0, "total": 0}

    for bookmaker in bookmakers:
        for match in data.get(bookmaker, []):
            stats["total"] += 1
            if est_faux_match(match):
                stats["faux_matchs"] += 1
                continue
            if match.get("debut"):
                stats["avec_heure"] += 1

            meilleur, meilleur_score, inverse = None, 0.0, False
            for groupe in groupes:
                if bookmaker in groupe:      # jamais d'ecrasement
                    continue
                for existant in groupe.values():
                    res = comparer(existant, match)
                    if res and res[0] > meilleur_score:
                        meilleur, meilleur_score, inverse = groupe, res[0], res[1]

            if meilleur is not None:
                if inverse:
                    match = retourner(match)
                    stats["retournes"] += 1
                meilleur[bookmaker] = match
            else:
                groupes.append({bookmaker: match})

    return groupes, stats


def premier_de_groupe(groupe, cle):
    """Premiere valeur non vide de `cle` en suivant ORDRE_AFFICHAGE."""
    for b in ORDRE_AFFICHAGE:
        if b in groupe and groupe[b].get(cle):
            return groupe[b][cle]
    for m in groupe.values():
        if m.get(cle):
            return m[cle]
    return None
