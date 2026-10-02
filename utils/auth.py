from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import select

from config.database import db_dependency
from config.settings import settings
from models import RefreshToken, User
from utils.security import (
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_token,
)

oauth2_bearer = OAuth2PasswordBearer(tokenUrl="auth/token")


def parse_file_number(email_or_file: str) -> int | None:
    local = email_or_file.strip().split("@")[0]
    return int(local) if local.isdigit() else None


async def authenticate_user(db, email: str, password: str) -> User | None:
    file_number = parse_file_number(email)
    if file_number is None:
        return None
    user = (await db.exec(select(User).where(User.file_number == file_number))).first()
    if not user or not user.verify_password(password):
        return None
    return user


async def issue_token_pair(db, user: User) -> dict:
    refresh = generate_refresh_token()
    db.add(
        RefreshToken(
            id_user=user.id_user,
            token_hash=hash_token(refresh),
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_DAYS),
        )
    )
    await db.commit()
    return {
        "access_token": create_access_token(user.id_user, user.file_number),
        "refresh_token": refresh,
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