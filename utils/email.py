import asyncio
import logging
import smtplib
from email.message import EmailMessage

from config.settings import settings

logger = logging.getLogger("uvicorn.error")


def _send_sync(msg: EmailMessage) -> None:
    with smtplib.SMTP(
        settings.SMTP_HOST, settings.SMTP_PORT, timeout=settings.SMTP_TIMEOUT
    ) as server:
        server.starttls()
        server.login(settings.EMAIL, settings.EMAIL_PASSWORD)
        server.send_message(msg)


async def send_email(to: str, subject: str, body: str) -> bool:
    """Devuelve True si salió, False si falló (el motivo queda en el log)."""
    if settings.EMAIL_BACKEND == "console":
        logger.info("[MAIL] to=%s | %s\n%s", to, subject, body)
        return True

    if not settings.EMAIL or not settings.EMAIL_PASSWORD:
        logger.error("Faltan EMAIL / EMAIL_PASSWORD: no se envió '%s'", subject)
        return False

    recipient = settings.EMAIL_DEV_REDIRECT or to
    msg = EmailMessage()
    msg["From"] = settings.EMAIL_FROM or settings.EMAIL
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        await asyncio.to_thread(_send_sync, msg)
        return True
    except Exception as e:
        logger.error("Falló el envío de '%s' a %s: %s", subject, recipient, e)
        return False


async def send_otp_email(to: str, code: str) -> bool:
    body = (
        "Hola,\n\n"
        f"Tu código de verificación de Socrates es: {code}\n\n"
        f"Vence en {settings.OTP_MINUTES} minutos y se puede usar una sola vez.\n"
        "Si no lo pediste, ignora este mensaje."
    )
    return await send_email(to, "Tu código de verificación - Socrates", body)


async def send_welcome_emails(recipients: list[tuple[str, str]]) -> None:
    """recipients: lista de (mail, nombre)."""
    if not settings.SEND_WELCOME_EMAILS:
        return
    for mail, first_name in recipients:
        body = (
            f"Hola {first_name},\n\n"
            "Se creó tu cuenta en Socrates.\n\n"
            f"Para empezar, ingresa a Socrates y elige 'Crear contraseña' con este mail: {mail}\n"
            "Te llegará un código de verificación para completar el proceso.\n\n"
            "Si no esperabas este mensaje, ignóralo."
        )
        await send_email(mail, "Tu cuenta de Socrates fue creada", body)