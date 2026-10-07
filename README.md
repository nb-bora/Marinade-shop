# Marinade

**Restaurant Operating System (ROS) multi-tenant pour les restaurants du Cameroun, puis d'Afrique francophone.**

Marinade est une API FastAPI qui réunit, pour un restaurant, ce que l'on achète d'ordinaire en plusieurs outils : catalogue composable, prise de commande en salle, tickets cuisine et bar, caisse, stock et recettes, réservations, paiements Mobile Money, et abonnements SaaS. Chaque restaurant est isolé des autres jusque dans la base de données.

> Ce document décrit ce que le code fait **aujourd'hui**. Les écarts avec la vision sont listés sans fard dans [État d'avancement](#état-davancement-et-limites-connues). Dernière revue complète : 6 octobre 2026.

## Sommaire

- [Vision et positionnement](#vision-et-positionnement)
- [État d'avancement et limites connues](#état-davancement-et-limites-connues)
- [Démarrage rapide](#démarrage-rapide)
- [Configuration](#configuration)
- [Architecture](#architecture)
- [Multi-tenant et sécurité](#multi-tenant-et-sécurité)
- [Authentification](#authentification)
- [Rôles d'équipe](#rôles-déquipe)
- [Parcours métier](#parcours-métier)
- [Paiements](#paiements)
- [Référence de l'API](#référence-de-lapi)
- [Migrations](#migrations)
- [Tests](#tests)
- [Passage en production](#passage-en-production)
- [Dépannage](#dépannage)
- [Documentation complémentaire](#documentation-complémentaire)

## Vision et positionnement

Marinade vise à devenir le système d'exploitation de référence des restaurants camerounais : du maquis au restaurant de standing, avec la même base technique.

Les choix de conception qui en découlent :

- **Localisation native** : francs CFA (XAF), TVA camerounaise de 19,25 % par défaut, numéros `+237`, opérateurs MTN et Orange reconnus par préfixe.
- **Mobile Money d'abord** : paiement par l'intermédiaire d'Easy Transact, avec webhook signé et journal comptable.
- **Catalogue composable** : un plat peut être une combinaison de composants (base + sauce + protéine), avec suppléments tarifés côté serveur et stock par composant.
- **Isolation stricte** : un restaurant ne voit jamais les données d'un autre. Le contrôle est appliqué deux fois, dans l'API et dans PostgreSQL (row level security).
- **Équipe réelle** : serveur, caissier, chef, sous-chef, barman, hôte, manager, livreur, avec des droits distincts.
- **Tolérance aux coupures** : synchronisation par lot de commandes et d'encaissements enregistrés hors ligne, rejouable sans doublon grâce aux clés d'idempotence.

### Ce qui distingue Marinade, et où il en est

La comparaison porte sur des catégories d'outils (caisses restaurant type Toast, Square, Lightspeed ou Clover ; plateformes de facturation type Stripe Billing ou Chargebee ; offres d'abonnement restaurant de niche). Le détail se trouve dans [docs/POSITIONING_ANALYSIS.md](docs/POSITIONING_ANALYSIS.md).

| Atout visé | Statut dans le code |
|---|---|
| FCFA, TVA 19,25 %, numéros camerounais | Disponible |
| Orange Money et MTN via Easy Transact (webhook signé, journal) | Disponible pour les commandes historiques et les abonnements ; **pas encore relié au moteur ROS** |
| Catalogue composable, suppléments, stock réservé | Disponible, avec des corrections de stock à venir |
| Isolation par restaurant (API + RLS PostgreSQL) | Disponible et vérifiée |
| Rôles d'équipe granulaires | Disponible |
| 2FA (TOTP et codes de secours) | Disponible |
| Tickets cuisine/bar, caisse avec écart, factures, synchronisation hors ligne | Disponible via l'API ROS |
| Réservations et liste d'attente | Partiel (voir limites) |
| Alertes et rappels par SMS / WhatsApp | Canaux simulés, aucun envoi réel |
| Prix calculés côté serveur | Disponible pour les commandes historiques ; **le moteur ROS accepte encore le prix envoyé par la caisse** |

## État d'avancement et limites connues

Aucune ligne ci-dessous n'est cachée : ce sont les écarts constatés à la lecture du code et par les tests.

### Ce qui est solide

- **Isolation tenant** : tout est protégé par un garde d'accès à l'API et par la RLS PostgreSQL (36 tables). Un test parcourt **toutes** les routes et échoue si l'une n'a ni authentification ni garde de restaurant.
- **Authentification** : JWT, rotation des refresh tokens, 2FA réelle branchée sur le login, aucun secret de vérification dans les réponses HTTP.
- **Rôles d'équipe** appliqués sur les routes sensibles : un serveur ne change ni un prix ni un remboursement, et n'encaisse pas.
- **Scénarios ROS de bout en bout** : 12 scénarios passent sur une vraie base (commande avec ou sans table, tickets, paiement, encaissement partagé, caisse avec écart, synchronisation hors ligne, stock, isolation).
- **Parcours complet par l'API avec le rôle applicatif sous RLS réelle** : 47 tests d'intégration couvrent l'inscription, la 2FA, le catalogue, la nomenclature des plats, la commande ROS jusqu'à l'encaissement et la clôture de session, les réservations, les remboursements, les abonnements, les transactions, les paiements, l'administration, l'isolation entre restaurants et les droits par rôle.

### Routes corrigées lors de la dernière revue

Chaque route a été exercée contre une vraie base par `tests/test_api_integration.py`. Étaient cassées, et ne le sont plus :

- création de plat (`composant_ids`), de catégorie (identifiant du menu pris dans l'URL), les quatre routes de nomenclature d'un plat ;
- demande, liste, approbation et rejet de remboursement ;
- toutes les routes de réservation et de liste d'attente (elles validaient la transaction en cours de requête, ce qui faisait perdre le contexte du restaurant) ;
- `PUT /subscriptions/{id}/status` (une valeur inconnue répond désormais `422`, un abonnement inconnu `404`) ;
- les réponses « introuvable » des tables et des commandes ;
- la clôture d'une session ROS (`RosInvoice.amount_due`) ;
- le webhook de paiement : la signature est contrôlée avant toute lecture du contenu, un appelant non authentifié reçoit donc toujours la même réponse.

### Manques fonctionnels importants

- **Prix ROS non contrôlés** : le moteur ROS prend `unit_price` tel qu'envoyé. Le calcul serveur existe pour les commandes historiques, pas encore pour ROS.
- **Pas de lien ROS ↔ Easy Transact** : les encaissements ROS sont enregistrés (espèces, MTN, Orange, carte, Wave, virement) sans appel au fournisseur.
- **Écran cuisine temps réel** : le WebSocket est authentifié mais aucun événement n'y est encore diffusé, et son jeton n'est pas revérifié après la connexion.
- **Réservations** : les routes écrivent directement, sans contrôle de conflit d'horaire ni de l'état des tables. `ReservationService` (qui le fait) n'est pas branché et utilise d'anciens noms de champs.
- **Notifications** : les canaux e-mail, SMS et WhatsApp sont **simulés**. Conséquence : mot de passe oublié, vérification d'e-mail et de téléphone ne peuvent pas aboutir en production tant qu'un vrai fournisseur n'est pas intégré.
- **Pas de limitation de débit** : codes 2FA et code SMS à 6 chiffres sont théoriquement devinables par essais répétés.
- **Journaux applicatifs** : les loggers des modules ne sont pas rattachés à la configuration, les messages `info` n'apparaissent donc pas.

### Stock et paiement (correction prévue)

- Une combinaison payée peut être déduite deux fois du stock.
- À l'annulation, le stock peut gonfler (libération puis remise d'une quantité jamais retirée).
- Un remboursement partiel remet en stock toute la commande ; les demandes en attente ne sont pas additionnées, le total remboursé peut donc dépasser le total de la commande.
- Les plats simples ne sont pas réservés à la commande, seulement déduits au paiement : le webhook peut échouer après que le client a payé.
- Moteur ROS : pas de verrou sur le stock, pas de contrôle de stock négatif, un `product_id` de plat est ignoré.
- Encaissements ROS : un client peut payer plus que le dû ; la clôture de caisse additionne les espèces de tous les caissiers ; en synchronisation hors ligne, un élément en erreur peut faire échouer le lot.

### Infrastructure

- `Dockerfile` et `docker-compose.yml` sont vides : la base se prépare à la main (voir [Démarrage rapide](#démarrage-rapide)).
- `tests/test_ros.py` écrit dans la base configurée et suppose un superutilisateur (voir [Tests](#tests)).

## Démarrage rapide

### Prérequis

- Python 3.13 (3.14 peut poser problème avec certaines dépendances).
- PostgreSQL 14 ou plus (développé et testé avec la version 18) ; Docker convient.
- Optionnel : pgAdmin.

### 1. Installer

```powershell
py -3.13 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Sous Linux ou macOS : `python3.13 -m venv venv && source venv/bin/activate`, puis `cp .env.example .env`.

### 2. Préparer la base : deux rôles distincts

La RLS ne protège que si l'application se connecte avec un rôle qui **n'est ni superutilisateur, ni propriétaire des tables, ni `BYPASSRLS`**. Il faut donc deux rôles :

| Rôle | Usage |
|---|---|
| `marinade_owner` | Propriétaire de la base. Exécute les migrations Alembic, sert aussi à se connecter avec pgAdmin. |
| `marinade_app` | Utilisé par l'API. Lit et écrit les données, sans droit sur le schéma. |

Dans un conteneur PostgreSQL existant, en tant que superutilisateur (remplace les mots de passe) :

```sql
CREATE ROLE marinade_owner LOGIN PASSWORD '...' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
CREATE ROLE marinade_app   LOGIN PASSWORD '...' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
CREATE DATABASE marinade OWNER marinade_owner ENCODING 'UTF8';
REVOKE ALL ON DATABASE marinade FROM PUBLIC;
GRANT CONNECT ON DATABASE marinade TO marinade_app;
```

Puis, **connecté à la base `marinade`** :

```sql
GRANT USAGE ON SCHEMA public TO marinade_app;
ALTER DEFAULT PRIVILEGES FOR ROLE marinade_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO marinade_app;
ALTER DEFAULT PRIVILEGES FOR ROLE marinade_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO marinade_app;
```

Avec Docker : `docker exec -i <conteneur> psql -U <superutilisateur> -d postgres` et coller les commandes.

### 3. Configurer `.env`

```dotenv
DB_HOST=localhost
DB_PORT=5432
DB_NAME=marinade
DB_USER=marinade_app
DB_PASSWORD=...
MIGRATION_DATABASE_URL=postgresql://marinade_owner:...@localhost:5432/marinade

SECRET_KEY=une-valeur-aleatoire-d-au-moins-32-caracteres
```

Le fichier `.env` est ignoré par git. Toutes les variables sont décrites dans [Configuration](#configuration).

### 4. Migrer

```powershell
python -m alembic upgrade head
python -m alembic current      # doit afficher 20260926_1000 (head)
```

Alembic utilise `MIGRATION_DATABASE_URL` si elle est définie, sinon la connexion de l'application.

### 5. Lancer

```powershell
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

| Adresse | Contenu |
|---|---|
| http://localhost:8000/docs | Swagger : tester les routes |
| http://localhost:8000/redoc | Documentation ReDoc |
| http://localhost:8000/health | Santé de l'API |

Au démarrage, l'API vérifie le rôle de connexion : s'il contourne la RLS, elle le signale par un avertissement (développement) ou **refuse de démarrer** (production).

### 6. Se connecter avec pgAdmin

Si pgAdmin tourne dans un autre réseau Docker que PostgreSQL, il ne peut pas joindre le serveur par le nom de son conteneur. Utilise le port publié :

| Champ | Valeur |
|---|---|
| Host | `host.docker.internal` (ou `localhost` si pgAdmin est installé sur ta machine) |
| Port | `5432` |
| Maintenance database | `marinade` |
| Username | `marinade_owner` |

Rafraîchis ensuite le serveur pour voir `marinade → Schemas → public → Tables`.

### 7. Premier appel

Dans Swagger, ou avec n'importe quel client HTTP :

```http
POST /v1/auth/register
{
  "email": "gerant@example.com",
  "phone": "+237600000000",
  "password": "MotDePasseFort123!",
  "first_name": "Jean",
  "last_name": "Dupont",
  "role": "restaurant"
}
```

Le mot de passe doit faire **12 caractères au minimum**. Le champ `role` est exigé par le schéma mais le serveur impose toujours `restaurant`.

```http
POST /v1/auth/login
{ "email": "gerant@example.com", "password": "MotDePasseFort123!" }
```

Copie l'`access_token`, clique sur **Authorize** dans Swagger et colle-le. Crée ensuite ton restaurant :

```http
POST /v1/restaurants
{ "name": "Chez Marinade", "currency": "XAF", "city": "Douala", "country": "Cameroun", "taux_service": 10 }
```

## Configuration

Les paramètres sont lus dans `.env` (fichier ignoré par git) puis dans les variables d'environnement, qui l'emportent. Modèle : [.env.example](.env.example).

### Base de données

| Variable | Défaut | Rôle |
|---|---|---|
| `DB_HOST` / `DB_PORT` / `DB_NAME` | `localhost` / `5432` / `marinade` | Cible PostgreSQL |
| `DB_USER` / `DB_PASSWORD` | `postgres` / `postgres` | Rôle **applicatif** (ni superutilisateur ni propriétaire) |
| `DB_SSLMODE` | `prefer` | Mode TLS |
| `DB_CONNECT_TIMEOUT_SECONDS` | `5` | Délai de connexion |
| `MIGRATION_DATABASE_URL` | vide | URL du rôle propriétaire, utilisée par Alembic seulement |
| `SKIP_DB_INIT` | `true` | Ne pas créer les tables au démarrage (obligatoire en production : on migre avec Alembic) |

### Sécurité

| Variable | Défaut | Rôle |
|---|---|---|
| `SECRET_KEY` | valeur d'exemple | Signature des JWT. 32 caractères minimum, privée, obligatoire en production |
| `ALGORITHM` | `HS256` | Algorithme JWT |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Durée du jeton d'accès |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Durée du refresh token |
| `RESET_TOKEN_EXPIRE_MINUTES` | `15` | Validité du lien de réinitialisation et du code SMS |
| `VERIFICATION_TOKEN_EXPIRE_HOURS` | `24` | Validité du jeton de vérification d'e-mail |
| `TWO_FACTOR_ISSUER` | `Marinade` | Nom affiché dans l'application d'authentification |
| `TWO_FACTOR_ENCRYPTION_KEY` | vide | Clé de chiffrement des secrets TOTP. À défaut `SECRET_KEY` est utilisée : la changer invalide alors les secrets 2FA existants. Définir une clé dédiée en production |
| `DEV_EXPOSE_AUTH_TOKENS` | `false` | **Développement uniquement** : renvoie les jetons de vérification dans la réponse HTTP, faute de fournisseur e-mail/SMS. Refusé en production |

### Application et CORS

| Variable | Défaut | Rôle |
|---|---|---|
| `APP_NAME` / `APP_VERSION` | `Marinade API` / `1.0.0` | Identité de l'application |
| `DEBUG` | `true` | Mode debug (interdit en production) |
| `ENVIRONMENT` | `development` | `production`, `prod` ou `staging` activent les contrôles stricts |
| `ALLOW_ORIGINS` | `http://localhost:3000` | Origines CORS, séparées par des virgules (jamais `*` en production) |
| `ALLOW_CREDENTIALS` | `true` | Cookies et en-têtes d'authentification CORS |
| `ALLOW_METHODS` | `GET,POST,PUT,PATCH,DELETE,OPTIONS` | Méthodes CORS |
| `ALLOW_HEADERS` | `Authorization,Content-Type,X-Request-ID,X-Tenant-ID,X-Signature` | En-têtes CORS |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | Utilisés par `python -m app.main` |

### Easy Transact (paiement Mobile Money)

| Variable | Défaut | Rôle |
|---|---|---|
| `EASYTRANSACT_API_BASE_URL` | vide | URL de l'API du fournisseur |
| `EASYTRANSACT_API_TOKEN` | vide | Jeton d'API (secret) |
| `EASYTRANSACT_WEBHOOK_SECRET` | vide | Secret de signature des webhooks (secret) |
| `EASYTRANSACT_WEBHOOK_SIGNATURE_HEADER` | `X-Signature` | En-tête qui porte la signature |
| `EASYTRANSACT_WEBHOOK_SIGNATURE_ALGORITHM` | `hmac-sha256` | Seul algorithme accepté |
| `EASYTRANSACT_WEBHOOK_MAX_BODY_BYTES` | `1048576` | Taille maximale d'un webhook |
| `EASYTRANSACT_HTTP_TIMEOUT_SECONDS` | `10` | Délai des appels sortants |
| `EASYTRANSACT_STATUS_REFERENCE_PARAM` | `vendor_reference` | Paramètre de la requête de statut |
| `ALLOW_LEGACY_PAYMENT_SIMULATION` | `false` | Interdit en production |

Un restaurant peut avoir son propre secret : voir [Paiements](#paiements).

## Architecture

```text
API (app/api)              Routes FastAPI, validation HTTP, gardes d'accès
Services (app/services)    Règles métier et orchestration
Repositories               Accès SQLAlchemy ; ne font jamais de commit
Modèles / Schémas          Tables PostgreSQL / contrats Pydantic
```

### Transactions

`get_db` ouvre une session par requête, la valide en fin de requête et l'annule en cas d'exception. Les repositories ne valident jamais : c'est la requête qui est l'unité de travail.

### Structure

```text
app/
├── api/
│   ├── dependencies.py       Authentification, résolution du restaurant, rôles
│   ├── permissions.py        Matrice des rôles (une seule source de vérité)
│   ├── exception_handlers.py
│   └── v1/                   auth, users, subscriptions, transactions, restaurants,
│                             ros, reservations, payments, operators
├── core/                     config.py (réglages), database.py (session, contexte RLS)
├── integrations/             easy_transact.py (client HTTP)
├── models/                   user, tenant, subscription, transaction, payment,
│                             restaurant, ros, reservation, operator
├── repositories/             Accès aux données
├── schemas/                  Contrats Pydantic
├── services/                 auth, user, subscription, transaction, restaurant,
│                             ros, reservation, payment, easy_transact, notification
└── utils/                    crypto, enums, ros_enums, exceptions, phone,
                              payment_secrets, payment_methods, notification_channels,
                              ws_manager, logging
alembic/versions/             Migrations
tests/                        Tests automatisés
docs/                         Guides et analyses
```

### Gestion des erreurs

Les exceptions métier (`AuthenticationError`, `AuthorizationError`, `ValidationError`, `NotFoundError`, `ConflictError`, `BusinessLogicError`, `DatabaseError`) deviennent des réponses JSON :

```json
{ "error": "ConflictError", "message": "Idempotency key already used", "details": null }
```

Les erreurs d'accès levées par les gardes (`401`, `403`, `404`) gardent le format FastAPI `{ "detail": "..." }`, et les erreurs de validation de requête répondent `422`.

## Multi-tenant et sécurité

### Un restaurant = un tenant

Chaque table métier porte un `restaurant_id`. Le restaurant visé par une requête est déterminé ainsi :

1. l'identifiant dans l'URL (`/restaurants/{restaurant_id}/...`) ou celui du restaurant propriétaire d'une ressource désignée dans l'URL (une table, un ticket, une commande…) ;
2. à défaut, l'en-tête `X-Tenant-ID` ;
3. à défaut, le restaurant dont l'utilisateur est propriétaire, ou son unique appartenance.

Un utilisateur membre de plusieurs restaurants **doit** envoyer `X-Tenant-ID`. Un restaurant auquel l'utilisateur n'a aucun accès répond `404` (et non `403`) pour ne pas en révéler l'existence.

### Deux couches de protection

**Dans l'API** : chaque requête vérifie l'accès au restaurant visé, puis le rôle de l'utilisateur dans ce restaurant. Un routeur ROS est protégé par défaut, de sorte qu'une route ajoutée sans contrôle reste isolée.

**Dans PostgreSQL** : 36 tables ont `ROW LEVEL SECURITY` activée et forcée. La requête place trois variables locales à la transaction (`app.current_user_id`, `app.current_tenant_id`, `app.is_platform_admin`), et les politiques n'exposent que les lignes du restaurant courant. Même une requête qui oublierait un filtre ne verrait pas les données d'un autre restaurant.

Quatre tables n'ont pas de RLS, volontairement : `users`, `refresh_tokens`, `subscription_tiers` et `alembic_version`.

### Pour que la RLS protège vraiment

- L'application doit se connecter avec un rôle `NOSUPERUSER NOBYPASSRLS` qui n'est pas propriétaire des tables (voir [Démarrage rapide](#2-préparer-la-base--deux-rôles-distincts)).
- Au démarrage, l'API contrôle ce rôle et refuse de démarrer en production s'il contourne la RLS.
- Limite à connaître : les variables de contexte sont posées par l'application elle-même. La RLS protège contre un oubli de filtre ou une route mal écrite, pas contre un code malveillant déjà exécuté côté serveur.

### Références croisées

Une clé étrangère prouve qu'une ligne existe, pas qu'elle appartient au bon restaurant. Les identifiants envoyés dans un corps de requête (table, client, session) sont donc revérifiés, et une clé d'idempotence déjà utilisée par un autre restaurant produit un conflit au lieu de renvoyer sa commande.

## Authentification

### Jetons

- **Jeton d'accès** : JWT signé, 30 minutes par défaut, à envoyer dans `Authorization: Bearer <jeton>`.
- **Refresh token** : valeur aléatoire opaque, stockée hachée, **renouvelée à chaque usage**. `POST /v1/auth/refresh?refresh_token=...` retourne une nouvelle paire.
- **Déconnexion** : `POST /v1/auth/logout` révoque tous les refresh tokens de l'utilisateur. Une réinitialisation de mot de passe fait de même.

### Authentification à deux facteurs (TOTP)

1. `POST /v1/auth/2fa/setup` renvoie le `secret`, une URL `otpauth://` à transformer en QR code, et **8 codes de secours** (affichés une seule fois).
2. `POST /v1/auth/2fa/confirm` avec un code à 6 chiffres active la 2FA.
3. Ensuite, `POST /v1/auth/login` exige `two_factor_code` (code TOTP ou code de secours). Sans lui, la réponse est `401` avec `details.two_factor_required = true`.

```http
POST /v1/auth/login
{ "email": "gerant@example.com", "password": "...", "two_factor_code": "123456" }
```

- Le secret TOTP est **chiffré en base** ; les codes de secours sont **hachés** et à usage unique.
- `POST /v1/auth/2fa/recovery-codes` (avec le mot de passe) génère un nouveau lot et invalide l'ancien.
- `POST /v1/auth/2fa/disable` exige le mot de passe.

### Mot de passe oublié, e-mail et téléphone

| Route | Rôle |
|---|---|
| `POST /v1/auth/forgot-password` | Même réponse que le compte existe ou non |
| `POST /v1/auth/reset-password` | Jeton valable 15 minutes, usage unique |
| `POST /v1/auth/send-verification-email` puis `verify-email` | Vérifie l'adresse |
| `POST /v1/auth/send-verification-phone` puis `verify-phone` | Vérifie le numéro par code à 6 chiffres |

Les jetons ne sont **jamais** dans les réponses. Ils partent par e-mail ou SMS, qui sont simulés pour l'instant (voir limites). En développement uniquement, `DEV_EXPOSE_AUTH_TOKENS=true` les renvoie dans la réponse pour permettre les tests.

## Rôles d'équipe

Le propriétaire du restaurant, les membres `manager` et les administrateurs de la plateforme passent **tous** les contrôles. Les autres rôles ne passent que là où ils sont listés. La matrice est dans [app/api/permissions.py](app/api/permissions.py).

| Domaine | Rôles autorisés (en plus de propriétaire, manager, admin) |
|---|---|
| Lecture du catalogue, des tables, du stock, des commandes | Tout membre du restaurant |
| Créer ou modifier carte, prix, composants, combinaisons, recettes, tables | Manager seul |
| Mouvements de stock | Chef, sous-chef |
| Commandes, sessions, clients, statut des tables | Serveur, caissier, hôte, barman |
| Encaissements, caisse, demande de remboursement | Caissier |
| Approuver ou rejeter un remboursement | Manager seul |
| Tickets cuisine et bar | Chef, sous-chef, barman, serveur, hôte |
| Propositions d'approvisionnement | Chef, sous-chef |
| Réservations et liste d'attente | Hôte, serveur, caissier |
| Configuration des paiements d'un restaurant | Manager seul |

Les rôles proviennent de `restaurant_members.staff_role` (`waiter`, `cashier`, `chef`, `sous_chef`, `manager`, `delivery`, `bartender`, `host`). Les anciennes lignes dont seule la colonne `role` est renseignée restent reconnues (`kitchen` vaut chef), et le rôle générique `staff` n'accorde aucun privilège.

Un lot de synchronisation hors ligne qui contient des paiements exige en plus le rôle caissier.

## Parcours métier

Les exemples ci-dessous ne s'appuient que sur des routes qui fonctionnent.

### Prendre une commande en salle (ROS)

```http
POST /v1/ros/restaurants/{restaurant_id}/sessions
{ "table_context": "Terrasse gauche" }
```

```http
POST /v1/ros/restaurants/{restaurant_id}/orders
X-Idempotency-Key: 6f1c1e0a-...   (UUID, optionnel mais recommandé)

{
  "session_id": "<id de la session>",
  "fulfillment_type": "DINE_IN",
  "order_channel": "POS",
  "items": [
    { "product_name": "Poulet braisé", "quantity": 1, "unit_price": 4000,
      "tax_rate": 19.25, "destination_station": "KITCHEN" },
    { "product_name": "Jus d'ananas", "quantity": 2, "unit_price": 1500,
      "destination_station": "BAR" }
  ]
}
```

Règles appliquées par le serveur :

- Total = somme des lignes + TVA par ligne (19,25 % par défaut).
- `DINE_IN` : commande **confirmée** tout de suite, tickets envoyés à la cuisine et au bar. Le paiement se fait après le repas.
- `TAKEAWAY`, `DELIVERY`, `COUNTER` : paiement **avant** préparation, la commande reste `PENDING_PAYMENT` et les tickets ne partent qu'une fois payée.
- Une facture est créée (numéro, empreinte SHA-256) ; plusieurs commandes d'une même session s'ajoutent à la même facture.
- La même clé d'idempotence rejoue la commande sans la dupliquer.

### Faire avancer la cuisine et le bar

```http
GET /v1/ros/restaurants/{restaurant_id}/tickets/KITCHEN
PUT /v1/ros/restaurants/{restaurant_id}/tickets/{ticket_id}/status
{ "status": "IN_PREPARATION" }     // QUEUED, IN_PREPARATION, READY, SERVED
```

Stations : `KITCHEN`, `BAR`, `DESSERT`, `PACKAGING`.

### Caisse

```http
POST /v1/ros/restaurants/{restaurant_id}/shifts/open     { "opening_balance": 15000 }
POST /v1/ros/restaurants/{restaurant_id}/shifts/close    { "closing_balance_counted": 15500 }
```

La clôture calcule le solde attendu (fond de caisse + espèces encaissées), l'écart, et l'enregistre dans le journal d'audit. Un second shift ouvert par le même opérateur répond `409`.

### Encaisser

La réponse de création d'une commande contient `invoice_id` et `invoice_number`. Pour une session, c'est la facture **partagée** par toutes ses commandes. On la consulte avec :

```http
GET /v1/ros/restaurants/{restaurant_id}/invoices/{invoice_id}
GET /v1/ros/restaurants/{restaurant_id}/sessions/{session_id}/invoice     // l'addition de la table
```

La facture indique `amount_paid` et `amount_due`. On encaisse ensuite :

```http
POST /v1/ros/restaurants/{restaurant_id}/payments
{ "invoice_id": "<id>", "payment_method": "CASH", "amount": 8347.50 }
```

`POST .../payments/split` règle une même facture avec plusieurs moyens (`CASH`, `MTN_MOMO`, `ORANGE_MONEY`, `CARD`, `WAVE`, `BANK_TRANSFER`). Une session ne peut être fermée qu'une fois la facture soldée.

### Mode hors ligne

```http
POST /v1/ros/restaurants/{restaurant_id}/sync
{ "orders": [ ... ], "payments": [ ... ] }
```

Les commandes et paiements enregistrés sans réseau sont rejoués ; chaque élément porte sa clé d'idempotence, ce qui rend le rejeu sûr. La réponse indique le nombre d'éléments traités et les erreurs.

### Catalogue composable et stock

- Un **composant** (riz, sauce tomate, poulet…) a un prix de supplément, une disponibilité et un stock (`quantite`, `reservee`, `seuil_alerte`).
- Une **combinaison** a son propre prix et référence des composants du même restaurant.
- Stock disponible = stock physique − stock réservé. `GET .../combinaisons/recommandations` ne propose que les combinaisons dont les composants obligatoires sont disponibles.
- Mouvements : `entree`, `ajustement`, `perte`.
- Les prix et suppléments d'une commande historique sont calculés **par le serveur** : le client ne peut pas imposer un prix.

**Nomenclature d'un plat.** Un plat consomme des composants à chaque commande. Le plat est désigné par l'URL, jamais par le corps :

```http
POST /v1/restaurants/plats/{plat_id}/composants      { "composant_id": "<id>", "quantite": 2, "unite": "portion" }
PUT  /v1/restaurants/plats/{plat_id}/composants/{composant_id}   { "quantite": 3 }
DELETE /v1/restaurants/plats/{plat_id}/composants/{composant_id}
PUT  /v1/restaurants/plats/{plat_id}/composants      [ { "composant_id": "...", "quantite": 1 }, ... ]   // remplace tout
```

Un composant n'apparaît qu'une fois par plat (`409` sinon) et doit appartenir au même restaurant. À la création ou à la modification d'un plat, `composant_ids` est un raccourci qui crée la nomenclature avec une quantité de 1 chacun (`[]` la vide).

**Remboursements** (commandes historiques). Les champs de la demande sont `montant`, `raison` et, pour un remboursement partiel d'articles, `item_ids`. La réponse porte `statut` (`requested`, `approved`, `rejected`…), `effectue_par_id` (qui a demandé) et `traite_par_id` (qui a décidé).

Voir [docs/RESTAURANT_GUIDE.md](docs/RESTAURANT_GUIDE.md) pour la configuration d'un restaurant.

### Réservations et liste d'attente

Création, consultation, confirmation, arrivée (`check-in`), annulation, et liste d'attente avec mise en place d'une table. Voir les limites pour le contrôle de conflits.

### Abonnements et solde quotidien

Des offres (`SubscriptionTier`) définissent une limite journalière et des prix mensuel et annuel en FCFA. Un restaurant a au plus **un abonnement actif**. Les transactions du point de vente débitent un solde quotidien, avec une clé d'idempotence par restaurant ; une transaction qui dépasserait le solde du jour est refusée. La réinitialisation quotidienne crée le solde à la limite de l'offre.

### Commandes historiques (dépréciées)

Les routes `/v1/restaurants/.../commandes` (modèle `Commande`) sont marquées `deprecated`, répondent avec l'en-tête `X-Deprecated-Endpoint: use-ros-orders` et sont journalisées. Le moteur ROS est le chemin cible. Elles restent actives le temps de la migration et conservent les remboursements et le calcul de prix côté serveur.

## Paiements

### Mobile Money via Easy Transact

1. `PUT /v1/payments/easytransact/configuration` enregistre la configuration d'un restaurant (manager).
2. `POST /v1/payments/easytransact/checkout` crée un lien de paiement pour **une** commande historique ou **un** abonnement, avec une clé d'idempotence. Le montant doit égaler le total de la commande.
3. Le fournisseur appelle `POST /v1/payments/easytransact/webhook/{restaurant_id}` : l'URL est propre à chaque restaurant pour que la base puisse établir son contexte RLS. Il n'existe pas de webhook sans identifiant de restaurant.

### Webhook sécurisé

- Signature HMAC-SHA256 du corps brut obligatoire, comparée en temps constant (préfixe `sha256=` toléré). Corps limité à 1 Mo.
- Chaque événement du fournisseur est **dédupliqué** par son identifiant.
- Transitions d'état contrôlées : un paiement terminé ne peut pas changer de statut.
- Un paiement `success` marque la commande payée, consomme le stock réservé et écrit une entrée `capture` dans le journal de paiement.
- Une commande ne peut **pas** être marquée payée à la main (`PUT ... statut=payee` est refusé) : seul le webhook signé le fait.

### Secrets par restaurant

Une configuration ne stocke pas de secret : elle stocke le **nom** de la variable d'environnement qui le contient. Pour qu'un restaurant ne puisse pas désigner une variable dont il connaît la valeur et signer de faux webhooks, seuls ces noms sont acceptés :

- jeton d'API : `EASYTRANSACT_API_TOKEN` ou `EASYTRANSACT_API_TOKEN_<SUFFIXE>` ;
- secret de webhook : `EASYTRANSACT_WEBHOOK_SECRET` ou `EASYTRANSACT_WEBHOOK_SECRET_<SUFFIXE>`.

Seul un administrateur de la plateforme peut choisir un suffixe propre à un restaurant ; l'opérateur provisionne la variable correspondante. Le contrôle est refait à chaque usage.

### Numéros et opérateurs

Les numéros doivent être camerounais (`+237`, neuf chiffres, commençant par 6). L'opérateur est déduit du plus long préfixe correspondant (MTN : 650–654, 67 ; Orange : 655–659, 69). La table des préfixes se modifie via `/v1/admin/mobile-operator-prefixes` (administrateur).

## Référence de l'API

Toutes les routes sont préfixées par `/v1`. La colonne **Accès** résume qui peut appeler : *public*, *membre* (utilisateur connecté, restaurant vérifié), un ou plusieurs rôles d'équipe (voir [Rôles d'équipe](#rôles-déquipe)), ou *admin*. La référence exhaustive et interactive est Swagger (`/docs`).

### Authentification

| Méthode | Route | Accès |
|---|---|---|
| POST | `/auth/register`, `/auth/login`, `/auth/refresh` | public |
| POST | `/auth/logout` | membre |
| POST | `/auth/forgot-password`, `/auth/reset-password`, `/auth/verify-email` | public |
| POST | `/auth/send-verification-email`, `/auth/send-verification-phone`, `/auth/verify-phone` | membre |
| POST | `/auth/2fa/setup`, `/auth/2fa/confirm`, `/auth/2fa/disable`, `/auth/2fa/recovery-codes` | membre |

### Utilisateurs et abonnements

| Méthode | Route | Accès |
|---|---|---|
| GET | `/users/me` | membre |
| GET, POST, PUT, DELETE | `/users`, `/users/{user_id}` | admin |
| GET | `/subscriptions/tiers`, `/subscriptions/tiers/{tier_id}` | public |
| POST, PUT | `/subscriptions/tiers`, `/subscriptions/tiers/{tier_id}` | admin |
| GET | `/subscriptions/me` | membre |
| POST | `/subscriptions`, `/subscriptions/{id}/balances`, `/subscriptions/{id}/reset` | admin |
| GET, PUT | `/subscriptions/{id}`, `/subscriptions/{id}/status` | admin |
| GET | `/subscriptions/{id}/balances`, `/subscriptions/{id}/balances/current` | membre du restaurant concerné |

### Transactions

| Méthode | Route | Accès |
|---|---|---|
| POST | `/transactions` | caissier |
| GET | `/transactions/pos/{pos_transaction_id}` | caissier |
| GET | `/transactions/{id}`, `/transactions/subscription/{id}`, `/transactions/my` | membre du restaurant concerné |

### Restaurants, catalogue, stock

| Méthode | Route | Accès |
|---|---|---|
| POST, GET | `/restaurants`, `/restaurants/me`, `/restaurants/{id}` | membre |
| PUT | `/restaurants/{id}` | propriétaire ou admin |
| POST, PUT | `/restaurants/{id}/menus`, `/restaurants/menus/{id}` | manager |
| POST, PUT | `/restaurants/menus/{id}/categories`, `/restaurants/categories/{id}` | manager |
| POST, PUT | `/restaurants/{id}/composants`, `/restaurants/composants/{id}` | manager |
| POST, PUT | `/restaurants/{id}/combinaisons`, `/restaurants/combinaisons/{id}` | manager |
| POST, PUT | `/restaurants/{id}/plats`, `/restaurants/plats/{id}` | manager |
| GET, POST, PUT, DELETE | `/restaurants/plats/{id}/composants` (nomenclature) | lecture : membre ; écriture : manager |
| POST, PUT | `/restaurants/{id}/boissons`, `/restaurants/boissons/{id}` | manager |
| POST | `/restaurants/{id}/tables` | manager |
| PUT | `/restaurants/tables/{id}` | serveur, caissier, hôte, barman |
| GET | `.../menus`, `.../composants`, `.../stock`, `.../combinaisons`, `.../combinaisons/recommandations`, `.../plats`, `.../boissons`, `.../tables`, `.../tables/free` | membre |
| POST | `/restaurants/composants/{id}/stock/mouvements` | chef, sous-chef |

### Commandes historiques et remboursements (dépréciés)

| Méthode | Route | Accès |
|---|---|---|
| POST, PUT | `/restaurants/{id}/commandes`, `/restaurants/commandes/{id}`, `.../items` | serveur, caissier, hôte, barman |
| GET | `/restaurants/{id}/commandes`, `.../commandes/active`, `/restaurants/commandes/{id}`, `.../items` | membre |
| POST | `/restaurants/commandes/{id}/refunds` | caissier |
| GET | `/restaurants/commandes/{id}/refunds` | membre |
| POST | `.../refunds/{refund_id}/approve`, `.../refunds/{refund_id}/reject` | manager |

### Moteur ROS

| Méthode | Route | Accès |
|---|---|---|
| POST | `/ros/restaurants/{id}/customers`, `.../sessions`, `.../orders` | serveur, caissier, hôte, barman |
| GET | `/ros/restaurants/{id}/sessions`, `.../sessions/{session_id}/invoice`, `.../invoices/{invoice_id}` | serveur, caissier, hôte, barman |
| POST | `/ros/restaurants/{id}/sessions/{session_id}/close` | serveur, caissier, hôte, barman |
| GET | `/ros/restaurants/{id}/tickets/{station}` | chef, sous-chef, barman, serveur, hôte |
| PUT | `/ros/restaurants/{id}/tickets/{ticket_id}/status` | chef, sous-chef, barman, serveur, hôte |
| POST | `/ros/restaurants/{id}/payments`, `.../payments/split` | caissier |
| POST | `/ros/restaurants/{id}/shifts/open`, `.../shifts/close` | caissier |
| POST | `/ros/restaurants/{id}/sync` | serveur, caissier, hôte, barman (caissier si paiements) |
| GET | `/ros/restaurants/{id}/procurement/suggestions` | chef, sous-chef |
| GET | `/ros/group/reporting` | membre (restaurants dont on est propriétaire) |
| WS | `/ros/ws/kds/{restaurant_id}/{station}` | chef, sous-chef, barman, serveur, hôte |

Le WebSocket s'authentifie lors de la poignée de main. Navigateur : `new WebSocket(url, ["bearer", accessToken])` (le jeton n'est jamais dans l'URL). Client non navigateur : en-tête `Authorization: Bearer ...`. Une connexion refusée reçoit une réponse HTTP `403`.

### Réservations

| Méthode | Route | Accès |
|---|---|---|
| POST, GET | `/reservations/restaurants/{id}/reservations`, `.../waitlist` | hôte, serveur, caissier |
| GET, PUT, DELETE | `/reservations/{reservation_id}` | hôte, serveur, caissier |
| POST | `/reservations/{id}/confirm`, `/check-in`, `/cancel` | hôte, serveur, caissier |
| POST, DELETE | `/reservations/waitlist/{waitlist_id}/seat`, `/reservations/waitlist/{waitlist_id}` | hôte, serveur, caissier |

### Paiements et administration

| Méthode | Route | Accès |
|---|---|---|
| PUT | `/payments/easytransact/configuration` | manager |
| POST | `/payments/easytransact/checkout`, `/payments/easytransact/initiate` | caissier |
| GET | `/payments/easytransact/{payment_intent_id}/status` | membre du restaurant concerné |
| POST | `/payments/easytransact/webhook/{restaurant_id}` | public (signature HMAC) |
| GET, POST, PATCH | `/admin/mobile-operator-prefixes` | admin |

## Migrations

La base se gère uniquement avec Alembic ; `SKIP_DB_INIT=true` empêche la création automatique des tables.

```powershell
python -m alembic current                    # révision appliquée
python -m alembic upgrade head               # appliquer
python -m alembic downgrade -1               # annuler la dernière
python -m alembic upgrade head --sql         # voir le SQL sans l'exécuter
python -m alembic revision --autogenerate -m "description"
```

Relire toute migration générée avant de l'appliquer. Les migrations s'exécutent avec `MIGRATION_DATABASE_URL`.

| Révision | Contenu |
|---|---|
| `20260914_1200` | Utilisateurs, offres, abonnements, soldes, transactions, refresh tokens |
| `20260915_1400` | Restaurants, menus, catégories, plats, boissons, tables, commandes |
| `20260916_1000` | Composants, combinaisons, suppléments |
| `20260916_1200` | Stock, réservations de stock, mouvements |
| `20260924_1200` | Isolation tenant (RLS), membres, journal de paiement, préfixes d'opérateurs |
| `20260925_1600` | Moteur ROS : clients, sessions, commandes, tickets, factures, paiements, caisse, audit |
| `20260925_1700` | Rôles étendus, vérifications, 2FA, nomenclature des plats, remboursements, réservations, liste d'attente, suppression logique |
| `20260926_1000` | RLS sur les tables ROS, réservations, nomenclature et remboursements |

## Tests

```powershell
python -m pytest --ignore=tests/test_ros.py -q
```

184 tests, **sans base de données** : ils tournent en quelques secondes et couvrent notamment :

- **Couverture des routes** : échec si une route n'a ni authentification ni garde de restaurant, ou si une action sensible (prix, remboursement, encaissement) est ouverte à un rôle trop large.
- **Rôles** : décision d'accès pour propriétaire, manager, serveur, caissier, anciens rôles.
- **2FA** : activation, exigence du code au login, code de secours à usage unique, secret chiffré.
- **Secrets** : aucun jeton dans les réponses, noms de secrets de paiement restreints, webhook signé.
- **WebSocket** : refus des connexions anonymes ou au jeton falsifié.
- **Références croisées** : identifiants et clés d'idempotence d'un autre restaurant.

### Tests d'intégration de l'API

`tests/test_api_integration.py` (47 tests) appelle **toutes les routes** contre PostgreSQL, avec le **rôle applicatif** donc sous RLS réelle, comme en production. Il détecte ce que les tests unitaires ne voient pas : une route dont le service a une autre signature, un schéma de réponse différent du modèle, une transaction validée en cours de requête.

Il s'ignore sans `TEST_DATABASE_URL`. Cette URL doit viser une base **jetable** (le nom contient `test`), migrée à la dernière révision, avec le rôle applicatif. Les requêtes sont validées comme en production : les données restent dans cette base.

```powershell
# 1. créer la base jetable et la migrer (voir Démarrage rapide, avec marinade_test comme nom)
# 2. lancer
$env:TEST_DATABASE_URL = "postgresql://marinade_app:...@localhost:5432/marinade_test"
python -m pytest tests/test_api_integration.py -q
```

### Scénarios ROS d'intégration

`tests/test_ros.py` (12 scénarios) exige une base PostgreSQL migrée et **écrit dedans** : ne le lance jamais sur une base qui contient des données. Il suppose un superutilisateur (il insère ses données de départ sans contexte de restaurant, ce que la RLS refuserait au rôle applicatif). Sur une base jetable :

```powershell
# 1. créer une base jetable "marinade_test" appartenant à marinade_owner (voir Démarrage rapide)
# 2. la migrer
$env:MIGRATION_DATABASE_URL = "postgresql://marinade_owner:...@localhost:5432/marinade_test"
python -m alembic upgrade head
# 3. lancer les scénarios en superutilisateur
$env:DB_NAME="marinade_test"; $env:DB_USER="<superutilisateur>"; $env:DB_PASSWORD="..."
python -m pytest tests/test_ros.py -q
```

Adapter ce test pour qu'il respecte la RLS et la règle « jamais la base de développement » fait partie des travaux prévus. Le fichier `tests/conftest.py` fournit déjà la fixture `postgres_test_session`, qui exige `TEST_DATABASE_URL` et annule tout en fin de test.

## Passage en production

Avec `ENVIRONMENT=production` (ou `prod`, `staging`), l'application **refuse de démarrer** si :

- `SECRET_KEY` est celle d'exemple ou fait moins de 32 caractères ;
- `DEBUG` est actif, ou `SKIP_DB_INIT` est faux ;
- `ALLOW_ORIGINS` est vide ou vaut `*`, ou des méthodes `*` sont combinées à des credentials ;
- `ALLOW_LEGACY_PAYMENT_SIMULATION` ou `DEV_EXPOSE_AUTH_TOKENS` est actif ;
- les identifiants Easy Transact ou le secret de webhook manquent ;
- le rôle de connexion à la base est superutilisateur ou `BYPASSRLS`.

À prévoir en plus (non couvert par le code) :

- un fournisseur réel d'e-mail et de SMS (sinon mot de passe oublié et vérifications sont inutilisables) ;
- une limitation de débit sur l'authentification et la 2FA ;
- `TWO_FACTOR_ENCRYPTION_KEY` dédiée, distincte de `SECRET_KEY` ;
- HTTPS en frontal, sauvegardes de la base et test de restauration, rotation des secrets ;
- une supervision (journaux centralisés, alertes).

## Dépannage

| Symptôme | Cause probable |
|---|---|
| `new row violates row-level security policy` | Le rôle connecté n'a pas de contexte de restaurant : requête hors API, ou test qui insère directement |
| L'API répond `404` sur un restaurant qui existe | L'utilisateur n'en est ni propriétaire ni membre actif (volontaire) |
| `400 X-Tenant-ID is required` | L'utilisateur appartient à plusieurs restaurants : envoyer `X-Tenant-ID` |
| `403 Insufficient permissions` | Le rôle d'équipe de l'utilisateur ne fait pas partie de ceux autorisés (voir [Rôles](#rôles-déquipe)) |
| Les tables n'existent pas | Migrations non appliquées : `python -m alembic upgrade head` |
| `permission denied for table …` avec `marinade_app` | Les privilèges par défaut n'ont pas été accordés avant la création des tables (voir [Démarrage rapide](#2-préparer-la-base--deux-rôles-distincts)) |
| Mot de passe oublié sans e-mail reçu | Les e-mails sont simulés ; en développement, activer `DEV_EXPOSE_AUTH_TOKENS=true` |
| `401` avec `two_factor_required` | La 2FA est activée : ajouter `two_factor_code` au login |
| Port 8000 occupé | `--port 8001` |
| pgAdmin n'atteint pas PostgreSQL | Utiliser `host.docker.internal` si les deux conteneurs sont sur des réseaux Docker différents |
| Erreur 500 à l'inscription ou à la connexion, `password cannot be longer than 72 bytes` | `bcrypt` 5 ou plus est incompatible avec `passlib 1.7.4` : `pip install -r requirements.txt` (la version `bcrypt==4.0.1` y est fixée) |
| Erreurs d'import au lancement | Utiliser Python 3.13 et recréer le venv |

## Documentation complémentaire

- [docs/RESTAURANT_GUIDE.md](docs/RESTAURANT_GUIDE.md) : configuration d'un restaurant (horaires, menus, plats, tables). En cours d'alignement avec le moteur ROS.
- [docs/POSITIONING_ANALYSIS.md](docs/POSITIONING_ANALYSIS.md) : analyse de positionnement face aux solutions existantes. En cours de mise à jour.
- [.trae/documents/P0_implementation_plan.md](.trae/documents/P0_implementation_plan.md) : plan des correctifs P0.
- [AGENTS.md](AGENTS.md) : guide pour les assistants de développement.

## Licence et contribution

La licence et la politique de contribution restent à préciser avant toute publication. Tout changement de schéma s'accompagne d'une migration Alembic et de tests ciblés.
