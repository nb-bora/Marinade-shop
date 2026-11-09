"""Tables de sécurité de l'authentification (ASVS V6, V7).

Tables globales (sans restaurant_id, donc sans RLS, comme ``users`` et
``refresh_tokens``) : elles sont lues AVANT qu'un contexte de restaurant existe.

* ``auth_sessions`` : une session = une famille de jetons de rafraîchissement. Chaque
  jeton d'accès porte l'identifiant de sa session (``sid``) ; une session révoquée rend
  immédiatement ses jetons d'accès inutilisables.
* ``auth_throttle`` : compteurs de limitation de débit et de verrouillage, partagés
  entre tous les workers (clé = empreinte HMAC, jamais l'adresse e-mail en clair).
* ``auth_one_time_use`` : marqueurs « déjà utilisé » (pas de TOTP rejoué dans sa fenêtre).
"""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.core.database import Base


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_used_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # Limite absolue : aucune rotation ne prolonge la session au-delà.
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revoked_reason = Column(String(40), nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(255), nullable=True)

    __table_args__ = (Index("idx_auth_sessions_user", "user_id", "revoked_at"),)


class AuthThrottle(Base):
    __tablename__ = "auth_throttle"

    key = Column(String(128), primary_key=True)
    window_start = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    hits = Column(Integer, nullable=False, default=0, server_default="0")
    failures = Column(Integer, nullable=False, default=0, server_default="0")
    locked_until = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (Index("idx_auth_throttle_updated", "updated_at"),)


class AuthOneTimeUse(Base):
    __tablename__ = "auth_one_time_use"

    key = Column(String(128), primary_key=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("idx_auth_one_time_use_expires", "expires_at"),)
