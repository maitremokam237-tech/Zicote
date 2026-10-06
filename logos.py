"""Logos des equipes pour Zicote.

- Selections nationales : drapeau (flagcdn.com, service gratuit de drapeaux).
- Clubs : logo uniquement s'il est declare dans `logos_clubs.json`
  (voir la note sur les droits ci-dessous). Sinon la page affiche le badge
  a initiales deja present dans le template.

NOTE DROITS : les logos de clubs sont des marques deposees. Sur un site
monetise, utilise des images dont tu as la licence (API sous licence comme
API-Football / Sportmonks, ou accord du club) puis declare-les dans
`logos_clubs.json` : {"arsenal": "https://.../arsenal.png", ...}
(cle = nom anglais en minuscules, sans accents ni ponctuation).
"""
import json
import re
import unicodedata
from pathlib import Path

CLUBS_PATH = Path(__file__).with_name("logos_clubs.json")

# Nom anglais (normalise) -> code drapeau flagcdn
PAYS = {
    "afghanistan": "af", "albania": "al", "algeria": "dz", "andorra": "ad", "angola": "ao",
    "antigua and barbuda": "ag", "argentina": "ar", "armenia": "am", "australia": "au",
    "austria": "at", "azerbaijan": "az", "bahamas": "bs", "bahrain": "bh", "bangladesh": "bd",
    "barbados": "bb", "belarus": "by", "belgium": "be", "belize": "bz", "benin": "bj",
    "bermuda": "bm", "bhutan": "bt", "bolivia": "bo", "bosnia and herzegovina": "ba",
    "bosnia herzegovina": "ba", "botswana": "bw", "brazil": "br", "brunei": "bn",
    "bulgaria": "bg", "burkina faso": "bf", "burundi": "bi", "cambodia": "kh", "cameroon": "cm",
    "canada": "ca", "cape verde": "cv", "cape verde islands": "cv", "cabo verde": "cv",
    "central african republic": "cf", "chad": "td", "chile": "cl", "china": "cn",
    "china pr": "cn", "colombia": "co", "comoros": "km", "congo": "cg", "congo dr": "cd",
    "dr congo": "cd", "democratic republic of the congo": "cd", "costa rica": "cr",
    "croatia": "hr", "cuba": "cu", "curacao": "cw", "cyprus": "cy", "czech republic": "cz",
    "czechia": "cz", "denmark": "dk", "djibouti": "dj", "dominica": "dm",
    "dominican republic": "do", "ecuador": "ec", "egypt": "eg", "el salvador": "sv",
    "england": "gb-eng", "equatorial guinea": "gq", "eritrea": "er", "estonia": "ee",
    "eswatini": "sz", "swaziland": "sz", "ethiopia": "et", "faroe islands": "fo",
    "fiji": "fj", "finland": "fi", "france": "fr", "gabon": "ga", "gambia": "gm",
    "georgia": "ge", "germany": "de", "ghana": "gh", "gibraltar": "gi", "greece": "gr",
    "grenada": "gd", "guatemala": "gt", "guinea": "gn", "guinea bissau": "gw", "guyana": "gy",
    "haiti": "ht", "honduras": "hn", "hong kong": "hk", "hungary": "hu", "iceland": "is",
    "india": "in", "indonesia": "id", "iran": "ir", "iraq": "iq", "ireland": "ie",
    "republic of ireland": "ie", "israel": "il", "italy": "it", "ivory coast": "ci",
    "cote d ivoire": "ci", "jamaica": "jm", "japan": "jp", "jordan": "jo", "kazakhstan": "kz",
    "kenya": "ke", "kosovo": "xk", "kuwait": "kw", "kyrgyzstan": "kg", "laos": "la",
    "latvia": "lv", "lebanon": "lb", "lesotho": "ls", "liberia": "lr", "libya": "ly",
    "liechtenstein": "li", "lithuania": "lt", "luxembourg": "lu", "macau": "mo",
    "madagascar": "mg", "malawi": "mw", "malaysia": "my", "maldives": "mv", "mali": "ml",
    "malta": "mt", "mauritania": "mr", "mauritius": "mu", "mexico": "mx", "moldova": "md",
    "mongolia": "mn", "montenegro": "me", "morocco": "ma", "mozambique": "mz", "myanmar": "mm",
    "namibia": "na", "nepal": "np", "netherlands": "nl", "new zealand": "nz",
    "nicaragua": "ni", "niger": "ne", "nigeria": "ng", "north korea": "kp",
    "north macedonia": "mk", "macedonia": "mk", "northern ireland": "gb-nir", "norway": "no",
    "oman": "om", "pakistan": "pk", "palestine": "ps", "panama": "pa",
    "papua new guinea": "pg", "paraguay": "py", "peru": "pe", "philippines": "ph",
    "poland": "pl", "portugal": "pt", "puerto rico": "pr", "qatar": "qa", "romania": "ro",
    "russia": "ru", "rwanda": "rw", "san marino": "sm", "sao tome and principe": "st",
    "saudi arabia": "sa", "scotland": "gb-sct", "senegal": "sn", "serbia": "rs",
    "seychelles": "sc", "sierra leone": "sl", "singapore": "sg", "slovakia": "sk",
    "slovenia": "si", "solomon islands": "sb", "somalia": "so", "south africa": "za",
    "south korea": "kr", "korea republic": "kr", "south sudan": "ss", "spain": "es",
    "sri lanka": "lk", "sudan": "sd", "suriname": "sr", "sweden": "se", "switzerland": "ch",
    "syria": "sy", "tahiti": "pf", "taiwan": "tw", "chinese taipei": "tw", "tajikistan": "tj",
    "tanzania": "tz", "thailand": "th", "timor leste": "tl", "togo": "tg",
    "trinidad and tobago": "tt", "tunisia": "tn", "turkey": "tr", "turkiye": "tr",
    "turkmenistan": "tm", "uganda": "ug", "ukraine": "ua", "united arab emirates": "ae",
    "uae": "ae", "united states": "us", "usa": "us", "uruguay": "uy", "uzbekistan": "uz",
    "vanuatu": "vu", "venezuela": "ve", "vietnam": "vn", "wales": "gb-wls", "yemen": "ye",
    "zambia": "zm", "zimbabwe": "zw",
    # variantes de noms et petits territoires (noms vus dans les donnees des bookmakers)
    "republic of north macedonia": "mk", "macedonia fyr": "mk", "ir iran": "ir",
    "united states of america": "us", "st kitts and nevis": "kn", "saint kitts and nevis": "kn",
    "st lucia": "lc", "saint lucia": "lc", "st vincent and the grenadines": "vc",
    "saint vincent and the grenadines": "vc", "sint maarten": "sx", "st maarten": "sx",
    "aruba": "aw", "french guiana": "gf", "guadeloupe": "gp", "martinique": "mq",
    "new caledonia": "nc", "cook islands": "ck", "american samoa": "as", "samoa": "ws",
    "tonga": "to", "guam": "gu", "cayman islands": "ky", "montserrat": "ms",
    "turks and caicos islands": "tc", "us virgin islands": "vi",
    "british virgin islands": "vg", "anguilla": "ai", "bonaire": "bq", "reunion": "re",
    "northern mariana islands": "mp", "mayotte": "yt", "bosnia": "ba",
}

_SUFFIXES = re.compile(r"\b(u ?1[5-9]|u ?2[0-3]|women|w|olympic|b team|ii)$")


def normaliser(nom):
    """'Côte d'Ivoire' -> 'cote d ivoire'."""
    nom = unicodedata.normalize("NFKD", str(nom or ""))
    nom = "".join(c for c in nom if not unicodedata.combining(c)).lower()
    nom = re.sub(r"[^a-z0-9]+", " ", nom).strip()
    return nom


def _charger_clubs():
    try:
        brut = json.loads(CLUBS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {normaliser(k): v for k, v in brut.items() if isinstance(v, str) and v}


_CLUBS = _charger_clubs()


def logo_equipe(nom_en=None, nom_fr=None):
    """URL du logo d'une equipe, ou None (le template affiche alors les initiales)."""
    for nom in (nom_en, nom_fr):
        cle = normaliser(nom)
        if not cle:
            continue
        if cle in _CLUBS:
            return _CLUBS[cle]
        # Selections : les variantes jeunes/feminines ("Spain U21", "Spain W")
        # gardent le drapeau du pays.
        base = _SUFFIXES.sub("", cle).strip()
        code = PAYS.get(cle) or PAYS.get(base)
        if code:
            return f"https://flagcdn.com/w80/{code}.png"
    return None

