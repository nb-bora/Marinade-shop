"""Référentiels ISO embarqués : pays (ISO 3166-1 alpha-2), devises (ISO 4217), fuseaux (IANA).

Aucune dépendance obligatoire : babel et pycountry ne sont pas installés sur la plateforme.

* Pays : la liste COMPLÈTE des codes valides vient de ``iso3166.tab`` du paquet ``tzdata``
  (noms anglais) ; la table ``_PAYS`` ci-dessous ajoute le nom français et la devise par défaut
  pour l'Afrique, l'Europe, l'Amérique du Nord et les principaux autres pays. Un pays valide
  absent de la table garde son nom anglais en français et n'a pas de devise par défaut (il faut
  alors la fournir explicitement).
* Fuseaux par pays : ``zone.tab`` de ``tzdata`` (un pays peut en avoir plusieurs).
* Devises : liste ISO 4217 active, avec l'« exposant » (nombre de décimales des unités mineures).
* Indicatif téléphonique : ``phonenumbers`` (métadonnées libphonenumber).
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

# --------------------------------------------------------------------------- devises
# code: (exposant ISO 4217, nom français, nom anglais)
DEVISES: Dict[str, Tuple[int, str, str]] = {
    "AED": (2, "dirham des Émirats arabes unis", "UAE Dirham"),
    "AFN": (2, "afghani", "Afghani"),
    "ALL": (2, "lek albanais", "Lek"),
    "AMD": (2, "dram arménien", "Armenian Dram"),
    "ANG": (2, "florin antillais", "Netherlands Antillean Guilder"),
    "AOA": (2, "kwanza angolais", "Kwanza"),
    "ARS": (2, "peso argentin", "Argentine Peso"),
    "AUD": (2, "dollar australien", "Australian Dollar"),
    "AWG": (2, "florin arubais", "Aruban Florin"),
    "AZN": (2, "manat azerbaïdjanais", "Azerbaijan Manat"),
    "BAM": (2, "mark convertible", "Convertible Mark"),
    "BBD": (2, "dollar barbadien", "Barbados Dollar"),
    "BDT": (2, "taka", "Taka"),
    "BGN": (2, "lev bulgare", "Bulgarian Lev"),
    "BHD": (3, "dinar bahreïni", "Bahraini Dinar"),
    "BIF": (0, "franc burundais", "Burundi Franc"),
    "BMD": (2, "dollar bermudien", "Bermudian Dollar"),
    "BND": (2, "dollar brunéien", "Brunei Dollar"),
    "BOB": (2, "boliviano", "Boliviano"),
    "BRL": (2, "réal brésilien", "Brazilian Real"),
    "BSD": (2, "dollar bahaméen", "Bahamian Dollar"),
    "BTN": (2, "ngultrum", "Ngultrum"),
    "BWP": (2, "pula", "Pula"),
    "BYN": (2, "rouble biélorusse", "Belarusian Ruble"),
    "BZD": (2, "dollar bélizien", "Belize Dollar"),
    "CAD": (2, "dollar canadien", "Canadian Dollar"),
    "CDF": (2, "franc congolais", "Congolese Franc"),
    "CHF": (2, "franc suisse", "Swiss Franc"),
    "CLP": (0, "peso chilien", "Chilean Peso"),
    "CNY": (2, "yuan renminbi", "Yuan Renminbi"),
    "COP": (2, "peso colombien", "Colombian Peso"),
    "CRC": (2, "colón costaricien", "Costa Rican Colon"),
    "CUP": (2, "peso cubain", "Cuban Peso"),
    "CVE": (2, "escudo capverdien", "Cabo Verde Escudo"),
    "CZK": (2, "couronne tchèque", "Czech Koruna"),
    "DJF": (0, "franc djiboutien", "Djibouti Franc"),
    "DKK": (2, "couronne danoise", "Danish Krone"),
    "DOP": (2, "peso dominicain", "Dominican Peso"),
    "DZD": (2, "dinar algérien", "Algerian Dinar"),
    "EGP": (2, "livre égyptienne", "Egyptian Pound"),
    "ERN": (2, "nakfa", "Nakfa"),
    "ETB": (2, "birr éthiopien", "Ethiopian Birr"),
    "EUR": (2, "euro", "Euro"),
    "FJD": (2, "dollar fidjien", "Fiji Dollar"),
    "FKP": (2, "livre des Falkland", "Falkland Islands Pound"),
    "GBP": (2, "livre sterling", "Pound Sterling"),
    "GEL": (2, "lari", "Lari"),
    "GHS": (2, "cedi ghanéen", "Ghana Cedi"),
    "GIP": (2, "livre de Gibraltar", "Gibraltar Pound"),
    "GMD": (2, "dalasi", "Dalasi"),
    "GNF": (0, "franc guinéen", "Guinean Franc"),
    "GTQ": (2, "quetzal", "Quetzal"),
    "GYD": (2, "dollar du Guyana", "Guyana Dollar"),
    "HKD": (2, "dollar de Hong Kong", "Hong Kong Dollar"),
    "HNL": (2, "lempira", "Lempira"),
    "HTG": (2, "gourde", "Gourde"),
    "HUF": (2, "forint", "Forint"),
    "IDR": (2, "roupie indonésienne", "Rupiah"),
    "ILS": (2, "nouveau shekel", "New Israeli Sheqel"),
    "INR": (2, "roupie indienne", "Indian Rupee"),
    "IQD": (3, "dinar irakien", "Iraqi Dinar"),
    "IRR": (2, "rial iranien", "Iranian Rial"),
    "ISK": (0, "couronne islandaise", "Iceland Krona"),
    "JMD": (2, "dollar jamaïcain", "Jamaican Dollar"),
    "JOD": (3, "dinar jordanien", "Jordanian Dinar"),
    "JPY": (0, "yen", "Yen"),
    "KES": (2, "shilling kényan", "Kenyan Shilling"),
    "KGS": (2, "som", "Som"),
    "KHR": (2, "riel", "Riel"),
    "KMF": (0, "franc comorien", "Comorian Franc"),
    "KPW": (2, "won nord-coréen", "North Korean Won"),
    "KRW": (0, "won sud-coréen", "Won"),
    "KWD": (3, "dinar koweïtien", "Kuwaiti Dinar"),
    "KYD": (2, "dollar des îles Caïmans", "Cayman Islands Dollar"),
    "KZT": (2, "tenge", "Tenge"),
    "LAK": (2, "kip", "Lao Kip"),
    "LBP": (2, "livre libanaise", "Lebanese Pound"),
    "LKR": (2, "roupie srilankaise", "Sri Lanka Rupee"),
    "LRD": (2, "dollar libérien", "Liberian Dollar"),
    "LSL": (2, "loti", "Loti"),
    "LYD": (3, "dinar libyen", "Libyan Dinar"),
    "MAD": (2, "dirham marocain", "Moroccan Dirham"),
    "MDL": (2, "leu moldave", "Moldovan Leu"),
    "MGA": (2, "ariary", "Malagasy Ariary"),
    "MKD": (2, "denar", "Denar"),
    "MMK": (2, "kyat", "Kyat"),
    "MNT": (2, "tugrik", "Tugrik"),
    "MOP": (2, "pataca", "Pataca"),
    "MRU": (2, "ouguiya", "Ouguiya"),
    "MUR": (2, "roupie mauricienne", "Mauritius Rupee"),
    "MVR": (2, "rufiyaa", "Rufiyaa"),
    "MWK": (2, "kwacha malawite", "Malawi Kwacha"),
    "MXN": (2, "peso mexicain", "Mexican Peso"),
    "MYR": (2, "ringgit", "Malaysian Ringgit"),
    "MZN": (2, "metical", "Mozambique Metical"),
    "NAD": (2, "dollar namibien", "Namibia Dollar"),
    "NGN": (2, "naira", "Naira"),
    "NIO": (2, "córdoba oro", "Cordoba Oro"),
    "NOK": (2, "couronne norvégienne", "Norwegian Krone"),
    "NPR": (2, "roupie népalaise", "Nepalese Rupee"),
    "NZD": (2, "dollar néo-zélandais", "New Zealand Dollar"),
    "OMR": (3, "rial omanais", "Rial Omani"),
    "PAB": (2, "balboa", "Balboa"),
    "PEN": (2, "sol", "Sol"),
    "PGK": (2, "kina", "Kina"),
    "PHP": (2, "peso philippin", "Philippine Peso"),
    "PKR": (2, "roupie pakistanaise", "Pakistan Rupee"),
    "PLN": (2, "zloty", "Zloty"),
    "PYG": (0, "guarani", "Guarani"),
    "QAR": (2, "riyal qatari", "Qatari Rial"),
    "RON": (2, "leu roumain", "Romanian Leu"),
    "RSD": (2, "dinar serbe", "Serbian Dinar"),
    "RUB": (2, "rouble russe", "Russian Ruble"),
    "RWF": (0, "franc rwandais", "Rwanda Franc"),
    "SAR": (2, "riyal saoudien", "Saudi Riyal"),
    "SBD": (2, "dollar des îles Salomon", "Solomon Islands Dollar"),
    "SCR": (2, "roupie seychelloise", "Seychelles Rupee"),
    "SDG": (2, "livre soudanaise", "Sudanese Pound"),
    "SEK": (2, "couronne suédoise", "Swedish Krona"),
    "SGD": (2, "dollar de Singapour", "Singapore Dollar"),
    "SHP": (2, "livre de Sainte-Hélène", "Saint Helena Pound"),
    "SLE": (2, "leone", "Leone"),
    "SOS": (2, "shilling somalien", "Somali Shilling"),
    "SRD": (2, "dollar surinamais", "Surinam Dollar"),
    "SSP": (2, "livre sud-soudanaise", "South Sudanese Pound"),
    "STN": (2, "dobra", "Dobra"),
    "SVC": (2, "colón salvadorien", "El Salvador Colon"),
    "SYP": (2, "livre syrienne", "Syrian Pound"),
    "SZL": (2, "lilangeni", "Lilangeni"),
    "THB": (2, "baht", "Baht"),
    "TJS": (2, "somoni", "Somoni"),
    "TMT": (2, "manat turkmène", "Turkmenistan New Manat"),
    "TND": (3, "dinar tunisien", "Tunisian Dinar"),
    "TOP": (2, "pa’anga", "Pa’anga"),
    "TRY": (2, "livre turque", "Turkish Lira"),
    "TTD": (2, "dollar de Trinité-et-Tobago", "Trinidad and Tobago Dollar"),
    "TWD": (2, "nouveau dollar taïwanais", "New Taiwan Dollar"),
    "TZS": (2, "shilling tanzanien", "Tanzanian Shilling"),
    "UAH": (2, "hryvnia", "Hryvnia"),
    "UGX": (0, "shilling ougandais", "Uganda Shilling"),
    "USD": (2, "dollar des États-Unis", "US Dollar"),
    "UYU": (2, "peso uruguayen", "Peso Uruguayo"),
    "UZS": (2, "sum", "Uzbekistan Sum"),
    "VES": (2, "bolívar soberano", "Bolívar Soberano"),
    "VND": (0, "dông", "Dong"),
    "VUV": (0, "vatu", "Vatu"),
    "WST": (2, "tala", "Tala"),
    "XAF": (0, "franc CFA (BEAC)", "CFA Franc BEAC"),
    "XCD": (2, "dollar des Caraïbes orientales", "East Caribbean Dollar"),
    "XCG": (2, "florin caribéen", "Caribbean Guilder"),
    "XOF": (0, "franc CFA (BCEAO)", "CFA Franc BCEAO"),
    "XPF": (0, "franc CFP", "CFP Franc"),
    "YER": (2, "rial yéménite", "Yemeni Rial"),
    "ZAR": (2, "rand", "Rand"),
    "ZMW": (2, "kwacha zambien", "Zambian Kwacha"),
    "ZWG": (2, "zimbabwe gold", "Zimbabwe Gold"),
}

# Symboles usuels (CLDR) ; à défaut, le code ISO est affiché.
SYMBOLES: Dict[str, Dict[str, str]] = {
    "fr": {"XAF": "FCFA", "XOF": "F CFA", "EUR": "€", "USD": "$ US", "GBP": "£GB",
           "CAD": "$ CA", "NGN": "NGN", "JPY": "JPY", "CHF": "CHF"},
    "en": {"XAF": "FCFA", "XOF": "F CFA", "EUR": "€", "USD": "$", "GBP": "£",
           "CAD": "CA$", "NGN": "NGN", "JPY": "¥", "CHF": "CHF"},
}

# --------------------------------------------------------------------------- pays
# code: (nom français, nom anglais, devise par défaut)
_PAYS: Dict[str, Tuple[str, str, str]] = {
    # Afrique
    "DZ": ("Algérie", "Algeria", "DZD"),
    "AO": ("Angola", "Angola", "AOA"),
    "BJ": ("Bénin", "Benin", "XOF"),
    "BW": ("Botswana", "Botswana", "BWP"),
    "BF": ("Burkina Faso", "Burkina Faso", "XOF"),
    "BI": ("Burundi", "Burundi", "BIF"),
    "CV": ("Cap-Vert", "Cabo Verde", "CVE"),
    "CM": ("Cameroun", "Cameroon", "XAF"),
    "CF": ("République centrafricaine", "Central African Republic", "XAF"),
    "TD": ("Tchad", "Chad", "XAF"),
    "KM": ("Comores", "Comoros", "KMF"),
    "CG": ("Congo", "Congo", "XAF"),
    "CD": ("République démocratique du Congo", "Democratic Republic of the Congo", "CDF"),
    "CI": ("Côte d’Ivoire", "Côte d’Ivoire", "XOF"),
    "DJ": ("Djibouti", "Djibouti", "DJF"),
    "EG": ("Égypte", "Egypt", "EGP"),
    "GQ": ("Guinée équatoriale", "Equatorial Guinea", "XAF"),
    "ER": ("Érythrée", "Eritrea", "ERN"),
    "SZ": ("Eswatini", "Eswatini", "SZL"),
    "ET": ("Éthiopie", "Ethiopia", "ETB"),
    "GA": ("Gabon", "Gabon", "XAF"),
    "GM": ("Gambie", "Gambia", "GMD"),
    "GH": ("Ghana", "Ghana", "GHS"),
    "GN": ("Guinée", "Guinea", "GNF"),
    "GW": ("Guinée-Bissau", "Guinea-Bissau", "XOF"),
    "KE": ("Kenya", "Kenya", "KES"),
    "LS": ("Lesotho", "Lesotho", "LSL"),
    "LR": ("Libéria", "Liberia", "LRD"),
    "LY": ("Libye", "Libya", "LYD"),
    "MG": ("Madagascar", "Madagascar", "MGA"),
    "MW": ("Malawi", "Malawi", "MWK"),
    "ML": ("Mali", "Mali", "XOF"),
    "MR": ("Mauritanie", "Mauritania", "MRU"),
    "MU": ("Maurice", "Mauritius", "MUR"),
    "YT": ("Mayotte", "Mayotte", "EUR"),
    "MA": ("Maroc", "Morocco", "MAD"),
    "MZ": ("Mozambique", "Mozambique", "MZN"),
    "NA": ("Namibie", "Namibia", "NAD"),
    "NE": ("Niger", "Niger", "XOF"),
    "NG": ("Nigéria", "Nigeria", "NGN"),
    "RE": ("La Réunion", "Réunion", "EUR"),
    "RW": ("Rwanda", "Rwanda", "RWF"),
    "ST": ("Sao Tomé-et-Principe", "Sao Tome and Principe", "STN"),
    "SN": ("Sénégal", "Senegal", "XOF"),
    "SC": ("Seychelles", "Seychelles", "SCR"),
    "SL": ("Sierra Leone", "Sierra Leone", "SLE"),
    "SO": ("Somalie", "Somalia", "SOS"),
    "ZA": ("Afrique du Sud", "South Africa", "ZAR"),
    "SS": ("Soudan du Sud", "South Sudan", "SSP"),
    "SD": ("Soudan", "Sudan", "SDG"),
    "TZ": ("Tanzanie", "Tanzania", "TZS"),
    "TG": ("Togo", "Togo", "XOF"),
    "TN": ("Tunisie", "Tunisia", "TND"),
    "UG": ("Ouganda", "Uganda", "UGX"),
    "ZM": ("Zambie", "Zambia", "ZMW"),
    "ZW": ("Zimbabwe", "Zimbabwe", "ZWG"),
    # Europe
    "AL": ("Albanie", "Albania", "ALL"),
    "AD": ("Andorre", "Andorra", "EUR"),
    "AT": ("Autriche", "Austria", "EUR"),
    "BY": ("Biélorussie", "Belarus", "BYN"),
    "BE": ("Belgique", "Belgium", "EUR"),
    "BA": ("Bosnie-Herzégovine", "Bosnia and Herzegovina", "BAM"),
    "BG": ("Bulgarie", "Bulgaria", "BGN"),
    "HR": ("Croatie", "Croatia", "EUR"),
    "CY": ("Chypre", "Cyprus", "EUR"),
    "CZ": ("Tchéquie", "Czechia", "CZK"),
    "DK": ("Danemark", "Denmark", "DKK"),
    "EE": ("Estonie", "Estonia", "EUR"),
    "FI": ("Finlande", "Finland", "EUR"),
    "FR": ("France", "France", "EUR"),
    "DE": ("Allemagne", "Germany", "EUR"),
    "GR": ("Grèce", "Greece", "EUR"),
    "HU": ("Hongrie", "Hungary", "HUF"),
    "IS": ("Islande", "Iceland", "ISK"),
    "IE": ("Irlande", "Ireland", "EUR"),
    "IT": ("Italie", "Italy", "EUR"),
    "XK": ("Kosovo", "Kosovo", "EUR"),
    "LV": ("Lettonie", "Latvia", "EUR"),
    "LI": ("Liechtenstein", "Liechtenstein", "CHF"),
    "LT": ("Lituanie", "Lithuania", "EUR"),
    "LU": ("Luxembourg", "Luxembourg", "EUR"),
    "MT": ("Malte", "Malta", "EUR"),
    "MD": ("Moldavie", "Moldova", "MDL"),
    "MC": ("Monaco", "Monaco", "EUR"),
    "ME": ("Monténégro", "Montenegro", "EUR"),
    "NL": ("Pays-Bas", "Netherlands", "EUR"),
    "MK": ("Macédoine du Nord", "North Macedonia", "MKD"),
    "NO": ("Norvège", "Norway", "NOK"),
    "PL": ("Pologne", "Poland", "PLN"),
    "PT": ("Portugal", "Portugal", "EUR"),
    "RO": ("Roumanie", "Romania", "RON"),
    "RU": ("Russie", "Russia", "RUB"),
    "SM": ("Saint-Marin", "San Marino", "EUR"),
    "RS": ("Serbie", "Serbia", "RSD"),
    "SK": ("Slovaquie", "Slovakia", "EUR"),
    "SI": ("Slovénie", "Slovenia", "EUR"),
    "ES": ("Espagne", "Spain", "EUR"),
    "SE": ("Suède", "Sweden", "SEK"),
    "CH": ("Suisse", "Switzerland", "CHF"),
    "UA": ("Ukraine", "Ukraine", "UAH"),
    "GB": ("Royaume-Uni", "United Kingdom", "GBP"),
    "VA": ("Vatican", "Vatican City", "EUR"),
    # Amérique du Nord et Caraïbes
    "CA": ("Canada", "Canada", "CAD"),
    "US": ("États-Unis", "United States", "USD"),
    "MX": ("Mexique", "Mexico", "MXN"),
    "PM": ("Saint-Pierre-et-Miquelon", "Saint Pierre and Miquelon", "EUR"),
    "GP": ("Guadeloupe", "Guadeloupe", "EUR"),
    "MQ": ("Martinique", "Martinique", "EUR"),
    "GF": ("Guyane", "French Guiana", "EUR"),
    "HT": ("Haïti", "Haiti", "HTG"),
    "DO": ("République dominicaine", "Dominican Republic", "DOP"),
    "JM": ("Jamaïque", "Jamaica", "JMD"),
    "CU": ("Cuba", "Cuba", "CUP"),
    "BS": ("Bahamas", "Bahamas", "BSD"),
    "BB": ("Barbade", "Barbados", "BBD"),
    "TT": ("Trinité-et-Tobago", "Trinidad and Tobago", "TTD"),
    "PR": ("Porto Rico", "Puerto Rico", "USD"),
    # Autres pays fréquents
    "BR": ("Brésil", "Brazil", "BRL"),
    "AR": ("Argentine", "Argentina", "ARS"),
    "CN": ("Chine", "China", "CNY"),
    "IN": ("Inde", "India", "INR"),
    "JP": ("Japon", "Japan", "JPY"),
    "AE": ("Émirats arabes unis", "United Arab Emirates", "AED"),
    "SA": ("Arabie saoudite", "Saudi Arabia", "SAR"),
    "LB": ("Liban", "Lebanon", "LBP"),
    "TR": ("Turquie", "Türkiye", "TRY"),
    "AU": ("Australie", "Australia", "AUD"),
    "NC": ("Nouvelle-Calédonie", "New Caledonia", "XPF"),
    "PF": ("Polynésie française", "French Polynesia", "XPF"),
    "VN": ("Viêt Nam", "Viet Nam", "VND"),
}

LANGUES = {"fr": ("français", "French"), "en": ("anglais", "English")}


def _tzdata_file(nom: str) -> Optional[str]:
    try:
        import tzdata  # noqa: F401  (Windows : la base IANA vient de ce paquet)

        chemin = os.path.join(os.path.dirname(tzdata.__file__), "zoneinfo", nom)
        if os.path.exists(chemin):
            return chemin
    except ImportError:
        pass
    for base in ("/usr/share/zoneinfo", "/usr/lib/zoneinfo"):
        chemin = os.path.join(base, nom)
        if os.path.exists(chemin):
            return chemin
    return None


@lru_cache(maxsize=1)
def _iso3166() -> Dict[str, str]:
    """Tous les codes ISO 3166-1 alpha-2 avec leur nom anglais (iso3166.tab)."""
    noms = {code: en for code, (_, en, _) in _PAYS.items()}
    chemin = _tzdata_file("iso3166.tab")
    if chemin:
        with open(chemin, encoding="utf-8") as fichier:
            for ligne in fichier:
                if ligne.startswith("#") or "\t" not in ligne:
                    continue
                code, nom = ligne.rstrip("\n").split("\t", 1)
                noms.setdefault(code.strip(), nom.strip())
    return noms


@lru_cache(maxsize=1)
def _zones_par_pays() -> Dict[str, Tuple[str, ...]]:
    zones: Dict[str, List[str]] = {}
    chemin = _tzdata_file("zone.tab")
    if chemin:
        with open(chemin, encoding="utf-8") as fichier:
            for ligne in fichier:
                if ligne.startswith("#"):
                    continue
                colonnes = ligne.rstrip("\n").split("\t")
                if len(colonnes) >= 3:
                    zones.setdefault(colonnes[0], []).append(colonnes[2])
    return {code: tuple(liste) for code, liste in zones.items()}


# --------------------------------------------------------------------------- API
def normaliser_pays(valeur: Optional[str]) -> Optional[str]:
    """Code ISO 3166-1 alpha-2 en majuscules s'il est valide, sinon ``None``."""
    if not valeur:
        return None
    code = valeur.strip().upper()
    return code if len(code) == 2 and code in _iso3166() else None


def pays_valides() -> Dict[str, str]:
    return dict(_iso3166())


def nom_pays(code: str, langue: str = "fr") -> str:
    connu = _PAYS.get(code)
    if connu:
        return connu[0] if langue == "fr" else connu[1]
    return _iso3166().get(code, code)


def devise_par_defaut(pays: Optional[str]) -> Optional[str]:
    connu = _PAYS.get((pays or "").upper())
    return connu[2] if connu else None


def normaliser_devise(valeur: Optional[str]) -> Optional[str]:
    if not valeur:
        return None
    code = valeur.strip().upper()
    return code if code in DEVISES else None


def exposant(devise: Optional[str]) -> int:
    """Nombre de décimales ISO 4217 (XAF 0, EUR 2, TND 3). Devise inconnue : 2."""
    return DEVISES.get((devise or "").upper(), (2, "", ""))[0]


def nom_devise(code: str, langue: str = "fr") -> str:
    _, fr, en = DEVISES.get(code, (2, code, code))
    return fr if langue == "fr" else en


def symbole(code: str, langue: str = "fr") -> str:
    return SYMBOLES.get(langue, {}).get(code, code)


def fuseaux(pays: Optional[str]) -> Tuple[str, ...]:
    return _zones_par_pays().get((pays or "").upper(), ())


def fuseau_par_defaut(pays: Optional[str]) -> Optional[str]:
    """Le fuseau du pays s'il n'en a qu'un ; ``None`` s'il en a plusieurs (choix explicite)."""
    zones = fuseaux(pays)
    return zones[0] if len(zones) == 1 else None


@lru_cache(maxsize=1)
def _fuseaux_valides() -> frozenset:
    return frozenset(available_timezones())


def fuseau_valide(nom: Optional[str]) -> bool:
    if not nom or nom != nom.strip() or nom.startswith("/") or ".." in nom:
        return False
    if nom in _fuseaux_valides():
        return True
    try:
        ZoneInfo(nom)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


def indicatif(pays: str) -> Optional[int]:
    try:
        import phonenumbers

        code = phonenumbers.country_code_for_region(pays)
        return code or None
    except Exception:  # pragma: no cover
        return None


# Noms de pays tels qu'ils ont pu être saisis en texte libre avant la normalisation
# (migration 20261019) : français, anglais, sans accents, minuscules.
def code_depuis_nom(texte: Optional[str]) -> Optional[str]:
    import unicodedata

    if not texte or not texte.strip():
        return None
    direct = normaliser_pays(texte)
    if direct:
        return direct

    def _simple(s: str) -> str:
        s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
        return "".join(c for c in s.lower() if c.isalnum())

    cible = _simple(texte)
    for code, (fr, en, _) in _PAYS.items():
        if cible in (_simple(fr), _simple(en)):
            return code
    for code, en in _iso3166().items():
        if cible == _simple(en):
            return code
    return None
