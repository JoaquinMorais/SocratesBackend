from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import select

from config.database import db_dependency
from config.settings import settings
from models import Professor, RefreshToken, Student, User
from utils.security import (
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_token,
)

REFRESH_COOKIE = "refresh_token"
REFRESH_COOKIE_PATH = "/auth"  # el navegador solo la envía a /auth/*

oauth2_bearer = OAuth2PasswordBearer(tokenUrl="auth/token")


def set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=token,
        max_age=settings.REFRESH_DAYS * 86400,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        path=REFRESH_COOKIE_PATH,
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)


async def get_user_by_mail(db, mail: str) -> User | None:
    """Mail institucional ({legajo}@dominio) -> alumno; cualquier otro -> profesor."""
    mail = mail.strip().lower()
    local, _, domain = mail.partition("@")

    if domain == settings.EMAIL_DOMAIN:
        if not local.isdigit():
            return None
        stmt = (
            select(User)
            .join(Student, Student.id_student == User.id_user)
            .where(User.legajo == int(local))
        )
    else:
        stmt = (
            select(User)
            .join(Professor, Professor.id_professor == User.id_user)
            .where(Professor.mail == mail)
        )
    return (await db.exec(stmt)).first()


async def authenticate_user(db, mail: str, password: str) -> User | None:
    user = await get_user_by_mail(db, mail)
    if not user or not user.verify_password(password):
        return None
    return user


async def issue_tokens(db, user: User, response: Response) -> dict:
    """Guarda el refresh (hasheado) en BD, lo manda por cookie y devuelve el access."""
    refresh = generate_refresh_token()
    db.add(
        RefreshToken(
            id_user=user.id_user,
            token_hash=hash_token(refresh),
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_DAYS),
        )
    )
    await db.commit()
    set_refresh_cookie(response, refresh)
    return {
        "access_token": create_access_token(user.id_user, user.legajo),
        "token_type": "bearer",
    }


async def get_current_user(
    token: Annotated[str, Depends(oauth2_bearer)], db: db_dependency
) -> User:
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    user = await db.get(User, int(payload["sub"]))
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    return user


user_dependency = Annotated[User, Depends(get_current_user)]