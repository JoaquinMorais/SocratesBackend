from typing import Annotated, Literal

from fastapi import APIRouter, File, Query, UploadFile, status

from config.database import db_dependency
from schemas.attendance import (
    AttendanceBulkCreate,
    AttendanceBulkResult,
    AttendanceCheckIn,
    AttendancePublic,
    AttendanceSessionOpenedPublic,
    ClassAttendancePublic,
)
from schemas.attendance_transcript import (
    AttendanceTranscriptReport,
    AttendanceTranscriptText,
)
from utils.attendance_transcript import (
    import_transcript_from_file,
    import_transcript_from_text,
)
from utils.attendance import (
    check_in,
    close_attendance,
    list_attendance,
    mark_manual,
    mark_manual_bulk,
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
                "El usuario no es alumno, o no tiene una cursada `attending` en ese curso lectivo"
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

    - Requiere tener una cursada **`attending`** en el curso lectivo de la clase.
      Una inscripción `registered` o una cursada `finished_*` no alcanza.
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

    Devuelve los alumnos con cursada **`attending`** o **`finished_*`** en el
    curso lectivo, con su `state`, `present` (los no marcados vienen en `false`),
    el método (`code`, `manual` o `transcript`) y la hora de la marca. También
    incluye `attendance` con `attended_classes`, `total_classes` y
    `attendance_percentage` del curso lectivo completo. Las inscripciones
    `registered` y las cursadas `abandoned` no aparecen. Incluye el estado de la
    sesión (abierta/cerrada y vencimiento), **sin exponer el código**. Orden:
    apellido y nombre.
    """
    return await list_attendance(
        db, await build_access(db, user), id_calendar_class
    )


@attendance_router.post(
    "/{id_calendar_class}/attendance/bulk",
    response_model=AttendanceBulkResult,
    summary="Marcar la asistencia de varios alumnos a mano",
    responses={
        **_WRITE_ERRORS,
        409: {
            "description": (
                "La asistencia cambió mientras se guardaba; reintentar la operación"
            )
        },
        422: {
            "description": (
                "Lista vacía, más de 200 alumnos, IDs inválidos o alumnos "
                "inexistentes/no cursando (`attending`) en el curso lectivo. "
                "`detail` lista `[{row, id_student, detail}]`"
            )
        },
    },
)
async def mark_manual_bulk_route(
    id_calendar_class: int,
    data: AttendanceBulkCreate,
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
):
    """
    Marca presentes a **varios alumnos a mano**. **Profesor del curso lectivo o
    super admin.**

    - Recibe `id_students` (1 a 200). El backend resuelve la cursada
      **`attending`** de cada alumno en el curso lectivo de la clase; no recibe
      el proyecto, el frontend arma la selección.
    - Es **todo o nada**: si algún alumno no existe o no tiene una cursada
      `attending` en ese curso lectivo, responde 422 con
      `{row, id_student, detail}` y no marca a ninguno.
    - Los IDs repetidos se deduplican; `requested` cuenta los alumnos únicos.
    - Es **idempotente**: los que ya estaban presentes se reportan en
      `already_present` y conservan su `method` original (`code`, `manual` o
      `transcript`).
    - Funciona con la toma de asistencia abierta o cerrada.
    """
    return await mark_manual_bulk(
        db, await build_access(db, user), id_calendar_class, data.id_students
    )


@attendance_router.post(
    "/{id_calendar_class}/attendance/students/{id_student_section_year}",
    response_model=AttendancePublic,
    summary="Marcar la asistencia de un alumno a mano",
    responses={
        **_WRITE_ERRORS,
        404: {"description": "No existe la clase o la cursada"},
        422: {
            "description": (
                "La cursada no pertenece al curso lectivo de la clase o no está "
                "en estado `attending`"
            )
        },
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

    - La cursada debe pertenecer al mismo curso lectivo que la clase y estar en
      estado **`attending`** (**422** si no).
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


_TRANSCRIPT_ERRORS = {
    401: {"description": "Token ausente, inválido o vencido"},
    403: {
        "description": (
            "El usuario no es profesor, o no está asignado al curso lectivo de la clase"
        )
    },
    404: {"description": "No existe la clase"},
    413: {"description": "El texto supera el tamaño máximo"},
    422: {
        "description": (
            "Texto vacío, no se encontró ningún par legajo-nombre, CSV inválido "
            "o formato desconocido"
        )
    },
}


@attendance_router.post(
    "/{id_calendar_class}/attendance/import-transcript",
    response_model=AttendanceTranscriptReport,
    summary="Importar asistencia desde un archivo de chat",
    responses=_TRANSCRIPT_ERRORS,
)
async def import_transcript_file_route(
    id_calendar_class: int,
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
    file: Annotated[
        UploadFile,
        File(description="Transcripción del chat (.txt) o un CSV con legajo y nombre"),
    ],
    dry_run: Annotated[
        bool,
        Query(description="true: solo preview; false: crea las asistencias"),
    ] = True,
    fmt: Annotated[
        Literal["auto", "text", "csv"],
        Query(alias="format", description="Formato del archivo (auto detecta por extensión)"),
    ] = "auto",
):
    """
    Importa asistencias desde la transcripción del chat. **Profesor del curso
    lectivo o super admin.**

    - Espera mensajes con `LEGAJO-ApellidoNombre` (separadores `-`, `–`, `—`,
      `:`, `,` o `;`). El **legajo debe ser exacto**; el nombre tolera tildes,
      errores, orden invertido y nombres faltantes (umbral configurable).
    - `dry_run` es **true por defecto**: solo devuelve el reporte. Para crear las
      asistencias, repetir con `?dry_run=false`.
    - Los asistentes se marcan con `method: "transcript"`; una asistencia
      existente (`code`/`manual`) no se pisa y se reporta `already_present`.
      Solo se consideran alumnos con cursada `attending` en ese curso lectivo.
    - El archivo no se guarda. Límite `ATTENDANCE_TRANSCRIPT_MAX_BYTES` (2 MB).
    - Funciona para cualquier modalidad de clase.
    """
    return await import_transcript_from_file(
        db,
        await build_access(db, user),
        id_calendar_class,
        file,
        dry_run=dry_run,
        fmt=fmt,
    )


@attendance_router.post(
    "/{id_calendar_class}/attendance/import-transcript/text",
    response_model=AttendanceTranscriptReport,
    summary="Importar asistencia desde texto o CSV pegado",
    responses=_TRANSCRIPT_ERRORS,
)
async def import_transcript_text_route(
    id_calendar_class: int,
    data: AttendanceTranscriptText,
    db: db_dependency,
    user: user_dependency,
    _: professor_dependency,
    dry_run: Annotated[
        bool,
        Query(description="true: solo preview; false: crea las asistencias"),
    ] = True,
):
    """
    Igual que la importación desde archivo, pero con el texto pegado en el body.

    - `format` es `text` (chat libre) o `csv` (`legajo,nombre` /
      `legajo,apellido,nombre`, con encabezado opcional).
    - `dry_run` es **true por defecto**; enviar `?dry_run=false` para confirmar.
    - Se aplican las mismas reglas de legajo exacto y nombre tolerante.
    """
    return await import_transcript_from_text(
        db,
        await build_access(db, user),
        id_calendar_class,
        data.text,
        dry_run=dry_run,
        fmt=data.format,
    )
