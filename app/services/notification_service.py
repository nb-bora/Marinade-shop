from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from app.utils.notification_channels import NotificationFactory
from app.utils.logging import get_logger

logger = get_logger(__name__)


class NotificationTemplateManager:
    """Gestionnaire de templates de notifications"""

    # Templates prédéfinis pour différents types de notifications
    _templates = {
        "commande_confirme": {
            "email": {
                "subject": "Commande confirmée - {restaurant_name}",
                "message": """
Bonjour {customer_name},

Votre commande #{commande_id} a été confirmée.

Détails de la commande:
- Restaurant: {restaurant_name}
- Total: {total} {currency}
- Statut: {statut}

Merci pour votre commande!

L'équipe {restaurant_name}
                """.strip(),
            },
            "sms": {
                "subject": "",  # SMS n'a pas de sujet
                "message": "Commande #{commande_id} confirmée chez {restaurant_name}. Total: {total} {currency}. Merci!",
            },
            "whatsapp": {
                "subject": "",  # WhatsApp n'a pas de sujet
                "message": """
🎉 Commande confirmée!

Restaurant: {restaurant_name}
Commande: #{commande_id}
Total: {total} {currency}

Merci pour votre commande! 🙏
                """.strip(),
            },
        },
        "commande_prete": {
            "email": {
                "subject": "Votre commande est prête - {restaurant_name}",
                "message": """
Bonjour {customer_name},

Votre commande #{commande_id} est prête à être récupérée.

Veuillez vous présenter à l'accueil.

L'équipe {restaurant_name}
                """.strip(),
            },
            "sms": {
                "subject": "",
                "message": "Commande #{commande_id} prête chez {restaurant_name}. Venez la récupérer!",
            },
            "whatsapp": {
                "subject": "",
                "message": """
🍽️ Votre commande est prête!

Commande: #{commande_id}
Restaurant: {restaurant_name}

Venez la récupérer! 🏃‍♂️
                """.strip(),
            },
        },
        "payment_confirme": {
            "email": {
                "subject": "Paiement confirmé - {restaurant_name}",
                "message": """
Bonjour {customer_name},

Votre paiement de {amount} {currency} a été confirmé.

Détails:
- Commande: #{commande_id}
- Méthode: {payment_method}
- Restaurant: {restaurant_name}

Merci!

L'équipe {restaurant_name}
                """.strip(),
            },
            "sms": {
                "subject": "",
                "message": "Paiement de {amount} {currency} confirmé pour commande #{commande_id}. Méthode: {payment_method}",
            },
            "whatsapp": {
                "subject": "",
                "message": """
💳 Paiement confirmé!

Montant: {amount} {currency}
Commande: #{commande_id}
Méthode: {payment_method}

Merci! 🎉
                """.strip(),
            },
        },
        "inscription": {
            "email": {
                "subject": "Bienvenue sur Marinade - {restaurant_name}",
                "message": """
Bonjour {customer_name},

Bienvenue sur Marinade!

Votre compte a été créé avec succès.
Restaurant: {restaurant_name}

Connectez-vous pour commencer à utiliser nos services.

L'équipe Marinade
                """.strip(),
            },
            "sms": {
                "subject": "",
                "message": "Bienvenue sur Marinade! Votre compte pour {restaurant_name} est créé. Connectez-vous pour commencer.",
            },
            "whatsapp": {
                "subject": "",
                "message": """
🎉 Bienvenue sur Marinade!

Votre compte est créé!
Restaurant: {restaurant_name}

Connectez-vous pour commencer! 🚀
                """.strip(),
            },
        },
    }

    @classmethod
    def get_template(cls, template_type: str, channel: str) -> Optional[Dict[str, str]]:
        """
        Récupère un template pour un type et canal spécifiques

        Args:
            template_type: Type de template (commande_confirme, payment_confirme, etc.)
            channel: Canal de notification (email, sms, whatsapp)

        Returns:
            Dict avec subject et message, ou None si non trouvé
        """
        template = cls._templates.get(template_type, {}).get(channel)
        if not template:
            logger.warning(f"Template not found: {template_type} for channel {channel}")
        return template

    @classmethod
    def register_template(
        cls, template_type: str, channel: str, subject: str, message: str
    ) -> None:
        """
        Enregistre un nouveau template personnalisé

        Args:
            template_type: Type de template
            channel: Canal de notification
            subject: Sujet du template
            message: Corps du template
        """
        if template_type not in cls._templates:
            cls._templates[template_type] = {}

        cls._templates[template_type][channel] = {
            "subject": subject,
            "message": message,
        }
        logger.info(
            f"Registered custom template: {template_type} for channel {channel}"
        )

    @classmethod
    def get_available_templates(cls) -> List[str]:
        """Retourne la liste des types de templates disponibles"""
        return list(cls._templates.keys())


class NotificationService:
    """Service orchestrateur pour les notifications"""

    def __init__(
        self, db: Optional[Session] = None, notification_config: Dict[str, Any] = None
    ):
        self.db = db
        self.notification_config = notification_config or {}
        self.template_manager = NotificationTemplateManager()

    def send_notification(
        self,
        channel_type: str,
        recipient: str,
        template_type: str = None,
        subject: str = None,
        message: str = None,
        template_data: Dict[str, Any] = None,
        channel_config: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """
        Envoie une notification via le canal spécifié

        Args:
            channel_type: Type de canal (email, sms, whatsapp)
            recipient: Destinataire
            template_type: Type de template à utiliser (optionnel)
            subject: Sujet personnalisé (si pas de template)
            message: Message personnalisé (si pas de template)
            template_data: Données pour le template
            channel_config: Configuration spécifique au canal

        Returns:
            Résultat de l'envoi
        """
        try:
            # Récupérer ou créer le template
            if template_type:
                template = self.template_manager.get_template(
                    template_type, channel_type
                )
                if template:
                    final_subject = template["subject"]
                    final_message = template["message"]
                else:
                    final_subject = subject or ""
                    final_message = message or ""
            else:
                final_subject = subject or ""
                final_message = message or ""

            # Créer le canal de notification
            config = {
                **self.notification_config.get(channel_type, {}),
                **(channel_config or {}),
            }
            notification_channel = NotificationFactory.create_notification_channel(
                channel_type, config
            )

            # Envoyer la notification
            result = notification_channel.send_notification(
                recipient=recipient,
                subject=final_subject,
                message=final_message,
                template_data=template_data,
            )

            logger.info(
                f"Notification sent: {channel_type} to {recipient}, success: {result.get('success')}"
            )
            return result

        except ValueError as e:
            logger.error(f"Notification channel error: {str(e)}")
            return {"success": False, "error": str(e), "channel": channel_type}
        except Exception as e:
            logger.error(f"Notification sending error: {str(e)}")
            return {
                "success": False,
                "error": "Notification sending failed",
                "channel": channel_type,
            }

    def send_bulk_notification(
        self,
        channel_type: str,
        recipients: List[str],
        template_type: str = None,
        subject: str = None,
        message: str = None,
        template_data: Dict[str, Any] = None,
        channel_config: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """
        Envoie une notification en masse via le canal spécifié

        Args:
            channel_type: Type de canal
            recipients: Liste des destinataires
            template_type: Type de template à utiliser (optionnel)
            subject: Sujet personnalisé (si pas de template)
            message: Message personnalisé (si pas de template)
            template_data: Données pour le template
            channel_config: Configuration spécifique au canal

        Returns:
            Résultat de l'envoi en masse
        """
        try:
            # Récupérer ou créer le template
            if template_type:
                template = self.template_manager.get_template(
                    template_type, channel_type
                )
                if template:
                    final_subject = template["subject"]
                    final_message = template["message"]
                else:
                    final_subject = subject or ""
                    final_message = message or ""
            else:
                final_subject = subject or ""
                final_message = message or ""

            # Créer le canal de notification
            config = {
                **self.notification_config.get(channel_type, {}),
                **(channel_config or {}),
            }
            notification_channel = NotificationFactory.create_notification_channel(
                channel_type, config
            )

            # Envoyer la notification en masse
            result = notification_channel.send_bulk_notification(
                recipients=recipients,
                subject=final_subject,
                message=final_message,
                template_data=template_data,
            )

            logger.info(
                f"Bulk notification sent: {channel_type} to {len(recipients)} recipients, success: {result.get('success')}"
            )
            return result

        except Exception as e:
            logger.error(f"Bulk notification sending error: {str(e)}")
            return {"success": False, "error": str(e), "channel": channel_type}

    def send_multi_channel_notification(
        self,
        channels: List[str],
        recipient: str,
        template_type: str = None,
        subject: str = None,
        message: str = None,
        template_data: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """
        Envoie une notification via plusieurs canaux simultanément

        Args:
            channels: Liste des canaux à utiliser
            recipient: Destinataire
            template_type: Type de template à utiliser (optionnel)
            subject: Sujet personnalisé (si pas de template)
            message: Message personnalisé (si pas de template)
            template_data: Données pour le template

        Returns:
            Résultat combiné de tous les canaux
        """
        results = {}
        successful = 0
        failed = 0

        for channel in channels:
            result = self.send_notification(
                channel_type=channel,
                recipient=recipient,
                template_type=template_type,
                subject=subject,
                message=message,
                template_data=template_data,
            )
            results[channel] = result

            if result.get("success"):
                successful += 1
            else:
                failed += 1

        return {
            "success": failed == 0,
            "channels_used": channels,
            "successful": successful,
            "failed": failed,
            "results": results,
        }

    def get_supported_channels(self) -> List[str]:
        """Retourne la liste des canaux supportés"""
        return NotificationFactory.get_supported_channels()

    def get_available_templates(self) -> List[str]:
        """Retourne la liste des templates disponibles"""
        return self.template_manager.get_available_templates()
