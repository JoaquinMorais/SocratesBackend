from typing import Annotated

from fastapi import APIRouter, Query, status

from config.database import db_dependency
from schemas.student_section_year import (
    StudentSectionYearCreate,
    StudentSectionYearList,
    StudentSectionYearPublic,
    StudentSectionYearUpdate,
)
from utils.permissions import professor_dependency, super_admin_dependency
from utils.student_section_years import (
    create_enrollment,
    delete_enrollment,
    get_enrollment,
    list_enrollments,
    to_public,
    update_enrollment,
)

student_section_years_router = APIRouter(
    prefix="/student-section-years", tags=["student-section-years"]
)

_READ_ERRORS = {
    401: {"description": "Token ausente, inválido o vencido"},
    403: {"description": "El usuario no es profesor"},
}
_WRITE_ERRORS = {
    401: {"description": "Token ausente, inválido o vencido"},
    403: {"description": "El usuario no es profesor super admin"},
}
_NOT_FOUND = {404: {"description": "No existe la cursada"}}


@student_section_years_router.post(
    "",
    response_model=StudentSectionYearPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Inscribir un alumno en un curso lectivo",
    responses={
        **_WRITE_ERRORS,
        404: {"description": "No existe el alumno o el curso lectivo"},
        409: {"description": "El alumno ya está inscripto en ese curso lectivo"},
        422: {"description": "Ids inválidos, campos faltantes o desconocidos"},
    },
)
async def create_enrollment_route(
    data: StudentSectionYearCreate, db: db_dependency, _: super_admin_dependency
):
    """
    Inscribe a un alumno en un curso lectivo (su **cursada**). **Solo super admin.**

    - `id_student` debe ser el id de un **alumno** (`GET /students`); el id de un
      profesor responde 404.
    - `id_section_year` es el id de un curso lectivo (`/section-years`).
    - La relación es muchos a muchos: un alumno puede cursar varios años
      lectivos a lo largo del tiempo y un curso lectivo tiene muchos alumnos,
      pero el mismo par no puede repetirse (409).
    """
    return await create_enrollment(db, data)


@student_section_years_router.get(
    "",
    response_model=StudentSectionYearList,
    summary="Listar cursadas",
    responses=_READ_ERRORS,
)
async def get_enrollments(
    db: db_dependency,
    _: professor_dependency,
    id_student: Annotated[int | None, Query(description="Filtrar por alumno")] = None,
    id_section_year: Annotated[
        int | None, Query(description="Filtrar por curso lectivo")
    ] = None,
    year: Annotated[int | None, Query(description="Filtrar por año")] = None,
    id_section: Annotated[int | None, Query(description="Filtrar por comisión")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """
    Lista qué alumno cursó qué curso lectivo. **Solo profesores** (incluye super admin).

    Sirve para ver las cursadas de un alumno (`id_student`) o los alumnos de un
    curso lectivo (`id_section_year`). Orden: año más reciente primero, luego
    comisión y apellido del alumno. Está paginado: `total` es la cantidad total
    que cumple los filtros. No incluye el mail ni la fecha de nacimiento del alumno.
    """
    items, total = await list_enrollments(
        db,
        id_student=id_student,
        id_section_year=id_section_year,
        year=year,
        id_section=id_section,
        limit=limit,
        offset=offset,
    )
    return StudentSectionYearList(
        items=[to_public(i) for i in items], total=total, limit=limit, offset=offset
    )


@student_section_years_router.get(
    "/{id_student_section_year}",
    response_model=StudentSectionYearPublic,
    summary="Consultar una cursada",
    responses={**_READ_ERRORS, **_NOT_FOUND},
)
async def get_enrollment_route(
    id_student_section_year: int, db: db_dependency, _: professor_dependency
):
    """Devuelve una cursada por su id. **Solo profesores** (incluye super admin)."""
    return to_public(await get_enrollment(db, id_student_section_year))


@student_section_years_router.patch(
    "/{id_student_section_year}",
    response_model=StudentSectionYearPublic,
    summary="Modificar una cursada",
    responses={
        **_WRITE_ERRORS,
        404: {
            "description": "No existe la cursada, el alumno o el curso lectivo"
        },
        409: {"description": "El par alumno + curso lectivo ya existe en otra cursada"},
        422: {"description": "Ids inválidos, body vacío o campos desconocidos"},
    },
)
async def update_enrollment_route(
    id_student_section_year: int,
    data: StudentSectionYearUpdate,
    db: db_dependency,
    _: super_admin_dependency,
):
    """
    Corrige la cursada (cambia el alumno o el curso lectivo). **Solo super admin.**

    Se envían solo los campos que cambian (`id_student`, `id_section_year`); un
    body vacío responde 422. Reenviar los mismos valores no da error. Si el par
    resultante ya existe en otra cursada, responde 409.
    """
    return await update_enrollment(db, id_student_section_year, data)


@student_section_years_router.delete(
    "/{id_student_section_year}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar una cursada",
    responses={**_WRITE_ERRORS, **_NOT_FOUND},
)
async def delete_enrollment_route(
    id_student_section_year: int, db: db_dependency, _: super_admin_dependency
):
    """
    Elimina la cursada (solo el vínculo). **Solo super admin.**

    Ni el alumno ni el curso lectivo se borran; un curso lectivo con cursadas no
    se puede eliminar hasta quitarlas.
    """
    await delete_enrollment(db, id_student_section_year)
