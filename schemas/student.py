from datetime import date

from sqlmodel import Field, SQLModel


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