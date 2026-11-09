"""Emails déclenchés par l'activité d'un restaurant.

- client : réservation en attente / confirmée / annulée, reçu de commande soldée ;
- propriétaire : récapitulatif de clôture de caisse.

Chaque fonction lit ce qu'il faut dans la transaction courante, prépare l'email et ne
l'envoie qu'après le commit (``send_after_commit``). Aucune ne lève : un email raté ne doit
jamais faire échouer une réservation, un paiement ou une clôture.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.restaurant import Restaurant, Table
from app.models.ros import RosCustomer, RosOrder, RosOrderItem
from app.models.user import User
from app.services import email_templates
from app.utils.logging import get_logger

logger = get_logger(__name__)

_FUSEAU_DEFAUT = "Africa/Douala"
_JOURS = {
    "fr": ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"],
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
}
_MOIS = {
    "fr": ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
           "septembre", "octobre", "novembre", "décembre"],
    "en": ["January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December"],
}
_MOYENS = {
    "fr": {"CASH": "Espèces", "MTN_MOMO": "MTN MoMo", "ORANGE_MONEY": "Orange Money",
           "CARD": "Carte bancaire", "WAVE": "Wave", "BANK_TRANSFER": "Virement"},
    "en": {"CASH": "Cash", "MTN_MOMO": "MTN MoMo", "ORANGE_MONEY": "Orange Money",
           "CARD": "Card", "WAVE": "Wave", "BANK_TRANSFER": "Bank transfer"},
}


def _lang(restaurant: Restaurant) -> str:
    locale = str(getattr(restaurant, "locale", "") or "").lower()
    return "en" if locale.startswith("en") else "fr"


def _fuseau(restaurant: Restaurant):
    nom = getattr(restaurant, "timezone", None) or _FUSEAU_DEFAUT
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(nom)
    except Exception:
        from datetime import timedelta

        return timezone(timedelta(hours=1))


def _local(instant: datetime, restaurant: Restaurant) -> datetime:
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(_fuseau(restaurant))


def _date_longue(instant: datetime, lang: str) -> str:
    j, m = _JOURS[lang][instant.weekday()], _MOIS[lang][instant.month - 1]
    return f"{j} {instant.day} {m} {instant.year}" if lang == "fr" else f"{j}, {m} {instant.day}, {instant.year}"


def _restaurant(db: Session, restaurant_id: uuid.UUID) -> Optional[Restaurant]:
    return db.get(Restaurant, restaurant_id)


def _public_url(path: str) -> str:
    return email_templates.email_service.frontend_url(path)


# --------------------------------------------------------------------------- réservations


def notify_reservation(db: Session, reservation: Any, kind: str) -> None:
    """``kind`` : ``pending`` | ``confirmed`` | ``cancelled``. Sans email client : rien."""
    try:
        to = (getattr(reservation, "customer_email", None) or "").strip()
        if not to:
            return
        restaurant = _restaurant(db, reservation.restaurant_id)
        if restaurant is None:
            return
        lang = _lang(restaurant)
        quand = _local(reservation.reservation_date, restaurant)
        table = db.get(Table, reservation.table_id) if reservation.table_id else None
        data = {
            "customer_name": reservation.customer_name,
            "restaurant": restaurant.name,
            "date": _date_longue(quand, lang),
            "time": quand.strftime("%H:%M"),
            "party_size": reservation.party_size,
            "table": table.numero if table else None,
            "reference": str(reservation.id)[:8].upper(),
            "kind": kind,
        }
        email_templates.send_after_commit(db, "reservation", to, data, lang)
    except Exception as exc:
        logger.warning(f"Email de réservation non préparé : {exc}")


# --------------------------------------------------------------------------- reçu


def notify_receipt(db: Session, invoice: Any, payment_method: str) -> None:
    """Reçu envoyé quand la facture d'une commande est soldée, si le client a un email."""
    try:
        if not invoice.order_id:
            return
        order = db.get(RosOrder, invoice.order_id)
        if order is None or order.customer_id is None:
            return
        customer = db.get(RosCustomer, order.customer_id)
        to = ((customer.email if customer else None) or "").strip()
        if not to:
            return
        restaurant = _restaurant(db, invoice.restaurant_id)
        if restaurant is None:
            return
        lang = _lang(restaurant)
        cur = restaurant.currency or "XAF"
        items: List[RosOrderItem] = (
            db.query(RosOrderItem).filter(RosOrderItem.order_id == order.id).all()
        )
        lines = [
            (f"{i.product_name} x{i.quantity}", i.unit_price * i.quantity) for i in items
        ]
        # Les montants de gabarit sont en unité mineure : conversion depuis les Numeric.
        lines = [(label, _mineur(v, cur)) for label, v in lines]
        fixed = [
            ("Service", _mineur(invoice.service_charge, cur))
        ] if invoice.service_charge else []
        taxes = [
            ("TVA" if lang == "fr" else "VAT", _mineur(invoice.tax_amount, cur))
        ] if invoice.tax_amount else []
        data = {
            "customer_name": customer.name or "",
            "restaurant": restaurant.name,
            "order_number": invoice.invoice_number,
            "lines": lines + fixed + taxes,
            "total": _mineur(invoice.total_amount, cur),
            "currency": cur,
            "payment_method": _MOYENS[lang].get(payment_method, payment_method),
            "paid": True,
        }
        email_templates.send_after_commit(db, "order_receipt", to, data, lang)
    except Exception as exc:
        logger.warning(f"Email de reçu non préparé : {exc}")


def _mineur(valeur: Any, devise: str) -> int:
    from decimal import ROUND_HALF_UP, Decimal

    exp = email_templates._exposant(devise)
    return int((Decimal(str(valeur)) * (10**exp)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------- caisse


def notify_shift_closed(db: Session, shift: Any, summary: Dict[str, Any]) -> None:
    """Récapitulatif de clôture de caisse envoyé au propriétaire du restaurant."""
    try:
        restaurant = _restaurant(db, shift.restaurant_id)
        if restaurant is None:
            return
        owner = db.get(User, restaurant.user_id)
        if owner is None or not owner.email or not owner.is_active:
            return
        operator = db.get(User, shift.operator_user_id)
        lang = _lang(restaurant)
        moyens = _MOYENS[lang]
        data = {
            "first_name": owner.first_name,
            "restaurant": restaurant.name,
            "operator": f"{operator.first_name} {operator.last_name}".strip() if operator else "—",
            "opened_at": _local(shift.opened_at, restaurant).strftime(
                "%d/%m/%Y %H:%M" if lang == "fr" else "%Y-%m-%d %H:%M"
            ),
            "closed_at": _local(shift.closed_at or datetime.now(timezone.utc), restaurant).strftime(
                "%d/%m/%Y %H:%M" if lang == "fr" else "%Y-%m-%d %H:%M"
            ),
            "opening": shift.opening_balance,
            "expected": shift.closing_balance_expected,
            "counted": shift.closing_balance_counted,
            "variance": shift.variance,
            "by_method": [
                (moyens.get(m, m), v["total"]) for m, v in summary["payments_by_method"].items()
            ],
            "total": summary["payments_total"],
            "currency": restaurant.currency or "XAF",
            "url": _public_url("/caisse"),
        }
        email_templates.send_after_commit(db, "shift_closed", owner.email, data, lang)
    except Exception as exc:
        logger.warning(f"Email de clôture de caisse non préparé : {exc}")
