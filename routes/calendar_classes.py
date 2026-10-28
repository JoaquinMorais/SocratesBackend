from fastapi import APIRouter, status

from config.database import db_dependency
from schemas.calendar_class import CalendarClassPublic, CalendarClassUpdate
from utils.auth import user_dependency
from utils.calendar_classes import (
    delete_calendar_class,
    get_calendar_class,
    to_public,
    update_calendar_class,
)
from utils.permissions import professor_dependency
from utils.projects import build_access
from utils.section_years import require_view_section_year

calendar_classes_router = APIRouter(prefix="/calendar-classes", tags=["calendar"])

_READ_ERRORS = {
    401: {"description": "Token ausente, inválido o vencido"},
    403: {"description": "El usuario no pertenece al curso lectivo del calendario"},
    404: {"description": "No existe la clase"},
}
_WRITE_ERRORS = {
    401: {"description": "Token ausente, inválido o vencido"},
    403: {
        "description": (
            "El usuario no es profesor, o no está asignado al curso lectivo del "
            "calendario (los super admin pueden en cualquiera)"
        )
    },
    404: {"description": "No existe la clase"},
}


@calendar_classes_router.get(
    "/{id_calendar_class}",
    response_model=CalendarClassPublic,
    summary="Consultar una clase",
    responses=_READ_ERRORS,
)
async def get_calendar_class_route(
    id_calendar_class: int, db: db_dependency, user: user_dependency
):
    """Devuelve una clase concreta del calendario. Mismas restricciones de lectura que el calendario."""
    calendar_class = await get_calendar_class(db, id_calendar_class)
    await require_view_section_year(
        db,
        user,
        await build_access(db, user),
        calendar_class.calendar.id_section_year,
    )
    return to_public(calendar_class)


@calendar_classes_router.patch(
    "/{id_calendar_class}",
    response_model=CalendarClassPublic,
    summary="Modificar una clase",
    responses={
        **_WRITE_ERRORS,
        409: {
            "description": (
                "La clase resultante se superpone con otra o empieza a la misma hora"
            )
        },
        422: {
            "description": (
                "Body vacío, fecha fuera del año del curso lectivo, `end_time` no "
                "posterior a `start_time`, link inválido o campos desconocidos"
            )
        },
    },
)
async def update_calendar_class_route(
    id_calendar_class: int,
    data: CalendarClassUpdate,
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
):
    """
    Modifica una clase concreta. **Profesor del curso lectivo o super admin.**

    Se envían solo los campos que cambian: `date`, `start_time`, `end_time`,
    `modality`, `title`, `location` y `meeting_url`. Un body vacío responde 422.

    - Cambiar la `date` mueve esa única clase (tiene que seguir en el año del
      curso lectivo).
    - `title`, `location` y `meeting_url` se limpian enviando `null`.
    - Si el resultado se superpone con otra clase del calendario, responde 409.
    """
    return await update_calendar_class(
        db, await build_access(db, user), id_calendar_class, data
    )


@calendar_classes_router.delete(
    "/{id_calendar_class}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar una clase",
    responses=_WRITE_ERRORS,
)
async def delete_calendar_class_route(
    id_calendar_class: int,
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
):
    """
    Elimina una clase concreta (por ejemplo, porque esa fecha es feriado).
    **Profesor del curso lectivo o super admin.** No borra el resto del calendario.
    """
    await delete_calendar_class(
        db, await build_access(db, user), id_calendar_class
    )
