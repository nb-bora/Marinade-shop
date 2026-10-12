"""Fuseau et bornes de jour d'un pressing.

Le modèle ``Restaurant`` ne porte pas de fuseau : tous les pressings sont réputés être à
``Africa/Douala`` (UTC+1, sans heure d'été). Si la base de fuseaux de l'hôte est absente
(Windows sans ``tzdata``), on retombe sur un décalage fixe de +1 h, identique.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Tuple

FUSEAU_NOM = "Africa/Douala"

try:  # pragma: no cover - dépend de l'hôte
    from zoneinfo import ZoneInfo

    FUSEAU = ZoneInfo(FUSEAU_NOM)
except Exception:  # pragma: no cover
    FUSEAU = timezone(timedelta(hours=1), FUSEAU_NOM)


def maintenant() -> datetime:
    return datetime.now(timezone.utc)


def jour_local(instant: datetime) -> date:
    return instant.astimezone(FUSEAU).date()


def heure_locale(instant: datetime) -> str:
    """« HH:MM » à l'heure du pressing : toute heure affichée dans un message passe par ici
    (les horodatages sont stockés en UTC)."""
    return f"{instant.astimezone(FUSEAU):%H:%M}"


def debut_du_jour(jour: date) -> datetime:
    """Minuit local du jour, en UTC."""
    return datetime(jour.year, jour.month, jour.day, tzinfo=FUSEAU).astimezone(timezone.utc)


def bornes_jour(jour: date) -> Tuple[datetime, datetime]:
    """[début, fin[ du jour local, en UTC."""
    return debut_du_jour(jour), debut_du_jour(jour + timedelta(days=1))
