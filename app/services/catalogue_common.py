"""Briques communes du catalogue (menus, catégories, plats, boissons) : vocabulaire normalisé, noms,
validité des menus, dates.

Rien ici n'écrit en base : ce sont des fonctions pures, testables sans base de données.

Allergènes et régimes
---------------------
``plats.allergenes`` (JSONB) est normalisé en ``{"contient": [codes...], "regimes": [codes...]}``. Les codes sont
stables (jamais renommés) ; les libellés servent à l'affichage et à l'export. Les anciennes valeurs libres
(``{"gluten": true}``) restent lisibles : :func:`allergenes_normalises` les convertit sans rien perdre de connu.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo

# Les 14 allergènes à déclaration obligatoire (règlement UE 1169/2011), dans l'ordre d'affichage.
ALLERGENES: Dict[str, str] = {
    "gluten": "Gluten",
    "crustaces": "Crustacés",
    "oeufs": "Œufs",
    "poisson": "Poisson",
    "arachides": "Arachides",
    "soja": "Soja",
    "lait": "Lait",
    "fruits_a_coque": "Fruits à coque",
    "celeri": "Céleri",
    "moutarde": "Moutarde",
    "sesame": "Sésame",
    "sulfites": "Sulfites",
    "lupin": "Lupin",
    "mollusques": "Mollusques",
}

REGIMES: Dict[str, str] = {
    "vegetarien": "Végétarien",
    "vegan": "Végan",
    "halal": "Halal",
    "sans_porc": "Sans porc",
}

# Libellés des raisons pour lesquelles un article n'est pas vendable (clé stable -> phrase).
MOTIFS_INDISPONIBLES: Dict[str, str] = {
    "archive": "Archivé",
    "desactive": "Désactivé",
    "menu_archive": "Son menu est archivé",
    "menu_inactif": "Son menu est désactivé",
    "menu_hors_validite": "Son menu n'est pas valide aujourd'hui",
    "categorie_archivee": "Sa catégorie est archivée",
    "rupture_stock": "Rupture de stock",
}

JOURS_SEMAINE = {1: "Lundi", 2: "Mardi", 3: "Mercredi", 4: "Jeudi", 5: "Vendredi", 6: "Samedi", 7: "Dimanche"}


# ---------------------------------------------------------------------------------------------- noms
_SPACES = re.compile(r"\s+")


def clean_text(value: Optional[str]) -> Optional[str]:
    """Texte nettoyé (espaces de bord retirés, espaces internes réduits) ; ``None`` si vide."""
    if value is None:
        return None
    cleaned = _SPACES.sub(" ", str(value)).strip()
    return cleaned or None


def normalize_key(value: Optional[str]) -> str:
    """Clé de comparaison des noms : sans accents, sans casse, espaces réduits.

    « Crème  Brûlée » et « creme brulee » donnent la même clé : c'est elle qui décide si deux noms sont identiques.
    """
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFD", str(value))
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _SPACES.sub(" ", stripped).strip().casefold()


def unique_copy_name(base: str, taken_keys: Iterable[str], max_len: int = 255) -> str:
    """« X (copie) », « X (copie 2) »... : premier nom libre pour la copie d'un élément."""
    taken = set(taken_keys)
    for rank in range(1, 1000):
        suffix = " (copie)" if rank == 1 else f" (copie {rank})"
        candidate = base[: max_len - len(suffix)].rstrip() + suffix
        if normalize_key(candidate) not in taken:
            return candidate
    return f"{base[: max_len - 12]} ({datetime.now().strftime('%H%M%S')})"


# --------------------------------------------------------------------------------- allergènes, régimes
def allergenes_normalises(raw: Any) -> Dict[str, List[str]]:
    """``plats.allergenes`` quel que soit son format historique -> ``{"contient": [...], "regimes": [...]}``.

    Formats lus : le format normalisé, une liste de codes, ou un dictionnaire libre dont les clés connues valent
    vrai (``{"gluten": true, "lait": true}``). Les codes inconnus sont ignorés.
    """
    contient: set = set()
    regimes: set = set()

    def take(code: Any) -> None:
        key = normalize_key(str(code)).replace(" ", "_").replace("-", "_")
        if key in ALLERGENES:
            contient.add(key)
        elif key in REGIMES:
            regimes.add(key)

    if isinstance(raw, dict):
        if "contient" in raw or "regimes" in raw:
            for code in raw.get("contient") or []:
                take(code)
            for code in raw.get("regimes") or []:
                take(code)
        else:
            for code, active in raw.items():
                if active:
                    take(code)
    elif isinstance(raw, (list, tuple, set)):
        for code in raw:
            take(code)
    return {
        "contient": [code for code in ALLERGENES if code in contient],
        "regimes": [code for code in REGIMES if code in regimes],
    }


def allergene_code(label: str) -> Optional[str]:
    """Code d'un allergène ou d'un régime écrit à la main (« Fruits à coque », « sans porc »...), sinon ``None``."""
    key = normalize_key(label).replace(" ", "_").replace("-", "_")
    aliases = {"oeuf": "oeufs", "crustace": "crustaces", "arachide": "arachides", "mollusque": "mollusques",
               "sulfite": "sulfites", "fruit_a_coque": "fruits_a_coque", "fruits_coque": "fruits_a_coque",
               "vegetalien": "vegan", "porc_free": "sans_porc"}  # fmt: skip
    key = aliases.get(key, key)
    return key if key in ALLERGENES or key in REGIMES else None


# --------------------------------------------------------------------------------------------- validité
def restaurant_today(timezone_name: Optional[str], now: Optional[datetime] = None) -> date:
    """Date du jour dans le fuseau du restaurant (UTC si le fuseau est inconnu)."""
    current = now or datetime.now(timezone.utc)
    try:
        zone = ZoneInfo(timezone_name) if timezone_name else timezone.utc
    except Exception:  # noqa: BLE001 - fuseau illisible : on retombe sur UTC plutôt que d'échouer
        zone = timezone.utc
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(zone).date()


def valid_on(valide_du: Optional[date], valide_au: Optional[date], jours: Optional[Iterable[int]], day: date) -> bool:
    """Un menu est valide ce jour-là si la date tombe dans sa période et dans ses jours de semaine."""
    if valide_du is not None and day < valide_du:
        return False
    if valide_au is not None and day > valide_au:
        return False
    jours = list(jours or [])
    return not jours or day.isoweekday() in jours


def menu_etat(
    *, actif: Optional[bool], deleted_at: Any, valide_du: Optional[date], valide_au: Optional[date],
    jours: Optional[Iterable[int]], day: date,
) -> str:
    """``archive`` | ``inactif`` | ``hors_validite`` | ``actif`` : l'état d'un menu à la date ``day``."""
    if deleted_at is not None:
        return "archive"
    if not actif:
        return "inactif"
    return "actif" if valid_on(valide_du, valide_au, jours, day) else "hors_validite"


def menu_blocking_reason(etat: str) -> Optional[str]:
    """Motif d'indisponibilité des plats d'un menu dans cet état (``None`` : le menu ne bloque rien)."""
    return {"archive": "menu_archive", "inactif": "menu_inactif", "hors_validite": "menu_hors_validite"}.get(etat)
