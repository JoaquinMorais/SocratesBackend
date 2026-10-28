from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from config.database import db_dependency
from schemas.attendance import MyAttendanceListPublic
from schemas.me_calendar import MyCalendarPublic
from schemas.me_project import MyProjectPublic
from schemas.me_section_year import MySectionYearsPublic
from schemas.project import ProjectList
from schemas.user import UserPublic, UserUpdate
from utils.attendance import list_my_attendance
from utils.auth import user_dependency
from utils.calendars import get_my_calendar
from utils.permissions import student_dependency
from utils.projects import (
    build_access,
    current_section_years,
    list_my_section_year_projects,
    to_public as project_public,
)
from utils.section_years import to_public as section_year_public
from utils.student_projects import get_my_project
from utils.users import to_public, update_user

me_router = APIRouter(prefix="/me", tags=["me"])


@me_router.get(
    "",
    response_model=UserPublic,
    response_model_exclude_none=True,
    summary="Mis datos",
    responses={401: {"description": "Token ausente, inválido o vencido"}},
)
async def get_me(user: user_dependency):
    """
    Devuelve los datos del usuario del token: nombre, legajo, mail y rol
    (`student` o `professor`), fecha de nacimiento, edad y, según el rol,
    `enrollment_year` (alumnos) o `is_super_admin` (profesores).

    Sirve para que el frontend sepa qué pantallas mostrar según el rol.
    """
    return to_public(user)


@me_router.patch(
    "",
    response_model=UserPublic,
    response_model_exclude_none=True,
    summary="Modificar mis datos",
    responses={
        401: {"description": "Token ausente, inválido o vencido"},
        422: {"description": "Datos inválidos, body vacío o campos que no se pueden modificar"},
    },
)
async def update_me(data: UserUpdate, user: user_dependency, db: db_dependency):
    """
    Modifica los datos personales del usuario logueado (alumno o profesor).

    **Campos editables** (opcionales, se envían solo los que cambian):
    `first_name`, `last_name`, `birth_date` (no puede ser futura ni dejar al
    usuario con menos de 18 años).

    Cualquier otro campo (`legajo`, `email`...) responde 422. Si hay que
    corregir el legajo o el mail, lo hace un profesor (alumnos) o un super admin
    (profesores). La contraseña se cambia con `POST /auth/password/request` y
    `POST /auth/password/confirm`.
    """
    if not data.model_dump(exclude_none=True):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No fields to update")
    user = await update_user(db, user, data)
    return to_public(user)


@me_router.get(
    "/project",
    response_model=MyProjectPublic,
    summary="Consultar mi proyecto",
    responses={
        401: {"description": "Token ausente, inválido o vencido"},
        403: {"description": "El usuario no es alumno"},
    },
)
async def get_my_project_route(db: db_dependency, student: student_dependency):
    """
    El **alumno logueado** consulta su proyecto. **Solo alumnos.** Devuelve:

    - `project`: su **equipo**, el grupo donde es miembro (membresía `active` o
      `finished`). Va con el detalle completo, igual que
      `GET /projects/{id}/overview`: estado del proyecto, privacidad,
      integrantes (`active`/`finished`), los responsables (los profesores de su
      curso lectivo, sin mail) y el jefe (`leader`; el propio alumno aparece
      marcado con `is_leader` si lo es). Si no pertenece a ningún grupo es
      `null`.
    - `requests`: sus **solicitudes de ingreso** en estado `pending_approval` y
      `rejected`, con el resumen de cada grupo (comisión, año, número y el
      estado de la solicitud). Las pendientes van primero y, dentro de cada
      estado, de la más nueva a la más vieja. Una solicitud `rejected` solo se
      puede volver a enviar mientras el alumno no sea miembro de otro grupo.

    Un alumno sin equipo y sin solicitudes recibe
    `{"project": null, "requests": []}`.
    """
    return await get_my_project(db, student.id_student)


@me_router.get(
    "/section-year",
    response_model=MySectionYearsPublic,
    summary="Consultar mi curso lectivo actual",
    responses={401: {"description": "Token ausente, inválido o vencido"}},
)
async def get_my_section_year_route(db: db_dependency, user: user_dependency):
    """
    Devuelve el/los **cursos lectivos actuales** del usuario logueado. **Cualquier
    usuario logueado.**

    Se toma el **año más reciente** del usuario:

    - **Profesor**: sus cursos lectivos asignados (`/professor-section-years`).
      Puede haber más de uno si dicta varias comisiones de ese año.
    - **Alumno**: el curso de sus cursadas (`/student-section-years`); un alumno
      no puede cursar dos comisiones del mismo año, así que es uno solo. Si
      todavía no tiene cursadas, se usa el curso lectivo de su grupo actual
      (membresía `active` o `finished`).

    Sin cursos (por ejemplo, un profesor sin asignaciones o un super admin que no
    dicta) devuelve `{"section_years": []}`. Cada curso incluye año, comisión y
    el rango de estudiantes por grupo.
    """
    access = await build_access(db, user)
    years = await current_section_years(db, user, access)
    return MySectionYearsPublic(
        section_years=[section_year_public(sy) for sy in years]
    )


@me_router.get(
    "/section-year/projects",
    response_model=ProjectList,
    summary="Listar los proyectos de mi curso lectivo actual",
    responses={401: {"description": "Token ausente, inválido o vencido"}},
)
async def get_my_section_year_projects_route(
    db: db_dependency,
    user: user_dependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """
    Lista **todos los proyectos** de los cursos lectivos actuales del usuario
    (los del año más reciente, ver `GET /me/section-year`). **Cualquier usuario
    logueado.**

    - Se aplican las mismas reglas de **privacidad** que `GET /projects`: los
      `uninsured` se tratan como públicos, los `public` se ven completos, los
      `protected` muestran solo la información básica a quien no es privilegiado
      (`restricted` en `true`) y los `private` desaparecen para el resto (el
      profesor del curso lectivo y el super admin ven todo).
    - Orden: año más reciente, comisión y número de grupo. Está paginado: `total`
      es la cantidad de proyectos visibles que cumplen el filtro.
    - Sin curso lectivo actual devuelve la lista vacía (200).
    """
    access = await build_access(db, user)
    years = await current_section_years(db, user, access)
    items, total = await list_my_section_year_projects(
        db,
        access,
        [sy.id_section_year for sy in years],
        limit=limit,
        offset=offset,
    )
    return ProjectList(
        items=[
            project_public(p, restricted=not access.can_see_detail(p)) for p in items
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@me_router.get(
    "/calendar",
    response_model=MyCalendarPublic,
    summary="Consultar mi calendario",
    responses={
        401: {"description": "Token ausente, inválido o vencido"},
        422: {
            "description": (
                "Se envió solo uno de `from`/`to`, `from` es posterior a `to` o el "
                "rango supera los 366 días"
            )
        },
    },
)
async def get_my_calendar_route(
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
    Devuelve **mi calendario**: las clases y actividades de mis cursos lectivos
    actuales. **Cualquier usuario logueado.**

    - Los cursos actuales son los del **año más reciente** del usuario, igual que
      `GET /me/section-year`: un profesor puede tener varias comisiones de ese año;
      un alumno tiene una (o la de su grupo si no tiene cursadas).
    - Sin cursos actuales devuelve `section_years`, `classes` y `activities` vacíos.
    - `from`/`to` son opcionales (ambos o ninguno, máximo 366 días) y filtran por
      fecha de clase o de entrega.
    - Las clases y las actividades vienen en arreglos separados, ordenadas por
      fecha y hora. Cada ítem trae `id_section_year`; `section_years` aporta año y
      comisión.
    """
    return await get_my_calendar(
        db,
        user,
        await build_access(db, user),
        from_date=from_date,
        to_date=to_date,
    )


@me_router.get(
    "/attendance",
    response_model=MyAttendanceListPublic,
    summary="Consultar mi asistencia",
    responses={
        401: {"description": "Token ausente, inválido o vencido"},
        403: {"description": "El usuario no es alumno"},
        422: {
            "description": (
                "Se envió solo uno de `from`/`to`, `from` es posterior a `to` o el "
                "rango supera los 366 días"
            )
        },
    },
)
async def get_my_attendance_route(
    db: db_dependency,
    student: student_dependency,
    from_date: Annotated[
        date | None, Query(alias="from", description="Primer día (YYYY-MM-DD)")
    ] = None,
    to_date: Annotated[
        date | None, Query(alias="to", description="Último día (YYYY-MM-DD)")
    ] = None,
):
    """
    Devuelve el **historial de asistencias** del alumno logueado. **Solo alumnos.**

    - Incluye solo las clases a las que asistió, con los datos del curso lectivo
      (año y comisión) y de la clase.
    - `from`/`to` son opcionales (ambos o ninguno, máximo 366 días) y filtran por
      fecha de la clase.
    - Orden: clase más reciente primero.
    """
    return await list_my_attendance(
        db, student, from_date=from_date, to_date=to_date
    )
