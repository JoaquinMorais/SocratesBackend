from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from config.database import db_dependency
from schemas.section_year import (
    SectionYearCreate,
    SectionYearList,
    SectionYearPublic,
    SectionYearSettingsUpdate,
    SectionYearUpdate,
)
from utils.auth import user_dependency
from utils.permissions import professor_dependency, super_admin_dependency
from utils.projects import build_access
from utils.section_years import (
    create_section_year,
    delete_section_year,
    get_section_year,
    list_section_years,
    to_public,
    update_section_year,
    update_section_year_settings,
)

section_years_router = APIRouter(prefix="/section-years", tags=["section-years"])

_AUTH_ERRORS = {
    401: {"description": "Token ausente, inválido o vencido"},
    403: {"description": "El usuario no es profesor super admin"},
}
_NOT_FOUND = {404: {"description": "No existe el curso lectivo"}}
_READ_ERRORS = {401: {"description": "Token ausente, inválido o vencido"}}

@section_years_router.post(
    "",
    response_model=SectionYearPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un curso lectivo",
    responses={
        **_AUTH_ERRORS,
        404: {"description": "No existe la comisión indicada"},
        409: {"description": "Ya existe esa comisión en ese año"},
        422: {"description": "Año fuera de rango, rango de estudiantes inválido (max < min o fuera de 1-100), campos faltantes o desconocidos"},
    },
)
async def create_section_year_route(
    data: SectionYearCreate, db: db_dependency, _: super_admin_dependency
):
    """
    Crea un curso lectivo: una comisión en un año (por ejemplo, `3K1` de `2025`).
    **Solo super admin.**

    - `year` debe estar entre 2000 y 2100.
    - `id_section` es el id de una comisión existente (`POST /sections`).
    - `min_students` y `max_students` definen cuántos alumnos debe tener cada
      grupo (ambos entre 1 y 100, y `max_students` no puede ser menor que
      `min_students`). Se usarán más adelante para validar el estado del grupo.
    - La combinación año + comisión no puede repetirse. Una misma comisión sí
      puede existir en distintos años, y un mismo año en distintas comisiones.
    - `allow_project_joins` (por defecto `false`) permite que un alumno con
      cursada `finished_failed` vuelva a unirse a un grupo de este curso.
    """
    return await create_section_year(db, data)


@section_years_router.get(
    "",
    response_model=SectionYearList,
    summary="Listar cursos lectivos",
    responses=_READ_ERRORS,
)
async def get_section_years(
    db: db_dependency,
    _: user_dependency,
    year: Annotated[int | None, Query(description="Filtrar por año")] = None,
    id_section: Annotated[int | None, Query(description="Filtrar por comisión")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """
    Lista los cursos lectivos. **Cualquier usuario logeado.**

    Orden: año más reciente primero y, dentro del año, por nombre de comisión.
    Se puede filtrar por `year` y/o `id_section`. Está paginado: `total` es la
    cantidad total que cumple los filtros.
    """
    items, total = await list_section_years(
        db, year=year, id_section=id_section, limit=limit, offset=offset
    )
    return SectionYearList(
        items=[to_public(sy) for sy in items], total=total, limit=limit, offset=offset
    )


@section_years_router.get(
    "/{id_section_year}",
    response_model=SectionYearPublic,
    summary="Consultar un curso lectivo",
    responses={**_READ_ERRORS, **_NOT_FOUND},
)
async def get_section_year_route(
    id_section_year: int, db: db_dependency, _: user_dependency
):
    """Devuelve un curso lectivo por su id. **Cualquier usuario logeado.**"""
    return to_public(await get_section_year(db, id_section_year))


@section_years_router.patch(
    "/{id_section_year}/settings",
    response_model=SectionYearPublic,
    summary="Configurar el curso lectivo",
    responses={
        401: {"description": "Token ausente, inválido o vencido"},
        403: {"description": "El usuario no es profesor del curso lectivo ni super admin"},
        **_NOT_FOUND,
        422: {"description": "Body vacío, falta `allow_project_joins` o hay campos desconocidos"},
    },
)
async def update_section_year_settings_route(
    id_section_year: int,
    data: SectionYearSettingsUpdate,
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
):
    """
    Cambia la configuración del curso lectivo. **Profesor asignado al curso o
    super admin.**

    - `allow_project_joins`: si es `true`, un alumno con cursada
      `finished_failed` en ese curso puede volver a unirse a un grupo de la misma
      comisión/año y su cursada se reactiva como `attending`. Si es `false`
      (valor por defecto), el intento responde 409.
    - Las cursadas `finished_approved` no se pueden reintentar con esta opción.
    - El resto de los datos del curso lectivo se siguen modificando con
      `PATCH /section-years/{id}` (solo super admin).
    """
    access = await build_access(db, user)
    if not access.can_manage(id_section_year):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only a professor of this section year or a super admin can change it",
        )
    return await update_section_year_settings(db, id_section_year, data)


@section_years_router.patch(
    "/{id_section_year}",
    response_model=SectionYearPublic,
    summary="Modificar un curso lectivo",
    responses={
        **_AUTH_ERRORS,
        404: {"description": "No existe el curso lectivo o la comisión indicada"},
        409: {"description": "Ya existe esa comisión en ese año"},
        422: {"description": "Body vacío, año fuera de rango, rango de estudiantes inválido (max < min o fuera de 1-100) o campos desconocidos"},
    },
)
async def update_section_year_route(
    id_section_year: int,
    data: SectionYearUpdate,
    db: db_dependency,
    _: super_admin_dependency,
):
    """
    Cambia el año, la comisión y/o el rango de estudiantes de un curso lectivo.
    **Solo super admin.**

    Todos los campos son opcionales (se envían solo los que cambian), pero debe
    enviarse al menos uno. `min_students` y `max_students` se validan juntos
    (entre 1 y 100 y `max_students >= min_students`), por lo que si se envía solo
    uno se compara con el valor actual del otro. Aplica la misma regla de
    unicidad que al crear: reenviar los valores actuales no da error.
    También puede incluir `allow_project_joins`.
    """
    return await update_section_year(db, id_section_year, data)


@section_years_router.delete(
    "/{id_section_year}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar un curso lectivo",
    responses={
        **_AUTH_ERRORS,
        **_NOT_FOUND,
        409: {"description": "El curso lectivo tiene profesores asignados, inscripciones/cursadas de alumnos, proyectos u otros datos y no se puede eliminar"},
    },
)
async def delete_section_year_route(
    id_section_year: int, db: db_dependency, _: super_admin_dependency
):
    """
    Elimina un curso lectivo. **Solo super admin.** La acción es irreversible; la
    combinación año + comisión queda libre para volver a crearse.

    Si tiene profesores asignados (`/professor-section-years`),
    inscripciones/cursadas de alumnos (`/student-section-years`), proyectos
    (`/projects`) u otros datos asociados responde 409: hay que quitarlos
    primero.
    """
    await delete_section_year(db, id_section_year)