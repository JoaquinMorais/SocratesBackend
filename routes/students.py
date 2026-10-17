from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Query, status

from config.database import db_dependency
from schemas.status import MembershipStatus
from schemas.student import (
    StudentBulkCreate,
    StudentCreate,
    StudentList,
    StudentPublic,
    StudentUpdate,
)
from utils.auth import user_dependency
from utils.email import send_welcome_emails
from utils.permissions import professor_dependency
from utils.projects import build_access
from utils.statuses import MEMBER, STUDENT_PROJECT
from utils.students import create_students, list_students, update_student

students_router = APIRouter(prefix="/students", tags=["students"])

_AUTH_ERRORS = {
    401: {"description": "Token ausente, inválido o vencido"},
    403: {"description": "El usuario no es profesor"},
}


@students_router.get(
    "",
    response_model=StudentList,
    summary="Listar alumnos registrados",
    responses={
        401: {"description": "Token ausente, inválido o vencido"},
        403: {
            "description": (
                "El usuario no es profesor, o pidió un curso lectivo del que no es "
                "profesor (los super admin pueden cualquiera)"
            )
        },
        422: {"description": "Algún `status` no es un estado de membresía válido"},
    },
)
async def get_students(
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
    status_filter: Annotated[
        list[MembershipStatus],
        Query(
            alias="status",
            description=(
                "Estados de la membresía a incluir (repetible). Por defecto "
                "`active` y `finished`"
            ),
        ),
    ] = list(STUDENT_PROJECT.codes_of(MEMBER)),
    id_section_year: Annotated[
        int | None, Query(description="Filtrar por curso lectivo")
    ] = None,
    year: Annotated[int | None, Query(description="Filtrar por año")] = None,
    id_section: Annotated[int | None, Query(description="Filtrar por comisión")] = None,
    q: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=100,
            description="Busca en nombre, apellido o legajo (exacto)",
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """
    Lista los alumnos registrados junto con los grupos a los que pertenecen.
    **Solo profesores.**

    - Un **super admin** ve todos los alumnos; sin filtros, también los que no
      están en ningún grupo (`groups` vacío). Un **profesor común** solo ve los
      alumnos de los cursos lectivos a los que está asignado.
    - Cada grupo incluye `id_project`, `project_name`, `group_number`, `is_leader`
      (si el alumno es jefe del grupo), su `status` de membresía y los datos del
      curso lectivo (año, comisión). Nunca expone datos privados del alumno (como
      la fecha de nacimiento) ni el detalle del proyecto.
    - Filtros: `status` (repetible; por defecto `active` y `finished`),
      `id_section_year`, `year`, `id_section` y `q` (nombre, apellido o legajo
      exacto). Un `status` desconocido responde **422**. Si un profesor pide un
      `id_section_year` que no dicta, responde **403**.
    - Un alumno sin ninguna membresía sigue apareciendo mientras no se filtre por
      curso/año/comisión; al filtrar por ellos, solo aparecen los alumnos con al
      menos una membresía en los estados pedidos dentro del alcance.

    Orden: apellido, nombre. Dentro de cada alumno, los grupos van por estado
    (`active`, `pending_approval`, `finished`, `abandoned`, `expelled`,
    `rejected`) y después del curso más reciente al más viejo. Está paginado:
    `total` es la cantidad que cumple los filtros.
    """
    access = await build_access(db, user)
    items, total = await list_students(
        db,
        access,
        statuses=status_filter,
        id_section_year=id_section_year,
        year=year,
        id_section=id_section,
        q=q,
        limit=limit,
        offset=offset,
    )
    return StudentList(items=items, total=total, limit=limit, offset=offset)


@students_router.post(
    "",
    response_model=StudentPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un alumno",
    responses={
        **_AUTH_ERRORS,
        422: {"description": "Datos inválidos o legajo ya existente entre alumnos"},
    },
)
async def create_student(
    data: StudentCreate,
    background: BackgroundTasks,
    db: db_dependency,
    _: professor_dependency,
):
    """
    Crea un alumno. **Solo profesores** (sean o no super admin).

    - El mail del alumno se calcula como `{legajo}@sistemas.frc.utn.edu.ar`.
    - El alumno se crea **sin contraseña**: no puede iniciar sesión hasta crearla
      con `POST /auth/password/request` y `POST /auth/password/confirm`.
    - El legajo no puede repetirse entre alumnos.
    - Se envía un mail de bienvenida al alumno.
    """
    created = await create_students(db, [data])
    background.add_task(
        send_welcome_emails, [(s.email, s.first_name) for s in created]
    )
    return created[0]


@students_router.post(
    "/bulk",
    response_model=list[StudentPublic],
    status_code=status.HTTP_201_CREATED,
    summary="Crear varios alumnos a la vez",
    responses={
        **_AUTH_ERRORS,
        422: {
            "description": (
                "Datos inválidos o filas con error. Si falla alguna fila no se crea ninguna; "
                "`detail` lista los errores como `[{row, legajo, detail}]` (fila empieza en 1)"
            )
        },
    },
)
async def create_students_bulk(
    data: StudentBulkCreate,
    background: BackgroundTasks,
    db: db_dependency,
    _: professor_dependency,
):
    """
    Crea de 1 a 500 alumnos en una sola request (pensado para cargar un Excel).
    **Solo profesores.**

    Es **todo o nada**: si alguna fila tiene un problema (legajo repetido dentro
    del lote o ya existente) no se crea ninguna y la respuesta indica qué filas
    corregir para volver a enviar el lote completo.

    Las reglas por alumno son las mismas que en `POST /students`.
    """
    created = await create_students(db, data.students)
    background.add_task(
        send_welcome_emails, [(s.email, s.first_name) for s in created]
    )
    return created


@students_router.patch(
    "/{id_student}",
    response_model=StudentPublic,
    summary="Modificar un alumno",
    responses={
        **_AUTH_ERRORS,
        404: {"description": "No existe el alumno"},
        409: {"description": "Otro alumno ya tiene ese legajo"},
        422: {"description": "Datos inválidos, body vacío o campos que no se pueden modificar"},
    },
)
async def update_student_route(
    id_student: int,
    data: StudentUpdate,
    db: db_dependency,
    _: professor_dependency,
):
    """
    Corrige los datos de un alumno. **Solo profesores** (sean o no super admin).

    **Campos editables** (opcionales, se envían solo los que cambian):
    `first_name`, `last_name`, `birth_date`, `legajo`, `enrollment_year`.

    - Cambiar el `legajo` cambia también el mail de login del alumno
      (`{legajo}@sistemas.frc.utn.edu.ar`); sus sesiones siguen abiertas.
    - El legajo no puede repetirse entre alumnos (409).
    - Cualquier otro campo responde 422. La contraseña no se puede modificar
      desde acá.
    """
    return await update_student(db, id_student, data)