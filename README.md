# Marinade API

API de gestion d'abonnements et transactions pour une solution de paiement.

## Technologies

- **Framework**: FastAPI 0.104.1
- **Base de données**: PostgreSQL avec SQLAlchemy 2.0.25
- **Authentification**: JWT avec python-jose et passlib
- **Migrations**: Alembic 1.13.0
- **Tests**: pytest

## Installation

```bash
# Installer les dépendances
pip install -r requirements.txt

# Configurer les variables d'environnement
cp .env.example .env
# Éditez .env avec vos configurations de base de données
# Les variables de base de données sont segmentées :
# DB_HOST=localhost
# DB_PORT=5432
# DB_NAME=marinade
# DB_USER=fairfairehq
# DB_PASSWORD=password
```

## Structure du projet

```
Marinade/
├── app/
│   ├── api/
│   │   ├── v1/
│   │   │   ├── auth.py          # Routes d'authentification
│   │   │   ├── users.py         # Routes utilisateurs
│   │   │   ├── subscriptions.py # Routes abonnements
│   │   │   └── transactions.py  # Routes transactions
│   │   ├── dependencies.py      # Dépendances d'authentification
│   │   └── router.py            # Routeur principal
│   ├── core/
│   │   └── database.py          # Configuration base de données
│   ├── models/
│   │   ├── user.py              # Modèle utilisateur
│   │   ├── subscription.py      # Modèles abonnement
│   │   └── transaction.py       # Modèles transaction
│   ├── repositories/
│   │   ├── base.py              # Repository de base
│   │   ├── user_repository.py   # Repository utilisateur
│   │   ├── subscription_repository.py # Repository abonnement
│   │   └── transaction_repository.py  # Repository transaction
│   ├── schemas/
│   │   ├── user.py              # Schémas utilisateur
│   │   ├── subscription.py      # Schémas abonnement
│   │   └── transaction.py       # Schémas transaction
│   ├── services/
│   │   ├── auth_service.py      # Service d'authentification
│   │   ├── user_service.py      # Service utilisateur
│   │   ├── subscription_service.py # Service abonnement
│   │   └── transaction_service.py  # Service transaction
│   ├── utils/
│   │   └── enums.py             # Énumérations
│   └── main.py                  # Point d'entrée FastAPI
├── alembic/
│   ├── versions/
│   │   └── 20260914_1200_initial_migration.py
│   └── env.py
├── tests/
│   └── test_main.py
├── requirements.txt
└── .env.example
```

## Fonctionnalités

### Authentification
- Inscription d'utilisateurs
- Connexion avec JWT
- Refresh tokens
- Déconnexion

### Gestion des utilisateurs
- CRUD utilisateurs
- Rôles : admin, pos (Point of Sale)
- Validation email et téléphone

### Abonnements
- Gestion des tiers d'abonnement
- Création d'abonnements utilisateurs
- Suivi des soldes quotidiens
- Gestion des statuts (pending, active, suspended, cancelled, expired)

### Transactions
- Création de transactions
- Idempotency keys pour éviter les doublons
- Validation des soldes quotidiens
- Historique des transactions

## API Endpoints

### Authentification
- `POST /v1/auth/register` - Inscription
- `POST /v1/auth/login` - Connexion
- `POST /v1/auth/refresh` - Rafraîchir le token
- `POST /v1/auth/logout` - Déconnexion

### Utilisateurs
- `GET /v1/users/` - Liste des utilisateurs (admin)
- `GET /v1/users/me` - Profil utilisateur
- `GET /v1/users/{user_id}` - Détails utilisateur (admin)
- `POST /v1/users/` - Créer utilisateur (admin)
- `PUT /v1/users/{user_id}` - Modifier utilisateur (admin)
- `DELETE /v1/users/{user_id}` - Supprimer utilisateur (admin)

### Abonnements
- `GET /v1/subscriptions/tiers` - Liste des tiers
- `GET /v1/subscriptions/tiers/{tier_id}` - Détails tier
- `POST /v1/subscriptions/tiers` - Créer tier (admin)
- `PUT /v1/subscriptions/tiers/{tier_id}` - Modifier tier (admin)
- `GET /v1/subscriptions/me` - Mon abonnement
- `POST /v1/subscriptions/` - Créer abonnement (admin)
- `PUT /v1/subscriptions/{subscription_id}/status` - Modifier statut (admin)
- `GET /v1/subscriptions/{subscription_id}/balances` - Soldes
- `POST /v1/subscriptions/{subscription_id}/reset` - Reset quotidien (admin)

### Transactions
- `POST /v1/transactions/` - Créer transaction (POS)
- `GET /v1/transactions/{transaction_id}` - Détails transaction
- `GET /v1/transactions/subscription/{subscription_id}` - Transactions abonnement
- `GET /v1/transactions/pos/{pos_transaction_id}` - Transaction POS
- `GET /v1/transactions/my` - Mes transactions

## Migrations de base de données

```bash
# Appliquer les migrations
alembic upgrade head

# Créer une nouvelle migration
alembic revision --autogenerate -m "description"

# Annuler la dernière migration
alembic downgrade -1
```

## Lancer l'application

```bash
# En développement
python -m app.main

# Avec uvicorn
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

La documentation API sera disponible sur `http://localhost:8000/docs`

## Tests

```bash
# Lancer les tests
pytest

# Tests avec détails
pytest -v
```

## Configuration

Variables d'environnement dans `.env`:
- `DATABASE_URL` - URL de connexion PostgreSQL
- `SECRET_KEY` - Clé secrète pour JWT
- `ACCESS_TOKEN_EXPIRE_MINUTES` - Durée de vie des access tokens
- `REFRESH_TOKEN_EXPIRE_DAYS` - Durée de vie des refresh tokens
- `SKIP_DB_INIT` - Skip l'initialisation automatique de la DB (true/false)

## Sécurité

- Mot de passe hashé avec bcrypt
- Tokens JWT avec expiration
- Validation des entrées avec Pydantic
- Protection CORS configurable
- Rôles d'accès (admin, pos)
