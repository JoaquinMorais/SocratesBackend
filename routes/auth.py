from typing import Annotated

from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException,Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import delete

from config.database import db_dependency
from models import RefreshToken, User
from schemas.auth import AccessToken, LoginRequest, UserPublic
from utils.auth import (
    REFRESH_COOKIE,
    authenticate_user,
    clear_refresh_cookie,
    issue_tokens,
    user_dependency,
)
from utils.security import hash_token

auth_router = APIRouter(prefix="/auth", tags=["auth"])

RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE)]


def _invalid_credentials() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")


@auth_router.post("/login", response_model=AccessToken)
async def login(data: LoginRequest, response: Response, db: db_dependency):
    user = await authenticate_user(db, data.email, data.password)
    if not user:
        raise _invalid_credentials()
    return await issue_tokens(db, user, response)


@auth_router.post("/token", response_model=AccessToken, include_in_schema=False)
async def token_form(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    response: Response,
    db: db_dependency,
):
    """Solo para el botón Authorize de Swagger."""
    user = await authenticate_user(db, form.username, form.password)
    if not user:
        raise _invalid_credentials()
    return await issue_tokens(db, user, response)

@auth_router.post("/refresh", response_model=AccessToken)
async def refresh(request: Request, response: Response, db: db_dependency):
    refresh_token = request.cookies.get(REFRESH_COOKIE)
    if not refresh_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing refresh token")
    
    # DELETE atómico: si dos requests llegan con el mismo token, solo una lo consume.
    # Un token vencido no coincide, así que también se rechaza.
    result = await db.exec(
        delete(RefreshToken)
        .where(
            RefreshToken.token_hash == hash_token(refresh_token),
            RefreshToken.expires_at > datetime.now(timezone.utc),
        )
        .returning(RefreshToken.id_user)
    )
    id_user = result.scalar_one_or_none()
    await db.commit()

    user = await db.get(User, id_user) if id_user else None
    if not user:
        clear_refresh_cookie(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")

    return await issue_tokens(db, user, response)


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, db: db_dependency):
    refresh_token = request.cookies.get(REFRESH_COOKIE)
    
    if refresh_token:
        await db.exec(
            delete(RefreshToken).where(
                RefreshToken.token_hash == hash_token(refresh_token)
            )
        )
        await db.commit()
    clear_refresh_cookie(response)


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