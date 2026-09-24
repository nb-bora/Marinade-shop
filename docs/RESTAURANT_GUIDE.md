# Guide de Personnalisation Marinade pour Restaurants

## Vue d'ensemble

Marinade a été adapté pour permettre à **n'importe quel restaurant** de personnaliser le système selon ses besoins spécifiques, tout en maintenant une base de gestion d'abonnements et de transactions.

## Ce qui est personnalisable par restaurant

### 1. Identité du Restaurant

Le restaurant peut configurer :

- **Nom du restaurant** : Nom affiché dans l'interface
- **Logo** : URL du logo personnalisé
- **Devise** : Devise par défaut (XAF, USD, EUR, etc.)
- **Téléphone** : Numéro de contact
- **Adresse** : Adresse physique
- **Ville/Pays** : Localisation
- **Taux de service** : Pourcentage de service appliqué automatiquement

### 2. Configuration d'Horaires

Via le champ `horaires_ouverture` (JSONB), le restaurant peut définir :

```json
{
  "lundi": {
    "ouverture": "08:00",
    "fermeture": "22:00",
    "actif": true
  },
  "mardi": {
    "ouverture": "08:00",
    "fermeture": "22:00",
    "actif": true
  },
  "mercredi": {
    "ouverture": "08:00",
    "fermeture": "22:00",
    "actif": true
  },
  "jeudi": {
    "ouverture": "08:00",
    "fermeture": "23:00",
    "actif": true
  },
  "vendredi": {
    "ouverture": "08:00",
    "fermeture": "23:00",
    "actif": true
  },
  "samedi": {
    "ouverture": "10:00",
    "fermeture": "00:00",
    "actif": true
  },
  "dimanche": {
    "ouverture": "10:00",
    "fermeture": "22:00",
    "actif": true
  }
}
```

### 3. Menus et Catégories

Le restaurant peut créer plusieurs menus avec :

- **Nom du menu** : Ex: "Menu du Midi", "Menu du Soir", "Menu Spécial"
- **Description** : Description détaillée du menu
- **Catégories personnalisées** : Entrées, Plats principaux, Desserts, Boissons, etc.
- **Ordre des catégories** : Ordre d'affichage dans l'interface
- **Actif/Inactif** : Activer/désactiver un menu selon les saisons

**Exemple de création de menu :**

```bash
POST /v1/restaurants/{restaurant_id}/menus
{
  "name": "Menu du Midi",
  "description": "Menu de midi pour les jours de semaine",
  "actif": true
}
```

### 4. Plats Personnalisés

Pour chaque plat, le restaurant peut configurer :

- **Nom du plat** : Nom affiché
- **Description** : Description détaillée
- **Prix** : Prix unitaire
- **Devise** : Devise du prix
- **Disponibilité** : Actif/inactif
- **Allergènes** : Liste des allergènes (JSONB)
- **Photo** : URL de la photo du plat
- **Temps de préparation** : En minutes
- **Attributs personnalisés** : Champs personnalisés via JSONB

**Exemple de création de plat :**

```bash
POST /v1/restaurants/{restaurant_id}/plats
{
  "nom": "Poulet Rôti",
  "description": "Poulet rôti avec légumes de saison",
  "prix": 8500,
  "devise": "XAF",
  "disponible": true,
  "allergènes": {
    "gluten": false,
    "lactose": false,
    "noix": false
  },
  "photo_url": "https://example.com/poulet.jpg",
  "temps_preparation": 25,
  "attributs_jsonb": {
    "specialite": "signature",
    "saison": ["ete", "automne"],
    "calories": 450
  }
}
```

### 5. Boissons Personnalisées

Pour chaque boisson, le restaurant peut configurer :

- **Nom de la boisson** : Nom affiché
- **Description** : Description détaillée
- **Prix** : Prix unitaire
- **Alcool/Non-alcool** : Type de boisson
- **Catégorie** : Vin, bière, soda, eau, etc.
- **Disponibilité** : Actif/inactif
- **Attributs personnalisés** : Degré d'alcool, volume, etc.

**Exemple de création de boisson :**

```bash
POST /v1/restaurants/{restaurant_id}/boissons
{
  "nom": "Bière Locale",
  "description": "Bière brassée localement",
  "prix": 1500,
  "devise": "XAF",
  "alcool": true,
  "disponible": true,
  "category": "biere",
  "attributs_jsonb": {
    "degres": 5.5,
    "volume": "33cl",
    "origine": "Cameroun"
  }
}
```

### 6. Tables et Capacité

Le restaurant peut configurer ses tables :

- **Numéro de table** : Identifiant unique
- **Capacité** : Nombre de places
- **Emplacement** : Terrasse, intérieur, VIP, etc.
- **Statut** : Libre, occupée, réservée, maintenance
- **Attributs personnalisés** : Proche fenêtre, accessible PMR, etc.

**Exemple de création de table :**

```bash
POST /v1/restaurants/{restaurant_id}/tables
{
  "numero": "T1",
  "capacite": 4,
  "emplacement": "interieur",
  "statut": "libre",
  "attributs_jsonb": {
    "proche_fenetre": true,
    "accessible_pmr": false,
    "zone": "non_fumeur"
  }
}
```

### 7. Configuration Avancée (JSONB)

Via le champ `config_jsonb`, le restaurant peut ajouter des configurations personnalisées :

```json
{
  "modes_paiement": ["especes", "carte", "mobile"],
  "taxes": {
    "tva": 19.25,
    "autre_taxe": 2.0
  },
  "minimum_commande": 2000,
  "pourboire_minimum": 500,
  "delai_preparation": 15,
  "notification_email": true,
  "notification_sms": false,
  "langue": "fr",
  "fuseau_horaire": "Africa/Douala"
}
```

### 8. Composants, combinaisons et stock

Les offres composées doivent être configurées avec des composants indépendants : base, sauce, protéine ou accompagnement.
Une combinaison possède son propre prix, tandis qu'un supplément est tarifé depuis le composant sélectionné.

Exemple de composant :

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

Exemple de combinaison :

```json
{
  "nom": "Riz sauce tomate poulet",
  "prix": 3500,
  "devise": "XAF",
  "composant_ids": ["<riz_id>", "<sauce_tomate_id>", "<poulet_id>"]
}
```

Le stock disponible est égal au stock physique moins le stock réservé par les commandes en cours.
Une combinaison est recommandée uniquement si ses composants sont actifs et disponibles.
L'ajout d'une combinaison à une commande réserve le stock ; le paiement le consomme et l'annulation le libère.

Endpoints :

- `POST /v1/restaurants/{id}/composants` - Créer un composant
- `GET /v1/restaurants/{id}/composants` - Lister les composants
- `GET /v1/restaurants/{id}/stock` - Consulter le stock disponible et réservé
- `POST /v1/restaurants/composants/{id}/stock/mouvements` - Ajouter une entrée ou un ajustement
- `POST /v1/restaurants/{id}/combinaisons` - Créer une combinaison tarifée
- `GET /v1/restaurants/{id}/combinaisons/recommandations` - Obtenir les combinaisons vendables

Pour ajouter une combinaison à une commande, utiliser `combinaison_id`. Pour un supplément, transmettre les identifiants dans `supplement_ids`.

## API Endpoints pour la Personnalisation

### Restaurant

- `POST /v1/restaurants/` - Créer son restaurant
- `GET /v1/restaurants/me` - Voir son restaurant
- `PUT /v1/restaurants/{id}` - Modifier son restaurant

### Menus

- `POST /v1/restaurants/{id}/menus` - Créer un menu
- `GET /v1/restaurants/{id}/menus` - Lister ses menus
- `PUT /v1/restaurants/menus/{id}` - Modifier un menu

### Catégories

- `POST /v1/restaurants/menus/{id}/categories` - Créer une catégorie
- `GET /v1/restaurants/menus/{id}/categories` - Lister les catégories d'un menu
- `PUT /v1/restaurants/categories/{id}` - Modifier une catégorie

### Plats

- `POST /v1/restaurants/{id}/plats` - Créer un plat
- `GET /v1/restaurants/{id}/plats` - Lister ses plats
- `PUT /v1/restaurants/plats/{id}` - Modifier un plat

### Boissons

- `POST /v1/restaurants/{id}/boissons` - Créer une boisson
- `GET /v1/restaurants/{id}/boissons` - Lister ses boissons
- `PUT /v1/restaurants/boissons/{id}` - Modifier une boisson

### Tables

- `POST /v1/restaurants/{id}/tables` - Créer une table
- `GET /v1/restaurants/{id}/tables` - Lister ses tables
- `GET /v1/restaurants/{id}/tables/free` - Tables libres
- `PUT /v1/restaurants/tables/{id}` - Modifier une table

### Commandes

- `POST /v1/restaurants/{id}/commandes` - Créer une commande
- `GET /v1/restaurants/{id}/commandes` - Lister ses commandes
- `GET /v1/restaurants/{id}/commandes/active` - Commandes actives
- `PUT /v1/restaurants/commandes/{id}` - Modifier une commande
- `POST /v1/restaurants/commandes/{id}/items` - Ajouter un item
- `GET /v1/restaurants/commandes/{id}/items` - Lister les items

## Scénarios d'Utilisation

### Scénario 1 : Création d'un nouveau restaurant

1. L'utilisateur s'inscrit avec le rôle "restaurant"
2. Il crée son profil restaurant :
   ```bash
   POST /v1/restaurants/
   {
     "name": "Le Gourmet",
     "description": "Restaurant africain authentique",
     "currency": "XAF",
     "phone": "+237 123 456 789",
     "address": "123 Rue Principale",
     "city": "Douala",
     "country": "Cameroun",
     "taux_service": 10.0
   }
   ```
3. Il configure ses horaires d'ouverture
4. Il crée ses menus
5. Il ajoute ses plats et boissons
6. Il configure ses tables

### Scénario 2 : Modification du menu saisonnier

1. Le restaurant désactive l'ancien menu
2. Il crée un nouveau menu "Menu Été"
3. Il ajoute les plats d'été
4. Il met à jour les prix si nécessaire
5. Il active le nouveau menu

### Scénario 3 : Gestion des tables

1. Le restaurant crée ses tables avec capacité
2. En temps réel, il met à jour le statut des tables (libre/occupée)
3. Il peut consulter les tables libres pour assigner aux clients
4. Il peut réserver des tables pour les futures réservations

## Intégration avec les Abonnements

Les restaurants peuvent avoir des abonnements qui déterminent :

- **Nombre de tables** : Selon le tier d'abonnement
- **Nombre de menus** : Limites sur le nombre de menus actifs
- **Fonctionnalités** : Accès aux commandes, rapports, etc.
- **Support** : Niveau de support technique

**Exemple de tiers d'abonnement restaurant :**

- **Starter** : 10 tables, 2 menus, commandes basiques
- **Standard** : 30 tables, 5 menus, commandes + rapports
- **Premium** : 100 tables, menus illimités, fonctionnalités avancées

## Sécurité et Permissions

### Rôle Restaurant

- Accès complet à son restaurant
- Création/modification de ses menus, plats, boissons, tables
- Gestion de ses commandes
- Impossible d'accéder aux données d'autres restaurants

### Rôle Admin

- Accès à tous les restaurants
- Gestion des abonnements restaurant
- Support technique

## Configuration Multi-tenant

Chaque restaurant est isolé :

- **Isolation des données** : Chaque restaurant voit uniquement ses données
- **Isolation des permissions** : Un restaurant ne peut pas accéder aux autres
- **Configuration personnalisée** : Chaque restaurant a sa propre configuration
- **Abonnement indépendant** : Chaque restaurant a son propre abonnement

## Extensions Futures

### Configuration Avancée (Futur)

À terme, le système permettra :

- **Règles métier configurables** : Ex: "Si commande > 50000 FCFA, appliquer 5% de réduction"
- **Workflows personnalisés** : Processus de validation de commandes
- **Templates de menus** : Templates prédéfinis pour différents types de restaurants
- **Intégrations** : Paiement mobile, SMS, email
- **Rapports personnalisés** : Statistiques de vente,最受欢迎 plats, etc.

### Admin Studio (Futur)

Interface no-code permettant aux restaurants de :

- Créer des menus visuellement
- Configurer des règles de pricing
- Personnaliser l'interface
- Créer des rapports personnalisés
- Automatiser des processus

## Exemple Complet de Configuration

```bash
# 1. Créer le restaurant
POST /v1/restaurants/
{
  "name": "Saveur d'Afrique",
  "description": "Cuisine africaine traditionnelle",
  "currency": "XAF",
  "phone": "+237 699 123 456",
  "address": "45 Avenue Kennedy",
  "city": "Yaoundé",
  "country": "Cameroun",
  "horaires_ouverture": {
    "lundi": {"ouverture": "11:00", "fermeture": "23:00", "actif": true},
    "dimanche": {"ouverture": "12:00", "fermeture": "22:00", "actif": true}
  },
  "taux_service": 10.0,
  "config_jsonb": {
    "minimum_commande": 3000,
    "pourboire_minimum": 500,
    "modes_paiement": ["especes", "mobile"],
    "taxes": {"tva": 19.25}
  }
}

# 2. Créer un menu
POST /v1/restaurants/{restaurant_id}/menus
{
  "name": "Menu Signature",
  "description": "Nos plats signature",
  "actif": true
}

# 3. Créer des catégories
POST /v1/restaurants/menus/{menu_id}/categories
{
  "name": "Entrées",
  "ordre": 1
}

POST /v1/restaurants/menus/{menu_id}/categories
{
  "name": "Plats Principaux",
  "ordre": 2
}

# 4. Créer des plats
POST /v1/restaurants/{restaurant_id}/plats
{
  "nom": "Ndolé",
  "description": "Ndolé avec bœuf et arachide",
  "prix": 12000,
  "devise": "XAF",
  "disponible": true,
  "category_id": "{category_id}",
  "allergenes": {"arachide": true},
  "temps_preparation": 30
}

# 5. Créer des boissons
POST /v1/restaurants/{restaurant_id}/boissons
{
  "nom": "Jus d'Ananas",
  "description": "Jus d'ananas frais",
  "prix": 1500,
  "devise": "XAF",
  "alcool": false,
  "disponible": true,
  "category": "jus"
}

# 6. Créer des tables
POST /v1/restaurants/{restaurant_id}/tables
{
  "numero": "T1",
  "capacite": 4,
  "emplacement": "interieur",
  "statut": "libre"
}

POST /v1/restaurants/{restaurant_id}/tables
{
  "numero": "T2",
  "capacite": 6,
  "emplacement": "terrasse",
  "statut": "libre"
}
```

## Support et Maintenance

### Documentation

- API documentation disponible via Swagger/OpenAPI
- Guides d'utilisation pour chaque fonctionnalité
- Exemples de configurations

### Support

- Support technique via email/téléphone
- Formation pour les nouveaux restaurants
- Mises à jour régulières du système

## Conclusion

Marinade offre une plateforme flexible et personnalisable pour les restaurants, permettant à chaque établissement de configurer le système selon ses besoins spécifiques tout en bénéficiant d'une infrastructure de gestion d'abonnements robuste.
