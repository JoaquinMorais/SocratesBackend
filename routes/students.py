from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from sqlmodel import select

from config.database import db_dependency
from models import Student, StudentSectionYear
from schemas.attendance import MyAttendanceListPublic
from schemas.status import MembershipStatus
from schemas.student import (
    StudentBulkCreate,
    StudentCreate,
    StudentList,
    StudentPublic,
    StudentUpdate,
)
from schemas.student_statistics import StudentStatisticsPublic
from models.state.student_section_year import REGISTERED
from utils.attendance import list_student_attendance
from utils.auth import user_dependency
from utils.email import send_welcome_emails
from utils.permissions import professor_dependency, super_admin_dependency
from models.state import MEMBER_CODES
from utils.projects import build_access
from utils.student_statistics import build_student_statistics
from utils.students import create_students, delete_student, list_students, update_student

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
    ] = list(MEMBER_CODES),
    id_section_year: Annotated[
        int | None, Query(description="Filtrar por curso lectivo")
    ] = None,
    year: Annotated[int | None, Query(description="Filtrar por año")] = None,
    id_section: Annotated[int | None, Query(description="Filtrar por comisión")] = None,
    kind: Annotated[
        Literal["project", "attending", "registered"] | None,
        Query(
            description=(
                "Población de alumnos a listar: `project` (con membresía de proyecto "
                "en los `status` pedidos), `attending` (con cursada `attending`) o "
                "`registered` (con inscripción `registered`). Sin valor se mantiene "
                "el comportamiento actual."
            )
        ),
    ] = None,
    q: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=100,
            description="Busca en nombre, apellido, legajo (prefijo) o nombre de proyecto",
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
    - `section_years` incluye todas las inscripciones (`registered`) y la cursada
      actual (`attending`) del alumno, con su `state` y `status`; no incluye
      cursadas `abandoned` ni `finished_*`. Los filtros de curso/año/comisión
      también acotan esta lista. Un profesor común ve todos los cursos lectivos
      del alumno, aunque no los dicte.
    - Filtros: `status` (repetible; por defecto `active` y `finished`),
      `id_section_year`, `year`, `id_section`, `kind` y `q` (nombre, apellido,
      legajo (prefijo) o nombre de alguno de sus proyectos en los estados pedidos).
      Un `status` desconocido responde **422** y un `kind` desconocido también.
      Si un profesor pide un `id_section_year` que no dicta, responde **403**.
    - `kind` elige la población de alumnos: `project` (con membresía de proyecto
      en los `status` pedidos), `attending` (con cursada `attending`) o
      `registered` (con inscripción `registered`). Sin `kind` se mantiene el
      comportamiento anterior: un super admin sin filtros de curso ve a todos; con
      filtros de curso o un profesor común, solo los alumnos con proyecto en el
      alcance. En `attending`/`registered`, `status` no restringe la población,
      solo los grupos devueltos.
    - Un alumno sin ninguna membresía sigue apareciendo mientras no se filtre por
      curso/año/comisión; al filtrar por ellos, solo aparecen los alumnos con al
      menos una membresía en los estados pedidos dentro del alcance.

    Orden: apellido, nombre. Dentro de cada alumno, los grupos van por estado
    (`active`, `pending_approval`, `finished`, `abandoned`, `expelled`,
    `rejected`) y después del curso más reciente al más viejo; los
    `section_years` van con la cursada `attending` primero y luego por año
    descendente. Está paginado: `total` es la cantidad que cumple los filtros.
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
        kind=kind,
        limit=limit,
        offset=offset,
    )
    return StudentList(items=items, total=total, limit=limit, offset=offset)


async def _student_statistics_route(
    db,
    user,
    population: str,
    id_section_year: int | None,
    year: int | None,
    id_section: int | None,
    limit: int,
    offset: int,
):
    access = await build_access(db, user)
    return await build_student_statistics(
        db,
        access,
        population=population,
        id_section_year=id_section_year,
        year=year,
        id_section=id_section,
        limit=limit,
        offset=offset,
    )


@students_router.get(
    "/statistics/registered",
    response_model=StudentStatisticsPublic,
    summary="Estadísticas de alumnos inscriptos",
    responses={
        **_AUTH_ERRORS,
        403: {"description": "El usuario no es profesor o no dicta el curso consultado"},
        404: {"description": "No existe el curso lectivo"},
        422: {"description": "Filtros o paginación inválidos"},
    },
)
async def get_registered_students_statistics_route(
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
    id_section_year: Annotated[
        int | None, Query(gt=0, description="Filtrar por curso lectivo")
    ] = None,
    year: Annotated[int | None, Query(description="Filtrar por año")] = None,
    id_section: Annotated[
        int | None, Query(gt=0, description="Filtrar por comisión")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """
    Estadísticas de los alumnos con inscripción **`registered`**. **Solo
    profesores**; un profesor común ve solo sus cursos.

    Incluye totales, desglose por curso lectivo, proyectos del mismo curso,
    distribución de membresías y listado por alumno. La inscripción no tiene
    cursada, por lo que su asistencia es `null`.
    """
    return await _student_statistics_route(
        db,
        user,
        "registered",
        id_section_year,
        year,
        id_section,
        limit,
        offset,
    )


@students_router.get(
    "/statistics/attending",
    response_model=StudentStatisticsPublic,
    summary="Estadísticas de alumnos cursando",
    responses={
        **_AUTH_ERRORS,
        403: {"description": "El usuario no es profesor o no dicta el curso consultado"},
        404: {"description": "No existe el curso lectivo"},
        422: {"description": "Filtros o paginación inválidos"},
    },
)
async def get_attending_students_statistics_route(
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
    id_section_year: Annotated[
        int | None, Query(gt=0, description="Filtrar por curso lectivo")
    ] = None,
    year: Annotated[int | None, Query(description="Filtrar por año")] = None,
    id_section: Annotated[
        int | None, Query(gt=0, description="Filtrar por comisión")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """
    Estadísticas de los alumnos con cursada **`attending`**. **Solo profesores**;
    un profesor común ve solo sus cursos.

    Incluye totales, desglose por curso lectivo, proyectos del mismo curso,
    distribución de membresías, asistencia agregada y listado por alumno con su
    asistencia individual.
    """
    return await _student_statistics_route(
        db,
        user,
        "attending",
        id_section_year,
        year,
        id_section,
        limit,
        offset,
    )


@students_router.get(
    "/{id_student}/attendance",
    response_model=MyAttendanceListPublic,
    summary="Consultar la asistencia de un alumno",
    responses={
        **_AUTH_ERRORS,
        403: {
            "description": (
                "El usuario no es profesor del curso donde cursa el alumno o super admin"
            )
        },
        404: {"description": "No existe el alumno"},
        422: {
            "description": (
                "Se envió solo uno de `from`/`to`, `from` es posterior a `to` o el "
                "rango supera los 366 días"
            )
        },
    },
)
async def get_student_attendance_route(
    id_student: int,
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
    from_date: Annotated[
        date | None, Query(alias="from", description="Primer día (YYYY-MM-DD)")
    ] = None,
    to_date: Annotated[
        date | None, Query(alias="to", description="Último día (YYYY-MM-DD)")
    ] = None,
):
    """
    Devuelve el **historial de asistencias de un alumno**. **Solo profesor de
    alguno de sus cursos lectivos o super admin.**

    - Un profesor común solo ve las cursadas de los cursos lectivos que dicta;
      el super admin ve todas.
    - `section_years` resume cada cursada y `items` lista las clases a las que
      asistió, igual que `GET /me/attendance`.
    - `from`/`to` son opcionales (ambos o ninguno, máximo 366 días) y filtran por
      fecha de la clase.
    - Alumno inexistente: **404**. Profesor sin cursos en común: **403**.
    """
    student = await db.get(Student, id_student)
    if student is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")

    access = await build_access(db, user)
    if access.is_super_admin:
        section_year_ids = None
    else:
        allowed = (
            await db.exec(
                select(StudentSectionYear.id_section_year)
                .where(
                    StudentSectionYear.id_student == id_student,
                    StudentSectionYear.state != REGISTERED,
                    StudentSectionYear.id_section_year.in_(
                        access.section_year_ids
                    ),
                )
                .limit(1)
            )
        ).first()
        if allowed is None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Only a professor of one of this student's courses can see attendance",
            )
        section_year_ids = access.section_year_ids

    return await list_student_attendance(
        db,
        id_student,
        section_year_ids=section_year_ids,
        from_date=from_date,
        to_date=to_date,
    )


@students_router.post(
    "",
    response_model=StudentPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un alumno",
    responses={
        **_AUTH_ERRORS,
        422: {
            "description": (
                "Datos inválidos, campos desconocidos, legajo ya existente entre "
                "alumnos, curso lectivo inexistente o el alumno tiene menos de 18 años "
                "(a la fecha de hoy o al 31/12 del año de ingreso)"
            )
        },
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
    - El alumno debe tener **al menos 18 años** a la fecha de alta (422 si no).
    - Además, el alumno debe tener **al menos 18 años al 31/12 de su año de ingreso**
      (422 si no).
    - `id_section_year` es opcional: si se envía, se crea la **inscripción**
      (`registered`) del alumno en ese curso lectivo (un id inexistente responde
      422 junto con el resto de errores de la fila). Para sumar otras
      inscripciones después, usar `POST /student-section-years`.
    - Cualquier otro campo responde 422.
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
    del lote o ya existente, o un curso lectivo inexistente) no se crea ninguna y
    la respuesta indica qué filas corregir para volver a enviar el lote completo.

    Cada fila puede incluir `id_section_year` para crear la **inscripción**
    (`registered`) del alumno en ese curso lectivo; un alumno puede tener varias
    inscripciones a lo largo del tiempo (las adicionales se agregan con
    `POST /student-section-years`).

    Las reglas por alumno son las mismas que en `POST /students`, incluida la
    mayoría de edad: si algún alumno tiene menos de 18 años (a la fecha de
    alta o al 31/12 del año de ingreso), el lote entero se rechaza con **422**
    (error de validación de campo).
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
        422: {
            "description": (
                "Datos inválidos, body vacío, campos que no se pueden modificar, "
                "o una `birth_date` o un `enrollment_year` que dejen al alumno con "
                "menos de 18 años (a la fecha de hoy o al 31/12 del año de ingreso)"
            )
        },
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
    - La `birth_date` no puede dejar al alumno con menos de 18 años (422).
    - La combinación `birth_date`/`enrollment_year` no puede dejar al alumno con
      menos de 18 años al 31/12 del año de ingreso (422).
    - Cualquier otro campo responde 422. La contraseña no se puede modificar
      desde acá.
    """
    return await update_student(db, id_student, data)


@students_router.delete(
    "/{id_student}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar un alumno (alta errónea)",
    responses={
        401: {"description": "Token ausente, inválido o vencido"},
        403: {"description": "El usuario no es super admin"},
        404: {"description": "No existe el alumno"},
        409: {
            "description": (
                "El alumno tiene una membresía vigente (`active`), terminada "
                "(`finished`) o en espera (`pending_approval`) y no se puede eliminar"
            )
        },
    },
)
async def delete_student_route(id_student: int, db: db_dependency, _: super_admin_dependency):
    """
    Elimina a un alumno. **Solo super admin.**

    Pensado solo para **altas erróneas**: no es la forma de dar de baja a un
    alumno que participó de un grupo (para eso están `abandon`, `expel` y los
    estados `finished`).

    - El alumno no puede tener ninguna membresía `active`, `finished` ni
      `pending_approval` en ningún proyecto (**409**); sí se permite si solo
      tiene restos viejos (`abandoned`, `expelled`, `rejected`), que se eliminan
      junto con él sin afectar a los proyectos.
    - Al eliminarlo se borran sus datos personales, el registro de alumno, sus
      inscripciones y cursadas (alumno + curso lectivo), sus sesiones (refresh
      tokens) y sus códigos de contraseña pendientes; su legajo queda libre para
      volver a cargarlo.
    """
    await delete_student(db, id_student)