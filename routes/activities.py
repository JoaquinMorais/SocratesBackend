from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, status

from config.database import db_dependency
from schemas.activity import (
    ActivityCreate,
    ActivityList,
    ActivityPublic,
    ActivityUpdate,
)
from utils.activities import (
    create_activity,
    delete_activity,
    get_activity,
    list_activities,
    to_public,
    update_activity,
)
from utils.auth import user_dependency
from utils.permissions import professor_dependency
from utils.projects import build_access
from utils.section_years import require_view_section_year

section_activities_router = APIRouter(
    prefix="/section-years", tags=["activities"]
)
activities_router = APIRouter(prefix="/activities", tags=["activities"])

_READ_ERRORS = {
    401: {"description": "Token ausente, inválido o vencido"},
    403: {"description": "El usuario no pertenece a ese curso lectivo"},
    404: {"description": "No existe el curso lectivo"},
}
_WRITE_ERRORS = {
    401: {"description": "Token ausente, inválido o vencido"},
    403: {
        "description": (
            "El usuario no es profesor, o no está asignado a ese curso lectivo "
            "(los super admin pueden en cualquiera)"
        )
    },
    404: {"description": "No existe el curso lectivo"},
}


@section_activities_router.get(
    "/{id_section_year}/activities",
    response_model=ActivityList,
    summary="Listar las actividades del curso lectivo",
    responses={
        **_READ_ERRORS,
        422: {
            "description": (
                "Se envió solo uno de `from`/`to`, `from` es posterior a `to` o el "
                "rango supera los 366 días"
            )
        },
    },
)
async def get_activities(
    id_section_year: int,
    db: db_dependency,
    user: user_dependency,
    from_date: Annotated[
        date | None, Query(alias="from", description="Primer día (YYYY-MM-DD)")
    ] = None,
    to_date: Annotated[
        date | None, Query(alias="to", description="Último día (YYYY-MM-DD)")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """
    Lista las **actividades/entregas** del curso lectivo. **Solo quienes
    pertenecen al curso:** super admin, profesores asignados y alumnos con
    cursada o con un grupo en ese curso lectivo.

    - Las actividades son de todo el curso lectivo: no se distinguen por grupo.
    - `from`/`to` son opcionales (ambos o ninguno, máximo 366 días) y filtran por
      fecha de entrega.
    - Orden: fecha de entrega y hora. Está paginado: `total` es la cantidad que
      cumple el filtro.
    """
    items, total = await list_activities(
        db,
        user,
        await build_access(db, user),
        id_section_year,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
    )
    return ActivityList(
        items=[to_public(i) for i in items], total=total, limit=limit, offset=offset
    )


@section_activities_router.post(
    "/{id_section_year}/activities",
    response_model=ActivityPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Crear una actividad",
    responses={
        **_WRITE_ERRORS,
        422: {
            "description": (
                "Título vacío o demasiado largo, fecha de entrega fuera del año "
                "del curso lectivo, campos faltantes o desconocidos"
            )
        },
    },
)
async def create_activity_route(
    id_section_year: int,
    data: ActivityCreate,
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
):
    """
    Crea una **actividad/entrega** para todo el curso lectivo. **Profesor del
    curso o super admin.**

    - `title` es obligatorio (se recorta, máximo 200).
    - `due_date` es obligatoria y debe caer en el año del curso lectivo;
      `due_time` es opcional.
    - `description` es opcional.
    - `link_required` (por defecto `false`) indica si los proyectos deben cargar
      un link antes de entregar.
    """
    return await create_activity(
        db, await build_access(db, user), id_section_year, data
    )


@activities_router.get(
    "/{id_activity}",
    response_model=ActivityPublic,
    summary="Consultar una actividad",
    responses={
        401: {"description": "Token ausente, inválido o vencido"},
        403: {"description": "El usuario no pertenece al curso lectivo"},
        404: {"description": "No existe la actividad"},
    },
)
async def get_activity_route(
    id_activity: int, db: db_dependency, user: user_dependency
):
    """Devuelve una actividad. Mismas restricciones de lectura que el curso lectivo."""
    activity = await get_activity(db, id_activity)
    await require_view_section_year(
        db, user, await build_access(db, user), activity.calendar.id_section_year
    )
    return to_public(activity)


@activities_router.patch(
    "/{id_activity}",
    response_model=ActivityPublic,
    summary="Modificar una actividad",
    responses={
        **_WRITE_ERRORS,
        404: {"description": "No existe la actividad"},
        422: {
            "description": (
                "Body vacío, título vacío o `null`, fecha fuera del año del curso "
                "lectivo o campos desconocidos"
            )
        },
    },
)
async def update_activity_route(
    id_activity: int,
    data: ActivityUpdate,
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
):
    """
    Modifica una actividad. **Profesor del curso lectivo o super admin.**

    Se envían solo los campos que cambian: `title`, `description`, `due_date`,
    `due_time` y `link_required`. Un body vacío responde 422.

    - `title` no admite `null`.
    - `description` y `due_time` se **limpian** enviando `null`.
    - `link_required` no admite `null`.
    - La fecha debe seguir dentro del año del curso lectivo.
    """
    return await update_activity(
        db, await build_access(db, user), id_activity, data
    )


@activities_router.delete(
    "/{id_activity}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar una actividad",
    responses={
        **_WRITE_ERRORS,
        404: {"description": "No existe la actividad"},
        409: {"description": "La actividad tiene entregas con datos y no se puede eliminar"},
    },
)
async def delete_activity_route(
    id_activity: int,
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
):
    """
    Elimina una actividad. **Profesor del curso lectivo o super admin.**

    Si alguna entrega de la actividad tiene link o notas responde 409; las
    entregas vacías se limpian con la actividad.
    """
    await delete_activity(db, await build_access(db, user), id_activity)
