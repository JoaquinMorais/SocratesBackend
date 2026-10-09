from fastapi import APIRouter, HTTPException, status

from config.database import db_dependency
from schemas.user import UserPublic, UserUpdate
from utils.auth import user_dependency
from utils.users import to_public, update_user

me_router = APIRouter(prefix="/me", tags=["me"])


@me_router.get(
    "",
    response_model=UserPublic,
    response_model_exclude_none=True,
    summary="Mis datos",
    responses={401: {"description": "Token ausente, inválido o vencido"}},
)
async def get_me(user: user_dependency):
    """
    Devuelve los datos del usuario del token: nombre, legajo, mail y rol
    (`student` o `professor`). Solo los profesores incluyen `is_super_admin`.

    Sirve para que el frontend sepa qué pantallas mostrar según el rol.
    """
    return to_public(user)


@me_router.patch(
    "",
    response_model=UserPublic,
    response_model_exclude_none=True,
    summary="Modificar mis datos",
    responses={
        401: {"description": "Token ausente, inválido o vencido"},
        422: {"description": "Datos inválidos, body vacío o campos que no se pueden modificar"},
    },
)
async def update_me(data: UserUpdate, user: user_dependency, db: db_dependency):
    """
    Modifica los datos personales del usuario logueado (alumno o profesor).

    **Campos editables** (opcionales, se envían solo los que cambian):
    `first_name`, `last_name`, `birth_date` (no puede ser futura).

    Cualquier otro campo (`legajo`, `email`...) responde 422. Si hay que
    corregir el legajo o el mail, lo hace un profesor (alumnos) o un super admin
    (profesores). La contraseña se cambia con `POST /auth/password/request` y
    `POST /auth/password/confirm`.
    """
    if not data.model_dump(exclude_none=True):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No fields to update")
    user = await update_user(db, user, data)
    return to_public(user)