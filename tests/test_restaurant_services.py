import pytest
from decimal import Decimal
import uuid

# Tests unitaires sans base de données pour valider la logique business


@pytest.fixture
def test_user_id():
    """Fixture pour un ID utilisateur de test"""
    return uuid.uuid4()


@pytest.fixture
def restaurant_service(db_session):
    """Fixture pour le service restaurant"""
    return RestaurantService(db_session)


@pytest.fixture
def menu_service(db_session):
    """Fixture pour le service menu"""
    return MenuService(db_session)


@pytest.fixture
def plat_service(db_session):
    """Fixture pour le service plat"""
    return PlatService(db_session)


@pytest.fixture
def boisson_service(db_session):
    """Fixture pour le service boisson"""
    return BoissonService(db_session)


@pytest.fixture
def table_service(db_session):
    """Fixture pour le service table"""
    return TableService(db_session)


@pytest.fixture
def commande_service(db_session):
    """Fixture pour le service commande"""
    return CommandeService(db_session)


@pytest.fixture
def payment_service(db_session):
    """Fixture pour le service paiement"""
    return PaymentService(db_session)


@pytest.fixture
def notification_service(db_session):
    """Fixture pour le service notification"""
    return NotificationService(db_session)


@pytest.fixture
def sample_restaurant(restaurant_service, test_user_id):
    """Fixture pour créer un restaurant de test"""
    restaurant_data = RestaurantCreate(
        name="Restaurant Test",
        description="Restaurant pour les tests",
        currency="XAF",
        phone="+237123456789",
        address="123 Rue Test",
        city="Douala",
        country="Cameroun",
        taux_service=Decimal("10.0")
    )
    return restaurant_service.create_restaurant(restaurant_data, test_user_id)


@pytest.fixture
def sample_menu(menu_service, sample_restaurant):
    """Fixture pour créer un menu de test"""
    menu_data = MenuCreate(
        name="Menu Principal",
        description="Menu principal du restaurant"
    )
    return menu_service.create_menu(menu_data, sample_restaurant.id)


@pytest.fixture
def sample_category(menu_service, sample_restaurant, sample_menu):
    """Fixture pour créer une catégorie de test"""
    category_data = MenuCategoryCreate(
        menu_id=sample_menu.id,
        name="Entrées",
        ordre=1
    )
    return menu_service.create_category(category_data, sample_restaurant.id)


class TestRestaurantService:
    """Tests pour RestaurantService"""
    
    def test_create_restaurant_success(self, restaurant_service, test_user_id):
        """Test création restaurant réussie"""
        restaurant_data = RestaurantCreate(
            name="Nouveau Restaurant",
            description="Description test",
            currency="XAF"
        )
        
        restaurant = restaurant_service.create_restaurant(restaurant_data, test_user_id)
        
        assert restaurant is not None
        assert restaurant.name == "Nouveau Restaurant"
        assert restaurant.user_id == test_user_id
        assert restaurant.currency == "XAF"
    
    def test_create_restaurant_duplicate(self, restaurant_service, test_user_id, sample_restaurant):
        """Test erreur création restaurant duplicate"""
        restaurant_data = RestaurantCreate(
            name="Restaurant Test",
            description="Duplicate test"
        )
        
        with pytest.raises(ValueError, match="User already has a restaurant"):
            restaurant_service.create_restaurant(restaurant_data, test_user_id)
    
    def test_get_user_restaurant(self, restaurant_service, test_user_id, sample_restaurant):
        """Test récupération restaurant par user"""
        restaurant = restaurant_service.get_user_restaurant(test_user_id)
        
        assert restaurant is not None
        assert restaurant.id == sample_restaurant.id
    
    def test_update_restaurant(self, restaurant_service, sample_restaurant):
        """Test mise à jour restaurant"""
        update_data = RestaurantCreate(
            name="Restaurant Modifié",
            description="Nouvelle description"
        )
        
        updated = restaurant_service.update_restaurant(sample_restaurant.id, update_data)
        
        assert updated.name == "Restaurant Modifié"
        assert updated.description == "Nouvelle description"


class TestMenuService:
    """Tests pour MenuService"""
    
    def test_create_menu_success(self, menu_service, sample_restaurant):
        """Test création menu réussie"""
        menu_data = MenuCreate(
            name="Menu Déjeuner",
            description="Menu de midi"
        )
        
        menu = menu_service.create_menu(menu_data, sample_restaurant.id)
        
        assert menu is not None
        assert menu.name == "Menu Déjeuner"
        assert menu.restaurant_id == sample_restaurant.id
    
    def test_create_menu_duplicate_name(self, menu_service, sample_restaurant, sample_menu):
        """Test erreur création menu avec nom duplicate"""
        menu_data = MenuCreate(
            name="Menu Principal",  # Nom déjà utilisé
            description="Duplicate name test"
        )
        
        with pytest.raises(ValueError, match="Menu name already exists"):
            menu_service.create_menu(menu_data, sample_restaurant.id)
    
    def test_create_category_success(self, menu_service, sample_restaurant, sample_menu):
        """Test création catégorie réussie"""
        category_data = MenuCategoryCreate(
            menu_id=sample_menu.id,
            name="Plats principaux",
            ordre=2
        )
        
        category = menu_service.create_category(category_data, sample_restaurant.id)
        
        assert category is not None
        assert category.name == "Plats principaux"
        assert category.ordre == 2
    
    def test_create_category_duplicate_order(self, menu_service, sample_restaurant, sample_menu, sample_category):
        """Test erreur création catégorie avec ordre duplicate"""
        category_data = MenuCategoryCreate(
            menu_id=sample_menu.id,
            name="Autre catégorie",
            ordre=1  # Ordre déjà utilisé
        )
        
        with pytest.raises(ValueError, match="Category order already exists"):
            menu_service.create_category(category_data, sample_restaurant.id)


class TestPlatService:
    """Tests pour PlatService"""
    
    def test_create_plat_success(self, plat_service, sample_restaurant, sample_category):
        """Test création plat réussie"""
        plat_data = PlatCreate(
            category_id=sample_category.id,
            nom="Poulet rôti",
            description="Poulet rôti avec légumes",
            prix=Decimal("5000.00"),
            devise="XAF"
        )
        
        plat = plat_service.create_plat(plat_data, sample_restaurant.id)
        
        assert plat is not None
        assert plat.nom == "Poulet rôti"
        assert plat.prix == Decimal("5000.00")
        assert plat.category_id == sample_category.id
    
    def test_create_plat_invalid_price(self, plat_service, sample_restaurant):
        """Test erreur création plat avec prix invalide"""
        plat_data = PlatCreate(
            nom="Plat gratuit",
            description="Plat avec prix négatif",
            prix=Decimal("-100.00"),
            devise="XAF"
        )
        
        with pytest.raises(ValueError, match="Price must be positive"):
            plat_service.create_plat(plat_data, sample_restaurant.id)
    
    def test_create_plat_invalid_category(self, plat_service, sample_restaurant):
        """Test erreur création plat avec catégorie invalide"""
        fake_category_id = uuid.uuid4()
        plat_data = PlatCreate(
            category_id=fake_category_id,
            nom="Plat sans catégorie",
            prix=Decimal("3000.00"),
            devise="XAF"
        )
        
        with pytest.raises(ValueError, match="Category not found"):
            plat_service.create_plat(plat_data, sample_restaurant.id)


class TestBoissonService:
    """Tests pour BoissonService"""
    
    def test_create_boisson_success(self, boisson_service, sample_restaurant):
        """Test création boisson réussie"""
        boisson_data = BoissonCreate(
            nom="Coca Cola",
            description="Boisson gazeuse",
            prix=Decimal("500.00"),
            devise="XAF",
            alcool=False,
            category="soda"
        )
        
        boisson = boisson_service.create_boisson(boisson_data, sample_restaurant.id)
        
        assert boisson is not None
        assert boisson.nom == "Coca Cola"
        assert boisson.prix == Decimal("500.00")
        assert boisson.alcool == False
    
    def test_create_boisson_alcoholic(self, boisson_service, sample_restaurant):
        """Test création boisson alcoolisée"""
        boisson_data = BoissonCreate(
            nom="Bière",
            description="Bière locale",
            prix=Decimal("1000.00"),
            devise="XAF",
            alcool=True,
            category="beer"
        )
        
        boisson = boisson_service.create_boisson(boisson_data, sample_restaurant.id)
        
        assert boisson.alcool == True
        assert boisson.category == "beer"


class TestTableService:
    """Tests pour TableService"""
    
    def test_create_table_success(self, table_service, sample_restaurant):
        """Test création table réussie"""
        table_data = TableCreate(
            numero="T1",
            capacite=4,
            emplacement="Terrasse"
        )
        
        table = table_service.create_table(table_data, sample_restaurant.id)
        
        assert table is not None
        assert table.numero == "T1"
        assert table.capacite == 4
        assert table.statut == "libre"
    
    def test_create_table_duplicate_number(self, table_service, sample_restaurant):
        """Test erreur création table avec numéro duplicate"""
        table_data = TableCreate(
            numero="T1",  # Numéro déjà utilisé
            capacite=2
        )
        
        with pytest.raises(ValueError, match="Table number already exists"):
            table_service.create_table(table_data, sample_restaurant.id)
    
    def test_get_free_tables(self, table_service, sample_restaurant):
        """Test récupération tables libres"""
        table_data = TableCreate(numero="T2", capacite=2)
        table_service.create_table(table_data, sample_restaurant.id)
        
        free_tables = table_service.get_free_tables(sample_restaurant.id)
        
        assert len(free_tables) >= 1
        assert all(table.statut == "libre" for table in free_tables)


class TestCommandeService:
    """Tests pour CommandeService"""
    
    def test_create_commande_success(self, commande_service, sample_restaurant, table_service):
        """Test création commande réussie"""
        # Créer une table
        table_data = TableCreate(numero="T3", capacite=4)
        table = table_service.create_table(table_data, sample_restaurant.id)
        
        commande_data = CommandeCreate(
            table_id=table.id,
            statut="en_cours",
            total=Decimal("0.00")
        )
        
        commande = commande_service.create_commande(commande_data, sample_restaurant.id)
        
        assert commande is not None
        assert commande.statut == "en_cours"
        assert commande.table_id == table.id
    
    def test_create_commande_with_invalid_table(self, commande_service, sample_restaurant):
        """Test erreur création commande avec table invalide"""
        fake_table_id = uuid.uuid4()
        commande_data = CommandeCreate(
            table_id=fake_table_id,
            statut="en_cours",
            total=Decimal("0.00")
        )
        
        with pytest.raises(ValueError, match="Invalid table"):
            commande_service.create_commande(commande_data, sample_restaurant.id)
    
    def test_add_plat_item(self, commande_service, sample_restaurant, plat_service, sample_category, table_service):
        """Test ajout item plat à commande"""
        # Créer un plat
        plat_data = PlatCreate(
            category_id=sample_category.id,
            nom="Test Plat",
            prix=Decimal("2000.00"),
            devise="XAF"
        )
        plat = plat_service.create_plat(plat_data, sample_restaurant.id)
        
        # Créer une table et commande
        table_data = TableCreate(numero="T4", capacite=2)
        table = table_service.create_table(table_data, sample_restaurant.id)
        
        commande_data = CommandeCreate(
            table_id=table.id,
            statut="en_cours",
            total=Decimal("0.00")
        )
        commande = commande_service.create_commande(commande_data, sample_restaurant.id)
        
        # Ajouter l'item
        item_data = CommandeItemCreate(
            plat_id=plat.id,
            quantite=2
        )
        
        item = commande_service.add_item(commande.id, item_data)
        
        assert item is not None
        assert item.plat_id == plat.id
        assert item.quantite == 2
        assert item.prix_unitaire == Decimal("2000.00")
        assert item.total == Decimal("4000.00")
    
    def test_add_item_unavailable_plat(self, commande_service, sample_restaurant, plat_service, sample_category, table_service):
        """Test erreur ajout item avec plat indisponible"""
        # Créer un plat indisponible
        plat_data = PlatCreate(
            category_id=sample_category.id,
            nom="Plat Indisponible",
            prix=Decimal("1500.00"),
            devise="XAF",
            disponible=False
        )
        plat = plat_service.create_plat(plat_data, sample_restaurant.id)
        
        # Créer une commande
        table_data = TableCreate(numero="T5", capacite=2)
        table = table_service.create_table(table_data, sample_restaurant.id)
        
        commande_data = CommandeCreate(
            table_id=table.id,
            statut="en_cours",
            total=Decimal("0.00")
        )
        commande = commande_service.create_commande(commande_data, sample_restaurant.id)
        
        # Essayer d'ajouter l'item
        item_data = CommandeItemCreate(
            plat_id=plat.id,
            quantite=1
        )
        
        with pytest.raises(ValueError, match="Plat is not available"):
            commande_service.add_item(commande.id, item_data)


class TestPaymentService:
    """Tests pour PaymentService"""
    
    def test_cash_payment_success(self, payment_service):
        """Test paiement cash réussi"""
        result = payment_service.process_payment(
            method_type="cash",
            amount=Decimal("5000.00"),
            payment_details={
                "received_by": "serveur_1",
                "currency": "XAF"
            }
        )
        
        assert result["success"] == True
        assert result["status"] == "completed"
        assert result["payment_method"] == "cash"
    
    def test_cash_payment_invalid_amount(self, payment_service):
        """Test erreur paiement cash avec montant invalide"""
        result = payment_service.process_payment(
            method_type="cash",
            amount=Decimal("-100.00"),
            payment_details={"amount": -100}
        )
        
        assert result["success"] == False
        assert result["status"] == "failed"
    
    def test_orange_money_payment_simulation(self, payment_service):
        """Test simulation paiement Orange Money"""
        result = payment_service.process_payment(
            method_type="orange_money",
            amount=Decimal("3000.00"),
            payment_details={
                "phone_number": "+237123456789",
                "currency": "XAF"
            }
        )
        
        assert "success" in result
        assert "transaction_id" in result
        assert result["payment_method"] == "orange_money"
    
    def test_unsupported_payment_method(self, payment_service):
        """Test erreur méthode de paiement non supportée"""
        result = payment_service.process_payment(
            method_type="bitcoin",
            amount=Decimal("1000.00"),
            payment_details={}
        )
        
        assert result["success"] == False
        assert "method_error" in result or "Unsupported" in result.get("error", "")


class TestNotificationService:
    """Tests pour NotificationService"""
    
    def test_email_notification_success(self, notification_service):
        """Test notification email réussie"""
        result = notification_service.send_notification(
            channel_type="email",
            recipient="test@example.com",
            subject="Test Subject",
            message="Test message"
        )
        
        assert result["success"] == True
        assert result["channel"] == "email"
    
    def test_email_notification_invalid_recipient(self, notification_service):
        """Test erreur notification email avec destinataire invalide"""
        result = notification_service.send_notification(
            channel_type="email",
            recipient="invalid-email",
            subject="Test",
            message="Test"
        )
        
        assert result["success"] == False
        assert "Invalid email" in result.get("error", "")
    
    def test_template_notification(self, notification_service):
        """Test notification avec template"""
        result = notification_service.send_notification(
            channel_type="email",
            recipient="customer@example.com",
            template_type="commande_confirme",
            template_data={
                "customer_name": "Jean Dupont",
                "restaurant_name": "Restaurant Test",
                "commande_id": "CMD-001",
                "total": "5000",
                "currency": "XAF",
                "statut": "confirmée"
            }
        )
        
        assert result["success"] == True
        assert "subject" in result
    
    def test_multi_channel_notification(self, notification_service):
        """Test notification multi-canal"""
        result = notification_service.send_multi_channel_notification(
            channels=["email", "sms"],
            recipient="+237123456789",
            subject="Test Multi",
            message="Test message multi-canal"
        )
        
        assert "results" in result
        assert len(result["results"]) == 2