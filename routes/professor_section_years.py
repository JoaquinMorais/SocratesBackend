from typing import Annotated

from fastapi import APIRouter, Query, status

from config.database import db_dependency
from schemas.professor_section_year import (
    ProfessorSectionYearCreate,
    ProfessorSectionYearList,
    ProfessorSectionYearPublic,
    ProfessorSectionYearUpdate,
)
from utils.auth import user_dependency
from utils.permissions import super_admin_dependency
from utils.professor_section_years import (
    create_assignment,
    delete_assignment,
    get_assignment,
    list_assignments,
    to_public,
    update_assignment,
)

professor_section_years_router = APIRouter(
    prefix="/professor-section-years", tags=["professor-section-years"]
)

_READ_ERRORS = {401: {"description": "Token ausente, inválido o vencido"}}
_WRITE_ERRORS = {
    **_READ_ERRORS,
    403: {"description": "El usuario no es profesor super admin"},
}
_NOT_FOUND = {404: {"description": "No existe la asignación"}}


@professor_section_years_router.post(
    "",
    response_model=ProfessorSectionYearPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Asignar un profesor a un curso lectivo",
    responses={
        **_WRITE_ERRORS,
        404: {"description": "No existe el profesor o el curso lectivo"},
        409: {"description": "El profesor ya está asignado a ese curso lectivo"},
        422: {"description": "Ids inválidos, campos faltantes o desconocidos"},
    },
)
async def create_assignment_route(
    data: ProfessorSectionYearCreate, db: db_dependency, _: super_admin_dependency
):
    """
    Asigna un profesor a un curso lectivo (por ejemplo, Marta dicta `3K1` de
    `2025`). **Solo super admin.**

    - `id_professor` debe ser el id de un **profesor** (`GET /users`); el id de
      un alumno responde 404.
    - `id_section_year` es el id de un curso lectivo (`/section-years`).
    - La relación es muchos a muchos: un profesor puede dictar varios cursos
      lectivos y un curso lectivo puede tener varios profesores, pero el mismo
      par no puede repetirse (409).
    """
    return await create_assignment(db, data)


@professor_section_years_router.get(
    "",
    response_model=ProfessorSectionYearList,
    summary="Listar asignaciones de profesores",
    responses=_READ_ERRORS,
)
async def get_assignments(
    db: db_dependency,
    _: user_dependency,
    id_professor: Annotated[int | None, Query(description="Filtrar por profesor")] = None,
    id_section_year: Annotated[int | None, Query(description="Filtrar por curso lectivo")] = None,
    year: Annotated[int | None, Query(description="Filtrar por año")] = None,
    id_section: Annotated[int | None, Query(description="Filtrar por comisión")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """
    Lista qué profesor dicta qué curso lectivo. **Cualquier usuario logueado.**

    Sirve para ver los profesores de un curso lectivo (`id_section_year`) o los
    cursos de un profesor (`id_professor`). Orden: año más reciente primero,
    luego comisión y apellido del profesor. Está paginado: `total` es la cantidad
    total que cumple los filtros. No incluye el mail del profesor.
    """
    items, total = await list_assignments(
        db,
        id_professor=id_professor,
        id_section_year=id_section_year,
        year=year,
        id_section=id_section,
        limit=limit,
        offset=offset,
    )
    return ProfessorSectionYearList(
        items=[to_public(i) for i in items], total=total, limit=limit, offset=offset
    )


@professor_section_years_router.get(
    "/{id_professor_section_year}",
    response_model=ProfessorSectionYearPublic,
    summary="Consultar una asignación",
    responses={**_READ_ERRORS, **_NOT_FOUND},
)
async def get_assignment_route(
    id_professor_section_year: int, db: db_dependency, _: user_dependency
):
    """Devuelve una asignación por su id. **Cualquier usuario logueado.**"""
    return to_public(await get_assignment(db, id_professor_section_year))


@professor_section_years_router.patch(
    "/{id_professor_section_year}",
    response_model=ProfessorSectionYearPublic,
    summary="Modificar una asignación",
    responses={
        **_WRITE_ERRORS,
        404: {"description": "No existe la asignación, el profesor o el curso lectivo"},
        409: {"description": "Ese profesor ya está asignado a ese curso lectivo"},
        422: {"description": "Body vacío, ids inválidos o campos desconocidos"},
    },
)
async def update_assignment_route(
    id_professor_section_year: int,
    data: ProfessorSectionYearUpdate,
    db: db_dependency,
    _: super_admin_dependency,
):
    """
    Reasigna: cambia el profesor y/o el curso lectivo de una asignación.
    **Solo super admin.**

    Ambos campos son opcionales (se envían solo los que cambian), pero debe
    enviarse al menos uno. Aplica las mismas reglas que al crear: reenviar los
    valores actuales no da error.
    """
    return await update_assignment(db, id_professor_section_year, data)


@professor_section_years_router.delete(
    "/{id_professor_section_year}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar una asignación",
    responses={**_WRITE_ERRORS, **_NOT_FOUND},
)
async def delete_assignment_route(
    id_professor_section_year: int, db: db_dependency, _: super_admin_dependency
):
    """
    Quita a un profesor de un curso lectivo. **Solo super admin.** No borra al
    profesor ni al curso lectivo; solo la relación, y puede volver a crearse.
    """
    await delete_assignment(db, id_professor_section_year)