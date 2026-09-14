# Marinade - Configuration et Guide du Projet

## Vue d'ensemble du Projet

Marinade est une API FastAPI de gestion d'abonnements et transactions pour les points de vente avec authentification JWT et contrôle des soldes quotidiens, adaptée spécifiquement pour les restaurants avec gestion complète de menus, boissons, tables et commandes.

## Structure du Projet

```
Marinade/
├── app/
│   ├── api/                      # Routes API
│   │   ├── v1/                  # Version 1 de l'API
│   │   │   ├── auth.py          # Authentification
│   │   │   ├── users.py         # Gestion utilisateurs
│   │   │   ├── subscriptions.py # Gestion abonnements
│   │   │   ├── transactions.py  # Gestion transactions
│   │   │   └── restaurants.py   # Gestion restaurants (NEW)
│   │   ├── dependencies.py      # Dépendances d'authentification
│   │   ├── exception_handlers.py # Gestion des erreurs
│   │   └── router.py            # Routeur principal
│   ├── core/                     # Configuration centrale
│   │   ├── config.py            # Configuration avec pydantic-settings
│   │   └── database.py          # Configuration base de données
│   ├── models/                   # Modèles SQLAlchemy
│   │   ├── user.py              # Modèle utilisateur
│   │   ├── subscription.py      # Modèles abonnement
│   │   ├── transaction.py       # Modèles transaction
│   │   └── restaurant.py        # Modèles restaurant (NEW)
│   ├── repositories/             # Accès aux données
│   │   ├── base.py              # Repository de base
│   │   ├── user_repository.py   # Repository utilisateur
│   │   ├── subscription_repository.py # Repository abonnement
│   │   ├── transaction_repository.py  # Repository transaction
│   │   └── restaurant_repository.py  # Repository restaurant (NEW)
│   ├── schemas/                  # Schémas Pydantic
│   │   ├── user.py              # Schémas utilisateur
│   │   ├── subscription.py      # Schémas abonnement
│   │   ├── transaction.py       # Schémas transaction
│   │   └── restaurant.py        # Schémas restaurant (NEW)
│   ├── services/                 # Logique métier
│   │   ├── auth_service.py      # Service authentification
│   │   ├── user_service.py      # Service utilisateur
│   │   ├── subscription_service.py # Service abonnement
│   │   ├── transaction_service.py  # Service transaction
│   │   └── restaurant_service.py  # Service restaurant (NEW)
│   ├── utils/                    # Utilitaires
│   │   ├── enums.py             # Énumérations
│   │   ├── logging.py           # Configuration logging
│   │   └── exceptions.py        # Exceptions personnalisées
│   └── main.py                   # Point d'entrée FastAPI
├── alembic/                      # Migrations de base de données
│   ├── versions/                # Fichiers de migration
│   └── env.py                   # Configuration Alembic
├── tests/                        # Tests
│   └── test_main.py             # Tests principaux
├── .env.example                  # Exemple de configuration
├── requirements.txt              # Dépendances Python
├── alembic.ini                   # Configuration Alembic
└── README.md                     # Documentation du projet
```

## Configuration de l'Environnement

### Variables d'Environnement Requises

```bash
# Base de données (segmentée)
DB_HOST=localhost
DB_PORT=5432
DB_NAME=marinade
DB_USER=fairfairehq
DB_PASSWORD=password

# Sécurité
SECRET_KEY=your-secret-key-here-change-this-in-production
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

# Application
APP_NAME=Marinade API
APP_VERSION=1.0.0
DEBUG=true
ENVIRONMENT=development

# Initialisation base de données
SKIP_DB_INIT=true

# CORS
ALLOW_ORIGINS=*
ALLOW_CREDENTIALS=true
ALLOW_METHODS=*
ALLOW_HEADERS=*

# Serveur
HOST=0.0.0.0
PORT=8000
```

## Commandes de Développement

### Installation
```bash
pip install -r requirements.txt
cp .env.example .env
# Éditer .env avec vos configurations
```

### Lancer l'Application
```bash
python -m app.main
# Ou avec uvicorn
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Migrations de Base de Données
```bash
# Créer une nouvelle migration
alembic revision --autogenerate -m "description"

# Appliquer les migrations
alembic upgrade head

# Annuler la dernière migration
alembic downgrade -1
```

### Tests
```bash
# Lancer tous les tests
pytest

# Tests avec détails
pytest -v

# Tests spécifiques
pytest tests/test_main.py::test_email_validation
```

## Points d'Accès API

### Authentification
- `POST /v1/auth/register` - Inscription
- `POST /v1/auth/login` - Connexion
- `POST /v1/auth/refresh` - Rafraîchir token
- `POST /v1/auth/logout` - Déconnexion

### Utilisateurs
- `GET /v1/users/` - Liste utilisateurs (admin)
- `GET /v1/users/me` - Profil utilisateur
- `GET /v1/users/{user_id}` - Détails utilisateur (admin)
- `POST /v1/users/` - Créer utilisateur (admin)
- `PUT /v1/users/{user_id}` - Modifier utilisateur (admin)
- `DELETE /v1/users/{user_id}` - Supprimer utilisateur (admin)

### Abonnements
- `GET /v1/subscriptions/tiers` - Liste des tiers
- `POST /v1/subscriptions/tiers` - Créer tier (admin)
- `GET /v1/subscriptions/me` - Mon abonnement
- `POST /v1/subscriptions/` - Créer abonnement (admin)
- `PUT /v1/subscriptions/{id}/status` - Modifier statut (admin)

### Transactions
- `POST /v1/transactions/` - Créer transaction (POS)
- `GET /v1/transactions/{id}` - Détails transaction
- `GET /v1/transactions/my` - Mes transactions

### Restaurants (NOUVEAU)
- `POST /v1/restaurants/` - Créer restaurant
- `GET /v1/restaurants/me` - Mon restaurant
- `PUT /v1/restaurants/{id}` - Modifier restaurant
- `POST /v1/restaurants/{id}/menus` - Créer menu
- `GET /v1/restaurants/{id}/menus` - Lister menus
- `POST /v1/restaurants/menus/{id}/categories` - Créer catégorie
- `POST /v1/restaurants/{id}/plats` - Créer plat
- `GET /v1/restaurants/{id}/plats` - Lister plats
- `POST /v1/restaurants/{id}/boissons` - Créer boisson
- `GET /v1/restaurants/{id}/boissons` - Lister boissons
- `POST /v1/restaurants/{id}/tables` - Créer table
- `GET /v1/restaurants/{id}/tables` - Lister tables
- `GET /v1/restaurants/{id}/tables/free` - Tables libres
- `POST /v1/restaurants/{id}/commandes` - Créer commande
- `GET /v1/restaurants/{id}/commandes` - Lister commandes

## Architecture en Couches

1. **API Layer** (`app/api/`) - Routes FastAPI et validation des requêtes
2. **Service Layer** (`app/services/`) - Logique métier et orchestration
3. **Repository Layer** (`app/repositories/`) - Accès aux données avec SQLAlchemy
4. **Model Layer** (`app/models/`) - Définition des schémas de base de données
5. **Schema Layer** (`app/schemas/`) - Validation Pydantic des données

## Gestion des Erreurs

Le système utilise des exceptions personnalisées :
- `AuthenticationError` - Erreurs d'authentification
- `AuthorizationError` - Erreurs d'autorisation
- `ValidationError` - Erreurs de validation
- `NotFoundError` - Ressource non trouvée
- `ConflictError` - Conflits (doublons, etc.)
- `BusinessLogicError` - Erreurs métier
- `DatabaseError` - Erreurs de base de données

## Logging

Le système de logging est configuré dans `app/utils/logging.py` :
- Niveau de log basé sur `DEBUG` settings
- Format structuré avec timestamp
- Log des opérations importantes dans les services

## Sécurité

- Mot de passe hashé avec bcrypt
- Tokens JWT avec expiration configurable
- Validation des emails avec vérification supplémentaire
- Protection CORS configurable
- Rôles d'accès (admin, pos, restaurant)

## Guide Restaurant

Pour la personnalisation spécifique aux restaurants, voir `RESTAURANT_GUIDE.md` :
- Configuration complète des menus, plats, boissons
- Gestion des tables et commandes
- Personnalisation par restaurant
- Exemples d'API et scénarios d'utilisation

## Notes Importantes

- La configuration base de données est segmentée pour plus de flexibilité
- Le SECRET_KEY doit être défini en production
- Les tests utilisent des variables d'environnement pour éviter les dépendances externes
- L'initialisation automatique de la base de données peut être désactivée avec `SKIP_DB_INIT=true`
- Utilisez Alembic pour les migrations en production
