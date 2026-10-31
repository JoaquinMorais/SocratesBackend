from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from config.database import db_dependency
from schemas.calendar import CalendarWithClassesPublic
from schemas.calendar_bulk import CalendarBulkLoad, CalendarBulkLoadReport
from schemas.calendar_class import (
    CalendarClassBulkCreate,
    CalendarClassBulkUpdate,
    CalendarClassCreate,
    CalendarClassPublic,
    CalendarClassSelector,
)
from utils.auth import user_dependency
from utils.calendar_bulk import bulk_load_calendar
from utils.calendar_classes import (
    bulk_create_calendar_classes,
    bulk_delete_calendar_classes,
    bulk_update_calendar_classes,
    create_calendar_class,
)
from utils.calendars import get_calendar_with_classes
from utils.permissions import professor_dependency
from utils.projects import build_access

calendars_router = APIRouter(prefix="/section-years", tags=["calendar"])

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


@calendars_router.get(
    "/{id_section_year}/calendar",
    response_model=CalendarWithClassesPublic,
    summary="Consultar el calendario del curso lectivo",
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
async def get_calendar(
    id_section_year: int,
    db: db_dependency,
    user: user_dependency,
    from_date: Annotated[
        date | None, Query(alias="from", description="Primer día (YYYY-MM-DD)")
    ] = None,
    to_date: Annotated[
        date | None, Query(alias="to", description="Último día (YYYY-MM-DD)")
    ] = None,
):
    """
    Devuelve el **calendario del curso lectivo** con sus clases concretas y actividades.
    **Super admin, profesores del curso y alumnos del curso** (con cursada o con
    un grupo en ese curso lectivo).

    - `from` y `to` son opcionales; si se envían, filtran las clases del rango
      (máximo 366 días) y deben venir juntos.
    - Las clases y las actividades vienen en arreglos separados, ordenadas por fecha y hora.
    - El calendario existe siempre: si el curso lectivo es viejo y no lo tenía,
      se crea en este momento.
    """
    return await get_calendar_with_classes(
        db,
        user,
        await build_access(db, user),
        id_section_year,
        from_date=from_date,
        to_date=to_date,
    )


@calendars_router.post(
    "/{id_section_year}/calendar-classes",
    response_model=CalendarClassPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Agregar una clase al calendario",
    responses={
        **_WRITE_ERRORS,
        409: {
            "description": (
                "Ya hay una clase a esa hora ese día, o la clase se superpone con "
                "otra del calendario"
            )
        },
        422: {
            "description": (
                "Fecha fuera del año del curso lectivo, `end_time` no posterior a "
                "`start_time`, link inválido, campos faltantes o desconocidos"
            )
        },
    },
)
async def create_calendar_class_route(
    id_section_year: int,
    data: CalendarClassCreate,
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
):
    """
    Crea una **clase puntual** en el calendario. **Profesor del curso lectivo o
    super admin.**

    - La fecha debe pertenecer al año del curso lectivo.
    - `end_time` debe ser posterior a `start_time`; `modality` es `in_person` o
      `virtual`; `title`, `location` y `meeting_url` son opcionales.
    - No puede empezar a la misma hora que otra clase del mismo día ni
      superponerse con ella (409).
    """
    return await create_calendar_class(
        db, await build_access(db, user), id_section_year, data
    )


@calendars_router.post(
    "/{id_section_year}/calendar-classes/bulk",
    response_model=list[CalendarClassPublic],
    status_code=status.HTTP_201_CREATED,
    summary="Crear un conjunto de clases recurrentes",
    responses={
        **_WRITE_ERRORS,
        409: {
            "description": (
                "Alguna fecha ya tiene una clase que se superpone. No se crea "
                "ninguna; `detail` lista `[{date, detail}]`"
            )
        },
        422: {
            "description": (
                "Días fuera de 1-7, `from` posterior a `to`, rango de más de 366 "
                "días o fechas fuera del año del curso lectivo (o ninguna fecha "
                "coincide con los días pedidos)"
            )
        },
    },
)
async def bulk_create_calendar_classes_route(
    id_section_year: int,
    data: CalendarClassBulkCreate,
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
):
    """
    Crea una clase por cada fecha que caiga en `weekdays` entre `from_date` y
    `to_date`.
    **Profesor del curso lectivo o super admin.**

    Por ejemplo, `weekdays: [2, 3]` entre el 1 de marzo y el 30 de noviembre crea
    todas las clases de martes y miércoles del período, con el mismo horario,
    modalidad y datos.

    - Es **todo o nada**: si alguna fecha ya tiene una clase que se superpone,
      responde 409 y no crea ninguna.
    - Los días se interpretan en ISO (`1` = lunes ... `7` = domingo); si se
      repiten, se toman una sola vez.
    """
    return await bulk_create_calendar_classes(
        db, await build_access(db, user), id_section_year, data
    )


@calendars_router.patch(
    "/{id_section_year}/calendar-classes/bulk",
    response_model=list[CalendarClassPublic],
    summary="Modificar un conjunto de clases",
    responses={
        **_WRITE_ERRORS,
        404: {"description": "Algún id no pertenece a este calendario"},
        409: {
            "description": (
                "El resultado se superpone con otras clases. No se modifica "
                "ninguna; `detail` lista `[{date, detail}]`"
            )
        },
        422: {
            "description": (
                "Sin `ids` ni `filter` (o con ambos), filtro sin criterios, "
                "`changes` vacío, intento de cambiar `date` o rango inválido"
            )
        },
    },
)
async def bulk_update_calendar_classes_route(
    id_section_year: int,
    data: CalendarClassBulkUpdate,
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
):
    """
    Modifica un conjunto de clases existentes. **Profesor del curso lectivo o
    super admin.**

    Se eligen con `ids` **o** con `filter` (`weekdays`, `from_date`, `to_date`), nunca
    ambos. `changes` no puede cambiar la `date` (para mover una clase se edita de
    a una): permite `start_time`, `end_time`, `modality`, `title`, `location` y
    `meeting_url` (estos últimos se limpian con `null`).

    Es todo o nada: si alguna clase resultante se superpone con otra (del
    conjunto o ajena), responde 409 y no modifica ninguna.
    """
    return await bulk_update_calendar_classes(
        db, await build_access(db, user), id_section_year, data
    )


@calendars_router.delete(
    "/{id_section_year}/calendar-classes/bulk",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar un conjunto de clases",
    responses={
        **_WRITE_ERRORS,
        404: {"description": "Algún id no pertenece a este calendario"},
        422: {
            "description": (
                "Sin `ids` ni `filter` (o con ambos), filtro sin criterios, rango "
                "inválido o ninguna clase coincide"
            )
        },
    },
)
async def bulk_delete_calendar_classes_route(
    id_section_year: int,
    data: CalendarClassSelector,
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
):
    """
    Elimina un conjunto de clases. **Profesor del curso lectivo o super admin.**

    Se eligen con `ids` o con `filter` (`weekdays`, `from_date`, `to_date`), nunca ambos.
    Es la forma de manejar un feriado o una suspensión: por ejemplo, `filter:
    {"from_date": "2026-04-02", "to_date": "2026-04-02"}` borra las clases de
    ese día.
    """
    await bulk_delete_calendar_classes(
        db, await build_access(db, user), id_section_year, data
    )


@calendars_router.post(
    "/{id_section_year}/calendar/bulk",
    response_model=CalendarBulkLoadReport,
    status_code=status.HTTP_201_CREATED,
    summary="Cargar el calendario en lote",
    responses={
        **_WRITE_ERRORS,
        409: {
            "description": (
                "Alguna clase del payload se superpone con una ya existente en el "
                "calendario. No se crea nada; `detail` lista `[{kind, row, detail}]`"
            )
        },
        422: {
            "description": (
                "Payload vacío, más de 1.000 clases o 200 actividades, fechas fuera "
                "del año, datos inválidos o clases que se superponen entre sí"
            )
        },
    },
)
async def bulk_load_calendar_route(
    id_section_year: int,
    data: CalendarBulkLoad,
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
    response: Response,
    dry_run: Annotated[
        bool,
        Query(description="true: valida y devuelve los conteos sin escribir"),
    ] = False,
):
    """
    Carga el **calendario completo de un curso lectivo** desde un JSON (por
    ejemplo, el que el frontend arma al procesar un Excel). **Profesor del curso
    lectivo o super admin.**

    - `classes` y `activities` son opcionales por separado, pero tiene que haber
      al menos una fila. Límites: **1.000 clases** y **200 actividades**.
    - Es un **append**: agrega al calendario existente y no borra nada.
    - Es **todo o nada**: valida el payload completo (fechas dentro del año,
      horarios, solapamientos internos y contra las clases ya cargadas) y, si
      algo falla, no crea ninguna fila.
    - Un solapamiento dentro del payload responde **422**; uno contra una clase
      existente responde **409**. En ambos casos `detail` lista
      `[{kind, row, detail}]` con la fila (empieza en 1) del arreglo
      correspondiente.
    - Las actividades comparten fecha con las clases sin problema; no se
      validan choques entre actividades.
    - `dry_run=true` valida y devuelve los conteos **sin escribir** (200). Sin
      `dry_run`, crea y responde 201.
    - No reemplaza el calendario: para vaciarlo hay que borrar las clases con
      los endpoints actuales.
    """
    if dry_run:
        response.status_code = status.HTTP_200_OK
    return await bulk_load_calendar(
        db, await build_access(db, user), id_section_year, data, dry_run=dry_run
    )
