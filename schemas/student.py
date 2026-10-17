from datetime import date

from sqlmodel import Field, SQLModel

from schemas.user import UserUpdate

class StudentCreate(SQLModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    legajo: int = Field(gt=0)
    birth_date: date
    enrollment_year: int = Field(ge=1950, le=2100)


class StudentBulkCreate(SQLModel):
    students: list[StudentCreate] = Field(min_length=1, max_length=500)


class StudentPublic(SQLModel):
    id_student: int
    first_name: str
    last_name: str
    legajo: int
    email: str
    enrollment_year: int


class StudentGroupPublic(SQLModel):
    id_project: int
    project_name: str | None = None
    group_number: int
    id_section_year: int
    year: int
    id_section: int
    section_name: str


class StudentListItem(SQLModel):
    id_student: int
    first_name: str
    last_name: str
    legajo: int
    email: str
    enrollment_year: int
    groups: list[StudentGroupPublic]


class StudentList(SQLModel):
    items: list[StudentListItem]
    total: int
    limit: int
    offset: int


class StudentUpdate(UserUpdate):
    """Hereda first_name, last_name y birth_date de UserUpdate (y rechaza campos extra)."""

    legajo: int | None = Field(default=None, gt=0)
    enrollment_year: int | None = Field(default=None, ge=1950, le=2100)