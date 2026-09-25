# Implémentation des Correctifs P0 - Marinade

## Repository Research

### État actuel analysé

**1. Double modèle de commandes (Commande vs RosOrder)**
- `Commande` dans [restaurant.py](file:///d:/MITS/Projets/Marinade/app/models/restaurant.py#L243-L265) : modèle simple, lié aux tables, statuts limités (en_cours, servie, annulée, payee, paiement_en_attente, paiement_a_verifier)
- `RosOrder` dans [ros.py](file:///d:/MITS/Projets/Marinade/app/models/ros.py#L51-L72) : modèle riche avec sessions, tickets de production, factures, gestion multi-stations, idempotence
- Aucune migration, aucun pont, aucune dépréciation formelle. Les deux modèles fonctionnent en parallèle sans coordination.

**2. Rôles limités (3 rôles seulement)**
- Modèle `User.role` avec contrainte CHECK : `admin | pos | restaurant` dans [user.py](file:///d:/MITS/Projets/Marinade/app/models/user.py#L23-L24)
- `UserRole` enum dans [enums.py](file:///d:/MITS/Projets/Marinade/app/utils/enums.py#L4-L7)
- `RestaurantMember` existe dans [tenant.py](file:///d:/MITS/Projets/Marinade/app/models/tenant.py) mais pas de rôle fin ni permission par établissement
- Les guards dans [dependencies.py](file:///d:/MITS/Projets/Marinade/app/api/dependencies.py#L130-L139) ne vérifient que les 3 rôles de base

**3. Absence de gestion des réservations**
- `TableStatut.RESERVEE` existe dans [enums.py](file:///d:/MITS/Projets/Marinade/app/utils/enums.py#L18-L22) mais n'est jamais exploité
- Aucune table de réservation, aucun endpoint, aucune logique métier
- Aucune gestion de liste d'attente ni de planning

**4. Authentification incomplète**
- Endpoints existants : register, login, refresh, logout dans [auth.py](file:///d:/MITS/Projets/Marinade/app/api/v1/auth.py)
- Pas de : forgot password, reset password, verify email, verify phone, 2FA/MFA
- `User` n'a pas de colonnes `email_verified_at`, `phone_verified_at`, `two_factor_secret`, `reset_token*`
- Aucun envoi d'email/SMS de vérification (le `notification_service.py` existe mais non branché sur l'authentification)

**5. Pas de BOM (Nomenclature) pour les plats standards**
- `CombinaisonComposant` lie correctement `Combinaison` → `Composant` avec quantité dans [restaurant.py](file:///d:/MITS/Projets/Marinade/app/models/restaurant.py#L117-L132)
- `Plat` n'a **aucun lien** vers `Composant`. Impossible de définir une recette pour un plat standard.
- Les `StockComposant` existent mais ne sont jamais déduits lors de la création d'une `Commande` classique contenant des plats
- `StockMouvement` existe mais n'est pas déclenché automatiquement par les commandes classiques

---

## Files and Modules

### Nouveaux fichiers à créer
- `alembic/versions/20260925_1700_p0_migration.py` : migration regroupant toutes les modifications P0
- `app/models/reservation.py` : modèles Reservation, ReservationGuest, WaitlistEntry
- `app/schemas/reservation.py` : schémas Pydantic pour réservations
- `app/repositories/reservation_repository.py` : Repository pour réservations
- `app/services/reservation_service.py` : Logique métier réservations

### Fichiers à modifier

**Modèles**
- `app/models/user.py` : + colonnes (email_verified_at, phone_verified_at, reset_token, reset_token_expires_at, two_factor_secret, two_factor_recovery_codes, two_factor_confirmed_at, is_deleted, deleted_at) + suppression CHECK(role) contraint
- `app/models/restaurant.py` : + PlatComposant (BOM plat→composants) + Commande refund fields + soft delete (deleted_at) sur entités restaurant-related
- `app/models/__init__.py` : exports des nouveaux modèles
- `app/models/tenant.py` : + RestaurantMember.role (granular)

**Enums**
- `app/utils/enums.py` : + StaffRole (serveur, caissier, chef, manager, livreur), ReservationStatus, RefundStatus, PlatType, VerificationStatus

**Schémas**
- `app/schemas/user.py` : nouveaux schémas (PasswordResetRequest, PasswordResetConfirm, EmailVerifyRequest, TwoFactorSetup, TwoFactorLogin, UserResponse étendu)
- `app/schemas/restaurant.py` : nouveaux schémas (PlatComposantCreate, PlatComposantUpdate, CommandeRefundRequest, Plat étendu avec BOM)
- `app/schemas/__init__.py` : exports

**Repositories**
- `app/repositories/restaurant_repository.py` : + PlatComposantRepository + extensions CommandeRepository (refund, stock deduction)
- `app/repositories/user_repository.py` : méthodes reset password, verification tokens, 2FA
- `app/repositories/__init__.py` : exports

**Services**
- `app/services/auth_service.py` : + forgot_password(), reset_password(), send_email_verification(), verify_email(), setup_2fa(), verify_2fa_login(), disable_2fa()
- `app/services/restaurant_service.py` : + PlatComposantService (CRUD nomenclatures) + déduction auto de stock sur Commande + Commande refund workflow
- `app/services/__init__.py` : exports

**API**
- `app/api/v1/auth.py` : nouveaux endpoints (/forgot-password, /reset-password, /verify-email, /resend-verification, /2fa/setup, /2fa/verify, /2fa/disable)
- `app/api/v1/restaurants.py` : nouveaux endpoints (/restaurant/{id}/plats/{plat_id}/composants, /commandes/{id}/refund, /commandes/{id}/refunds) + intérêt /reservations en import
- `app/api/v1/reservations.py` (NOUVEAU) : CRUD réservations + waitlist
- `app/api/router.py` : inclusion du routeur reservations

**Dépendances**
- `app/api/dependencies.py` : + require_staff_role(role_name) guard pour permissions fines

**Configuration**
- `app/core/config.py` : + RESET_TOKEN_EXPIRE_MINUTES, VERIFICATION_TOKEN_EXPIRE_HOURS, EMAIL_FROM, 2FA_ISSUER variables
- `.env.example` : nouvelles variables

---

## Implementation Steps (ordre de dépendance)

### Étape 1 : Modèles et schémas - Bases communes
1. Étendre `UserRole` enum et ajouter `StaffRole`, `ReservationStatus`, `RefundStatus`, `VerificationStatus` dans `enums.py`
2. Modifier `User` : ajouter colonnes vérification, reset password, 2FA, soft delete. Remplacer CHECK(role) par un CHECK plus large.
3. Modifier `RestaurantMember` : ajouter colonne `staff_role` avec enum granular
4. Créer modèle `PlatComposant` (BOM) avec FK plat_id, composant_id, quantité, unité, ordre
5. Ajouter colonnes refund sur `Commande` (refund_status, refunded_amount, refunded_at, refund_reason, refunded_by)
6. Ajouter `deleted_at` (soft delete) sur `Commande`, `Plat`, `Boisson`, `Composant`, `Menu`
7. Créer modèles `Reservation`, `ReservationGuest`, `WaitlistEntry` dans nouveau fichier
8. Mettre à jour `__init__.py` des modèles
9. Créer tous les schémas Pydantic associés

### Étape 2 : Migration de base de données
10. Générer une migration Alembic unique (`20260925_1700_p0_migration.py`) couvrant :
    - Nouvelles colonnes User
    - PlatComposant table
    - Reservation / Waitlist tables
    - Commande refund fields
    - Soft delete columns
    - RestaurantMember.staff_role
    - Index appropriés

### Étape 3 : Repositories
11. Étendre `UserRepository` : find_by_reset_token, save_reset_token, clear_reset_token, set_email_verified, set_phone_verified, save_2fa_secret
12. Étendre `RestaurantRepository` : PlatComposantRepository, refund méthodes CommandeRepository
13. Créer `ReservationRepository`, `WaitlistRepository`

### Étape 4 : Services - Logique métier
14. Étendre `AuthService` avec toutes les méthodes auth manquantes (reset pwd, verify email, 2FA)
    - Utiliser `notification_service.py` existant pour envoi emails/SMS
    - Génération de tokens sécurisés (JWT signés ou random url-safe)
    - Validation TOTP pour 2FA (utiliser `pyotp` si pas déjà dans requirements - vérifier d'abord)
15. Étendre `RestaurantService` :
    - PlatComposantService : CRUD nomenclatures, validation cohérence restaurant_id
    - Dans `CommandeService.create_commande()` : pour chaque CommandeItem, si plat → déduire stock via PlatComposant + créer StockMouvement. Si combinaison → utiliser logique existante CombinaisonComposant.
    - Refund workflow : initier_refund(), valider_refund() avec validation de montant, création de refund transactions, annulation/déduction de stock inversée
16. Créer `ReservationService` :
    - Vérification de disponibilité de table avec conflit horaires
    - Transition TableStatut ↔ RESERVEE
    - Gestion liste d'attente (promotion auto quand table libérée)
    - Notifications (rappel réservation J-1 / H-1)

### Étape 5 : API Endpoints
17. Étendre `/v1/auth/*` avec les 7 nouveaux endpoints (step 1 files list)
18. Créer `/v1/reservations.py` avec :
    - `POST /restaurants/{id}/reservations` - créer réservation
    - `GET /restaurants/{id}/reservations` - lister (filtres date/statut/table)
    - `GET /reservations/{id}` - détails
    - `PUT /reservations/{id}` - modifier
    - `DELETE /reservations/{id}` - annuler
    - `POST /restaurants/{id}/waitlist` - ajouter à la liste d'attente
    - `GET /restaurants/{id}/waitlist` - consulter liste d'attente
    - `POST /reservations/{id}/confirm` - confirmer réservation
19. Étendre `/v1/restaurants.py` :
    - BOM endpoints (CRUD PlatComposant)
    - Refund endpoints
20. Mettre à jour `require_tenant_path` dans `dependencies.py` pour couvrir `reservation_id`
21. Ajouter `require_staff_role()` guard dans `dependencies.py`
22. Imports et routage dans `api/router.py`

### Étape 6 : Intégration et configuration
23. Mettre à jour `core/config.py` avec nouvelles variables d'env
24. Mettre à jour `.env.example`
25. Vérifier requirements.txt pour dépendances (pyotp, etc.) - n'ajouter que si absent et réellement nécessaire

### Étape 7 : Dépréciation explicite de l'ancien modèle Commande (P0 - item 1)
26. Ajouter un event logger `DeprecationWarning` à chaque appel aux endpoints `/commandes` classique
27. Marquer les routes Commande classiques avec `deprecated=True` dans FastAPI (paramètre natif)
28. Ajouter un header de réponse `X-Deprecated-Endpoint: use-ros-orders`
29. Documenter la migration dans un commentaire TODO pour la migration V2 (pas de suppression dans ce P0 - juste dépréciation formelle et documentation)

---

## Dependencies and Considerations

### Dépendances externes potentielles
- `pyotp` : pour TOTP 2FA (vérifier si déjà dans requirements.txt)
- Aucune nouvelle dépendance lourde. Le `notification_service.py` existant suffit pour emails/SMS.

### Contraintes et points d'attention
- **Backward compatibility** : Ne PAS supprimer l'ancien modèle Commande. Seulement déprécier (marqueurs FastAPI `deprecated=True`). Les clients existants ne doivent pas casser.
- **RLS & Multi-tenant** : Toutes les nouvelles tables (Reservation, PlatComposant, etc.) DOIVENT avoir `restaurant_id` et être compatibles avec le mécanisme RLS existant dans `dependencies.py` (set_db_context + _authorize_tenant)
- **Performance** : La déduction de stock sur chaque commande DOIT être transactionnelle (DB transaction) et utiliser des verrous optimistes pour éviter les ventes en stock négatif.
- **2FA Recovery codes** : Doivent être hashés (bcrypt) avant stockage, jamais en clair.
- **Reset tokens** : JWT signés avec expiration courte (15 min recommandé) OU random token stocké hashé en DB. Préférence : random hashé en DB (révocable immédiatement).
- **Idempotence refunds** : Ajouter un `refund_idempotency_key` sur Commande pour éviter doubles remboursements.
- **Réservations conflictuelles** : Utiliser une transaction avec SERIALIZABLE ou verrou explicite sur la table lors de la vérification de disponibilité.

### Compatibilité ROS
- Le modèle RosOrder est déjà le chemin privilégié. L'ancien Commande ne reçoit que la déduction de stock et le refund pour parité fonctionnelle, pas d'évolutions supplémentaires.
- La déduction stock DOIT être implémentée aussi côté RosOrder si pas déjà le cas (vérifier dans ros_service.py).

---

## Validation

### Tests automatisés
- `pytest tests/` - tout l'existant doit passer (non-régression)
- Nouveaux tests dans `tests/test_auth_p0.py` : forgot/reset password flow, email verify, 2FA setup/verify/login/disable
- Nouveaux tests dans `tests/test_reservation.py` : CRUD réservation, conflit horaire, waitlist, annulation
- Nouveaux tests dans `tests/test_stock_bom.py` : PlatComposant CRUD, déduction stock auto sur commande, stock négatif bloqué
- Nouveaux tests dans `tests/test_refund.py` : refund total, refund partiel, refund impossible (montant > total), idempotence

### Vérifications manuelles
- Démarrer l'app : `uvicorn app.main:app --reload`
- Vérifier `/docs` OpenAPI : tous nouveaux endpoints visibles, schémas corrects
- Endpoints `/auth/*` : flow complet reset password, 2FA
- Endpoints `/reservations/*` : scénario complet création → conflit → waitlist → promotion
- `/restaurants/{id}/plats/{id}/composants` : création BOM, déduction stock sur commande classique

### Checks qualité
- `ruff format .`
- `ruff check .`
- `alembic upgrade head` → aucun erreur
- `alembic downgrade -1 && alembic upgrade head` → migration idempotente
- `GetDiagnostics` VS Code : zero erreurs de type

---

## Risques

| Risque | Probabilité | Impact | Mitigation |
|---|---|---|---|
| **Régression de l'ancien modèle Commande** | Moyenne | Élevée | Tests non-régression ciblés sur les routes existantes. Ne modifier que l'ajout de fonctionnalités, pas le comportement existant. |
| **Deadlock sur déduction stock concurrente** | Faible | Élevée | Utiliser `SELECT ... FOR UPDATE` sur StockComposant dans la transaction. Tests de charge simulés. |
| **2FA setup qui casse le login existant** | Faible | Critique | 2FA est OPT-IN (champ `two_factor_confirmed_at` NULL tant que non activé). Le flow login classique ne change pas pour les users sans 2FA. |
| **Reset token leak via logs** | Faible | Moyenne | Stocker les tokens hashés en DB (SHA256). Logger uniquement l'ID user, jamais le token brut. |
| **Migration Alembic échoue en production** | Faible | Élevée | Test de la migration sur base de staging avec données réelles. La migration est réversible (downgrade). Ajout de colonnes nullable uniquement, pas de renommage destructif. |
| **Réservations créées malgré un conflit horaire** | Moyenne | Moyenne | Transaction SQL avec niveau d'isolation REPEATABLE READ + contrainte d'exclusion (PostgreSQL `EXCLUDE USING gist` sur tsrange + table_id) si disponible. |
