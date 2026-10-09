from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import delete

from config.database import db_dependency
from models import RefreshToken, User
from schemas.auth import AccessToken, LoginRequest, PasswordConfirm, PasswordRequest
from schemas.user import UserPublic
from utils.auth import (
    REFRESH_COOKIE,
    authenticate_user,
    clear_refresh_cookie,
    get_user_by_mail,
    issue_tokens,
    user_dependency,
)
from utils.email import send_otp_email
from utils.security import hash_token
from utils.verification import consume_otp, create_otp

auth_router = APIRouter(prefix="/auth", tags=["auth"])


def _invalid_credentials() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")


@auth_router.post(
    "/login",
    response_model=AccessToken,
    summary="Iniciar sesión",
    responses={401: {"description": "Mail o contraseña incorrectos, o el usuario aún no tiene contraseña"}},
)
async def login(data: LoginRequest, response: Response, db: db_dependency):
    """
    Inicia sesión con el **mail completo** y la contraseña.

    - Alumnos: `{legajo}@sistemas.frc.utn.edu.ar`.
    - Profesores: su mail propio.

    Devuelve un `access_token` (JWT de 15 minutos) para el header
    `Authorization: Bearer <token>`. El refresh token se guarda automáticamente
    en una cookie `HttpOnly` (el frontend no lo ve ni lo maneja).

    Un usuario recién creado no tiene contraseña: debe crearla antes con
    `POST /auth/password/request` y `POST /auth/password/confirm`.
    """
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
    """Solo para el botón Authorize de Swagger (username = mail)."""
    user = await authenticate_user(db, form.username, form.password)
    if not user:
        raise _invalid_credentials()
    return await issue_tokens(db, user, response)


@auth_router.post(
    "/refresh",
    response_model=AccessToken,
    summary="Renovar el access token",
    responses={401: {"description": "No hay cookie de refresh, o es inválida, vencida o ya usada"}},
)
async def refresh(request: Request, response: Response, db: db_dependency):
    """
    Devuelve un `access_token` nuevo usando la cookie de refresh. **No lleva body.**

    El refresh token se rota: el que se usó queda inválido y la respuesta setea
    una cookie nueva. Si responde 401, hay que volver a iniciar sesión.

    El frontend debe llamarlo cuando una request devuelva 401 por token vencido
    (con `credentials: "include"` para que el navegador envíe la cookie).
    """
    refresh_token = request.cookies.get(REFRESH_COOKIE)
    if not refresh_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing refresh token")

    # DELETE atómico: si dos requests llegan con el mismo token, solo una lo consume.
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
        error = JSONResponse({"detail": "Invalid refresh token"}, status_code=401)
        clear_refresh_cookie(error)
        return error

    return await issue_tokens(db, user, response)


@auth_router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cerrar sesión",
)
async def logout(request: Request, response: Response, db: db_dependency):
    """
    Cierra la sesión: invalida el refresh token de la cookie y la borra.

    No requiere estar autenticado ni lleva body. Si no hay cookie, responde 204 igual.
    El access token ya emitido sigue siendo válido hasta que venza (máx. 15 min),
    así que el frontend debe descartarlo.
    """
    refresh_token = request.cookies.get(REFRESH_COOKIE)
    if refresh_token:
        await db.exec(
            delete(RefreshToken).where(
                RefreshToken.token_hash == hash_token(refresh_token)
            )
        )
        await db.commit()
    clear_refresh_cookie(response)


@auth_router.get(
    "/me",
    response_model=UserPublic,
    summary="Datos del usuario logueado",
    responses={401: {"description": "Token ausente, inválido o vencido"}},
)
async def me(user: user_dependency):
    """
    Devuelve los datos del usuario del token: nombre, legajo, mail, rol
    (`student` o `professor`) y si es super admin.

    Sirve para que el frontend sepa qué pantallas mostrar según el rol.
    """
    role = "student" if user.student else "professor" if user.professor else None
    return UserPublic(
        id_user=user.id_user,
        first_name=user.first_name,
        last_name=user.last_name,
        legajo=user.legajo,
        email=user.get_mail(),
        role=role,
        is_super_admin=bool(user.professor and user.professor.is_super_admin),
    )


@auth_router.post(
    "/password/request",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Pedir código para crear o recuperar la contraseña",
)
async def password_request(
    data: PasswordRequest, background: BackgroundTasks, db: db_dependency
):
    """
    Envía un código de 6 dígitos al mail del usuario. Sirve tanto para **crear la
    contraseña por primera vez** (cuentas recién creadas) como para **recuperarla**.

    - Responde siempre 202 con el mismo mensaje, exista o no el usuario
      (así no se puede averiguar qué mails están registrados).
    - El código vence a los 10 minutos y solo se puede usar una vez.
    - Hay una espera de 60 segundos entre pedidos para el mismo usuario.
    """
    user = await get_user_by_mail(db, data.email)
    if user:
        code = await create_otp(db, user)
        if code:
            background.add_task(send_otp_email, user.get_mail(), code)
    return {"detail": "Si el usuario existe, se envió un código a su mail"}


@auth_router.post(
    "/password/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Confirmar el código y fijar la contraseña",
    responses={
        400: {"description": "Código incorrecto, vencido, ya usado o bloqueado por demasiados intentos"},
        422: {"description": "Contraseña inválida (mínimo 8 caracteres)"},
    },
)
async def password_confirm(data: PasswordConfirm, db: db_dependency):
    """
    Verifica el código recibido por mail y guarda la contraseña nueva.

    - Tras 5 intentos fallidos el código se bloquea y hay que pedir otro.
    - Al cambiar la contraseña se cierran **todas** las sesiones del usuario.
    - Después de esto el usuario ya puede iniciar sesión con `POST /auth/login`.
    """
    user = await get_user_by_mail(db, data.email)
    if not user or not await consume_otp(db, user, data.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired code")

    user.set_password(data.new_password)
    db.add(user)
    await db.exec(delete(RefreshToken).where(RefreshToken.id_user == user.id_user))
    await db.commit()