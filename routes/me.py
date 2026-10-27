from fastapi import APIRouter, HTTPException, status

from config.database import db_dependency
from schemas.me_project import MyProjectPublic
from schemas.user import UserPublic, UserUpdate
from utils.auth import user_dependency
from utils.permissions import student_dependency
from utils.student_projects import get_my_project
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
    (`student` o `professor`), fecha de nacimiento, edad y, según el rol,
    `enrollment_year` (alumnos) o `is_super_admin` (profesores).

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
    `first_name`, `last_name`, `birth_date` (no puede ser futura ni dejar al
    usuario con menos de 18 años).

    Cualquier otro campo (`legajo`, `email`...) responde 422. Si hay que
    corregir el legajo o el mail, lo hace un profesor (alumnos) o un super admin
    (profesores). La contraseña se cambia con `POST /auth/password/request` y
    `POST /auth/password/confirm`.
    """
    if not data.model_dump(exclude_none=True):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No fields to update")
    user = await update_user(db, user, data)
    return to_public(user)


@me_router.get(
    "/project",
    response_model=MyProjectPublic,
    summary="Consultar mi proyecto",
    responses={
        401: {"description": "Token ausente, inválido o vencido"},
        403: {"description": "El usuario no es alumno"},
    },
)
async def get_my_project_route(db: db_dependency, student: student_dependency):
    """
    El **alumno logueado** consulta su proyecto. **Solo alumnos.** Devuelve:

    - `project`: su **equipo**, el grupo donde es miembro (membresía `active` o
      `finished`). Va con el detalle completo, igual que
      `GET /projects/{id}/overview`: estado del proyecto, privacidad,
      integrantes (`active`/`finished`), los responsables (los profesores de su
      curso lectivo, sin mail) y el jefe (`leader`; el propio alumno aparece
      marcado con `is_leader` si lo es). Si no pertenece a ningún grupo es
      `null`.
    - `requests`: sus **solicitudes de ingreso** en estado `pending_approval` y
      `rejected`, con el resumen de cada grupo (comisión, año, número y el
      estado de la solicitud). Las pendientes van primero y, dentro de cada
      estado, de la más nueva a la más vieja. Una solicitud `rejected` solo se
      puede volver a enviar mientras el alumno no sea miembro de otro grupo.

    Un alumno sin equipo y sin solicitudes recibe
    `{"project": null, "requests": []}`.
    """
    return await get_my_project(db, student.id_student)
