from fastapi import APIRouter, BackgroundTasks, status

from config.database import db_dependency
from schemas.student import StudentBulkCreate, StudentCreate, StudentPublic
from utils.email import send_welcome_emails
from utils.permissions import professor_dependency
from utils.students import create_students

students_router = APIRouter(prefix="/students", tags=["students"])


@students_router.post("", response_model=StudentPublic, status_code=status.HTTP_201_CREATED)
async def create_student(
    data: StudentCreate,
    background: BackgroundTasks,
    db: db_dependency,
    _: professor_dependency,
):
    created = await create_students(db, [data])
    background.add_task(
        send_welcome_emails, [(s.email, s.first_name) for s in created]
    )
    return created[0]


@students_router.post(
    "/bulk", response_model=list[StudentPublic], status_code=status.HTTP_201_CREATED
)
async def create_students_bulk(
    data: StudentBulkCreate,
    background: BackgroundTasks,
    db: db_dependency,
    _: professor_dependency,
):
    created = await create_students(db, data.students)
    background.add_task(
        send_welcome_emails, [(s.email, s.first_name) for s in created]
    )
    return created