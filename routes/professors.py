from fastapi import APIRouter, BackgroundTasks, status

from config.database import db_dependency
from schemas.professor import ProfessorCreate, ProfessorPublic
from utils.email import send_welcome_emails
from utils.permissions import super_admin_dependency
from utils.professors import create_professor

professors_router = APIRouter(prefix="/professors", tags=["professors"])


@professors_router.post(
    "",
    response_model=ProfessorPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un profesor",
    responses={
        401: {"description": "Token ausente, inválido o vencido"},
        403: {"description": "El usuario no es profesor super admin"},
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