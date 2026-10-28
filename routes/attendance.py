from fastapi import APIRouter, status

from config.database import db_dependency
from schemas.attendance import (
    AttendanceCheckIn,
    AttendancePublic,
    AttendanceSessionOpenedPublic,
    ClassAttendancePublic,
)
from utils.attendance import (
    check_in,
    close_attendance,
    list_attendance,
    mark_manual,
    open_attendance,
    unmark_manual,
)
from utils.auth import user_dependency
from utils.permissions import professor_dependency, student_dependency
from utils.projects import build_access

attendance_router = APIRouter(prefix="/calendar-classes", tags=["attendance"])

_READ_ERRORS = {
    401: {"description": "Token ausente, inválido o vencido"},
    403: {
        "description": (
            "El usuario no es profesor, o no está asignado al curso lectivo de la clase"
        )
    },
    404: {"description": "No existe la clase"},
}
_WRITE_ERRORS = _READ_ERRORS


@attendance_router.post(
    "/{id_calendar_class}/attendance/open",
    response_model=AttendanceSessionOpenedPublic,
    summary="Habilitar la asistencia de una clase",
    responses={
        **_WRITE_ERRORS,
        422: {"description": "Datos inválidos"},
    },
)
async def open_attendance_route(
    id_calendar_class: int,
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
):
    """
    Habilita (o reabre) la toma de asistencia de una clase. **Profesor del curso
    lectivo o super admin.**

    - Genera un **código de 6 dígitos** que vence a los
      `ATTENDANCE_CODE_MINUTES` minutos (10 por defecto).
    - El código se muestra **solo en esta respuesta**; en la base queda hasheado.
    - Si la toma ya estaba abierta o vencida, se **rota** el código y vence el
      anterior.
    - Para cerrarla antes del vencimiento, usar
      `POST /calendar-classes/{id}/attendance/close`.
    """
    return await open_attendance(db, await build_access(db, user), id_calendar_class)


@attendance_router.post(
    "/{id_calendar_class}/attendance/close",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cerrar la asistencia de una clase",
    responses={
        **_WRITE_ERRORS,
        404: {"description": "No existe la clase o no hay una toma de asistencia"},
    },
)
async def close_attendance_route(
    id_calendar_class: int,
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
):
    """
    Cierra la toma de asistencia: los alumnos ya no pueden marcar por código.
    **Profesor del curso lectivo o super admin.** Las marcas manuales siguen
    disponibles. Si no había una toma, responde 404.
    """
    await close_attendance(db, await build_access(db, user), id_calendar_class)


@attendance_router.post(
    "/{id_calendar_class}/attendance/check-in",
    response_model=AttendancePublic,
    summary="Marcar mi asistencia con el código",
    responses={
        401: {"description": "Token ausente, inválido o vencido"},
        403: {
            "description": (
                "El usuario no es alumno, o no tiene cursada en ese curso lectivo"
            )
        },
        404: {"description": "No existe la clase"},
        409: {"description": "La toma de asistencia está cerrada o vencida"},
        422: {"description": "El código no tiene 6 dígitos o es incorrecto"},
    },
)
async def check_in_route(
    id_calendar_class: int,
    data: AttendanceCheckIn,
    db: db_dependency,
    student: student_dependency,
):
    """
    El **alumno logueado** marca su asistencia a una clase con el código que dio
    el profesor.

    - Requiere tener **cursada** en el curso lectivo de la clase.
    - La toma debe estar abierta y el código vigente (**409** si está cerrada o
      vencida; **422** si el código no es válido).
    - Es **idempotente**: si ya estaba marcado, devuelve la asistencia existente.
    """
    return await check_in(db, student, id_calendar_class, data.code)


@attendance_router.get(
    "/{id_calendar_class}/attendance",
    response_model=ClassAttendancePublic,
    summary="Ver la asistencia de una clase",
    responses=_READ_ERRORS,
)
async def get_attendance(
    id_calendar_class: int,
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
):
    """
    Lista la asistencia de una clase. **Profesor del curso lectivo o super admin.**

    Devuelve **todos los alumnos con cursada en el curso lectivo**, con
    `present` (los no marcados vienen en `false`), el método (`code` o `manual`)
    y la hora de la marca. Incluye el estado de la sesión (abierta/cerrada y
    vencimiento), **sin exponer el código**. Orden: apellido y nombre.
    """
    return await list_attendance(
        db, await build_access(db, user), id_calendar_class
    )


@attendance_router.post(
    "/{id_calendar_class}/attendance/students/{id_student_section_year}",
    response_model=AttendancePublic,
    summary="Marcar la asistencia de un alumno a mano",
    responses={
        **_WRITE_ERRORS,
        404: {"description": "No existe la clase o la cursada"},
        422: {"description": "La cursada no pertenece al curso lectivo de la clase"},
    },
)
async def mark_manual_route(
    id_calendar_class: int,
    id_student_section_year: int,
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
):
    """
    Marca presente a un alumno a mano. **Profesor del curso lectivo o super
    admin.**

    - La cursada debe pertenecer al mismo curso lectivo que la clase (**422**).
    - Funciona aunque la toma esté cerrada y es **idempotente**.
    """
    return await mark_manual(
        db,
        await build_access(db, user),
        id_calendar_class,
        id_student_section_year,
    )


@attendance_router.delete(
    "/{id_calendar_class}/attendance/students/{id_student_section_year}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Quitar la asistencia de un alumno",
    responses={
        **_WRITE_ERRORS,
        404: {"description": "No existe la clase o la asistencia"},
    },
)
async def unmark_manual_route(
    id_calendar_class: int,
    id_student_section_year: int,
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
):
    """
    Quita la marca de asistencia de un alumno (por ejemplo, si se marcó por
    error). **Profesor del curso lectivo o super admin.** Responde 404 si no
    estaba marcado.
    """
    await unmark_manual(
        db,
        await build_access(db, user),
        id_calendar_class,
        id_student_section_year,
    )
