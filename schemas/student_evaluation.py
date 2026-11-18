from datetime import date as date_type
from datetime import datetime

from pydantic import ConfigDict, field_validator
from sqlmodel import Field, SQLModel

from schemas.student_project import StudentProjectAttendancePublic


class StudentEvaluationCreate(SQLModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    date: date_type

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name cannot be blank")
        return value


class StudentEvaluationUpdate(SQLModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    date: date_type | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("name cannot be blank")
        return value


class StudentEvaluationPublic(SQLModel):
    id_student_evaluation: int
    id_section_year: int
    year: int
    id_section: int
    section_name: str
    name: str
    description: str | None = None
    date: date_type
    created_at: datetime


class StudentEvaluationListItemPublic(StudentEvaluationPublic):
    grades_total: int
    graded_grades_total: int
    average_grade: float | None = None


class StudentEvaluationList(SQLModel):
    items: list[StudentEvaluationListItemPublic]
    total: int


class StudentGradeCreate(SQLModel):
    model_config = ConfigDict(extra="forbid")

    id_student_section_year: int = Field(gt=0)
    grade: int = Field(ge=0, le=10)


class StudentGradeUpdate(SQLModel):
    model_config = ConfigDict(extra="forbid")

    grade: int = Field(ge=1, le=10)


class StudentGradePublic(SQLModel):
    id_student_grade: int
    id_student_evaluation: int
    id_student_section_year: int
    id_student: int
    first_name: str
    last_name: str
    legajo: int
    grade: int
    updated_at: datetime


class StudentGradeList(SQLModel):
    items: list[StudentGradePublic]


class StudentGradeBulkItem(SQLModel):
    model_config = ConfigDict(extra="forbid")

    id_student_section_year: int = Field(gt=0)
    grade: int = Field(ge=1, le=10)


class StudentGradeBulkUpdate(SQLModel):
    model_config = ConfigDict(extra="forbid")

    grades: list[StudentGradeBulkItem] = Field(min_length=1, max_length=200)


class StudentEvaluationGradeSummaryPublic(SQLModel):
    id_student_evaluation: int
    name: str
    date: date_type
    grade: int


class StudentEvaluationSummaryPublic(SQLModel):
    evaluations_total: int = 0
    graded_grades_total: int = 0
    average_grade: float | None = None


class StudentEvaluationMemberPublic(StudentProjectAttendancePublic):
    student_evaluations: list[StudentEvaluationGradeSummaryPublic] = []
    average_student_evaluation: float | None = None


class MyStudentEvaluationPublic(StudentEvaluationPublic):
    grade: int


class MyStudentEvaluationList(SQLModel):
    items: list[MyStudentEvaluationPublic]
