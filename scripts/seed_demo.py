"""Donnees de demonstration : un super-admin, deux restaurants et leur equipe.

    python -m scripts.seed_demo            # cree ou met a jour (idempotent)
    python -m scripts.seed_demo --reset    # supprime d'abord les donnees demo

Le script se connecte comme l'application (DB_* du .env), donc SOUS RLS : il declare
explicitement le contexte administrateur de plateforme pour ses ecritures, exactement
comme le ferait une session admin. Il refuse de tourner en production.

Les comptes ci-dessous ont des mots de passe publics : uniquement pour le developpement.
"""

import argparse
import sys
import uuid
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.sql import func

from app.core.config import settings
from app.core.database import get_session_local, set_db_contexts
from app.models.restaurant import Boisson, Menu, MenuCategory, Plat, Restaurant, Table
from app.models.tenant import RestaurantMember
from app.models.user import User
from app.schemas.user import normalize_phone
from app.services.auth_service import pwd_context

PASSWORD = "Changeme@2026"
DOMAIN = "demo.marinade.test"

# (email local-part, prenom, nom, telephone, role du compte, role dans l'equipe)
ADMIN = ("superadmin", "Super", "Admin", "+237670000001")

RESTAURANTS = [
    {
        "name": "Chez Marinade (demo)",
        "slug": "chez",
        "city": "Douala",
        "owner": ("proprietaire", "Paul", "Mbarga", "+237670000010"),
        "team": [
            ("manager", "Manu", "Ngono", "+237670000011", "manager", "manager"),
            ("caissier", "Carine", "Fotso", "+237670000012", "cashier", "cashier"),
            ("serveur", "Serge", "Eto", "+237670000013", "waiter", "waiter"),
            ("chef", "Charles", "Biya", "+237670000014", "chef", "chef"),
            ("barman", "Boris", "Tchoua", "+237670000015", "waiter", "bartender"),
        ],
        "plats": [
            ("Ndole viande", "Ndole aux arachides, plantain", 3500, 25),
            ("Poulet DG", "Poulet saute, plantains murs", 5000, 30),
            ("Poisson braise", "Bar braise, miondo", 4500, 35),
            ("Eru et water fufu", "Eru, viande fumee", 3000, 25),
        ],
        "boissons": [
            ("Biere 33", False, "biere", 1000),
            ("Coca-Cola", False, "soda", 600),
            ("Jus de gingembre", False, "jus", 500),
            ("Whisky shot", True, "spiritueux", 2000),
        ],
        "tables": 8,
    },
    {
        # Second restaurant : sert a verifier a la main que rien ne fuit entre les deux.
        "name": "Concurrent (demo)",
        "slug": "rival",
        "city": "Yaounde",
        "owner": ("rival", "Rita", "Atangana", "+237670000020"),
        "team": [
            ("rival.caissier", "Remy", "Kamga", "+237670000021", "cashier", "cashier"),
        ],
        "plats": [("Sandwich club", "Pain, poulet, crudites", 2500, 10)],
        "boissons": [("Eau 1,5 L", False, "eau", 500)],
        "tables": 3,
    },
]


def email(local: str) -> str:
    return f"{local}@{DOMAIN}"


def upsert_user(db, local, first, last, phone, role, hashed) -> User:
    user = db.query(User).filter(User.email == email(local)).one_or_none()
    values = dict(
        first_name=first,
        last_name=last,
        phone=normalize_phone(phone),
        role=role,
        password_hash=hashed,
        is_active=True,
        is_deleted=False,
        deleted_at=None,
        email_verified_at=func.now(),
        phone_verified_at=func.now(),
    )
    if user is None:
        user = User(id=uuid.uuid4(), email=email(local), **values)
        db.add(user)
    else:
        for key, value in values.items():
            setattr(user, key, value)
    db.flush()
    return user


def seed_restaurant(db, spec, hashed) -> dict:
    owner = upsert_user(db, *spec["owner"][:1], *spec["owner"][1:], "restaurant", hashed)
    restaurant = db.query(Restaurant).filter(Restaurant.user_id == owner.id).one_or_none()
    if restaurant is None:
        restaurant = Restaurant(
            id=uuid.uuid4(), user_id=owner.id, name=spec["name"], currency="XAF"
        )
        db.add(restaurant)
    restaurant.name = spec["name"]
    restaurant.city = spec["city"]
    restaurant.country = "Cameroun"
    restaurant.is_active = True
    db.flush()

    for local, first, last, phone, role, staff_role in spec["team"]:
        member_user = upsert_user(db, local, first, last, phone, role, hashed)
        member = (
            db.query(RestaurantMember)
            .filter_by(restaurant_id=restaurant.id, user_id=member_user.id)
            .one_or_none()
        )
        if member is None:
            member = RestaurantMember(
                id=uuid.uuid4(), restaurant_id=restaurant.id, user_id=member_user.id
            )
            db.add(member)
        member.role = staff_role
        member.staff_role = staff_role
        member.is_active = True

    menu = (
        db.query(Menu)
        .filter_by(restaurant_id=restaurant.id, name="Carte")
        .one_or_none()
    )
    if menu is None:
        menu = Menu(id=uuid.uuid4(), restaurant_id=restaurant.id, name="Carte", actif=True)
        db.add(menu)
        db.flush()
    category = (
        db.query(MenuCategory)
        .filter_by(restaurant_id=restaurant.id, menu_id=menu.id, name="Plats")
        .one_or_none()
    )
    if category is None:
        category = MenuCategory(
            id=uuid.uuid4(), restaurant_id=restaurant.id, menu_id=menu.id, name="Plats"
        )
        db.add(category)
        db.flush()

    for nom, description, prix, minutes in spec["plats"]:
        exists = (
            db.query(Plat.id)
            .filter_by(restaurant_id=restaurant.id, nom=nom)
            .filter(Plat.deleted_at.is_(None))
            .first()
        )
        if not exists:
            db.add(
                Plat(
                    id=uuid.uuid4(),
                    restaurant_id=restaurant.id,
                    category_id=category.id,
                    nom=nom,
                    description=description,
                    prix=Decimal(prix),
                    temps_preparation=minutes,
                )
            )
    for nom, alcool, categorie, prix in spec["boissons"]:
        exists = (
            db.query(Boisson.id)
            .filter_by(restaurant_id=restaurant.id, nom=nom)
            .filter(Boisson.deleted_at.is_(None))
            .first()
        )
        if not exists:
            db.add(
                Boisson(
                    id=uuid.uuid4(),
                    restaurant_id=restaurant.id,
                    nom=nom,
                    alcool=alcool,
                    category=categorie,
                    prix=Decimal(prix),
                )
            )
    for number in range(1, spec["tables"] + 1):
        numero = f"T{number}"
        exists = (
            db.query(Table.id)
            .filter_by(restaurant_id=restaurant.id, numero=numero)
            .filter(Table.deleted_at.is_(None))
            .first()
        )
        if not exists:
            db.add(
                Table(
                    id=uuid.uuid4(),
                    restaurant_id=restaurant.id,
                    numero=numero,
                    capacite=4 if number % 3 else 6,
                    emplacement="salle" if number <= spec["tables"] // 2 else "terrasse",
                )
            )
    db.flush()
    return {"restaurant": restaurant, "owner": owner}


def reset(db) -> None:
    ids = [
        row[0]
        for row in db.execute(
            text("SELECT id FROM users WHERE email LIKE :pattern"),
            {"pattern": f"%@{DOMAIN}"},
        )
    ]
    if not ids:
        return
    # restaurants.user_id et restaurant_members.user_id cascadent vers le reste.
    db.execute(text("DELETE FROM restaurants WHERE user_id = ANY(:ids)"), {"ids": ids})
    db.execute(text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": ids})


# Repartition realiste des statuts d'un restaurant : surtout des succes.
PAYMENT_MIX = (
    ("success", 62), ("failed", 11), ("pending", 8), ("processing", 4),
    ("timeout", 5), ("expired", 3), ("refunded", 4), ("reversed", 3),
)
FAILURE_REASONS = (
    "Solde insuffisant", "Transaction refusee par l'operateur",
    "Code PIN incorrect", "Delai de confirmation depasse",
)
FINISHED = {"success", "failed", "timeout", "expired", "refunded", "reversed"}


def seed_payments(db, restaurant, count: int) -> int:
    """Cree des paiements fictifs pour `restaurant` jusqu'a en avoir `count` (idempotent)."""
    import random
    from datetime import datetime, timedelta, timezone

    from app.models.payment import PaymentConfiguration, PaymentEvent, PaymentIntent
    from app.utils.payment_references import new_reference_prefix, new_vendor_reference

    config = db.query(PaymentConfiguration).filter_by(restaurant_id=restaurant.id).one_or_none()
    if config is None:
        config = PaymentConfiguration(
            id=uuid.uuid4(),
            restaurant_id=restaurant.id,
            vendor_reference_prefix=new_reference_prefix(),
        )
        db.add(config)
        db.flush()

    existing = db.query(PaymentIntent).filter_by(restaurant_id=restaurant.id).count()
    rng = random.Random(str(restaurant.id))
    statuses = [s for s, weight in PAYMENT_MIX for _ in range(weight)]
    now = datetime.now(timezone.utc)
    created = 0

    for _ in range(max(0, count - existing)):
        status = rng.choice(statuses)
        amount = rng.choice((1500, 2000, 3500, 5000, 7500, 12000, 18500, 25000))
        # Les plus recents d'abord : 14 jours d'historique, dense aujourd'hui.
        born = now - timedelta(minutes=int(rng.expovariate(1 / (60 * 24 * 3))) + 1)
        finished = status in FINISHED
        fees = (Decimal(amount) * Decimal("0.02")).quantize(Decimal("1")) if status in ("success", "refunded") else None
        intent = PaymentIntent(
            id=uuid.uuid4(),
            restaurant_id=restaurant.id,
            provider="easytransact",
            vendor_reference=new_vendor_reference(config.vendor_reference_prefix, born),
            idempotency_key=f"demo-{uuid.uuid4()}",
            amount_fcfa=amount,
            currency="XAF",
            status=status,
            fees_fcfa=fees,
            fees_inclusive=True if fees is not None else None,
            completed_at=born + timedelta(seconds=rng.randint(8, 70)) if finished else None,
            failure_reason=rng.choice(FAILURE_REASONS) if status == "failed" else None,
            provider_transaction_id=f"ET-{uuid.uuid4().hex[:10].upper()}" if finished else None,
            created_at=born,
            updated_at=born,
        )
        db.add(intent)
        db.flush()
        for step in (["pending"] if status in ("pending", "processing") else ["pending", status]):
            db.add(
                PaymentEvent(
                    id=uuid.uuid4(),
                    payment_intent_id=intent.id,
                    provider_event_id=f"demo-{uuid.uuid4()}",
                    provider_status=step,
                    received_at=born + timedelta(seconds=3 if step == "pending" else 20),
                    processed_at=born + timedelta(seconds=3 if step == "pending" else 20),
                )
            )
        created += 1
    db.flush()
    return created


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reset", action="store_true", help="supprimer les donnees demo d'abord")
    parser.add_argument(
        "--with-payments", action="store_true",
        help="ajouter des paiements fictifs (80 pour le restaurant principal, 6 pour le concurrent)",
    )
    args = parser.parse_args()

    if settings.is_production:
        print("Refus : ENVIRONMENT designe la production.", file=sys.stderr)
        return 1

    hashed = pwd_context.hash(PASSWORD)
    db = get_session_local()()
    try:
        set_db_contexts(db, {"app.is_platform_admin": "true"})
        if args.reset:
            reset(db)
        local, first, last, phone = ADMIN
        upsert_user(db, local, first, last, phone, "admin", hashed)
        seeded = [seed_restaurant(db, spec, hashed) for spec in RESTAURANTS]
        if args.with_payments:
            for spec, result in zip(RESTAURANTS, seeded):
                count = 80 if spec["slug"] == "chez" else 6
                made = seed_payments(db, result["restaurant"], count)
                print(f"  {spec['name']} : {made} paiement(s) ajoute(s)")
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    print(f"Mot de passe de tous les comptes : {PASSWORD}\n")
    print(f"  super-admin    {email(ADMIN[0])}")
    for spec, result in zip(RESTAURANTS, seeded):
        print(f"\n  {spec['name']}  (restaurant_id = {result['restaurant'].id})")
        print(f"    proprietaire  {email(spec['owner'][0])}")
        for local, _f, _l, _p, _role, staff_role in spec["team"]:
            print(f"    {staff_role:<12}  {email(local)}")
    print("\nConnexion : POST /v1/auth/login  {\"email\": ..., \"password\": ...}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
