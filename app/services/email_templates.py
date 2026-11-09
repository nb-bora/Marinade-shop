"""Gabarits d'emails de Marinade, en français et en anglais.

Chaque gabarit reçoit un simple dictionnaire de données (aucun lien avec les modèles ORM) et
retourne un ``Mail`` (objet, texte brut, html) construit avec ``email_layout``. Les exemples de
``SAMPLES`` servent à l'aperçu administrateur (``/v1/emails/preview/{nom}``) et aux tests.

Montants : entiers en plus petite unité de la devise de l'établissement (XAF : 1 = 1 FCFA).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services import email_service
from app.services.email_layout import Details, Hero, Stat, Status, render_email
from app.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class Mail:
    subject: str
    text: str
    html: str


# --------------------------------------------------------------------------- formats


def _exposant(devise: str) -> int:
    try:
        from app.i18n.iso import exposant

        return exposant(devise)
    except Exception:
        return 0 if devise in {"XAF", "XOF", "JPY", "KRW", "RWF", "GNF"} else 2


def montant(valeur: int, devise: str = "XAF", lang: str = "fr") -> str:
    """« 41 870 » (fr) / « 41,870 » (en) ; décimales selon l'exposant ISO 4217 de la devise."""
    exp = _exposant(devise)
    nombre = valeur / (10**exp) if exp else valeur
    s = f"{nombre:,.{exp}f}"
    return s.replace(",", " ").replace(".", ",") if lang == "fr" else s


def montant_decimal(valeur: Any, devise: str = "XAF", lang: str = "fr") -> str:
    """Comme ``montant`` pour un ``Decimal`` exprimé en unité principale (colonnes Numeric)."""
    exp = _exposant(devise)
    mineur = (Decimal(str(valeur)) * (10**exp)).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return montant(int(mineur), devise, lang)


def _dt(valeur: Any, lang: str) -> str:
    if isinstance(valeur, datetime):
        return valeur.strftime("%d/%m/%Y %H:%M" if lang == "fr" else "%Y-%m-%d %H:%M")
    return str(valeur)


def _nom(data: Dict[str, Any]) -> str:
    return str(data.get("first_name") or data.get("customer_name") or "").strip()


def _hello(lang: str, name: str) -> str:
    base = "Bonjour" if lang == "fr" else "Hello"
    return f"{base} {name}," if name else f"{base},"


def _sign(lang: str) -> str:
    return "L'équipe Marinade" if lang == "fr" else "The Marinade team"


def _lang(lang: Optional[str]) -> str:
    return "en" if str(lang or "").lower().startswith("en") else "fr"


def _mail(subject: str, lang: str, **kw: Any) -> Mail:
    text, page = render_email(title=subject, lang=lang, **kw)
    return Mail(subject, text, page)


def _link(path: str, **query: str) -> str:
    return email_service.frontend_url(path, **query)


# --------------------------------------------------------------------------- authentification


def welcome(data: Dict[str, Any], lang: str = "fr") -> Mail:
    fr = lang == "fr"
    return _mail(
        "Bienvenue sur Marinade" if fr else "Welcome to Marinade",
        lang,
        status=Status("Compte créé" if fr else "Account created", "success"),
        greeting=_hello(lang, _nom(data)),
        paragraphs=[
            "Votre compte est prêt. Créez votre établissement, ajoutez votre carte ou vos "
            "machines, et encaissez dès aujourd'hui."
            if fr
            else "Your account is ready. Create your establishment, add your menu or machines, "
            "and start taking payments today."
        ],
        action_label="Ouvrir mon espace" if fr else "Open my workspace",
        action_url=_link("/login"),
        signature=_sign(lang),
    )


def activation_code(data: Dict[str, Any], lang: str = "fr") -> Mail:
    """Code à usage unique pour activer un compte tout juste créé."""
    fr = lang == "fr"
    minutes = settings.ACTIVATION_CODE_EXPIRE_MINUTES
    email = str(data.get("email") or "")
    return _mail(
        "Votre code d'activation Marinade" if fr else "Your Marinade activation code",
        lang,
        status=Status("Action requise" if fr else "Action required", "warning"),
        greeting=_hello(lang, _nom(data)),
        paragraphs=[
            "Merci de vous être inscrit sur Marinade. Saisissez le code ci-dessous pour "
            "activer votre compte."
            if fr
            else "Thanks for signing up to Marinade. Enter the code below to activate your "
            "account."
        ],
        code=str(data["code"]),
        action_label="Saisir mon code" if fr else "Enter my code",
        action_url=_link("/activate-account", email=email) if email else None,
        note=(
            f"Ce code est valable {minutes} minutes et ne peut être utilisé qu'une fois. "
            "Ne le communiquez à personne : l'équipe Marinade ne vous le demandera jamais. "
            "Si vous n'êtes pas à l'origine de cette inscription, ignorez simplement cet email."
            if fr
            else f"This code is valid for {minutes} minutes and can be used once. Do not share "
            "it with anyone: the Marinade team will never ask for it. If you did not sign up, "
            "simply ignore this email."
        ),
        signature=_sign(lang),
    )


def verify_email(data: Dict[str, Any], lang: str = "fr") -> Mail:
    fr = lang == "fr"
    hours = settings.VERIFICATION_TOKEN_EXPIRE_HOURS
    return _mail(
        "Vérifiez votre adresse email" if fr else "Verify your email address",
        lang,
        status=Status("Action requise" if fr else "Action required", "warning"),
        greeting=_hello(lang, _nom(data)),
        paragraphs=[
            "Confirmez votre adresse pour sécuriser votre compte et recevoir vos notifications."
            if fr
            else "Confirm your address to secure your account and receive notifications."
        ],
        action_label="Vérifier mon adresse" if fr else "Verify my address",
        action_url=_link("/verify-email", token=str(data["token"])),
        note=(
            f"Ce lien est valable {hours} h. Si vous n'êtes pas à l'origine de cette demande, "
            "ignorez cet email."
            if fr
            else f"This link is valid for {hours} h. If you did not request it, ignore this email."
        ),
        signature=_sign(lang),
    )


def password_reset(data: Dict[str, Any], lang: str = "fr") -> Mail:
    fr = lang == "fr"
    minutes = settings.RESET_TOKEN_EXPIRE_MINUTES
    return _mail(
        "Réinitialisation de votre mot de passe" if fr else "Reset your password",
        lang,
        status=Status("Sécurité" if fr else "Security", "info"),
        greeting=_hello(lang, _nom(data)),
        paragraphs=[
            "Une réinitialisation du mot de passe de votre compte a été demandée."
            if fr
            else "A password reset was requested for your account."
        ],
        action_label="Choisir un nouveau mot de passe" if fr else "Choose a new password",
        action_url=_link("/reset-password", token=str(data["token"])),
        note=(
            f"Ce lien est valable {minutes} min et ne sert qu'une fois. Si vous n'êtes pas à "
            "l'origine de cette demande, ignorez cet email : votre mot de passe reste inchangé."
            if fr
            else f"This link is valid for {minutes} min and works once. If you did not request "
            "it, ignore this email: your password is unchanged."
        ),
        signature=_sign(lang),
    )


def password_changed(data: Dict[str, Any], lang: str = "fr") -> Mail:
    fr = lang == "fr"
    return _mail(
        "Votre mot de passe a été modifié" if fr else "Your password was changed",
        lang,
        status=Status("Mot de passe modifié" if fr else "Password changed", "success"),
        greeting=_hello(lang, _nom(data)),
        paragraphs=[
            "Le mot de passe de votre compte vient d'être modifié et toutes vos sessions ont "
            "été fermées."
            if fr
            else "Your account password was just changed and all your sessions were signed out."
        ],
        note=(
            "Ce n'était pas vous ? Réinitialisez immédiatement votre mot de passe et contactez "
            "le support."
            if fr
            else "Was this not you? Reset your password immediately and contact support."
        ),
        action_label="Réinitialiser mon mot de passe" if fr else "Reset my password",
        action_url=_link("/forgot-password"),
        signature=_sign(lang),
    )


# --------------------------------------------------------------------------- restaurant


def reservation(data: Dict[str, Any], lang: str = "fr") -> Mail:
    """``data`` : customer_name, restaurant, date, time, party_size, table?, reference, kind
    (``confirmed`` | ``pending`` | ``cancelled``), url?"""
    fr = lang == "fr"
    kind = data.get("kind", "confirmed")
    statut = {
        "confirmed": ("Réservation confirmée" if fr else "Reservation confirmed", "success"),
        "pending": ("En attente de confirmation" if fr else "Awaiting confirmation", "warning"),
        "cancelled": ("Réservation annulée" if fr else "Reservation cancelled", "danger"),
        "table_ready": ("Votre table est prête" if fr else "Your table is ready", "success"),
    }[kind]
    corps = {
        "confirmed": "Votre table est réservée. Nous vous attendons !"
        if fr
        else "Your table is booked. We look forward to seeing you!",
        "pending": "Votre demande est bien reçue ; le restaurant la confirmera très vite."
        if fr
        else "We received your request; the restaurant will confirm it shortly.",
        "cancelled": "Votre réservation a été annulée. Vous pouvez en effectuer une nouvelle à tout moment."
        if fr
        else "Your reservation was cancelled. You can make a new one at any time.",
        "table_ready": "Une table est prête pour votre groupe. Présentez-vous à l'accueil dès que possible."
        if fr
        else "A table is ready for your party. Please come to the front desk as soon as you can.",
    }[kind]
    rows = [
        ("Date" if fr else "Date", str(data["date"])),
        ("Heure" if fr else "Time", str(data["time"])),
        ("Personnes" if fr else "Guests", str(data["party_size"])),
    ]
    if data.get("table"):
        rows.append(("Table", str(data["table"])))
    return _mail(
        f"{statut[0]} - {data['restaurant']}",
        lang,
        status=Status(*statut),
        greeting=_hello(lang, _nom(data)),
        paragraphs=[corps],
        details=Details(title="Détails" if fr else "Details", badge=str(data["restaurant"]), rows=rows),
        action_label="Voir la réservation" if fr else "View reservation",
        action_url=data.get("url"),
        reference=str(data.get("reference") or ""),
        signature=str(data["restaurant"]),
    )


def order_receipt(data: Dict[str, Any], lang: str = "fr") -> Mail:
    """Reçu d'une commande de restaurant. ``data`` : customer_name, restaurant, order_number,
    lines [(libellé, montant)], total, currency, payment_method?, paid (bool), url?"""
    fr = lang == "fr"
    cur = data.get("currency", "XAF")
    paid = bool(data.get("paid", True))
    rows: List = [
        (str(label), montant(int(amount), cur, lang)) for label, amount in data.get("lines", [])
    ]
    if data.get("payment_method"):
        rows.append(("Paiement" if fr else "Payment", str(data["payment_method"])))
    return _mail(
        (f"Reçu {data['order_number']} - {data['restaurant']}" if paid
         else f"Commande {data['order_number']} - {data['restaurant']}") if fr
        else (f"Receipt {data['order_number']} - {data['restaurant']}" if paid
              else f"Order {data['order_number']} - {data['restaurant']}"),
        lang,
        status=Status(
            ("Paiement reçu" if fr else "Payment received") if paid
            else ("Commande confirmée" if fr else "Order confirmed"),
            "success" if paid else "info",
        ),
        greeting=_hello(lang, _nom(data)),
        paragraphs=[
            f"Merci pour votre visite chez {data['restaurant']}. Voici le détail de votre commande."
            if fr
            else f"Thank you for visiting {data['restaurant']}. Here is your order summary."
        ],
        details=Details(
            title="Détail de la commande" if fr else "Order details",
            badge=str(data["order_number"]),
            rows=rows,
        ),
        stats=[Stat("Total", montant(int(data["total"]), cur, lang), cur)],
        action_label="Voir la commande" if fr else "View order",
        action_url=data.get("url"),
        reference=str(data["order_number"]),
        signature=str(data["restaurant"]),
    )


def shift_closed(data: Dict[str, Any], lang: str = "fr") -> Mail:
    """Clôture de caisse, pour le propriétaire. ``data`` : first_name, restaurant, operator,
    opened_at, closed_at, opening, expected, counted, variance (nombres, unité principale),
    by_method [(libellé, montant)], total, currency, url?"""
    fr = lang == "fr"
    cur = data.get("currency", "XAF")
    m = lambda v: f"{montant_decimal(v, cur, lang)} {cur}"  # noqa: E731
    ecart = Decimal(str(data["variance"]))
    if ecart == 0:
        statut = Status("Caisse juste" if fr else "Cash balanced", "success")
    elif ecart < 0:
        statut = Status("Manquant en caisse" if fr else "Cash shortage", "danger")
    else:
        statut = Status("Excédent en caisse" if fr else "Cash surplus", "warning")
    rows = [
        ("Caissier" if fr else "Cashier", str(data["operator"])),
        ("Ouverture" if fr else "Opened", _dt(data["opened_at"], lang)),
        ("Clôture" if fr else "Closed", _dt(data["closed_at"], lang)),
        ("Fond de caisse" if fr else "Opening float", m(data["opening"])),
        ("Espèces attendues" if fr else "Expected cash", m(data["expected"])),
        ("Espèces comptées" if fr else "Counted cash", m(data["counted"])),
    ]
    rows += [(str(label), m(amount)) for label, amount in data.get("by_method", [])]
    return _mail(
        (f"Clôture de caisse - {data['restaurant']}" if fr else f"Cash shift closed - {data['restaurant']}"),
        lang,
        status=statut,
        greeting=_hello(lang, _nom(data)),
        paragraphs=[
            f"Le caissier {data['operator']} vient de clôturer sa caisse."
            if fr
            else f"{data['operator']} has just closed their cash shift."
        ],
        details=Details(
            title="Récapitulatif" if fr else "Summary",
            badge=str(data["restaurant"]),
            rows=rows,
        ),
        stats=[
            Stat("Total encaissé" if fr else "Total collected", montant_decimal(data["total"], cur, lang), cur),
            Stat("Écart" if fr else "Variance", montant_decimal(ecart, cur, lang), cur),
        ],
        action_label="Ouvrir la caisse" if fr else "Open cash desk",
        action_url=data.get("url"),
        signature=str(data["restaurant"]),
    )


# --------------------------------------------------------------------------- pressing


def pressing_order(data: Dict[str, Any], lang: str = "fr") -> Mail:
    """Commande de pressing. ``data`` : customer_name, pressing, order_number, stage
    (``received`` | ``ready`` | ``delivered``), deposit_at, ready_at, weight_kg?, total,
    paid, currency, url?"""
    fr = lang == "fr"
    cur = data.get("currency", "XAF")
    stage = data.get("stage", "received")
    restant = int(data["total"]) - int(data.get("paid", 0))
    statut = {
        "received": ("Commande reçue" if fr else "Order received", "info"),
        "ready": ("Prête à retirer" if fr else "Ready for pickup", "success"),
        "delivered": ("Commande remise" if fr else "Order handed over", "brand"),
    }[stage]
    corps = {
        "received": "Nous avons bien pris en charge votre linge. Nous vous prévenons dès qu'il est prêt."
        if fr
        else "We have received your laundry. We will let you know as soon as it is ready.",
        "ready": "Votre linge est propre et vous attend au comptoir."
        if fr
        else "Your laundry is clean and waiting at the counter.",
        "delivered": "Merci de votre confiance, à très bientôt !"
        if fr
        else "Thank you for your trust, see you soon!",
    }[stage]
    rows = []
    if data.get("weight_kg") is not None:
        rows.append(("Poids" if fr else "Weight", f"{data['weight_kg']} kg"))
    rows.append(("Déjà réglé" if fr else "Already paid", f"{montant(int(data.get('paid', 0)), cur, lang)} {cur}"))
    stats = [Stat("Total", montant(int(data["total"]), cur, lang), cur)]
    if restant > 0:
        stats.append(Stat("Reste à payer" if fr else "Balance due", montant(restant, cur, lang), cur))
    return _mail(
        f"{statut[0]} {data['order_number']} - {data['pressing']}",
        lang,
        status=Status(*statut),
        greeting=_hello(lang, _nom(data)),
        paragraphs=[corps],
        details=Details(
            title="Votre commande" if fr else "Your order",
            badge=str(data["order_number"]),
            hero=Hero(
                "Déposé" if fr else "Dropped off", _dt(data["deposit_at"], lang),
                "Retrait" if fr else "Pickup", _dt(data["ready_at"], lang),
            ),
            rows=rows,
        ),
        stats=stats,
        action_label="Suivre ma commande" if fr else "Track my order",
        action_url=data.get("url"),
        reference=str(data["order_number"]),
        signature=str(data["pressing"]),
    )


# --------------------------------------------------------------------------- divers


def delivery_test(data: Dict[str, Any], lang: str = "fr") -> Mail:
    fr = lang == "fr"
    return _mail(
        "Test d'envoi - Marinade" if fr else "Delivery test - Marinade",
        lang,
        status=Status("Envoi opérationnel" if fr else "Delivery working", "success"),
        greeting=_hello(lang, _nom(data)),
        paragraphs=[
            "Cet email confirme que l'envoi depuis Marinade fonctionne. Vous pouvez l'ignorer."
            if fr
            else "This email confirms that sending from Marinade works. You can ignore it."
        ],
        action_label="Ouvrir Marinade" if fr else "Open Marinade",
        action_url=_link("/login"),
        signature=_sign(lang),
    )


BUILDERS: Dict[str, Callable[[Dict[str, Any], str], Mail]] = {
    "welcome": welcome,
    "activation_code": activation_code,
    "verify_email": verify_email,
    "password_reset": password_reset,
    "password_changed": password_changed,
    "reservation": reservation,
    "order_receipt": order_receipt,
    "shift_closed": shift_closed,
    "pressing_order": pressing_order,
    "test": delivery_test,
}

SAMPLES: Dict[str, Dict[str, Any]] = {
    "welcome": {"first_name": "Brice"},
    "activation_code": {"first_name": "Brice", "code": "482913", "email": "brice@example.com"},
    "verify_email": {"first_name": "Brice", "token": "exemple-de-jeton"},
    "password_reset": {"first_name": "Brice", "token": "exemple-de-jeton"},
    "password_changed": {"first_name": "Brice"},
    "reservation": {
        "customer_name": "Brice Nanyang", "restaurant": "Le Grand Maquis", "date": "samedi 14 novembre 2026",
        "time": "20:00", "party_size": 4, "table": "T7", "reference": "RES-2026-00184",
        "kind": "confirmed", "url": "https://example.com/reservations/184",
    },
    "order_receipt": {
        "customer_name": "Brice Nanyang", "restaurant": "Le Grand Maquis", "order_number": "CMD-00412",
        "lines": [("Ndolé crevettes x2", 9000), ("Poulet DG x1", 6500), ("Jus de gingembre x3", 3000)],
        "total": 18500, "currency": "XAF", "payment_method": "Orange Money", "paid": True,
        "url": "https://example.com/commandes/412",
    },
    "shift_closed": {
        "first_name": "Brice", "restaurant": "Le Grand Maquis", "operator": "Aïcha Mbarga",
        "opened_at": "06/11/2026 10:00", "closed_at": "06/11/2026 22:15", "opening": 20000,
        "expected": 148500, "counted": 147000, "variance": -1500,
        "by_method": [("Espèces", 128500), ("Orange Money", 64000), ("MTN MoMo", 31500)],
        "total": 224000, "currency": "XAF", "url": "https://example.com/caisse",
    },
    "pressing_order": {
        "customer_name": "Brice Nanyang", "pressing": "Pressing Nyanga", "order_number": "PRS-00087",
        "stage": "ready", "deposit_at": "12/11/2026 09:30", "ready_at": "13/11/2026 17:00",
        "weight_kg": "6,5", "total": 7500, "paid": 2000, "currency": "XAF",
        "url": "https://example.com/pressing/87",
    },
    "test": {"first_name": "Brice"},
}


def build(name: str, data: Dict[str, Any], lang: Optional[str] = "fr") -> Mail:
    try:
        builder = BUILDERS[name]
    except KeyError:
        raise ValueError(f"Gabarit d'email inconnu : {name}") from None
    return builder(data, _lang(lang))


def send(
    name: str, to: str, data: Dict[str, Any], lang: Optional[str] = "fr", background: bool = True
) -> Optional[Dict[str, Any]]:
    """Construit et envoie un gabarit. En arrière-plan par défaut (retourne ``None``) ; en
    synchrone retourne le résultat du transport. Ne lève jamais pour une erreur d'envoi."""
    try:
        mail = build(name, data, lang)
        if background:
            email_service.send_email_async(to, mail.subject, mail.text, mail.html)
            return None
        return email_service.send_email(to, mail.subject, mail.text, mail.html)
    except Exception as exc:
        logger.warning(f"Email '{name}' non émis : {exc}")
        return {"success": False, "error": str(exc)} if not background else None


def send_after_commit(
    db: Session, name: str, to: str, data: Dict[str, Any], lang: Optional[str] = "fr"
) -> None:
    """Prépare l'email maintenant (les données sont lues dans la transaction) mais ne
    l'envoie qu'APRÈS le commit : jamais d'email pour une action finalement annulée. Un
    rollback abandonne l'envoi. Ne lève jamais."""
    try:
        mail = build(name, data, lang)
    except Exception as exc:
        logger.warning(f"Email '{name}' non préparé : {exc}")
        return

    # Les écouteurs restent attachés à la session (la retirer pendant l'appel modifie la
    # liste en cours de parcours) : un drapeau garantit « une seule fois ».
    etat = {"clos": False}

    def _fire(_session: Session) -> None:
        if etat["clos"]:
            return
        etat["clos"] = True
        email_service.send_email_async(to, mail.subject, mail.text, mail.html)

    def _cancel(_session: Session, previous_transaction: Any) -> None:
        # Un retour en arrière partiel (SAVEPOINT) n'annule pas la transaction entière.
        if getattr(previous_transaction, "parent", None) is None:
            etat["clos"] = True

    event.listen(db, "after_commit", _fire)
    event.listen(db, "after_soft_rollback", _cancel)
