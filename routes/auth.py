from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import select
from typing import Annotated
from fastapi import Depends

from config.database import db_dependency
from models import RefreshToken, User
from schemas.auth import LoginRequest, RefreshRequest, TokenPair, UserPublic
from utils.auth import authenticate_user, issue_token_pair, user_dependency
from utils.security import hash_token

auth_router = APIRouter(prefix="/auth", tags=["auth"])

INVALID = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")


@auth_router.post("/login", response_model=TokenPair)
async def login(data: LoginRequest, db: db_dependency):
    user = await authenticate_user(db, data.email, data.password)
    if not user:
        raise INVALID
    return await issue_token_pair(db, user)


@auth_router.post("/token", response_model=TokenPair, include_in_schema=False)
async def token_form(
    form: Annotated[OAuth2PasswordRequestForm, Depends()], db: db_dependency
):
    """Solo para el botón Authorize de Swagger."""
    user = await authenticate_user(db, form.username, form.password)
    if not user:
        raise INVALID
    return await issue_token_pair(db, user)


@auth_router.post("/refresh", response_model=TokenPair)
async def refresh(data: RefreshRequest, db: db_dependency):
    stored = (
        await db.exec(
            select(RefreshToken).where(
                RefreshToken.token_hash == hash_token(data.refresh_token)
            )
        )
    ).first()
    if not stored or stored.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")

    user = await db.get(User, stored.id_user)
    await db.delete(stored)  # rotación: el token usado deja de servir
    await db.commit()
    return await issue_token_pair(db, user)


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(data: RefreshRequest, db: db_dependency):
    stored = (
        await db.exec(
            select(RefreshToken).where(
                RefreshToken.token_hash == hash_token(data.refresh_token)
            )
        )
    ).first()
    if stored:
        await db.delete(stored)
        await db.commit()


@auth_router.get("/me", response_model=UserPublic)
async def me(user: user_dependency):
    role = "student" if user.student else "professor" if user.professor else None
    return UserPublic(
        id_user=user.id_user,
        first_name=user.first_name,
        last_name=user.last_name,
        file_number=user.file_number,
        email=user.email,
        role=role,
    )