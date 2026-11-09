"""Internationalisation : langue de la requête, catalogue de messages, formatage localisé.

* Langues prises en charge (BCP 47) : ``fr`` (défaut) et ``en``.
* La langue d'une requête vient de l'en-tête ``Accept-Language`` (négociation RFC 9110 avec
  q-values) ; à défaut, de la locale de l'utilisateur authentifié ; à défaut, ``fr``.
* ``t(code, locale, **params)`` rend un message du catalogue (``messages_fr`` / ``messages_en``)
  avec des gabarits nommés ``{nom}``. Les paramètres typés (``Money``, ``Kg``, ``Label``, dates,
  nombres décimaux) sont formatés selon la langue ; les autres sont insérés tels quels.
"""

from __future__ import annotations

import contextvars
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Optional

from app.i18n import iso
from app.i18n.messages_en import MESSAGES as _EN
from app.i18n.messages_fr import MESSAGES as _FR

LANGUES = ("fr", "en")
LANGUE_DEFAUT = "fr"
CATALOGUES: Dict[str, Dict[str, str]] = {"fr": _FR, "en": _EN}


# --------------------------------------------------------------------------- contexte
class LocaleState:
    """Langue de la requête en cours. Objet MUTABLE partagé par le middleware et les
    dépendances (exécutées dans un autre thread : le contexte est copié, l'objet est le même)."""

    __slots__ = ("locale", "explicite")

    def __init__(self, locale: str = LANGUE_DEFAUT, explicite: bool = False):
        self.locale = locale
        self.explicite = explicite


_etat: contextvars.ContextVar[Optional[LocaleState]] = contextvars.ContextVar(
    "marinade_locale", default=None
)


def demarrer_requete(accept_language: Optional[str]) -> LocaleState:
    choisie = negocier(accept_language)
    etat = LocaleState(choisie or LANGUE_DEFAUT, explicite=choisie is not None)
    _etat.set(etat)
    return etat


def etat_courant() -> Optional[LocaleState]:
    return _etat.get()


def locale_courante() -> str:
    etat = _etat.get()
    return etat.locale if etat is not None else LANGUE_DEFAUT


def appliquer_locale_utilisateur(locale: Optional[str]) -> None:
    """Sans Accept-Language exploitable, la préférence de l'utilisateur authentifié s'applique."""
    etat = _etat.get()
    if etat is not None and not etat.explicite and locale in LANGUES:
        etat.locale = locale


def negocier(entete: Optional[str]) -> Optional[str]:
    """Négociation RFC 9110 §12.5.4 : meilleure langue prise en charge, ou ``None``.

    ``fr-CA`` correspond à ``fr`` (préfixe), ``*`` à toute langue non exclue par ``q=0``.
    À q égales, l'ordre de l'en-tête départage.
    """
    if not entete:
        return None
    meilleurs: Dict[str, tuple] = {}
    exclues = set()
    joker: Optional[tuple] = None
    for rang, morceau in enumerate(entete.split(",")):
        parties = [p.strip() for p in morceau.split(";")]
        etiquette = parties[0].lower()
        if not etiquette:
            continue
        q = 1.0
        for parametre in parties[1:]:
            if parametre.lower().startswith("q="):
                try:
                    q = float(parametre[2:])
                except ValueError:
                    q = 0.0
        q = max(0.0, min(q, 1.0))
        if etiquette == "*":
            joker = (q, -rang)
            continue
        primaire = etiquette.split("-")[0]
        if primaire not in LANGUES:
            continue
        if q == 0:
            exclues.add(primaire)
            continue
        cle = (q, -rang)
        if primaire not in meilleurs or cle > meilleurs[primaire]:
            meilleurs[primaire] = cle
    if joker is not None and joker[0] > 0:
        for langue in LANGUES:
            if langue not in meilleurs and langue not in exclues:
                meilleurs[langue] = (joker[0], joker[1] - 0.5 * (LANGUES.index(langue) + 1) / 10)
    for langue in exclues:
        meilleurs.pop(langue, None)
    if not meilleurs:
        return None
    return max(meilleurs.items(), key=lambda item: item[1])[0]


# --------------------------------------------------------------------------- paramètres
@dataclass(frozen=True)
class Money:
    """Montant en UNITÉS MINEURES ISO 4217 de ``devise`` (XAF : francs ; EUR : centimes)."""

    mineures: int
    devise: str


@dataclass(frozen=True)
class Kg:
    """Poids exprimé en grammes, affiché en kg (jusqu'à 3 décimales)."""

    grammes: int


@dataclass(frozen=True)
class Label:
    """Libellé traduit par le catalogue (ex. un état de machine)."""

    code: str


@dataclass(frozen=True)
class DateLocale:
    """Date affichée selon la langue (le jour est déjà calculé dans le fuseau de l'établissement)."""

    jour: date


# --------------------------------------------------------------------------- formatage
_ESPACE_FINE = " "  # séparateur de milliers français (CLDR)
_ESPACE_INSECABLE = " "


def formater_nombre(valeur, langue: str = LANGUE_DEFAUT, decimales_max: int = 3,
                    decimales_min: int = 0) -> str:
    """Nombre localisé : ``fr`` « 1 234,5 », ``en`` « 1,234.5 ». Arrondi demi vers le haut."""
    nombre = Decimal(str(valeur))
    quantum = Decimal(1).scaleb(-decimales_max)
    nombre = nombre.quantize(quantum, rounding=ROUND_HALF_UP)
    signe = "-" if nombre < 0 else ""
    entier, _, fraction = f"{abs(nombre):f}".partition(".")
    fraction = fraction.rstrip("0")
    if len(fraction) < decimales_min:
        fraction = fraction.ljust(decimales_min, "0")
    groupes = []
    while len(entier) > 3:
        groupes.insert(0, entier[-3:])
        entier = entier[:-3]
    groupes.insert(0, entier)
    milliers, virgule = (_ESPACE_FINE, ",") if langue == "fr" else (",", ".")
    texte = milliers.join(groupes)
    if fraction:
        texte += virgule + fraction
    return signe + texte


def formater_montant(mineures: int, devise: str, langue: str = LANGUE_DEFAUT) -> str:
    """Montant en unités mineures -> texte localisé (``fr`` « 1 500 FCFA », « 20,00 € » ;
    ``en`` « FCFA 1,500 », « €20.00 »). Utilise babel s'il est installé."""
    exp = iso.exposant(devise)
    valeur = Decimal(int(mineures)).scaleb(-exp)
    try:  # pragma: no cover - babel n'est pas installé sur la plateforme
        from babel.numbers import format_currency

        return format_currency(valeur, devise, locale=langue)
    except ImportError:
        pass
    nombre = formater_nombre(valeur, langue, decimales_max=exp, decimales_min=exp)
    symbole = iso.symbole(devise, langue)
    if langue == "fr":
        return f"{nombre}{_ESPACE_INSECABLE}{symbole}"
    if len(symbole) <= 2 or symbole in {"CA$"}:
        return f"{symbole}{nombre}" if not nombre.startswith("-") else f"-{symbole}{nombre[1:]}"
    return f"{symbole}{_ESPACE_INSECABLE}{nombre}"


def formater_date(jour: date, langue: str = LANGUE_DEFAUT) -> str:
    """``fr`` 19/10/2026 ; ``en`` 2026-10-19 (ISO 8601, sans ambiguïté jour/mois)."""
    return f"{jour:%d/%m/%Y}" if langue == "fr" else jour.isoformat()


def _rendre(valeur: Any, langue: str) -> str:
    if isinstance(valeur, Money):
        return formater_montant(valeur.mineures, valeur.devise, langue)
    if isinstance(valeur, Kg):
        return formater_nombre(Decimal(valeur.grammes) / 1000, langue, 3)
    if isinstance(valeur, Label):
        return t(valeur.code, langue)
    if isinstance(valeur, DateLocale):
        return formater_date(valeur.jour, langue)
    if isinstance(valeur, datetime):
        return valeur.isoformat()
    if isinstance(valeur, date):
        return formater_date(valeur, langue)
    if isinstance(valeur, (Decimal, float)):
        return formater_nombre(valeur, langue)
    if isinstance(valeur, bool):
        return str(valeur).lower()
    if isinstance(valeur, int):
        return formater_nombre(valeur, langue, 0) if abs(valeur) >= 10_000 else str(valeur)
    return str(valeur)


def parametres_json(params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Valeurs injectées, sérialisables en JSON (champ ``params`` des Problem Details)."""
    if not params:
        return None
    sortie: Dict[str, Any] = {}
    for cle, valeur in params.items():
        if isinstance(valeur, Money):
            sortie[cle] = {
                "montant": valeur.mineures,
                "devise": valeur.devise,
                "exposant": iso.exposant(valeur.devise),
            }
        elif isinstance(valeur, Kg):
            sortie[cle] = float(Decimal(valeur.grammes) / 1000)
        elif isinstance(valeur, Label):
            sortie[cle] = valeur.code.rsplit(".", 1)[-1]
        elif isinstance(valeur, DateLocale):
            sortie[cle] = valeur.jour.isoformat()
        elif isinstance(valeur, (datetime, date)):
            sortie[cle] = valeur.isoformat()
        elif isinstance(valeur, (Decimal, uuid.UUID)):
            sortie[cle] = str(valeur)
        elif valeur is None or isinstance(valeur, (str, int, float, bool)):
            sortie[cle] = valeur
        elif isinstance(valeur, (list, tuple)):
            sortie[cle] = [v if isinstance(v, (str, int, float, bool)) else str(v) for v in valeur]
        else:
            sortie[cle] = str(valeur)
    return sortie


class _Defaut(dict):
    def __missing__(self, cle):  # gabarit incomplet : la variable reste visible
        return "{" + cle + "}"


def existe(code: str) -> bool:
    return code in _FR


def t(code: str, locale: Optional[str] = None, **params: Any) -> str:
    """Message ``code`` dans ``locale`` (défaut : langue de la requête), gabarits remplis."""
    langue = locale if locale in LANGUES else locale_courante()
    gabarit = CATALOGUES[langue].get(code) or _FR.get(code)
    if gabarit is None:
        return code
    if not params:
        return gabarit
    rendus = _Defaut({cle: _rendre(valeur, langue) for cle, valeur in params.items()})
    return gabarit.format_map(rendus)
