import hmac
from datetime import datetime, timedelta, timezone

from sqlmodel import delete, select

from config.settings import settings
from models import EmailVerification, User
from utils.security import generate_otp, hash_otp


async def create_otp(db, user: User) -> str | None:
    """Devuelve el código, o None si todavía rige la espera entre pedidos."""
    now = datetime.now(timezone.utc)
    last = (
        await db.exec(
            select(EmailVerification)
            .where(EmailVerification.id_user == user.id_user)
            .order_by(EmailVerification.created_at.desc())
            .limit(1)
        )
    ).first()
    if last and (now - last.created_at).total_seconds() < settings.OTP_COOLDOWN_SECONDS:
        return None

    # un solo código vigente por usuario
    await db.exec(delete(EmailVerification).where(EmailVerification.id_user == user.id_user))
    code = generate_otp()
    db.add(
        EmailVerification(
            id_user=user.id_user,
            code_hash=hash_otp(code),
            expires_at=now + timedelta(minutes=settings.OTP_MINUTES),
        )
    )
    await db.commit()
    return code


async def consume_otp(db, user: User, code: str) -> bool:
    verification = (
        await db.exec(
            select(EmailVerification)
            .where(EmailVerification.id_user == user.id_user, EmailVerification.used == False)  # noqa: E712
            .order_by(EmailVerification.created_at.desc())
            .limit(1)
        )
    ).first()

    now = datetime.now(timezone.utc)
    if (
        not verification
        or verification.expires_at < now
        or verification.attempts >= settings.OTP_MAX_ATTEMPTS
    ):
        return False

    if not hmac.compare_digest(verification.code_hash, hash_otp(code.strip())):
        verification.attempts += 1
        db.add(verification)
        await db.commit()
        return False

    verification.used = True
    db.add(verification)
    await db.commit()
    return True