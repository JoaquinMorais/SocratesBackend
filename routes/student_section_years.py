from typing import Annotated, Literal

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
    enrollment_public_with_attendance,
    get_enrollment,
    list_enrollments_with_attendance,
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
        409: {"description": "El alumno ya tiene una inscripción para ese año"},
        422: {"description": "Ids inválidos, campos faltantes o desconocidos"},
    },
)
async def create_enrollment_route(
    data: StudentSectionYearCreate, db: db_dependency, _: super_admin_dependency
):
    """
    Registra la **inscripción** de un alumno en un curso lectivo. **Solo super admin.**

    - `id_student` debe ser el id de un **alumno** (`GET /students`); el id de un
      profesor responde 404.
    - `id_section_year` es el id de un curso lectivo (`/section-years`).
    - Un alumno tiene **una sola inscripción por año** (409 si ya tiene otra en
      ese año). Puede tener además una **cursada** en otra comisión del mismo año,
      que se crea automáticamente al unirse a un proyecto.
    - La fila nace en estado `registered`.
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
    state: Annotated[
        Literal[
            "registered",
            "attending",
            "abandoned",
            "finished_approved",
            "finished_failed",
        ]
        | None,
        Query(description="Filtrar por estado"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """
    Lista las inscripciones y cursadas de los alumnos. **Solo profesores**
    (incluye super admin).

    Cada fila indica su `state`: `registered` (inscripción), `attending`
    (cursada actual), `abandoned` o `finished_approved`/`finished_failed`.
    Las cursadas incluyen `attendance` (`attended_classes`, `total_classes` y
    `attendance_percentage`); la inscripción devuelve `attendance: null`.
    Sirve para ver las filas de un alumno (`id_student`) o de un curso lectivo
    (`id_section_year`), y se puede filtrar por `state`. Orden: año más reciente,
    comisión y apellido. Está paginado. No incluye mail ni fecha de nacimiento.
    """
    items, total = await list_enrollments_with_attendance(
        db,
        id_student=id_student,
        id_section_year=id_section_year,
        year=year,
        id_section=id_section,
        state=state,
        limit=limit,
        offset=offset,
    )
    return StudentSectionYearList(
        items=items, total=total, limit=limit, offset=offset
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
    """Devuelve una cursada por su id, con su porcentaje de asistencia. **Solo profesores** (incluye super admin)."""
    return await enrollment_public_with_attendance(
        db, await get_enrollment(db, id_student_section_year)
    )


@student_section_years_router.patch(
    "/{id_student_section_year}",
    response_model=StudentSectionYearPublic,
    summary="Modificar una cursada",
    responses={
        **_WRITE_ERRORS,
        404: {
            "description": "No existe la cursada, el alumno o el curso lectivo"
        },
        409: {
            "description": (
                "El alumno ya tiene una inscripción para ese año, o la fila es una "
                "cursada administrada automáticamente"
            )
        },
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
    Corrige una **inscripción** (cambia el alumno o el curso lectivo). **Solo super admin.**

    Se envían solo los campos que cambian (`id_student`, `id_section_year`); un
    body vacío responde 422. Reenviar los mismos valores no da error. Si el
    alumno ya tiene otra inscripción en el año resultante, responde 409. Las
    cursadas son administradas automáticamente por la membresía al proyecto y no
    se editan desde acá (409).
    """
    return await update_enrollment(db, id_student_section_year, data)


@student_section_years_router.delete(
    "/{id_student_section_year}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar una cursada",
    responses={
        **_WRITE_ERRORS,
        **_NOT_FOUND,
        409: {"description": "La fila es una cursada administrada automáticamente"},
    },
)
async def delete_enrollment_route(
    id_student_section_year: int, db: db_dependency, _: super_admin_dependency
):
    """
    Elimina una **inscripción**. **Solo super admin.**

    Las cursadas son administradas automáticamente y no se eliminan desde acá
    (409). Ni el alumno ni el curso lectivo se borran; un curso lectivo con
    inscripciones/cursadas no se puede eliminar.
    """
    await delete_enrollment(db, id_student_section_year)
