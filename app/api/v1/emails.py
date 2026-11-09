"""Diagnostic, aperçu et test de l'envoi d'emails (administrateur de la plateforme)."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, EmailStr

from app.api.dependencies import require_admin
from app.core.config import settings
from app.models.user import User
from app.services import email_service, email_templates

router = APIRouter(prefix="/emails", tags=["emails"])


class EmailStatus(BaseModel):
    backend: str
    smtp_configured: bool
    smtp_host: str
    smtp_port: int
    smtp_security: str
    sender: str
    templates: list[str]


class EmailTestRequest(BaseModel):
    to: Optional[EmailStr] = None
    template: str = "test"
    lang: str = "fr"


class EmailTestResponse(BaseModel):
    success: bool
    backend: str
    to: str
    error: Optional[str] = None


@router.get("/status", response_model=EmailStatus)
def email_status(_: User = Depends(require_admin)):
    """État de la configuration d'envoi. Ne renvoie jamais le mot de passe SMTP."""
    return EmailStatus(
        backend=email_service.active_backend(),
        smtp_configured=email_service.smtp_configured(),
        smtp_host=settings.SMTP_HOST,
        smtp_port=settings.SMTP_PORT,
        smtp_security=settings.SMTP_SECURITY,
        sender=settings.EMAIL_FROM,
        templates=sorted(email_templates.BUILDERS),
    )


@router.get("/preview/{name}", response_class=HTMLResponse)
def preview_template(
    name: str, lang: str = Query("fr", pattern="^(fr|en)$"), _: User = Depends(require_admin)
):
    """Aperçu HTML d'un gabarit avec des données d'exemple (rien n'est envoyé)."""
    if name not in email_templates.BUILDERS:
        raise HTTPException(status_code=404, detail="Unknown email template")
    return HTMLResponse(email_templates.build(name, email_templates.SAMPLES[name], lang).html)


@router.post("/test", response_model=EmailTestResponse)
def send_test_email(data: EmailTestRequest, admin: User = Depends(require_admin)):
    """Envoie un gabarit d'exemple (par défaut le test) à soi-même ou à l'adresse donnée."""
    if data.template not in email_templates.BUILDERS:
        raise HTTPException(status_code=404, detail="Unknown email template")
    to = str(data.to) if data.to else admin.email
    sample = {**email_templates.SAMPLES[data.template], "first_name": admin.first_name}
    result = email_templates.send(data.template, to, sample, data.lang, background=False)
    return EmailTestResponse(
        success=result["success"], backend=result.get("backend", email_service.active_backend()),
        to=to, error=result.get("error"),
    )
