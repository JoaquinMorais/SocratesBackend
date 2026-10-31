from pydantic import ConfigDict
from sqlmodel import Field, SQLModel

from schemas.attendance import AttendanceStatsPublic
from schemas.status import StatusPublic


class StudentSectionYearCreate(SQLModel):
    model_config = ConfigDict(extra="forbid")  # campos desconocidos -> 422

    id_student: int = Field(gt=0)
    id_section_year: int = Field(gt=0)


class StudentSectionYearUpdate(SQLModel):
    model_config = ConfigDict(extra="forbid")

    id_student: int | None = Field(default=None, gt=0)
    id_section_year: int | None = Field(default=None, gt=0)


class StudentSectionYearPublic(SQLModel):
    id_student_section_year: int
    id_student: int
    state: str
    status: StatusPublic
    student_first_name: str
    student_last_name: str
    student_legajo: int
    id_section_year: int
    year: int
    id_section: int
    section_name: str
    attendance: AttendanceStatsPublic | None = None


class StudentSectionYearList(SQLModel):
    items: list[StudentSectionYearPublic]
    total: int
    limit: int
    offset: int
