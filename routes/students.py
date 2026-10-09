from fastapi import APIRouter, BackgroundTasks, status

from config.database import db_dependency
from schemas.student import StudentBulkCreate, StudentCreate, StudentPublic, StudentUpdate
from utils.email import send_welcome_emails
from utils.permissions import professor_dependency
from utils.students import create_students, update_student

students_router = APIRouter(prefix="/students", tags=["students"])

_AUTH_ERRORS = {
    401: {"description": "Token ausente, inválido o vencido"},
    403: {"description": "El usuario no es profesor"},
}


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