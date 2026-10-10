from typing import Annotated

from fastapi import APIRouter, Query, status

from config.database import db_dependency
from schemas.section_year import (
    SectionYearCreate,
    SectionYearList,
    SectionYearPublic,
    SectionYearUpdate,
)
from utils.auth import user_dependency
from utils.permissions import super_admin_dependency
from utils.section_years import (
    create_section_year,
    delete_section_year,
    get_section_year,
    list_section_years,
    to_public,
    update_section_year,
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
        409: {"description": "El curso lectivo tiene profesores asignados, proyectos u otros datos y no se puede eliminar"},
        422: {"description": "Año fuera de rango, campos faltantes o desconocidos"},
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
    - La combinación año + comisión no puede repetirse. Una misma comisión sí
      puede existir en distintos años, y un mismo año en distintas comisiones.
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
    "/{id_section_year}",
    response_model=SectionYearPublic,
    summary="Modificar un curso lectivo",
    responses={
        **_AUTH_ERRORS,
        404: {"description": "No existe el curso lectivo o la comisión indicada"},
        409: {"description": "Ya existe esa comisión en ese año"},
        422: {"description": "Body vacío, año fuera de rango o campos desconocidos"},
    },
)
async def update_section_year_route(
    id_section_year: int,
    data: SectionYearUpdate,
    db: db_dependency,
    _: super_admin_dependency,
):
    """
    Cambia el año y/o la comisión de un curso lectivo. **Solo super admin.**

    Ambos campos son opcionales (se envían solo los que cambian), pero debe
    enviarse al menos uno. Aplica la misma regla de unicidad que al crear:
    reenviar los valores actuales no da error.
    """
    return await update_section_year(db, id_section_year, data)


@section_years_router.delete(
    "/{id_section_year}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar un curso lectivo",
    responses={
        **_AUTH_ERRORS,
        **_NOT_FOUND,
        409: {"description": "El curso lectivo tiene profesores asignados (u otros datos) y no se puede eliminar"},    },
)
async def delete_section_year_route(
    id_section_year: int, db: db_dependency, _: super_admin_dependency
):
    """
    Elimina un curso lectivo. **Solo super admin.** La acción es irreversible; la
    combinación año + comisión queda libre para volver a crearse.

    Si tiene profesores asignados (`/professor-section-years`), proyectos
    (`/projects`) u otros datos asociados responde 409: hay que quitarlos primero.
    """
    await delete_section_year(db, id_section_year)