from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from app.utils.logging import get_logger

logger = get_logger(__name__)


class NotificationChannel(ABC):
    """Interface abstraite pour tous les canaux de notification"""

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}

    @abstractmethod
    def send_notification(
        self,
        recipient: str,
        subject: str,
        message: str,
        template_data: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """
        Envoie une notification via ce canal

        Args:
            recipient: Destinataire (email, téléphone, etc.)
            subject: Sujet/titre de la notification
            message: Corps du message
            template_data: Données pour le template (optionnel)

        Returns:
            Dict contenant le résultat de l'envoi
        """
        pass

    @abstractmethod
    def send_bulk_notification(
        self,
        recipients: List[str],
        subject: str,
        message: str,
        template_data: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """
        Envoie une notification en masse via ce canal

        Args:
            recipients: Liste des destinataires
            subject: Sujet/titre de la notification
            message: Corps du message
            template_data: Données pour le template (optionnel)

        Returns:
            Dict contenant le résultat de l'envoi en masse
        """
        pass

    @abstractmethod
    def validate_recipient(self, recipient: str) -> bool:
        """
        Valide le format du destinataire pour ce canal

        Args:
            recipient: Destinataire à valider

        Returns:
            True si valide, False sinon
        """
        pass

    @abstractmethod
    def get_channel_name(self) -> str:
        """Retourne le nom du canal de notification"""
        pass


class EmailNotification(NotificationChannel):
    """Notifications par email"""

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        self.smtp_server = self.config.get("smtp_server", "smtp.gmail.com")
        self.smtp_port = self.config.get("smtp_port", 587)
        self.smtp_username = self.config.get("smtp_username")
        self.smtp_password = self.config.get("smtp_password")
        self.from_email = self.config.get("from_email", "noreply@marinade.com")
        self.from_name = self.config.get("from_name", "Marinade")

    def send_notification(
        self,
        recipient: str,
        subject: str,
        message: str,
        template_data: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        logger.info(f"Sending email to {recipient}: {subject}")

        # Validation du destinataire
        if not self.validate_recipient(recipient):
            return {
                "success": False,
                "error": "Invalid email address",
                "channel": "email",
            }

        # Application du template si fourni
        final_message = (
            self._apply_template(message, template_data) if template_data else message
        )
        final_subject = (
            self._apply_template(subject, template_data) if template_data else subject
        )

        try:
            # TODO: Intégration réelle avec SMTP
            # Pour l'instant, simulation
            result = self._simulate_email_send(recipient, final_subject, final_message)

            return {
                "success": result["success"],
                "channel": "email",
                "recipient": recipient,
                "subject": final_subject,
                "message_id": result.get("message_id"),
                "timestamp": result.get("timestamp"),
            }
        except Exception as e:
            logger.error(f"Email sending error: {str(e)}")
            return {"success": False, "error": str(e), "channel": "email"}

    def send_bulk_notification(
        self,
        recipients: List[str],
        subject: str,
        message: str,
        template_data: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        logger.info(f"Sending bulk email to {len(recipients)} recipients")

        results = []
        successful = 0
        failed = 0

        for recipient in recipients:
            result = self.send_notification(recipient, subject, message, template_data)
            results.append(
                {
                    "recipient": recipient,
                    "success": result.get("success"),
                    "error": result.get("error"),
                }
            )

            if result.get("success"):
                successful += 1
            else:
                failed += 1

        return {
            "success": failed == 0,
            "channel": "email",
            "total_recipients": len(recipients),
            "successful": successful,
            "failed": failed,
            "results": results,
        }

    def validate_recipient(self, recipient: str) -> bool:
        """Valide le format d'email"""
        import re

        email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        return bool(re.match(email_pattern, recipient))

    def get_channel_name(self) -> str:
        return "email"

    def _apply_template(self, template: str, data: Dict[str, Any]) -> str:
        """Applique les données au template"""
        try:
            return template.format(**data)
        except KeyError as e:
            logger.warning(f"Template variable missing: {e}")
            return template

    def _simulate_email_send(
        self, recipient: str, subject: str, message: str
    ) -> Dict[str, Any]:
        """Simulation d'envoi d'email (à remplacer par l'intégration SMTP réelle)"""
        import time
        import uuid

        time.sleep(0.3)  # Simulation de délai réseau

        return {
            "success": True,
            "message_id": str(uuid.uuid4()),
            "timestamp": time.time(),
        }


class SMSNotification(NotificationChannel):
    """Notifications par SMS"""

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        self.sms_provider = self.config.get(
            "sms_provider", "twilio"
        )  # twilio, africas_talking, etc.
        self.api_key = self.config.get("sms_api_key")
        self.api_secret = self.config.get("sms_api_secret")
        self.sender_id = self.config.get("sender_id", "Marinade")

    def send_notification(
        self,
        recipient: str,
        subject: str,
        message: str,
        template_data: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        logger.info(f"Sending SMS to {recipient}")

        # Validation du destinataire
        if not self.validate_recipient(recipient):
            return {"success": False, "error": "Invalid phone number", "channel": "sms"}

        # Application du template si fourni
        final_message = (
            self._apply_template(message, template_data) if template_data else message
        )

        try:
            # TODO: Intégration réelle avec Twilio/AfricasTalking
            result = self._simulate_sms_send(recipient, final_message)

            return {
                "success": result["success"],
                "channel": "sms",
                "recipient": recipient,
                "message_id": result.get("message_id"),
                "provider": self.sms_provider,
                "timestamp": result.get("timestamp"),
            }
        except Exception as e:
            logger.error(f"SMS sending error: {str(e)}")
            return {"success": False, "error": str(e), "channel": "sms"}

    def send_bulk_notification(
        self,
        recipients: List[str],
        subject: str,
        message: str,
        template_data: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        logger.info(f"Sending bulk SMS to {len(recipients)} recipients")

        results = []
        successful = 0
        failed = 0

        for recipient in recipients:
            result = self.send_notification(recipient, subject, message, template_data)
            results.append(
                {
                    "recipient": recipient,
                    "success": result.get("success"),
                    "error": result.get("error"),
                }
            )

            if result.get("success"):
                successful += 1
            else:
                failed += 1

        return {
            "success": failed == 0,
            "channel": "sms",
            "total_recipients": len(recipients),
            "successful": successful,
            "failed": failed,
            "results": results,
        }

    def validate_recipient(self, recipient: str) -> bool:
        """Valide le format de numéro de téléphone"""
        import re

        # Accepte formats internationaux avec + (min 10 chiffres après le +)
        phone_pattern = r"^\+[1-9]\d{9,14}$"
        return bool(re.match(phone_pattern, recipient))

    def get_channel_name(self) -> str:
        return "sms"

    def _apply_template(self, template: str, data: Dict[str, Any]) -> str:
        """Applique les données au template"""
        try:
            return template.format(**data)
        except KeyError as e:
            logger.warning(f"Template variable missing: {e}")
            return template

    def _simulate_sms_send(self, recipient: str, message: str) -> Dict[str, Any]:
        """Simulation d'envoi SMS (à remplacer par l'intégration réelle)"""
        import time
        import uuid

        time.sleep(0.5)  # Simulation de délai réseau

        return {
            "success": True,
            "message_id": str(uuid.uuid4()),
            "timestamp": time.time(),
        }


class WhatsAppNotification(NotificationChannel):
    """Notifications par WhatsApp"""

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        self.whatsapp_api_key = self.config.get("whatsapp_api_key")
        self.whatsapp_phone_number_id = self.config.get("whatsapp_phone_number_id")
        self.business_account_id = self.config.get("business_account_id")

    def send_notification(
        self,
        recipient: str,
        subject: str,
        message: str,
        template_data: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        logger.info(f"Sending WhatsApp message to {recipient}")

        # Validation du destinataire
        if not self.validate_recipient(recipient):
            return {
                "success": False,
                "error": "Invalid WhatsApp number",
                "channel": "whatsapp",
            }

        # Application du template si fourni
        final_message = (
            self._apply_template(message, template_data) if template_data else message
        )

        try:
            # TODO: Intégration réelle avec WhatsApp Business API
            result = self._simulate_whatsapp_send(recipient, final_message)

            return {
                "success": result["success"],
                "channel": "whatsapp",
                "recipient": recipient,
                "message_id": result.get("message_id"),
                "timestamp": result.get("timestamp"),
            }
        except Exception as e:
            logger.error(f"WhatsApp sending error: {str(e)}")
            return {"success": False, "error": str(e), "channel": "whatsapp"}

    def send_bulk_notification(
        self,
        recipients: List[str],
        subject: str,
        message: str,
        template_data: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        logger.info(f"Sending bulk WhatsApp messages to {len(recipients)} recipients")

        results = []
        successful = 0
        failed = 0

        for recipient in recipients:
            result = self.send_notification(recipient, subject, message, template_data)
            results.append(
                {
                    "recipient": recipient,
                    "success": result.get("success"),
                    "error": result.get("error"),
                }
            )

            if result.get("success"):
                successful += 1
            else:
                failed += 1

        return {
            "success": failed == 0,
            "channel": "whatsapp",
            "total_recipients": len(recipients),
            "successful": successful,
            "failed": failed,
            "results": results,
        }

    def validate_recipient(self, recipient: str) -> bool:
        """Valide le format de numéro WhatsApp"""
        import re

        # Accepte formats internationaux avec + (min 10 chiffres après le +)
        phone_pattern = r"^\+[1-9]\d{9,14}$"
        return bool(re.match(phone_pattern, recipient))

    def get_channel_name(self) -> str:
        return "whatsapp"

    def _apply_template(self, template: str, data: Dict[str, Any]) -> str:
        """Applique les données au template WhatsApp"""
        try:
            return template.format(**data)
        except KeyError as e:
            logger.warning(f"Template variable missing: {e}")
            return template

    def _simulate_whatsapp_send(self, recipient: str, message: str) -> Dict[str, Any]:
        """Simulation d'envoi WhatsApp (à remplacer par l'intégration réelle)"""
        import time
        import uuid

        time.sleep(0.6)  # Simulation de délai réseau

        return {
            "success": True,
            "message_id": str(uuid.uuid4()),
            "timestamp": time.time(),
        }


class NotificationFactory:
    """Factory pour créer les canaux de notification appropriés"""

    _notification_channels = {
        "email": EmailNotification,
        "sms": SMSNotification,
        "whatsapp": WhatsAppNotification,
    }

    @classmethod
    def create_notification_channel(
        cls, channel_type: str, config: Dict[str, Any] = None
    ) -> NotificationChannel:
        """
        Crée un canal de notification basé sur le type

        Args:
            channel_type: Type de canal (email, sms, whatsapp)
            config: Configuration spécifique au canal

        Returns:
            Instance du canal de notification

        Raises:
            ValueError: Si le type de canal n'est pas supporté
        """
        channel_class = cls._notification_channels.get(channel_type.lower())

        if not channel_class:
            raise ValueError(f"Unsupported notification channel: {channel_type}")

        logger.info(f"Creating notification channel: {channel_type}")
        return channel_class(config)

    @classmethod
    def get_supported_channels(cls) -> list:
        """Retourne la liste des canaux de notification supportés"""
        return list(cls._notification_channels.keys())

    @classmethod
    def register_notification_channel(
        cls, channel_type: str, channel_class: type
    ) -> None:
        """
        Enregistre un nouveau canal de notification personnalisé

        Args:
            channel_type: Identifiant unique du canal
            channel_class: Classe du canal de notification
        """
        cls._notification_channels[channel_type.lower()] = channel_class
        logger.info(f"Registered custom notification channel: {channel_type}")
