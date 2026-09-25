import pytest
from decimal import Decimal
from app.utils.payment_methods import (
    CashPayment,
    OrangeMoneyPayment,
    MobileMoneyPayment,
    PaymentFactory
)
from app.utils.notification_channels import (
    EmailNotification,
    SMSNotification,
    WhatsAppNotification,
    NotificationFactory
)
from app.services.payment_service import PaymentService
from app.services.notification_service import NotificationService, NotificationTemplateManager


class TestPaymentMethods:
    """Tests pour les méthodes de paiement"""
    
    def test_cash_payment_success(self):
        """Test paiement cash réussi"""
        cash_payment = CashPayment()
        result = cash_payment.process_payment(
            amount=Decimal("5000.00"),
            payment_details={
                "received_by": "serveur_1",
                "currency": "XAF"
            }
        )
        
        assert result["success"] == True
        assert result["status"] == "completed"
        assert result["payment_method"] == "cash"
        assert "transaction_id" in result
    
    def test_cash_payment_invalid_amount(self):
        """Test erreur paiement cash avec montant invalide"""
        cash_payment = CashPayment()
        result = cash_payment.process_payment(
            amount=Decimal("-100.00"),
            payment_details={"amount": -100}
        )
        
        assert result["success"] == False
        assert result["status"] == "failed"
        assert "Amount must be positive" in result["error"]
    
    def test_cash_payment_validation(self):
        """Test validation détails paiement cash"""
        cash_payment = CashPayment()
        
        # Détails valides
        assert cash_payment.validate_payment_details({"amount": 100}) == True
        
        # Détails invalides
        assert cash_payment.validate_payment_details({}) == False
        assert cash_payment.validate_payment_details({"amount": -50}) == False
    
    def test_orange_money_requires_easytransact(self):
        """Orange Money is not simulated: it must be routed to Easy Transact"""
        orange_payment = OrangeMoneyPayment()
        result = orange_payment.process_payment(
            amount=Decimal("3000.00"),
            payment_details={
                "phone_number": "+237655123456",
                "currency": "XAF"
            }
        )

        assert result["success"] == False
        assert result["status"] == "unsupported"
        assert result["payment_method"] == "easytransact"
        assert result["operator"] == "ORANGE_CM"
        # No fake transaction id may be returned for a non-executed payment.
        assert "transaction_id" not in result

    def test_orange_money_validation(self):
        """Orange Money validation requires a real Orange Cameroon number"""
        orange_payment = OrangeMoneyPayment()

        # Valid Orange number (national prefix 655)
        assert orange_payment.validate_payment_details({
            "phone_number": "+237655123456",
            "amount": 1000
        }) == True

        # Invalid details
        assert orange_payment.validate_payment_details({}) == False
        assert orange_payment.validate_payment_details({"phone_number": "invalid"}) == False
        # Landline / non-mobile prefix
        assert orange_payment.validate_payment_details({"phone_number": "+237123456789"}) == False
        # MTN number is not an Orange number
        assert orange_payment.validate_payment_details({"phone_number": "+237650123456"}) == False

    def test_mobile_money_requires_easytransact(self):
        """MTN Mobile Money is not simulated: it must be routed to Easy Transact"""
        mobile_payment = MobileMoneyPayment({"provider": "mtn"})
        result = mobile_payment.process_payment(
            amount=Decimal("2000.00"),
            payment_details={
                "phone_number": "+237650123456",
                "currency": "XAF"
            }
        )

        assert result["success"] == False
        assert result["status"] == "unsupported"
        assert result["provider"] == "MTN"
        assert "transaction_id" not in result

    def test_mobile_money_validation_is_operator_scoped(self):
        """Mobile Money validation checks the declared operator against the number"""
        mtn = MobileMoneyPayment({"provider": "mtn"})
        orange = MobileMoneyPayment({"provider": "orange"})
        undeclared = MobileMoneyPayment({})

        assert mtn.validate_payment_details({"phone_number": "+237650123456"}) == True
        assert mtn.validate_payment_details({"phone_number": "+237655123456"}) == False
        assert orange.validate_payment_details({"phone_number": "+237655123456"}) == True
        # Without a declared provider the adapter cannot be used.
        assert undeclared.validate_payment_details({"phone_number": "+237650123456"}) == False

    def test_payment_factory(self):
        """Test factory de méthodes de paiement"""
        # Création de méthodes existantes
        cash = PaymentFactory.create_payment_method("cash")
        assert isinstance(cash, CashPayment)
        
        orange = PaymentFactory.create_payment_method("orange_money")
        assert isinstance(orange, OrangeMoneyPayment)
        
        mobile = PaymentFactory.create_payment_method("mobile_money")
        assert isinstance(mobile, MobileMoneyPayment)
    
    def test_payment_factory_unsupported_method(self):
        """Test erreur factory avec méthode non supportée"""
        with pytest.raises(ValueError, match="Unsupported payment method"):
            PaymentFactory.create_payment_method("bitcoin")
    
    def test_payment_factory_supported_methods(self):
        """Test liste des méthodes supportées"""
        methods = PaymentFactory.get_supported_methods()
        
        assert "cash" in methods
        assert "orange_money" in methods
        assert "mobile_money" in methods


class TestPaymentService:
    """Tests pour le service de paiement"""
    
    def test_payment_service_cash(self):
        """Test service paiement cash"""
        payment_service = PaymentService()
        
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
    
    def test_payment_service_orange_money(self):
        """Test service paiement Orange Money"""
        payment_service = PaymentService()
        
        result = payment_service.process_payment(
            method_type="orange_money",
            amount=Decimal("3000.00"),
            payment_details={
                "phone_number": "+237123456789",
                "currency": "XAF"
            }
        )
        
        assert "success" in result
        assert result["payment_method"] == "orange_money"
    
    def test_payment_service_invalid_method(self):
        """Test service paiement avec méthode invalide"""
        payment_service = PaymentService()
        
        result = payment_service.process_payment(
            method_type="bitcoin",
            amount=Decimal("1000.00"),
            payment_details={}
        )
        
        assert result["success"] == False
        assert "method_error" in result["status"]
    
    def test_payment_service_validation_error(self):
        """Test service paiement avec détails invalides"""
        payment_service = PaymentService()
        
        result = payment_service.process_payment(
            method_type="orange_money",
            amount=Decimal("1000.00"),
            payment_details={}  # Détails invalides
        )
        
        assert result["success"] == False
        assert "validation_failed" in result["status"]


class TestNotificationChannels:
    """Tests pour les canaux de notification"""
    
    def test_email_notification(self):
        """Test notification email"""
        email_notification = EmailNotification()
        result = email_notification.send_notification(
            recipient="test@example.com",
            subject="Test Subject",
            message="Test message"
        )
        
        assert result["success"] == True
        assert result["channel"] == "email"
        assert "message_id" in result
    
    def test_email_validation(self):
        """Test validation email"""
        email_notification = EmailNotification()
        
        # Emails valides
        assert email_notification.validate_recipient("test@example.com") == True
        assert email_notification.validate_recipient("user.name+tag@domain.co.uk") == True
        
        # Emails invalides
        assert email_notification.validate_recipient("invalid-email") == False
        assert email_notification.validate_recipient("@example.com") == False
        assert email_notification.validate_recipient("test@") == False
    
    def test_sms_notification(self):
        """Test notification SMS"""
        sms_notification = SMSNotification()
        result = sms_notification.send_notification(
            recipient="+237123456789",
            subject="",  # SMS n'a pas de sujet
            message="Test SMS message"
        )
        
        assert result["success"] == True
        assert result["channel"] == "sms"
        assert "message_id" in result
    
    def test_sms_validation(self):
        """Test validation numéro SMS"""
        sms_notification = SMSNotification()
        
        # Numéros valides
        assert sms_notification.validate_recipient("+237123456789") == True
        assert sms_notification.validate_recipient("+33123456789") == True
        
        # Numéros invalides
        assert sms_notification.validate_recipient("237123456789") == False  # Manque +
        assert sms_notification.validate_recipient("+123") == False  # Trop court
        assert sms_notification.validate_recipient("invalid") == False
    
    def test_whatsapp_notification(self):
        """Test notification WhatsApp"""
        whatsapp_notification = WhatsAppNotification()
        result = whatsapp_notification.send_notification(
            recipient="+237123456789",
            subject="",  # WhatsApp n'a pas de sujet
            message="Test WhatsApp message"
        )
        
        assert result["success"] == True
        assert result["channel"] == "whatsapp"
        assert "message_id" in result
    
    def test_notification_factory(self):
        """Test factory de canaux de notification"""
        # Création de canaux existants
        email = NotificationFactory.create_notification_channel("email")
        assert isinstance(email, EmailNotification)
        
        sms = NotificationFactory.create_notification_channel("sms")
        assert isinstance(sms, SMSNotification)
        
        whatsapp = NotificationFactory.create_notification_channel("whatsapp")
        assert isinstance(whatsapp, WhatsAppNotification)
    
    def test_notification_factory_unsupported_channel(self):
        """Test erreur factory avec canal non supporté"""
        with pytest.raises(ValueError, match="Unsupported notification channel"):
            NotificationFactory.create_notification_channel("telegram")


class TestNotificationTemplateManager:
    """Tests pour le gestionnaire de templates"""
    
    def test_get_template_commande_confirme(self):
        """Test récupération template commande confirmée"""
        template = NotificationTemplateManager.get_template("commande_confirme", "email")
        
        assert template is not None
        assert "subject" in template
        assert "message" in template
        assert "{restaurant_name}" in template["subject"]
        assert "{commande_id}" in template["message"]
    
    def test_get_template_payment_confirme(self):
        """Test récupération template paiement confirmé"""
        template = NotificationTemplateManager.get_template("payment_confirme", "sms")
        
        assert template is not None
        assert "message" in template
        assert "{amount}" in template["message"]
        assert "{payment_method}" in template["message"]
    
    def test_get_template_not_found(self):
        """Test template non trouvé"""
        template = NotificationTemplateManager.get_template("non_existent", "email")
        
        assert template is None
    
    def test_register_custom_template(self):
        """Test enregistrement template personnalisé"""
        NotificationTemplateManager.register_template(
            template_type="custom_test",
            channel="email",
            subject="Custom Subject {name}",
            message="Custom Message {value}"
        )
        
        template = NotificationTemplateManager.get_template("custom_test", "email")
        
        assert template is not None
        assert template["subject"] == "Custom Subject {name}"
        assert template["message"] == "Custom Message {value}"
    
    def test_get_available_templates(self):
        """Test liste des templates disponibles"""
        templates = NotificationTemplateManager.get_available_templates()
        
        assert "commande_confirme" in templates
        assert "commande_prete" in templates
        assert "payment_confirme" in templates
        assert "inscription" in templates


class TestNotificationService:
    """Tests pour le service de notification"""
    
    def test_notification_service_email(self):
        """Test service notification email"""
        notification_service = NotificationService()
        
        result = notification_service.send_notification(
            channel_type="email",
            recipient="test@example.com",
            subject="Test Subject",
            message="Test message"
        )
        
        assert result["success"] == True
        assert result["channel"] == "email"
    
    def test_notification_service_with_template(self):
        """Test service notification avec template"""
        notification_service = NotificationService()
        
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
    
    def test_notification_service_invalid_recipient(self):
        """Test service notification avec destinataire invalide"""
        notification_service = NotificationService()
        
        result = notification_service.send_notification(
            channel_type="email",
            recipient="invalid-email",
            subject="Test",
            message="Test"
        )
        
        assert result["success"] == False
        assert "Invalid email" in result.get("error", "")
    
    def test_notification_service_multi_channel(self):
        """Test service notification multi-canal"""
        notification_service = NotificationService()
        
        result = notification_service.send_multi_channel_notification(
            channels=["email", "sms"],
            recipient="+237123456789",
            subject="Test Multi",
            message="Test message multi-canal"
        )
        
        assert "results" in result
        assert len(result["results"]) == 2
        assert "email" in result["results"]
        assert "sms" in result["results"]
    
    def test_notification_service_supported_channels(self):
        """Test liste des canaux supportés"""
        notification_service = NotificationService()
        channels = notification_service.get_supported_channels()
        
        assert "email" in channels
        assert "sms" in channels
        assert "whatsapp" in channels
    
    def test_notification_service_available_templates(self):
        """Test liste des templates disponibles"""
        notification_service = NotificationService()
        templates = notification_service.get_available_templates()
        
        assert len(templates) > 0
        assert "commande_confirme" in templates