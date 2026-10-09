from fastapi import APIRouter, BackgroundTasks, status

from config.database import db_dependency
from schemas.professor import ProfessorCreate, ProfessorPublic, ProfessorUpdate
from utils.email import send_welcome_emails
from utils.permissions import super_admin_dependency
from utils.professors import create_professor, update_professor

professors_router = APIRouter(prefix="/professors", tags=["professors"])

_AUTH_ERRORS = {
    401: {"description": "Token ausente, inválido o vencido"},
    403: {"description": "El usuario no es profesor super admin"},
}


@professors_router.post(
    "",
    response_model=ProfessorPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un profesor",
    responses={
        **_AUTH_ERRORS,
        409: {"description": "Ya existe un profesor con ese mail"},
        422: {"description": "Datos inválidos, o mail con el dominio reservado a alumnos"},
    },
)
async def create_professor_route(
    data: ProfessorCreate,
    background: BackgroundTasks,
    db: db_dependency,
    _: super_admin_dependency,
):
    """
    Crea un profesor. **Solo profesores super admin.**

    - El `mail` es el mail con el que inicia sesión; se guarda en minúsculas y no
      puede repetirse. No puede terminar en `@sistemas.frc.utn.edu.ar` (reservado
      a alumnos).
    - El `legajo` puede coincidir con el de otros usuarios.
    - `is_super_admin` es opcional (por defecto `false`); un super admin puede
      crear otros super admins.
    - Se crea **sin contraseña**: el profesor la define con
      `POST /auth/password/request` y `POST /auth/password/confirm`.
    - Se envía un mail de bienvenida.
    """
    created = await create_professor(db, data)
    background.add_task(send_welcome_emails, [(created.email, created.first_name)])
    return created


@professors_router.patch(
    "/{id_professor}",
    response_model=ProfessorPublic,
    summary="Modificar un profesor",
    responses={
        **_AUTH_ERRORS,
        404: {"description": "No existe el profesor"},
        409: {
            "description": (
                "Ya existe un profesor con ese mail, o un super admin intentó "
                "quitarse a sí mismo el rol de super admin"
            )
        },
        422: {"description": "Datos inválidos, body vacío, campos no modificables o mail con el dominio de alumnos"},
    },
)
async def update_professor_route(
    id_professor: int,
    data: ProfessorUpdate,
    db: db_dependency,
    admin: super_admin_dependency,
):
    """
    Corrige los datos de un profesor, incluido uno mismo. **Solo super admin.**

    **Campos editables** (opcionales, se envían solo los que cambian):
    `first_name`, `last_name`, `birth_date`, `legajo`, `mail`, `is_super_admin`.

    - El `mail` se guarda en minúsculas, no puede repetirse (409) ni usar el
      dominio de alumnos (422). Al cambiarlo se **cierran todas las sesiones** del
      profesor y se invalidan sus códigos pendientes; conserva su contraseña y
      vuelve a entrar con el mail nuevo. Si el super admin edita su propio mail,
      también se cierra su sesión.
    - Un super admin **no puede quitarse a sí mismo** el rol (409); sí puede
      quitárselo a otros.
    - Cualquier otro campo responde 422. La contraseña no se puede modificar
      desde acá.
    """
    return await update_professor(db, admin, id_professor, data)