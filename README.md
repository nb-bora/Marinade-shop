# Marinade API

Marinade est une API FastAPI de gestion d'abonnements, de transactions et d'exploitation de restaurants.
Elle fournit un socle pour gérer les utilisateurs, les droits d'accès, les offres d'abonnement, les soldes, les points de vente, les menus, les combinaisons de repas, le stock, les commandes et les paiements.

Le domaine restaurant est conçu autour d'un catalogue composable : un administrateur peut définir une combinaison comme `riz + sauce tomate + poulet`, lui attribuer un prix, gérer la disponibilité de chaque composant et facturer les suppléments demandés par le client.

## Sommaire

- [Positionnement](#positionnement)
- [Fonctionnalités](#fonctionnalités)
- [Architecture](#architecture)
- [Prérequis](#prérequis)
- [Installation](#installation)
- [Configuration](#configuration)
- [Lancement](#lancement)
- [Documentation Swagger](#documentation-swagger)
- [Authentification et rôles](#authentification-et-rôles)
- [Parcours métier](#parcours-métier)
- [API disponible](#api-disponible)
- [Catalogue composé et stock](#catalogue-composé-et-stock)
- [Paiements et notifications](#paiements-et-notifications)
- [Migrations Alembic](#migrations-alembic)
- [Tests](#tests)
- [Sécurité et production](#sécurité-et-production)
- [Dépannage](#dépannage)
- [Évolutions recommandées](#évolutions-recommandées)

## Positionnement

Marinade doit être compris comme un noyau de **Restaurant Operating System** :

```text
Authentification et rôles
        |
Abonnements et transactions
        |
Restaurant et catalogue
        |
Composants -> Combinaisons -> Commandes -> Paiement
                    |
               Stock réservé
```

Le système est adapté aux restaurants qui vendent des repas personnalisables et doivent gérer des composants variables : bases, sauces, protéines, accompagnements et suppléments.

## Fonctionnalités

### Plateforme et comptes

- Inscription, connexion, refresh token et déconnexion.
- Authentification JWT.
- Gestion des utilisateurs et des rôles.
- Validation des emails, téléphones et mots de passe.
- Gestion centralisée des erreurs métier.

### Abonnements et transactions

- Création et gestion des offres d'abonnement.
- Statuts `pending`, `active`, `suspended`, `cancelled`, `expired`.
- Soldes quotidiens et réinitialisation des compteurs.
- Transactions avec identifiants d'idempotence côté domaine transactionnel.

### Restaurants

- Création et mise à jour d'un restaurant.
- Menus et catégories.
- Plats et boissons avec prix et disponibilité.
- Tables, occupation et libération après clôture de commande.
- Commandes, items et statuts de service.

### Catalogue composé

- Composants comme riz, sauce tomate, sauce d'arachide, poulet, poisson ou émincé.
- Combinaisons tarifées.
- Suppléments tarifés côté serveur.
- Recommandations filtrées par disponibilité.
- Stock physique, stock réservé et mouvements de stock.
- Consommation du stock au paiement et libération à l'annulation.

### Paiements et notifications

- Abstraction pour espèces, Orange Money et mobile money.
- Abstraction de notification email, SMS et WhatsApp.
- Templates de notifications pour commande, paiement et inscription.
- Les adaptateurs externes doivent encore être configurés avec les credentials et contrats réels des fournisseurs.

## Architecture

Le projet suit une architecture en couches :

```text
app/api/          Routes FastAPI et validation HTTP
app/schemas/      Contrats Pydantic des requêtes et réponses
app/services/     Règles métier et orchestration
app/repositories/ Accès SQLAlchemy à la base
app/models/       Modèles persistants
app/core/         Configuration et base de données
app/utils/        Exceptions, enums, paiements et notifications
alembic/          Historique des migrations
tests/            Tests automatisés
```

### Structure importante

```text
app/
├── api/v1/
│   ├── auth.py
│   ├── users.py
│   ├── subscriptions.py
│   ├── transactions.py
│   └── restaurants.py
├── core/
│   ├── config.py
│   └── database.py
├── models/
│   ├── user.py
│   ├── subscription.py
│   ├── transaction.py
│   └── restaurant.py
├── repositories/
├── schemas/
├── services/
└── utils/
```

## Prérequis

- Python 3.13 recommandé.
- PostgreSQL 14 ou version supérieure.
- `pip` et un environnement virtuel Python.
- Une base PostgreSQL vide ou accessible.
- Une clé secrète JWT propre à l'environnement.

Python 3.14 peut provoquer des incompatibilités avec certaines versions de SQLAlchemy et de leurs dépendances. Pour reproduire l'environnement validé, utiliser Python 3.13.

## Installation

### Windows PowerShell

```powershell
py -3.13 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

### Linux ou macOS

```bash
python3.13 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

Après la copie, modifier `.env` avec les paramètres de PostgreSQL et une vraie clé secrète.

## Configuration

Les paramètres sont lus depuis `.env` par `app/core/config.py`.

| Variable | Exemple | Rôle |
|---|---|---|
| `DB_HOST` | `localhost` | Hôte PostgreSQL |
| `DB_PORT` | `5432` | Port PostgreSQL |
| `DB_NAME` | `marinade` | Nom de la base |
| `DB_USER` | `postgres` | Utilisateur PostgreSQL |
| `DB_PASSWORD` | `postgres` | Mot de passe PostgreSQL |
| `SECRET_KEY` | valeur longue aléatoire | Signature JWT |
| `ALGORITHM` | `HS256` | Algorithme JWT |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Durée de l'access token |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Durée du refresh token |
| `APP_NAME` | `Marinade API` | Nom de l'application |
| `APP_VERSION` | `1.0.0` | Version affichée |
| `DEBUG` | `true` | Mode debug |
| `ENVIRONMENT` | `development` | Environnement courant |
| `SKIP_DB_INIT` | `true` | Ne pas créer automatiquement les tables |
| `ALLOW_ORIGINS` | `http://localhost:3000` | Origines CORS autorisées |
| `ALLOW_CREDENTIALS` | `true` | Credentials CORS |
| `ALLOW_METHODS` | `*` | Méthodes CORS |
| `ALLOW_HEADERS` | `*` | Headers CORS |
| `HOST` | `0.0.0.0` | Adresse d'écoute |
| `PORT` | `8000` | Port applicatif |

### Configuration locale recommandée

```dotenv
DB_HOST=localhost
DB_PORT=5432
DB_NAME=marinade
DB_USER=postgres
DB_PASSWORD=postgres

SECRET_KEY=changez-cette-valeur-avec-une-cle-longue-et-aleatoire
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

APP_NAME=Marinade API
APP_VERSION=1.0.0
DEBUG=true
ENVIRONMENT=development
SKIP_DB_INIT=true

ALLOW_ORIGINS=http://localhost:3000
ALLOW_CREDENTIALS=true
ALLOW_METHODS=*
ALLOW_HEADERS=*

HOST=0.0.0.0
PORT=8001
```

Ne jamais utiliser `SECRET_KEY` par défaut en production. Ne jamais committer `.env`.

## Lancement

### Port 8000

```powershell
.\venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Port 8001

```powershell
.\venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

Ou définir `PORT=8001` et lancer :

```powershell
python -m app.main
```

L'application expose alors :

- API : `http://localhost:8001`
- Swagger UI : `http://localhost:8001/docs`
- ReDoc : `http://localhost:8001/redoc`
- OpenAPI JSON : `http://localhost:8001/openapi.json`
- Santé : `http://localhost:8001/health`

## Documentation Swagger

Swagger est la référence interactive pour les contrats HTTP.

1. Lancer l'API.
2. Ouvrir `/docs`.
3. Appeler `/v1/auth/login`.
4. Copier `access_token`.
5. Cliquer sur **Authorize**.
6. Saisir `Bearer <access_token>`.
7. Tester les endpoints protégés.

Les routes sont regroupées par domaines : authentification, utilisateurs, abonnements, transactions, restaurants, menus, plats, boissons, tables, commandes, combinaisons et stock.

## Authentification et rôles

### Inscription

```http
POST /v1/auth/register
Content-Type: application/json
```

```json
{
  "email": "gerant@example.com",
  "phone": "+237600000000",
  "password": "MotDePasseFort123!",
  "first_name": "Jean",
  "last_name": "Dupont",
  "role": "restaurant"
}
```

### Connexion

```http
POST /v1/auth/login
Content-Type: application/json
```

```json
{
  "email": "gerant@example.com",
  "password": "MotDePasseFort123!"
}
```

La réponse contient un `access_token` et un `refresh_token`.

### Utilisation du token

```http
Authorization: Bearer <access_token>
```

Rôles utilisés par le projet :

- `admin` : administration globale.
- `pos` : opérations de point de vente et transactions.
- `restaurant` : gestion opérationnelle d'un restaurant.

Toute route de gestion doit idéalement vérifier à la fois le rôle et l'appartenance au restaurant concerné. Cette isolation fine reste un point de durcissement obligatoire avant la production multi-tenant.

## Parcours métier

### Scénario 1 : créer un restaurant

```http
POST /v1/restaurants
Authorization: Bearer <access_token>
```

```json
{
  "name": "Chez Marinade",
  "description": "Cuisine africaine traditionnelle",
  "currency": "XAF",
  "phone": "+237600000000",
  "city": "Douala",
  "country": "Cameroun",
  "taux_service": 10
}
```

Conserver l'identifiant `restaurant_id` retourné : il sera utilisé pour le catalogue, le stock et les commandes.

### Scénario 2 : créer un menu et ses catégories

```http
POST /v1/restaurants/{restaurant_id}/menus
```

```json
{
  "name": "Menu du jour",
  "description": "Formules servies le midi",
  "actif": true
}
```

Puis créer les catégories : `Bases`, `Sauces`, `Protéines`, `Boissons`.

### Scénario 3 : vendre des plats simples

Créer un plat avec `POST /v1/restaurants/{restaurant_id}/plats` :

```json
{
  "nom": "Poulet braisé",
  "description": "Poulet braisé aux épices",
  "prix": 4500,
  "devise": "XAF",
  "disponible": true,
  "category_id": "<category_id>"
}
```

Le plat peut ensuite être ajouté directement à une commande avec `plat_id`.

### Scénario 4 : créer le catalogue composé

Créer séparément les composants :

```http
POST /v1/restaurants/{restaurant_id}/composants
```

```json
{
  "nom": "Poulet",
  "type": "proteine",
  "prix_supplement": 1000,
  "devise": "XAF",
  "stock_unite": "portion",
  "disponible": true
}
```

Répéter pour `riz`, `sauce tomate`, `sauce arachide`, `poisson` et `émincé`.

Créer ensuite une combinaison :

```http
POST /v1/restaurants/{restaurant_id}/combinaisons
```

```json
{
  "nom": "Riz sauce tomate poulet",
  "description": "Riz accompagné de sauce tomate et poulet",
  "prix": 3500,
  "devise": "XAF",
  "disponible": true,
  "menu_id": "<menu_id>",
  "composant_ids": [
    "<riz_id>",
    "<sauce_tomate_id>",
    "<poulet_id>"
  ]
}
```

Le prix `3500 XAF` est le prix de base de la combinaison. Il ne doit jamais être accepté depuis la requête de commande.

### Scénario 5 : approvisionner le stock

```http
POST /v1/restaurants/composants/{composant_id}/stock/mouvements
Authorization: Bearer <access_token>
```

```json
{
  "type": "entree",
  "quantite": 50,
  "notes": "Approvisionnement du matin"
}
```

Types de mouvement disponibles :

- `entree` : ajoute une quantité au stock physique.
- `ajustement` : remplace le stock physique par la quantité indiquée.
- `perte` : retire une quantité disponible pour perte ou gaspillage.

Consulter le stock :

```http
GET /v1/restaurants/{restaurant_id}/stock
```

Le résultat distingue :

```text
quantite   = stock physique
reservee   = stock engagé par les commandes en cours
disponible = quantite - reservee
```

### Scénario 6 : recommander uniquement les offres vendables

```http
GET /v1/restaurants/{restaurant_id}/combinaisons/recommandations
```

Une combinaison est recommandée si elle est active et si ses composants obligatoires sont disponibles.
Si la sauce tomate est désactivée ou épuisée, les combinaisons qui la nécessitent ne doivent plus être proposées.

### Scénario 7 : commander une combinaison avec supplément

Créer d'abord la commande :

```http
POST /v1/restaurants/{restaurant_id}/commandes
```

```json
{
  "table_id": "<table_id>",
  "statut": "en_cours",
  "total": 0
}
```

Ajouter une combinaison et un supplément :

```http
POST /v1/restaurants/commandes/{commande_id}/items
```

```json
{
  "combinaison_id": "<combinaison_id>",
  "quantite": 2,
  "supplement_ids": ["<poisson_id>"],
  "notes": "Sans piment"
}
```

Le serveur calcule :

```text
prix unitaire facturé = prix combinaison + prix des suppléments
total item = prix unitaire facturé x quantité
```

Avec une combinaison à `3500 XAF`, un supplément poisson à `1000 XAF` et une quantité de `2` :

```text
(3500 + 1000) x 2 = 9000 XAF
```

Le prix envoyé par le client est ignoré pour éviter toute fraude.

### Scénario 8 : réservation du stock

Lorsqu'un item composé est ajouté :

1. La disponibilité de la combinaison est vérifiée.
2. Les composants obligatoires sont vérifiés.
3. Le stock disponible est réservé.
4. Le prix est calculé côté serveur.
5. Les exigences de stock sont figées dans `details_jsonb`.

Deux commandes concurrentes ne doivent pas pouvoir réserver plus que le stock disponible grâce au verrouillage de ligne utilisé lors de la réservation.

### Scénario 9 : payer ou annuler une commande

Pour payer :

```http
PUT /v1/restaurants/commandes/{commande_id}
```

```json
{
  "statut": "payee"
}
```

Le système consomme le stock réservé et enregistre les mouvements de sortie.

Pour annuler :

```json
{
  "statut": "annulee"
}
```

Le stock réservé est libéré sans être consommé.

### Scénario 10 : table occupée puis libérée

Lorsqu'une commande est créée avec une table libre :

1. La table passe à `occupee`.
2. Les commandes sont suivies via `/commandes/active`.
3. La table revient à `libre` lorsque la commande est payée ou annulée.

### Scénario 11 : sauce épuisée

```text
Stock sauce tomate : 0
```

Conséquence :

- les combinaisons qui exigent cette sauce disparaissent des recommandations ;
- une tentative de commande est refusée ;
- l'administrateur peut enregistrer une entrée de stock ou désactiver la sauce.

La substitution automatique vers une autre sauce n'est pas encore implémentée : elle doit être configurée explicitement dans une future version.

## API disponible

Toutes les routes sont préfixées par `/v1`.

### Santé

| Méthode | Route | Usage |
|---|---|---|
| `GET` | `/` | Informations générales |
| `GET` | `/health` | Vérification de santé |

### Authentification

| Méthode | Route | Usage |
|---|---|---|
| `POST` | `/v1/auth/register` | Créer un compte |
| `POST` | `/v1/auth/login` | Obtenir les tokens |
| `POST` | `/v1/auth/refresh` | Renouveler l'access token |
| `POST` | `/v1/auth/logout` | Invalider les refresh tokens |

### Utilisateurs

| Méthode | Route | Usage |
|---|---|---|
| `GET` | `/v1/users` | Lister les utilisateurs |
| `GET` | `/v1/users/me` | Voir son profil |
| `GET` | `/v1/users/{user_id}` | Voir un utilisateur |
| `POST` | `/v1/users` | Créer un utilisateur |
| `PUT` | `/v1/users/{user_id}` | Modifier un utilisateur |
| `DELETE` | `/v1/users/{user_id}` | Supprimer un utilisateur |

### Abonnements

| Méthode | Route | Usage |
|---|---|---|
| `GET` | `/v1/subscriptions/tiers` | Lister les offres |
| `GET` | `/v1/subscriptions/tiers/{tier_id}` | Voir une offre |
| `POST` | `/v1/subscriptions/tiers` | Créer une offre |
| `PUT` | `/v1/subscriptions/tiers/{tier_id}` | Modifier une offre |
| `GET` | `/v1/subscriptions/me` | Voir son abonnement |
| `POST` | `/v1/subscriptions` | Créer un abonnement |
| `PUT` | `/v1/subscriptions/{subscription_id}/status` | Modifier un statut |
| `GET` | `/v1/subscriptions/{subscription_id}/balances` | Consulter les soldes |
| `POST` | `/v1/subscriptions/{subscription_id}/reset` | Réinitialiser un solde |

### Transactions

| Méthode | Route | Usage |
|---|---|---|
| `POST` | `/v1/transactions` | Créer une transaction |
| `GET` | `/v1/transactions/{transaction_id}` | Voir une transaction |
| `GET` | `/v1/transactions/subscription/{subscription_id}` | Transactions d'un abonnement |
| `GET` | `/v1/transactions/pos/{pos_transaction_id}` | Recherche par référence POS |
| `GET` | `/v1/transactions/my` | Ses transactions |

### Restaurant et menus

| Méthode | Route | Usage |
|---|---|---|
| `POST` | `/v1/restaurants` | Créer un restaurant |
| `GET` | `/v1/restaurants/me` | Voir son restaurant |
| `GET` | `/v1/restaurants/{restaurant_id}` | Voir un restaurant |
| `PUT` | `/v1/restaurants/{restaurant_id}` | Modifier un restaurant |
| `POST` | `/v1/restaurants/{restaurant_id}/menus` | Créer un menu |
| `GET` | `/v1/restaurants/{restaurant_id}/menus` | Lister les menus |
| `GET` | `/v1/restaurants/menus/{menu_id}` | Voir un menu |
| `PUT` | `/v1/restaurants/menus/{menu_id}` | Modifier un menu |
| `POST` | `/v1/restaurants/menus/{menu_id}/categories` | Créer une catégorie |
| `GET` | `/v1/restaurants/menus/{menu_id}/categories` | Lister les catégories |
| `PUT` | `/v1/restaurants/categories/{category_id}` | Modifier une catégorie |

### Plats, boissons et tables

| Méthode | Route | Usage |
|---|---|---|
| `POST` | `/v1/restaurants/{restaurant_id}/plats` | Créer un plat |
| `GET` | `/v1/restaurants/{restaurant_id}/plats` | Lister les plats |
| `GET` | `/v1/restaurants/plats/{plat_id}` | Voir un plat |
| `PUT` | `/v1/restaurants/plats/{plat_id}` | Modifier un plat |
| `POST` | `/v1/restaurants/{restaurant_id}/boissons` | Créer une boisson |
| `GET` | `/v1/restaurants/{restaurant_id}/boissons` | Lister les boissons |
| `GET` | `/v1/restaurants/boissons/{boisson_id}` | Voir une boisson |
| `PUT` | `/v1/restaurants/boissons/{boisson_id}` | Modifier une boisson |
| `POST` | `/v1/restaurants/{restaurant_id}/tables` | Créer une table |
| `GET` | `/v1/restaurants/{restaurant_id}/tables` | Lister les tables |
| `GET` | `/v1/restaurants/{restaurant_id}/tables/free` | Lister les tables libres |
| `GET` | `/v1/restaurants/tables/{table_id}` | Voir une table |
| `PUT` | `/v1/restaurants/tables/{table_id}` | Modifier une table |

### Composants, combinaisons et stock

| Méthode | Route | Usage |
|---|---|---|
| `POST` | `/v1/restaurants/{restaurant_id}/composants` | Créer un composant |
| `GET` | `/v1/restaurants/{restaurant_id}/composants` | Lister les composants |
| `PUT` | `/v1/restaurants/composants/{composant_id}` | Modifier un composant |
| `GET` | `/v1/restaurants/{restaurant_id}/stock` | Consulter le stock |
| `POST` | `/v1/restaurants/composants/{composant_id}/stock/mouvements` | Enregistrer un mouvement |
| `POST` | `/v1/restaurants/{restaurant_id}/combinaisons` | Créer une combinaison |
| `GET` | `/v1/restaurants/{restaurant_id}/combinaisons` | Lister les combinaisons |
| `GET` | `/v1/restaurants/{restaurant_id}/combinaisons/recommandations` | Recommander les offres vendables |
| `PUT` | `/v1/restaurants/combinaisons/{combinaison_id}` | Modifier une combinaison |

### Commandes

| Méthode | Route | Usage |
|---|---|---|
| `POST` | `/v1/restaurants/{restaurant_id}/commandes` | Créer une commande |
| `GET` | `/v1/restaurants/{restaurant_id}/commandes` | Historique paginé |
| `GET` | `/v1/restaurants/{restaurant_id}/commandes/active` | Commandes actives |
| `GET` | `/v1/restaurants/commandes/{commande_id}` | Voir une commande |
| `PUT` | `/v1/restaurants/commandes/{commande_id}` | Modifier une commande |
| `POST` | `/v1/restaurants/commandes/{commande_id}/items` | Ajouter un item |
| `GET` | `/v1/restaurants/commandes/{commande_id}/items` | Lister les items |

## Catalogue composé et stock

### Modèle métier

```text
Composant
├── nom
├── type
├── prix_supplement
├── stock_unite
└── disponible

Combinaison
├── prix
├── menu_id
├── disponible
└── composants

StockComposant
├── quantite
├── reservee
└── seuil_alerte
```

### Règles actuelles

- Un composant appartient à un restaurant.
- Une combinaison ne peut référencer que des composants du même restaurant.
- Le prix d'une combinaison est configuré par l'administrateur.
- Le prix d'un supplément est lu depuis le composant.
- Le client ne peut pas imposer `prix_unitaire`.
- Les composants sont réservés dès l'ajout de l'item.
- Le paiement consomme la réservation.
- L'annulation libère la réservation.
- Les quantités de recette sont actuellement à `1` par composant dans l'API existante.
- Les groupes de choix, substitutions et quantités avancées restent à implémenter.

## Paiements et notifications

### Paiements

Le service `PaymentService` expose une fabrique pour :

- `cash` ;
- `orange_money` ;
- `mobile_money`.

Les paiements sont actuellement structurés derrière des adaptateurs. La simulation locale ne constitue pas une intégration Orange Money de production.

Avant une mise en production, il faut ajouter :

- credentials fournisseur dans un gestionnaire de secrets ;
- signature et validation des webhooks ;
- idempotence par référence fournisseur ;
- vérification de statut asynchrone ;
- expiration des paiements en attente ;
- remboursement ;
- rapprochement journalier ;
- journal d'audit.

### Notifications

Le service `NotificationService` prend en charge les canaux structurés :

- `email` ;
- `sms` ;
- `whatsapp`.

Templates disponibles notamment :

- `commande_confirme` ;
- `commande_prete` ;
- `payment_confirme` ;
- `inscription`.

Les fournisseurs SMS, WhatsApp et email doivent être configurés séparément. Les templates ne remplacent pas une passerelle externe.

## Migrations Alembic

La base doit être gérée par Alembic en environnement partagé ou de production. Avec `SKIP_DB_INIT=true`, l'application ne tente pas de créer automatiquement les tables au démarrage.

### Vérifier l'état

```powershell
python -m alembic current
python -m alembic heads
python -m alembic history
```

### Appliquer les migrations

```powershell
python -m alembic upgrade head
```

### Générer une migration

Après modification d'un modèle :

```powershell
python -m alembic revision --autogenerate -m "description du changement"
```

Toujours relire la migration générée avant de l'appliquer. L'autogénération ne comprend pas toutes les intentions métier.

### Revenir en arrière

```powershell
python -m alembic downgrade -1
python -m alembic downgrade <revision_id>
```

### Afficher le SQL sans exécuter

```powershell
python -m alembic upgrade head --sql
```

### Historique actuel du domaine restaurant

```text
20260914_1200  Schéma initial utilisateurs, abonnements et transactions
20260915_1400  Restaurants, menus, plats, tables et commandes
20260916_1000  Composants, combinaisons et suppléments
20260916_1200  Stock, réservations et quantités de recette
```

## Tests

### Tests principaux

```powershell
python -m pytest tests/test_main.py tests/test_business_logic.py -q
```

### Toute la suite

```powershell
python -m pytest -q
```

### Tests ciblés

```powershell
python -m pytest tests/test_restaurant_services.py -q
python -m pytest -k stock -q
python -m pytest -k combinaison -q
```

Les tests restaurant historiques nécessitent une fixture `db_session` correctement configurée et une base de test disponible. Avant de considérer la suite complète comme verte, corriger cette infrastructure de test.

## Sécurité et production

### Obligatoire avant production

- Remplacer la `SECRET_KEY` par une valeur aléatoire et privée.
- Désactiver `DEBUG`.
- Remplacer `ALLOW_ORIGINS=*` par une liste explicite.
- Utiliser une base et des credentials dédiés à l'environnement.
- Ne pas exposer PostgreSQL publiquement.
- Configurer des sauvegardes et tester leur restauration.
- Ajouter une limitation de débit sur l'authentification.
- Valider la signature des webhooks de paiement.
- Centraliser les logs et les identifiants de corrélation.
- Mettre en place une politique de rotation des secrets.
- Vérifier l'isolation propriétaire/restaurant sur toutes les routes d'écriture.
- Tester les courses concurrentes de réservation de stock.

### Limites connues

Le code actuel est un socle applicatif avancé, pas encore une suite POS mondiale complète. Les éléments suivants nécessitent encore un développement dédié :

- groupes de choix avec minimum et maximum ;
- quantités de recette configurables par composant ;
- stock des plats et boissons simples ;
- substitutions validées par l'administrateur ;
- vraie intégration Orange Money et autres fournisseurs ;
- mode POS hors ligne ;
- écran cuisine et tickets d'impression ;
- caisse, clôture et rapprochement ;
- livraison et commande WhatsApp complète ;
- fidélité et CRM ;
- comptabilité et fiscalité par pays ;
- isolation multi-tenant complète.

## Dépannage

### L'application ne démarre pas avec Python 3.14

Utiliser Python 3.13 et recréer l'environnement virtuel :

```powershell
deactivate
Remove-Item -Recurse -Force .\venv
py -3.13 -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Erreur de connexion PostgreSQL

Vérifier :

1. PostgreSQL est démarré.
2. `DB_HOST` et `DB_PORT` sont corrects.
3. La base `DB_NAME` existe.
4. `DB_USER` et `DB_PASSWORD` sont valides.
5. Le fichier `.env` est situé à la racine du projet.

### La base n'est pas à jour

```powershell
python -m alembic current
python -m alembic upgrade head
```

### Swagger retourne une erreur 401

Se connecter, cliquer sur **Authorize**, puis fournir :

```text
Bearer <access_token>
```

### Une combinaison n'est pas recommandée

Vérifier :

- `combinaison.disponible` ;
- `composant.disponible` ;
- la présence d'une ligne dans `stock_composants` ;
- la quantité disponible après réservation ;
- l'appartenance des composants au restaurant.

### Un supplément est refusé

Vérifier :

- l'identifiant du composant ;
- sa disponibilité ;
- son stock disponible ;
- son appartenance au même restaurant que la commande.

## Évolutions recommandées

### Priorité 1 : fiabilité du noyau

1. Ajouter une autorisation propriétaire/admin centralisée par restaurant.
2. Exposer les quantités de recette dans les schémas API.
3. Corriger les recommandations pour comparer le stock aux quantités réelles.
4. Ajouter des contraintes de transition des statuts de commande.
5. Remplacer les commits automatiques des repositories par des transactions contrôlées par les services.
6. Ajouter des tests de concurrence et de rollback.

### Priorité 2 : expérience restaurant

1. Groupes de choix obligatoires et optionnels.
2. Variantes et tailles de portions.
3. Substitutions de composants.
4. Menus du jour avec dates et horaires.
5. Recettes et coûts de revient.
6. Tickets cuisine et écran de production.

### Priorité 3 : plateforme complète

1. POS hors ligne.
2. Paiements Mobile Money réels.
3. Paiement mixte et rapprochement de caisse.
4. Commande QR code et WhatsApp.
5. Livraison.
6. Fidélité, CRM et recommandations statistiques.

## Licence et contribution

Avant toute publication, préciser la licence du projet et la politique de contribution.
Les changements de schéma doivent toujours être accompagnés d'une migration Alembic et de tests métier ciblés.