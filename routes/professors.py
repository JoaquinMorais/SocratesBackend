from fastapi import APIRouter, BackgroundTasks, status

from config.database import db_dependency
from schemas.professor import ProfessorCreate, ProfessorPublic
from utils.email import send_welcome_emails
from utils.permissions import super_admin_dependency
from utils.professors import create_professor

professors_router = APIRouter(prefix="/professors", tags=["professors"])


@professors_router.post(
    "", response_model=ProfessorPublic, status_code=status.HTTP_201_CREATED
)
async def create_professor_route(
    data: ProfessorCreate,
    background: BackgroundTasks,
    db: db_dependency,
    _: super_admin_dependency,
):
    created = await create_professor(db, data)
    background.add_task(send_welcome_emails, [(created.email, created.first_name)])
    return created